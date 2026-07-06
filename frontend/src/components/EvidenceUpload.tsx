import { useRef } from "react";
import type { UploadedDocument } from "../types";

interface Props {
  documents: UploadedDocument[];
  uploading: boolean;
  error: string | null;
  maxDocuments: number;
  disabled: boolean;
  onUpload: (files: FileList | File[]) => void;
  onRemove: (documentId: string) => void;
}

const KIND_LABEL: Record<UploadedDocument["kind"], string> = {
  pdf: "PDF",
  csv: "CSV",
};

function ExhibitLabel(index: number): string {
  // Exhibit A, B, C — matches the case-file metaphor rather than "File 1, 2, 3".
  return `Exhibit ${String.fromCharCode(65 + index)}`;
}

export default function EvidenceUpload({
  documents,
  uploading,
  error,
  maxDocuments,
  disabled,
  onUpload,
  onRemove,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const roomLeft = maxDocuments - documents.length;

  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between mb-2">
        <span className="font-mono text-xs uppercase tracking-widest text-ink-secondary">
          Supporting evidence (optional)
        </span>
        <span className="font-mono text-xs text-ink-secondary">
          {documents.length}/{maxDocuments}
        </span>
      </div>

      {documents.length > 0 && (
        <div className="flex flex-col gap-1.5 mb-2">
          {documents.map((doc, i) => (
            <div
              key={doc.document_id}
              className="flex items-center gap-2 text-sm bg-chamber-panel border border-chamber-line rounded-md px-3 py-1.5"
            >
              <span className="font-mono text-[10px] text-ink-secondary uppercase shrink-0">{ExhibitLabel(i)}</span>
              <span className="text-ink-primary truncate flex-1">{doc.filename}</span>
              <span className="text-[10px] font-mono text-ink-secondary shrink-0">
                {KIND_LABEL[doc.kind]}
                {doc.row_count != null ? ` · ${doc.row_count} rows` : ""}
              </span>
              <button
                type="button"
                onClick={() => onRemove(doc.document_id)}
                disabled={disabled}
                className="text-ink-secondary hover:text-verdict text-xs shrink-0 disabled:opacity-40"
                aria-label={`Remove ${doc.filename}`}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}

      {roomLeft > 0 && (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={disabled || uploading}
          className="w-full text-left text-xs px-3 py-2 rounded-md border border-dashed border-chamber-line text-ink-secondary hover:border-ink-primary hover:text-ink-primary transition-colors disabled:opacity-40"
        >
          {uploading ? "Uploading..." : "+ attach a PDF or CSV as evidence"}
        </button>
      )}

      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.csv"
        multiple
        className="hidden"
        onChange={(e) => {
          if (e.target.files && e.target.files.length > 0) onUpload(e.target.files);
          e.target.value = "";
        }}
      />

      {error && <p className="mt-1.5 text-xs text-verdict">{error}</p>}

      <p className="mt-1.5 text-[11px] text-ink-secondary">
        PDF text is extracted as-is. CSV data is summarized statistically (columns, stats, sample rows) —
        not interpreted as a domain-specific simulation.
      </p>
    </div>
  );
}
