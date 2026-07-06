"""
Object storage for original uploaded file bytes (Alibaba Cloud OSS).

Extracted/summarized text lives in Postgres (documents table, see
db.py/schema.sql) — OSS only holds the *original* file, referenced by an
object_key stored alongside the extracted text. This split keeps Postgres
rows small and bounded (extracted_text is capped, see config.py) while
still archiving the source file for audit trail / re-extraction if parsing
logic improves later.

oss2 (the official Alibaba Cloud SDK) is synchronous/blocking, so calls are
wrapped in asyncio.to_thread to avoid stalling the event loop.

Falls back to a local-filesystem-backed store when OSS credentials aren't
configured, mirroring the DATABASE_URL-unset fallback pattern in db.py —
this keeps local dev and this test suite runnable without live Alibaba
Cloud credentials. LocalFilesystemObjectStore is explicitly NOT for
production use (see its docstring).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

from app.config import settings

logger = logging.getLogger("redcouncil.object_store")


class ObjectStoreProtocol(Protocol):
    async def upload(self, object_key: str, raw_bytes: bytes) -> None: ...
    async def download(self, object_key: str) -> bytes: ...


def build_object_key(document_id: str, filename: str) -> str:
    return f"redcouncil/documents/{document_id}/{filename}"


class OssObjectStore:
    """Alibaba Cloud OSS-backed store — used in production when OSS
    credentials are configured. NOTE: written against the documented oss2
    API but not executed against a live bucket in this environment — smoke
    test this against a real bucket before relying on it (see TASK.md §6)."""

    def __init__(self) -> None:
        import oss2  # imported lazily so the module doesn't hard-require it

        auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
        self._bucket = oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket_name)

    def _upload_sync(self, object_key: str, raw_bytes: bytes) -> None:
        self._bucket.put_object(object_key, raw_bytes)

    def _download_sync(self, object_key: str) -> bytes:
        return self._bucket.get_object(object_key).read()

    async def upload(self, object_key: str, raw_bytes: bytes) -> None:
        await asyncio.to_thread(self._upload_sync, object_key, raw_bytes)

    async def download(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._download_sync, object_key)


class LocalFilesystemObjectStore:
    """Fallback used when OSS credentials aren't configured — writes to a
    local directory. NOT for production use: no redundancy, no access
    control, disappears if the container filesystem resets. Exists purely
    so the ingestion pipeline is runnable/testable without live Alibaba
    Cloud credentials (local dev, CI, this project's own test suite)."""

    def __init__(self, base_dir: str = "/tmp/redcouncil-objects") -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, object_key: str) -> Path:
        # Flatten the key into a single filename — good enough for a local
        # dev fallback, not trying to replicate OSS's directory semantics.
        return self.base_dir / object_key.replace("/", "__")

    async def upload(self, object_key: str, raw_bytes: bytes) -> None:
        await asyncio.to_thread(self._path_for(object_key).write_bytes, raw_bytes)

    async def download(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._path_for(object_key).read_bytes)


def _build_object_store() -> ObjectStoreProtocol:
    if settings.oss_access_key_id and settings.oss_bucket_name:
        logger.info("Using Alibaba Cloud OSS for document storage (bucket=%s)", settings.oss_bucket_name)
        return OssObjectStore()
    logger.warning(
        "OSS credentials not set — falling back to LocalFilesystemObjectStore. "
        "This is fine for local dev/testing but NOT for production deployment."
    )
    return LocalFilesystemObjectStore()


object_store: ObjectStoreProtocol = _build_object_store()
