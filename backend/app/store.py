"""
Persistence layer for decisions. Defaults to PostgresStore (Alibaba Cloud
RDS) when DATABASE_URL is set; falls back to InMemoryStore otherwise, which
keeps local dev/testing runnable without live cloud credentials — same
pattern as object_store.py's OSS/local-filesystem split.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from app import db
from app.config import settings
from app.models import (
    AgentOutput,
    BaselineComparison,
    DecisionRecord,
    DecisionStatus,
    VulnerabilityReport,
)


class DecisionStoreProtocol(Protocol):
    async def create(self, record: DecisionRecord) -> None: ...
    async def update(self, record: DecisionRecord) -> None: ...
    async def get(self, decision_id: str) -> DecisionRecord | None: ...
    async def list_recent(self, limit: int = 20) -> list[DecisionRecord]: ...
    async def list_by_user(self, user_id: str, limit: int = 20) -> list[DecisionRecord]: ...


class InMemoryStore:
    """Local-dev / offline-test fallback. Data does not survive a restart —
    see PostgresStore for the persistent implementation used in deployment."""

    def __init__(self):
        self._records: dict[str, DecisionRecord] = {}

    async def create(self, record: DecisionRecord) -> None:
        self._records[record.id] = record

    async def update(self, record: DecisionRecord) -> None:
        self._records[record.id] = record

    async def get(self, decision_id: str) -> DecisionRecord | None:
        return self._records.get(decision_id)

    async def list_recent(self, limit: int = 20) -> list[DecisionRecord]:
        return sorted(self._records.values(), key=lambda r: r.submitted_at, reverse=True)[:limit]

    async def list_by_user(self, user_id: str, limit: int = 20) -> list[DecisionRecord]:
        user_records = [r for r in self._records.values() if r.user_id == user_id]
        return sorted(user_records, key=lambda r: r.submitted_at, reverse=True)[:limit]


class PostgresStore:
    """Alibaba Cloud RDS-backed implementation. Requires db.init_pool() to
    have run (see main.py's lifespan handler) before any method is called."""

    async def create(self, record: DecisionRecord) -> None:
        pool = self._pool()
        await pool.execute(
            """
            INSERT INTO decisions
                (id, decision_text, context, submitted_at, status,
                 report, raw_agent_outputs, baseline_comparison, total_latency_ms, error, user_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            """,
            record.id,
            record.decision_text,
            record.context,
            _parse_iso(record.submitted_at),
            record.status.value,
            record.report.model_dump(mode="json") if record.report else None,
            [o.model_dump(mode="json") for o in record.raw_agent_outputs] or None,
            record.baseline_comparison.model_dump(mode="json") if record.baseline_comparison else None,
            record.total_latency_ms,
            record.error,
            record.user_id,
        )

    async def update(self, record: DecisionRecord) -> None:
        pool = self._pool()
        await pool.execute(
            """
            UPDATE decisions
            SET status=$2, report=$3, raw_agent_outputs=$4, baseline_comparison=$5,
                total_latency_ms=$6, error=$7
            WHERE id=$1
            """,
            record.id,
            record.status.value,
            record.report.model_dump(mode="json") if record.report else None,
            [o.model_dump(mode="json") for o in record.raw_agent_outputs] or None,
            record.baseline_comparison.model_dump(mode="json") if record.baseline_comparison else None,
            record.total_latency_ms,
            record.error,
        )

    async def get(self, decision_id: str) -> DecisionRecord | None:
        pool = self._pool()
        row = await pool.fetchrow("SELECT * FROM decisions WHERE id=$1", decision_id)
        return _row_to_record(row) if row else None

    async def list_recent(self, limit: int = 20) -> list[DecisionRecord]:
        pool = self._pool()
        rows = await pool.fetch("SELECT * FROM decisions ORDER BY submitted_at DESC LIMIT $1", limit)
        return [_row_to_record(r) for r in rows]

    async def list_by_user(self, user_id: str, limit: int = 20) -> list[DecisionRecord]:
        pool = self._pool()
        rows = await pool.fetch("SELECT * FROM decisions WHERE user_id=$1 ORDER BY submitted_at DESC LIMIT $2", user_id, limit)
        return [_row_to_record(r) for r in rows]

    @staticmethod
    def _pool():
        pool = db.get_pool()
        if pool is None:
            raise RuntimeError(
                "PostgresStore used before db.init_pool() completed — check "
                "the FastAPI lifespan handler in main.py ran startup first."
            )
        return pool


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _row_to_record(row) -> DecisionRecord:
    return DecisionRecord(
        id=row["id"],
        decision_text=row["decision_text"],
        context=row["context"],
        submitted_at=row["submitted_at"].isoformat(),
        status=DecisionStatus(row["status"]),
        report=VulnerabilityReport.model_validate(row["report"]) if row["report"] else None,
        raw_agent_outputs=[AgentOutput.model_validate(o) for o in (row["raw_agent_outputs"] or [])],
        baseline_comparison=(
            BaselineComparison.model_validate(row["baseline_comparison"]) if row["baseline_comparison"] else None
        ),
        total_latency_ms=row["total_latency_ms"],
        error=row["error"],
        user_id=row["user_id"],
    )


def _build_store() -> DecisionStoreProtocol:
    if settings.database_url:
        return PostgresStore()
    return InMemoryStore()


store: DecisionStoreProtocol = _build_store()
