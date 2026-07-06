"""
LangGraph wiring for the RedCouncil debate flow (SPEC.md §7).

    validate_input --> round_1_fanout --> detect_conflicts --> round_2_fanout --> synthesize
           \\_________________________ compute_baseline (parallel branch) ________________/

`compute_baseline` runs concurrently with the main debate path and its result
is merged in at `synthesize`, so it never adds latency to the critical path.

Each node appends structured events to state["events"] as it progresses —
main.py drains these into the SSE stream as they're written.
"""

from __future__ import annotations

import asyncio
import time

from langgraph.graph import END, StateGraph

from app.agents.council import run_adversarial_agent, run_baseline, run_synthesizer
from app.conflict_detection import detect_conflicts
from app.models import AgentOutput, AgentRole, BaselineComparison
from app.security import validate_decision_text
from app.state import CouncilState

ADVERSARIAL_ROLES = [
    AgentRole.GROWTH,
    AgentRole.RISK,
    AgentRole.LEGAL,
    AgentRole.TECH_DEBT,
    AgentRole.CUSTOMER,
]


def _emit(state: CouncilState, event_type: str, payload: dict) -> None:
    state.setdefault("events", []).append(
        {"type": event_type, "timestamp": time.time(), "payload": payload}
    )


async def node_validate_input(state: CouncilState) -> CouncilState:
    result = validate_decision_text(
        state["decision"].decision_text, max_length=len(state["decision"].decision_text) + 1
    )
    state["decision"].decision_text = result.cleaned_text
    state["started_at"] = time.monotonic()
    _emit(state, "validation_complete", {"flagged": result.flagged})
    return state


async def node_round_1_fanout(state: CouncilState) -> CouncilState:
    decision = state["decision"]

    async def run_one(role: AgentRole) -> AgentOutput:
        _emit(state, "agent_started", {"agent": role.value, "round": 1})
        output = await run_adversarial_agent(
            role, round_num=1, decision_text=decision.decision_text, context=decision.context
        )
        # Include the full output (not just a latency number) so the UI can
        # render live findings per seat as they land, not just a status dot.
        _emit(
            state,
            "agent_completed",
            {"agent": role.value, "round": 1, "latency_ms": output.latency_ms, "output": output.model_dump(mode="json")},
        )
        return output

    results = await asyncio.gather(*(run_one(role) for role in ADVERSARIAL_ROLES))
    state["round_1_outputs"] = {role.value: out for role, out in zip(ADVERSARIAL_ROLES, results)}
    return state


async def node_detect_conflicts(state: CouncilState) -> CouncilState:
    conflicts = detect_conflicts(state["round_1_outputs"])
    state["conflicts"] = conflicts
    _emit(state, "conflict_detected", {"count": len(conflicts)})
    return state


async def node_round_2_fanout(state: CouncilState) -> CouncilState:
    decision = state["decision"]
    round_1 = state["round_1_outputs"]
    conflicts = state["conflicts"]
    hitl_note = state.get("hitl_note")

    _emit(state, "round_2_started", {})

    async def run_one(role: AgentRole) -> AgentOutput:
        own = round_1[role.value]
        others = {AgentRole(r): out for r, out in round_1.items() if r != role.value}
        relevant = [c for c in conflicts if role in (c.agent_a, c.agent_b)]

        _emit(state, "agent_started", {"agent": role.value, "round": 2})
        output = await run_adversarial_agent(
            role,
            round_num=2,
            decision_text=decision.decision_text,
            context=decision.context,
            own_round_1=own,
            other_round_1=others,
            relevant_conflicts=relevant,
            hitl_note=hitl_note,
        )
        _emit(
            state,
            "agent_completed",
            {"agent": role.value, "round": 2, "latency_ms": output.latency_ms, "output": output.model_dump(mode="json")},
        )
        return output

    results = await asyncio.gather(*(run_one(role) for role in ADVERSARIAL_ROLES))
    state["round_2_outputs"] = {role.value: out for role, out in zip(ADVERSARIAL_ROLES, results)}
    return state


async def node_compute_baseline(state: CouncilState) -> CouncilState:
    decision = state["decision"]
    baseline_output = await run_baseline(decision.decision_text, decision.context)
    state["baseline_raw_findings"] = [f.claim for f in baseline_output.findings]
    _emit(state, "baseline_ready", {"findings_count": len(baseline_output.findings)})
    return state


async def node_synthesize(state: CouncilState) -> CouncilState:
    _emit(state, "synthesis_started", {})
    report = await run_synthesizer(
        state["decision"].decision_text,
        state["round_1_outputs"],
        state["round_2_outputs"],
        state["conflicts"],
    )

    all_council_claims = {
        f.claim
        for out in list(state["round_1_outputs"].values()) + list(state["round_2_outputs"].values())
        for f in out.findings
    }
    baseline_claims = set(state.get("baseline_raw_findings", []))
    report.single_agent_baseline_comparison = BaselineComparison(
        baseline_findings_count=len(baseline_claims),
        council_findings_count=len(all_council_claims),
        baseline_distinct_categories=len(baseline_claims),
        council_distinct_categories=len(report.vulnerabilities),
        categories_missed_by_baseline=[
            v.title for v in report.vulnerabilities if len(v.raised_by) >= 1
        ][: max(0, len(report.vulnerabilities) - len(baseline_claims))],
    )

    report.total_latency_ms = int((time.monotonic() - state["started_at"]) * 1000)
    state["report"] = report
    _emit(state, "report_ready", {"report": report.model_dump(mode="json")})
    return state


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

    return graph.compile()


council_graph = build_graph()
