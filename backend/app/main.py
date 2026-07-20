"""
RedCouncil API. See SPEC.md §8 for the full endpoint contract.

Run locally:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from app.auth import verify_clerk_token, verify_clerk_token_query
from app.rate_limit import decision_rate_limiter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings
from app.graph import council_graph
from app.ingestion import DocumentTooLargeError, UnsupportedDocumentError, ingest_document
from app.models import DecisionInput, DecisionRecord, DecisionStatus, UploadedDocument
from app import db, document_store as document_store_module, object_store, sse, store as store_module

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("redcouncil.api")

async def _get_owned_decision(decision_id: str, user_id: str) -> DecisionRecord:
    """Fetch a decision and verify the caller owns it. Returns 404 for
    both 'does not exist' and 'exists but owned by another user' —
    intentionally indistinguishable to avoid leaking valid decision IDs."""
    record = await store_module.store.get(decision_id)
    if record is None or record.user_id != user_id:
        raise HTTPException(404, "unknown decision_id")
    return record

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initializes the Postgres pool (Alibaba Cloud RDS) if DATABASE_URL is
    # set — see db.py. store.py/document_store.py pick PostgresStore vs.
    # InMemoryStore at import time based on the same setting, so this must
    # run before any request is served, not lazily on first use.
    await db.init_pool()
    yield
    await db.close_pool()

app = FastAPI(title="RedCouncil API", version="1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DecisionRequest(BaseModel):
    decision_text: str
    context: str | None = None
    supporting_document_ids: list[str] = []


class DecisionResponse(BaseModel):
    decision_id: str
    stream_url: str


class HitlNoteRequest(BaseModel):
    note: str


@app.post("/api/v1/documents", response_model=UploadedDocument)
async def upload_document(file: UploadFile = File(...), user_id: str = Depends(verify_clerk_token)) -> UploadedDocument:
    """Extracts/summarizes a PDF or CSV synchronously and returns it for
    later reference by document_id. See SPEC.md §5.1 for scope boundaries —
    this deliberately does not attempt OCR or arbitrary simulation formats."""
    max_size = settings.max_document_size_bytes
    raw_bytes = await file.read(max_size + 1)
    if len(raw_bytes) > max_size:
        raise HTTPException(413, f"File exceeds the {max_size} byte limit.")

    try:
        document = ingest_document(file.filename or "upload", raw_bytes)
    except UnsupportedDocumentError as exc:
        raise HTTPException(400, str(exc)) from exc
    except DocumentTooLargeError as exc:
        raise HTTPException(413, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — malformed PDF/CSV content
        logger.exception("Failed to ingest document '%s'", file.filename)
        raise HTTPException(422, f"Could not process '{file.filename}': {exc}") from exc

    # Archive the original file in object storage (Alibaba Cloud OSS, or the
    # local-filesystem fallback in dev — see object_store.py) *before*
    # persisting the document record, so object_key is available for the
    # single create() call below. Best-effort: an OSS failure degrades to
    # object_key=None (no original file available for re-download) rather
    # than blocking the upload — extracted_text alone is sufficient for the
    # council to run.
    object_key = object_store.build_object_key(document.document_id, document.filename)
    try:
        await object_store.object_store.upload(object_key, raw_bytes)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to archive original file for document_id=%s", document.document_id)
        object_key = None

    await document_store_module.document_store.create(document, object_key=object_key)
    return document


@app.post("/api/v1/decisions", response_model=DecisionResponse)
async def submit_decision(req: DecisionRequest, user_id: str = Depends(verify_clerk_token)) -> DecisionResponse:
    if len(req.decision_text.strip()) < 10:
        raise HTTPException(400, "decision_text must be at least 10 characters")

    if len(req.supporting_document_ids) > settings.max_documents_per_decision:
        raise HTTPException(
            400, f"At most {settings.max_documents_per_decision} supporting documents are allowed"
        )

    decision_rate_limiter.check_and_increment(user_id)

    try:
        documents = await document_store_module.document_store.get_many(req.supporting_document_ids)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc

    decision_id = str(uuid.uuid4())
    decision_input = DecisionInput(
        decision_text=req.decision_text,
        context=req.context,
        supporting_document_ids=req.supporting_document_ids,
    )

    record = DecisionRecord(
        id=decision_id,
        decision_text=decision_input.decision_text,
        context=decision_input.context,
        submitted_at=decision_input.submitted_at,
        status=DecisionStatus.RUNNING,
        user_id=user_id,
    )
    await store_module.store.create(record)

    initial_state = {
        "decision_id": decision_id,
        "decision": decision_input,
        "documents": documents,
        "events": [],
    }

    sse.create_channel(decision_id)
    asyncio.create_task(_run_council(decision_id, initial_state))

    return DecisionResponse(decision_id=decision_id, stream_url=f"/api/v1/decisions/{decision_id}/stream")


async def _run_council(
    decision_id: str, input_data: dict | None
) -> None:
    """Runs the graph and forwards every event it appends to the SSE channel.
    Kept as a background task so submit_decision returns immediately."""
    config = {"configurable": {"thread_id": decision_id}}
    
    try:
        # LangGraph's ainvoke runs the whole graph to completion; we poll
        # state["events"] via astream to forward events as they land instead
        # of waiting for the entire run to finish before streaming anything.
        last_emitted = 0
        final_state = None
        async for state in council_graph.astream(input_data, config=config, stream_mode="values"):
            events = state.get("events", [])
            for event in events[last_emitted:]:
                sse.publish(decision_id, event)
            last_emitted = len(events)
            final_state = state

        state_snapshot = await council_graph.aget_state(config)
        if state_snapshot.next:
            # The graph is paused (e.g. for HITL). We emit an event but do NOT
            # close the SSE channel or mark the decision complete.
            sse.publish(decision_id, {"type": "hitl_paused", "timestamp": "ISO8601", "payload": {}})
            return

        record = await store_module.store.get(decision_id)
        if record is None:
            return

        report = final_state.get("report") if final_state else None
        if report is None:
            raise RuntimeError("Graph completed without producing a report")

        record.status = DecisionStatus.COMPLETE
        record.report = report
        record.raw_agent_outputs = list(final_state["round_1_outputs"].values()) + list(
            final_state["round_2_outputs"].values()
        )
        record.total_latency_ms = report.total_latency_ms
        await store_module.store.update(record)

    except Exception as exc:  # noqa: BLE001
        logger.exception("Council run failed for decision_id=%s", decision_id)
        sse.publish(decision_id, {"type": "error", "timestamp": "ISO8601", "payload": {"message": str(exc)}})
        record = await store_module.store.get(decision_id)
        if record:
            record.status = DecisionStatus.ERROR
            record.error = str(exc)
            await store_module.store.update(record)
    finally:
        state_snapshot = await council_graph.aget_state(config)
        if not state_snapshot.next:
            sse.close_channel(decision_id)


@app.get("/api/v1/decisions/{decision_id}/stream")
async def stream_decision(decision_id: str, user_id: str = Depends(verify_clerk_token_query)) -> StreamingResponse:
    record = await _get_owned_decision(decision_id, user_id)
    return StreamingResponse(sse.subscribe(decision_id), media_type="text/event-stream")


@app.get("/api/v1/decisions/{decision_id}")
async def get_decision(decision_id: str, user_id: str = Depends(verify_clerk_token)) -> DecisionRecord:
    record = await _get_owned_decision(decision_id, user_id)
    return record


@app.get("/api/v1/decisions/{decision_id}/baseline")
async def get_baseline(decision_id: str, user_id: str = Depends(verify_clerk_token)):
    record = await _get_owned_decision(decision_id, user_id)
    if record.report is None:
        raise HTTPException(202, "report not ready yet")
    return record.report.single_agent_baseline_comparison


@app.get("/api/v1/decisions/{decision_id}/state")
async def get_decision_state(decision_id: str, user_id: str = Depends(verify_clerk_token)):
    record = await _get_owned_decision(decision_id, user_id)
        
    config = {"configurable": {"thread_id": decision_id}}
    state_snapshot = await council_graph.aget_state(config)
    
    values = state_snapshot.values or {}
    
    return {
        "status": record.status,
        "is_paused": bool(state_snapshot.next),
        "round_1_outputs": values.get("round_1_outputs", {}),
        "round_2_outputs": values.get("round_2_outputs", {}),
        "conflict_count": values.get("conflict_count") if "conflict_count" in values else len(values.get("conflicts", [])),
        "report": values.get("report")
    }


@app.post("/api/v1/decisions/{decision_id}/hitl-note")
async def submit_hitl_note(decision_id: str, req: HitlNoteRequest, user_id: str = Depends(verify_clerk_token)):
    await _get_owned_decision(decision_id, user_id)
    if not settings.enable_hitl_gate:
        raise HTTPException(400, "HITL gate is disabled (set ENABLE_HITL_GATE=true)")
    
    config = {"configurable": {"thread_id": decision_id}}
    state = await council_graph.aget_state(config)
    if not state.next:
        raise HTTPException(400, "Graph is not paused for HITL")
        
    await council_graph.aupdate_state(config, {"hitl_note": req.note})
    asyncio.create_task(_run_council(decision_id, None))
    return {"status": "resumed"}


@app.get("/api/v1/decisions", response_model=list[DecisionRecord])
async def list_decisions(user_id: str = Depends(verify_clerk_token)):
    return await store_module.store.list_by_user(user_id=user_id)


@app.get("/api/v1/usage")
async def get_usage(user_id: str = Depends(verify_clerk_token)):
    """Lets the frontend show a small "N/5 reviews used today" indicator --
    read-only, doesn't consume any quota itself."""
    return decision_rate_limiter.status(user_id)


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
