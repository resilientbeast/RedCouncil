-- RedCouncil persistent storage schema (Alibaba Cloud RDS for PostgreSQL).
-- Applied idempotently at startup by app/db.py. No Alembic/migration
-- framework by design (see TASK.md §2, "Explicitly out of scope") — this is
-- intentionally bounded for hackathon-timeline scope. IDs are TEXT, not
-- UUID, because document_id values are short opaque strings (see
-- ingestion.py), not RFC4122 UUIDs.

CREATE TABLE IF NOT EXISTS decisions (
    id TEXT PRIMARY KEY,
    decision_text TEXT NOT NULL,
    context TEXT,
    submitted_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    report JSONB,
    raw_agent_outputs JSONB,
    baseline_comparison JSONB,
    total_latency_ms INT,
    error TEXT,
    user_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_decisions_submitted_at ON decisions (submitted_at DESC);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    kind TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    summary_stats JSONB,
    row_count INT,
    uploaded_at TIMESTAMPTZ NOT NULL,
    size_bytes INT NOT NULL,
    -- Pointer to the original raw file in Alibaba Cloud OSS. NULL if the
    -- object-store upload failed or was skipped (e.g. local dev without OSS
    -- credentials, falling back to LocalFilesystemObjectStore) — a missing
    -- object_key degrades to "no original file available for re-download",
    -- not a hard failure, since extracted_text alone is sufficient for the
    -- council to run.
    object_key TEXT
);

-- Idempotent schema upgrades
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS user_id TEXT;
