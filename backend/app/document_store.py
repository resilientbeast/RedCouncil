"""
Persistence layer for uploaded documents. Defaults to PostgresDocumentStore
(Alibaba Cloud RDS) when DATABASE_URL is set; falls back to
InMemoryDocumentStore otherwise.

Note the split with object_store.py: extracted_text/summary_stats live here
(Postgres), the *original* file bytes live in OSS — see object_store.py's
docstring for why.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from app import db
from app.config import settings
from app.models import DocumentKind, UploadedDocument


class DocumentStoreProtocol(Protocol):
    async def create(self, document: UploadedDocument, object_key: str | None = None) -> None: ...
    async def get(self, document_id: str) -> UploadedDocument | None: ...
    async def get_many(self, document_ids: list[str]) -> list[UploadedDocument]: ...


class InMemoryDocumentStore:
    """Local-dev / offline-test fallback — see PostgresDocumentStore for the
    persistent implementation used in deployment."""

    def __init__(self):
        self._documents: dict[str, UploadedDocument] = {}

    async def create(self, document: UploadedDocument, object_key: str | None = None) -> None:
        self._documents[document.document_id] = document

    async def get(self, document_id: str) -> UploadedDocument | None:
        return self._documents.get(document_id)

    async def get_many(self, document_ids: list[str]) -> list[UploadedDocument]:
        resolved = [self._documents[doc_id] for doc_id in document_ids if doc_id in self._documents]
        missing = set(document_ids) - {d.document_id for d in resolved}
        if missing:
            raise KeyError(f"Unknown document_id(s): {sorted(missing)}")
        return resolved


class PostgresDocumentStore:
    """Alibaba Cloud RDS-backed implementation. Requires db.init_pool() to
    have run before any method is called."""

    async def create(self, document: UploadedDocument, object_key: str | None = None) -> None:
        pool = self._pool()
        await pool.execute(
            """
            INSERT INTO documents
                (document_id, filename, kind, extracted_text, summary_stats,
                 row_count, uploaded_at, size_bytes, object_key)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            document.document_id,
            document.filename,
            document.kind.value,
            document.extracted_text,
            document.summary_stats,
            document.row_count,
            _parse_iso(document.uploaded_at),
            document.size_bytes,
            object_key,
        )

    async def get(self, document_id: str) -> UploadedDocument | None:
        pool = self._pool()
        row = await pool.fetchrow("SELECT * FROM documents WHERE document_id=$1", document_id)
        return _row_to_document(row) if row else None

    async def get_many(self, document_ids: list[str]) -> list[UploadedDocument]:
        if not document_ids:
            return []
        pool = self._pool()
        rows = await pool.fetch("SELECT * FROM documents WHERE document_id = ANY($1::text[])", document_ids)
        resolved = {r["document_id"]: _row_to_document(r) for r in rows}
        missing = set(document_ids) - set(resolved)
        if missing:
            raise KeyError(f"Unknown document_id(s): {sorted(missing)}")
        return [resolved[d] for d in document_ids]

    @staticmethod
    def _pool():
        pool = db.get_pool()
        if pool is None:
            raise RuntimeError(
                "PostgresDocumentStore used before db.init_pool() completed — "
                "check the FastAPI lifespan handler in main.py ran startup first."
            )
        return pool


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row_to_document(row) -> UploadedDocument:
    return UploadedDocument(
        document_id=row["document_id"],
        filename=row["filename"],
        kind=DocumentKind(row["kind"]),
        extracted_text=row["extracted_text"],
        summary_stats=row["summary_stats"],
        row_count=row["row_count"],
        uploaded_at=row["uploaded_at"].isoformat(),
        size_bytes=row["size_bytes"],
    )


def _build_document_store() -> DocumentStoreProtocol:
    if settings.database_url:
        return PostgresDocumentStore()
    return InMemoryDocumentStore()


document_store: DocumentStoreProtocol = _build_document_store()
