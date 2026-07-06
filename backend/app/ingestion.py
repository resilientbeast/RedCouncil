"""
Evidence ingestion: PDF text extraction and CSV tabular summarization.

Deliberately bounded scope (SPEC.md §5.1):
  - PDF: plain-text extraction only, no OCR. Scanned/image-only PDFs will
    yield little or no text — that's an accepted limitation, not a bug.
  - CSV: reduced to a statistical digest (columns, dtypes, row count,
    describe()-style stats, a handful of sample rows) via pandas. Agents
    never see a raw CSV dump. This is intentional: interpreting an arbitrary
    "simulation" format is out of scope, but a bounded statistical summary
    of tabular data is cheap, fast, and genuinely useful as evidence.

Do not extend this into a general document-format library (xlsx, JSON,
Parquet, proprietary simulation exports) — see SPEC.md §16 non-goals.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone

import pandas as pd
from pypdf import PdfReader

from app.config import settings
from app.models import DocumentKind, UploadedDocument
from app.security import validate_document_text


class UnsupportedDocumentError(Exception):
    pass


class DocumentTooLargeError(Exception):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_kind(filename: str) -> DocumentKind:
    lower = filename.lower()
    if lower.endswith(".pdf"):
        return DocumentKind.PDF
    if lower.endswith(".csv"):
        return DocumentKind.CSV
    raise UnsupportedDocumentError(
        f"Unsupported file type for '{filename}'. Only .pdf and .csv are accepted."
    )


_PDF_MAGIC = b"%PDF"

def _validate_content_type(raw_bytes: bytes, kind: DocumentKind) -> None:
    """Check that file content matches the expected type inferred from extension.
    Catches renamed binaries (e.g., an .exe renamed to .pdf) that would waste
    parser time or trigger edge-case bugs in pypdf/pandas."""
    if kind == DocumentKind.PDF:
        if not raw_bytes[:8].startswith(_PDF_MAGIC):
            raise UnsupportedDocumentError(
                "File has a .pdf extension but does not appear to be a valid PDF "
                "(missing %PDF header)."
            )
    elif kind == DocumentKind.CSV:
        # Check first 1KB for non-text bytes (NUL, control chars other than \\t\\n\\r).
        # This catches renamed binaries without being overly strict about encoding.
        sample = raw_bytes[:1024]
        non_text = sum(1 for b in sample if b < 0x09 or (0x0E <= b < 0x20 and b != 0x1B))
        if non_text > 0:
            raise UnsupportedDocumentError(
                "File has a .csv extension but contains binary content."
            )


def extract_pdf_text(raw_bytes: bytes, max_chars: int) -> str:
    """Plain-text extraction, page by page, stopping once max_chars is hit.
    No OCR — a scanned/image-only PDF will return little or nothing."""
    reader = PdfReader(io.BytesIO(raw_bytes))
    chunks: list[str] = []
    total_len = 0

    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        chunks.append(text)
        total_len += len(text)
        if total_len >= max_chars:
            break

    full_text = "\n\n".join(chunks)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars].rsplit(" ", 1)[0] + "…"

    return full_text


def summarize_csv(raw_bytes: bytes, sample_rows: int) -> tuple[str, dict, int]:
    """
    Returns (rendered_text_summary, summary_stats_dict, row_count).

    rendered_text_summary is what actually gets injected into agent
    prompts — columns/dtypes, numeric describe() stats, and a small sample
    of rows. summary_stats is the same numeric stats as a plain dict, kept
    separately on UploadedDocument for potential frontend charting later.
    """
    df = pd.read_csv(io.BytesIO(raw_bytes), nrows=settings.max_csv_rows)

    if len(df.columns) > settings.max_csv_columns:
        raise UnsupportedDocumentError(
            f"CSV has {len(df.columns)} columns, exceeding the {settings.max_csv_columns} column limit."
        )

    row_count = len(df)

    numeric_df = df.select_dtypes(include="number")
    stats: dict = {}
    if not numeric_df.empty:
        stats = numeric_df.describe().to_dict()

    lines = [
        f"Columns ({len(df.columns)}): " + ", ".join(f"{c} ({df[c].dtype})" for c in df.columns),
        f"Row count: {row_count}",
    ]

    # Sample rows come BEFORE aggregate stats, deliberately. A real run
    # showed an agent cite the aggregate describe() line verbatim as
    # "evidence" (e.g. "mean=85 std=136 min=-22 max=284") instead of a
    # specific segment — putting per-row data first, and labeling the
    # aggregate stats as unsuitable for direct citation, is a structural
    # nudge toward the agent-prompt rule added alongside this fix (see
    # agents/prompts.py). Neither alone is a guarantee, but doing both
    # costs nothing and compounds.
    sample = df.head(sample_rows)
    if not sample.empty:
        lines.append(f"Sample rows (first {len(sample)} of {row_count}) — cite THESE specific rows as evidence, not the aggregate stats below:")
        lines.append(sample.to_string(index=False))

    if stats:
        lines.append(
            "\nAggregate summary statistics (numeric columns) — for orientation only, "
            "NOT directly citable as evidence; cite a specific row above instead:"
        )
        for col, col_stats in stats.items():
            mean = col_stats.get("mean")
            std = col_stats.get("std")
            cmin = col_stats.get("min")
            cmax = col_stats.get("max")
            lines.append(
                f"  {col}: mean={mean:.3g} std={std:.3g} min={cmin:.3g} max={cmax:.3g}"
            )

    return "\n".join(lines), stats, row_count


def ingest_document(filename: str, raw_bytes: bytes) -> UploadedDocument:
    if len(raw_bytes) > settings.max_document_size_bytes:
        raise DocumentTooLargeError(
            f"'{filename}' is {len(raw_bytes)} bytes, exceeding the "
            f"{settings.max_document_size_bytes} byte cap."
        )

    # Strip path components — the filename comes from the client and may
    # contain directory traversal (../../etc/passwd.csv).
    filename = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not filename:
        filename = "upload"

    kind = _infer_kind(filename)
    _validate_content_type(raw_bytes, kind)
    
    document_id = str(uuid.uuid4())[:12]

    if kind == DocumentKind.PDF:
        extracted_text = extract_pdf_text(raw_bytes, settings.max_extracted_chars_per_document)
        summary_stats, row_count = None, None
    else:
        extracted_text, summary_stats, row_count = summarize_csv(raw_bytes, settings.csv_sample_rows)
        if len(extracted_text) > settings.max_extracted_chars_per_document:
            extracted_text = extracted_text[: settings.max_extracted_chars_per_document].rsplit("\n", 1)[0] + "\n…"

    validate_document_text(extracted_text, filename)  # logs a warning if flagged; see security.py

    return UploadedDocument(
        document_id=document_id,
        filename=filename,
        kind=kind,
        extracted_text=extracted_text or "(no extractable text found)",
        summary_stats=summary_stats,
        row_count=row_count,
        uploaded_at=_now_iso(),
        size_bytes=len(raw_bytes),
    )


def build_evidence_block(documents: list[UploadedDocument]) -> str:
    """Formats resolved documents into the block injected alongside the
    decision text — wrapped as untrusted data by security.py at the call
    site, exactly like the decision text itself (SPEC.md §5.1, security
    treatment)."""
    if not documents:
        return ""

    sections = ["Supporting documents provided by the user:\n"]
    for doc in documents:
        kind_label = "PDF excerpt" if doc.kind == DocumentKind.PDF else "CSV summary"
        sections.append(f"[{doc.filename} — {kind_label}]\n{doc.extracted_text}\n")

    return "\n".join(sections)
