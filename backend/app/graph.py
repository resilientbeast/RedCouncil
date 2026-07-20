"""
LangGraph wiring for the RedCouncil debate flow (SPEC.md §7).

    validate_input --> round_1_fanout --> detect_conflicts --> round_2_fanout --> synthesize
           \_________________________ compute_baseline (parallel branch) ________________/

`compute_baseline` runs concurrently with the main debate path and its result
is merged in at `synthesize`, so it never adds latency to the critical path.

Each node appends structured events to state["events"] as it progresses —
main.py drains these into the SSE stream as they're written.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from langgraph.graph import END, StateGraph
from langgraph.checkpoint.memory import MemorySaver

from app.agents.council import run_adversarial_agent, run_baseline, run_synthesizer
from app.conflict_detection import compute_categories_missed_by_baseline, count_distinct_topics, detect_conflicts
from app.models import AgentOutput, AgentRole, BaselineComparison, DetectedConflict
from app.security import validate_decision_text
from app.state import CouncilState

ADVERSARIAL_ROLES = [
    AgentRole.GROWTH,
    AgentRole.RISK,
    AgentRole.LEGAL,
    AgentRole.TECH_DEBT,
    AgentRole.CUSTOMER,
]


def _emit(event_type: str, payload: dict) -> dict:
    return {"type": event_type, "timestamp": time.time(), "payload": payload}


async def node_validate_input(state: CouncilState) -> dict:
    decision = state["decision"].model_copy() if hasattr(state["decision"], "model_copy") else state["decision"]
    result = validate_decision_text(
        decision.decision_text, max_length=len(decision.decision_text) + 1
    )
    decision.decision_text = result.cleaned_text
    
    events = [_emit("validation_complete", {"flagged": result.flagged})]

    documents = state.get("documents", [])
    if documents:
        events.append(_emit(
            "documents_attached",
            {"count": len(documents), "filenames": [d.filename for d in documents]},
        ))
    
    return {
        "decision": decision,
        "started_at": time.monotonic(),
        "events": events
    }


async def node_round_1_fanout(state: CouncilState) -> dict:
    decision = state["decision"]
    documents = state.get("documents", [])
    print(f"DEBUG: node_round_1_fanout received {len(documents)} documents")
    events = []

    async def run_one(role: AgentRole) -> tuple[AgentRole, AgentOutput, list[dict]]:
        local_events = [_emit("agent_started", {"agent": role.value, "round": 1})]
        output = await run_adversarial_agent(
            role, round_num=1, decision_text=decision.decision_text, context=decision.context, documents=documents
        )
        # Include the full output (not just a latency number) so the UI can
        # render live findings per seat as they land, not just a status dot.
        local_events.append(_emit(
            "agent_completed",
            {"agent": role.value, "round": 1, "latency_ms": output.latency_ms, "output": output.model_dump(mode="json")},
        ))
        return role, output, local_events

    results = await asyncio.gather(*(run_one(role) for role in ADVERSARIAL_ROLES))
    round_1_outputs = {}
    for role, out, local_events in results:
        round_1_outputs[role.value] = out
        events.extend(local_events)
    
    return {
        "round_1_outputs": round_1_outputs,
        "events": events
    }


async def node_detect_conflicts(state: CouncilState) -> dict:
    conflicts = detect_conflicts(state["round_1_outputs"])
    return {
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "events": [_emit("conflict_detected", {"count": len(conflicts)})]
    }


async def node_hitl_gate(state: CouncilState) -> dict:
    # We no longer use this node for interrupt. The graph uses interrupt_before 
    # natively. We keep it as a no-op pass-through or just remove it.
    pass


async def node_round_2_fanout(state: CouncilState) -> dict:
    decision = state["decision"]
    documents = state.get("documents", [])
    round_1 = state["round_1_outputs"]
    conflicts = state["conflicts"]
    hitl_note = state.get("hitl_note")
    events = [_emit("round_2_started", {})]

    async def run_one(role: AgentRole) -> tuple[AgentRole, AgentOutput, list[dict]]:
        own = round_1[role.value]
        others = {AgentRole(r): out for r, out in round_1.items() if r != role.value}
        relevant = [c for c in conflicts if role in (c.agent_a, c.agent_b)]

        local_events = [_emit("agent_started", {"agent": role.value, "round": 2})]
        output = await run_adversarial_agent(
            role,
            round_num=2,
            decision_text=decision.decision_text,
            context=decision.context,
            documents=documents,
            own_round_1=own,
            other_round_1=others,
            relevant_conflicts=relevant,
            hitl_note=hitl_note,
        )
        local_events.append(_emit(
            "agent_completed",
            {"agent": role.value, "round": 2, "latency_ms": output.latency_ms, "output": output.model_dump(mode="json")},
        ))
        return role, output, local_events

    results = await asyncio.gather(*(run_one(role) for role in ADVERSARIAL_ROLES))
    round_2_outputs = {}
    for role, out, local_events in results:
        round_2_outputs[role.value] = out
        events.extend(local_events)

    existing_conflicts = state.get("conflicts", [])
    seen_pairs: set[frozenset[AgentRole]] = set()
    rebuttal_conflicts: list[DetectedConflict] = []
    for role, out in round_2_outputs.items():
        for rebutted_role in out.rebuts:
            pair = frozenset({out.agent, rebutted_role})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            rebuttal_conflicts.append(
                DetectedConflict(
                    conflict_id=str(uuid.uuid4())[:8],
                    agent_a=out.agent,
                    agent_b=rebutted_role,
                    topic=f"{out.agent.value} rebuts {rebutted_role.value}",
                    agent_a_position=out.overall_position,
                    agent_b_position=round_1.get(rebutted_role.value, out).overall_position,
                    delta_severity=0,
                )
            )
    all_conflicts = existing_conflicts + rebuttal_conflicts
    total_conflict_count = len(all_conflicts)

    events.append(_emit("conflict_detected", {"count": total_conflict_count}))

    return {
        "round_2_outputs": round_2_outputs,
        "conflicts": all_conflicts,
        "conflict_count": total_conflict_count,
        "events": events
    }


async def node_compute_baseline(state: CouncilState) -> dict:
    decision = state["decision"]
    documents = state.get("documents", [])
    baseline_output = await run_baseline(decision.decision_text, decision.context, documents)
    events = [_emit("baseline_ready", {"findings_count": len(baseline_output.findings)})]
    return {
        "baseline_raw_findings": [f.claim for f in baseline_output.findings],
        "events": events
    }


async def node_synthesize(state: CouncilState) -> dict:
    events = [_emit("synthesis_started", {})]
    report = await run_synthesizer(
        state["decision"].decision_text,
        state["round_1_outputs"],
        state["round_2_outputs"],
        state["conflicts"],
    )

    # Round 1 only, deliberately — see count_distinct_topics()'s docstring
    # for why Round 2 findings (which are often close paraphrases of an
    # agent's own Round 1 position) would inflate this count if included.
    # This replaces an earlier version that used len(report.vulnerabilities)
    # directly, which made the metric hostage to Synthesizer grouping
    # quality — a live run showed 5 distinct high-severity findings
    # collapse into 1 vulnerability, reporting a misleading "1 vs 1 tie"
    # against the baseline (see TASK-002).
    round_1_claims = [f.claim for out in state["round_1_outputs"].values() for f in out.findings]
    baseline_claims = state.get("baseline_raw_findings", [])

    report.single_agent_baseline_comparison = BaselineComparison(
        baseline_findings_count=len(baseline_claims),
        council_findings_count=len(round_1_claims),
        baseline_distinct_categories=count_distinct_topics(baseline_claims),
        council_distinct_categories=count_distinct_topics(round_1_claims),
        categories_missed_by_baseline=compute_categories_missed_by_baseline(
            [v.title for v in report.vulnerabilities], baseline_claims
        ),
    )

    report.total_latency_ms = int((time.monotonic() - state["started_at"]) * 1000)
    events.append(_emit("report_ready", {"report": report.model_dump(mode="json")}))
    
    return {
        "report": report,
        "events": events
    }


def build_graph():
    graph = StateGraph(CouncilState)

    graph.add_node("validate_input", node_validate_input)
    graph.add_node("round_1_fanout", node_round_1_fanout)
    graph.add_node("detect_conflicts", node_detect_conflicts)
    graph.add_node("round_2_fanout", node_round_2_fanout)
    graph.add_node("compute_baseline", node_compute_baseline)
    graph.add_node("synthesize", node_synthesize)

    graph.set_entry_point("validate_input")

    # Main debate path.
    graph.add_edge("validate_input", "round_1_fanout")
    graph.add_edge("round_1_fanout", "detect_conflicts")
    graph.add_edge("detect_conflicts", "round_2_fanout")

    # Parallel baseline branch — starts alongside round_1_fanout.
    graph.add_edge("validate_input", "compute_baseline")

    # Join: passing a list of source nodes makes this a barrier — synthesize
    # only fires once BOTH round_2_fanout and compute_baseline have
    # completed, rather than running once per incoming edge. Using two
    # separate add_edge calls here would double-invoke synthesize since the
    # two branches are different lengths (4 hops vs 2 hops from
    # validate_input) and reach the join at different supersteps.
    graph.add_edge(["round_2_fanout", "compute_baseline"], "synthesize")

    graph.add_edge("synthesize", END)

    from app.config import settings
    if settings.enable_hitl_gate:
        return graph.compile(checkpointer=MemorySaver(), interrupt_before=["round_2_fanout"])
    return graph.compile(checkpointer=MemorySaver())


council_graph = build_graph()
