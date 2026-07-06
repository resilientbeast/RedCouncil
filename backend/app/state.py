"""
Shared state that flows through the LangGraph graph (see graph.py).

CouncilState is intentionally a plain TypedDict rather than a Pydantic model —
LangGraph reducers work most naturally against dict-shaped state, and each
field is already Pydantic-validated at the point it's produced by an agent
call, so re-validating the whole state on every node transition would be
redundant.
"""

from __future__ import annotations

from typing import Any, TypedDict, Annotated
import operator

from app.models import AgentOutput, BaselineComparison, DecisionInput, DetectedConflict, VulnerabilityReport, UploadedDocument


class CouncilState(TypedDict, total=False):
    decision_id: str
    decision: DecisionInput
    documents: list[UploadedDocument]

    round_1_outputs: dict[str, AgentOutput]
    conflicts: list[DetectedConflict]
    round_2_outputs: dict[str, AgentOutput]

    baseline: BaselineComparison | None
    baseline_raw_findings: list[str]

    report: VulnerabilityReport | None

    hitl_note: str | None

    # Append-only log consumed by sse.py to stream progress to clients.
    # Each entry: {"type": str, "timestamp": str, "payload": dict}
    events: Annotated[list[dict[str, Any]], operator.add]

    started_at: float  # time.monotonic(), for latency accounting
