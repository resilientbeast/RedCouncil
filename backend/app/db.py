"""
PostgreSQL connection pool (Alibaba Cloud RDS). Replaces the in-memory
stores in store.py and document_store.py when DATABASE_URL is set — see
TASK.md for the full migration rationale and testing notes.

Uses asyncpg directly rather than an ORM (SQLAlchemy, etc.) — deliberate,
matches the rest of this codebase's "thin explicit wrapper" style (see
agents/qwen_client.py). An ORM would pull in more schema-migration and
session-management machinery than a two-table schema needs.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import asyncpg

from app.config import settings

logger = logging.getLogger("redcouncil.db")

_pool: asyncpg.Pool | None = None

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def _init_connection(conn: asyncpg.Connection) -> None:
    # asyncpg returns JSONB as raw text by default; register a codec so
    # every caller gets/sets plain Python dicts/lists transparently instead
    # of hand-rolling json.dumps/loads at every call site.
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def init_pool() -> None:
    """Call once at app startup (see main.py's lifespan handler). No-ops
    with a warning if DATABASE_URL isn't set — callers should check
    get_pool() is not None before using a Postgres-backed store, or rely on
    the store.py/document_store.py factory functions, which already fall
    back to in-memory implementations when this hasn't run."""
    global _pool

    if not settings.database_url:
        logger.warning(
            "DATABASE_URL not set — persistence layer will use in-memory "
            "stores. Data will not survive a restart. Set DATABASE_URL "
            "(Alibaba Cloud RDS in production) before deploying."
        )
        return

    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=10,
        init=_init_connection,
    )
    await _bootstrap_schema()
    logger.info("PostgreSQL pool initialized against %s", _redact(settings.database_url))


async def _bootstrap_schema() -> None:
    assert _pool is not None
    schema_sql = _SCHEMA_PATH.read_text()
    async with _pool.acquire() as conn:
        await conn.execute(schema_sql)


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool | None:
    return _pool


def _redact(dsn: str) -> str:
    """Strips credentials out of a DSN before logging it."""
    if "@" in dsn:
        scheme_and_creds, host_part = dsn.rsplit("@", 1)
        scheme = scheme_and_creds.split("://")[0]
        return f"{scheme}://***@{host_part}"
    return dsn
