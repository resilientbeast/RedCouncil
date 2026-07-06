"""
Per-agent execution functions. Each wraps prompts.py + qwen_client.py into a
single call that takes a decision (+ optional Round 2 debate context) and
returns a validated AgentOutput.

All five adversarial agents share one code path (`run_adversarial_agent`) —
they differ only by which system prompt and role they're bound to. This
mirrors SPEC.md's instruction that Round 1 and Round 2 use the same system
prompt, with only the user-turn content differing.
"""

from __future__ import annotations

from app.agents.prompts import BASELINE_PROMPT, PROMPTS_BY_ROLE, SYNTHESIZER_PROMPT
from app.agents.qwen_client import call_agent
from app.models import AgentOutput, AgentRole, DetectedConflict, ResolvedVulnerability, VulnerabilityReport
from app.security import wrap_as_data_block


def _round_1_user_content(decision_text: str, context: str | None) -> str:
    parts = [wrap_as_data_block(decision_text)]
    if context:
        parts.append(f"\nAdditional context:\n{context}")
    return "\n".join(parts)


def _round_2_user_content(
    decision_text: str,
    context: str | None,
    own_round_1: AgentOutput,
    other_round_1: dict[AgentRole, AgentOutput],
    relevant_conflicts: list[DetectedConflict],
    hitl_note: str | None,
) -> str:
    lines = [
        _round_1_user_content(decision_text, context),
        "\nThis is Round 2. Here is your own Round 1 position:",
        f"- {own_round_1.overall_position}",
        "\nHere is what the other agents found in Round 1:",
    ]
    for role, output in other_round_1.items():
        lines.append(f"\n[{role.value}] {output.overall_position}")
        for finding in output.findings:
            lines.append(f"  - ({finding.severity}/10) {finding.claim}")

    if relevant_conflicts:
        lines.append("\nThe following direct conflicts involve your findings:")
        for c in relevant_conflicts:
            lines.append(
                f"  - {c.agent_a.value} vs {c.agent_b.value} on \"{c.topic}\" "
                f"(severity gap: {c.delta_severity})"
            )

    if hitl_note:
        lines.append(f"\nHuman reviewer note to weigh in this round: {hitl_note}")

    lines.append(
        "\nProduce your Round 2 output: refine your position, and rebut any "
        "other agent whose Round 1 finding you believe is wrong or "
        "understated, per your mandate's rebuttal rules. Populate `rebuts` "
        "with the roles you're directly rebutting."
    )
    return "\n".join(lines)


async def run_adversarial_agent(
    role: AgentRole,
    *,
    round_num: int,
    decision_text: str,
    context: str | None,
    own_round_1: AgentOutput | None = None,
    other_round_1: dict[AgentRole, AgentOutput] | None = None,
    relevant_conflicts: list[DetectedConflict] | None = None,
    hitl_note: str | None = None,
) -> AgentOutput:
    system_prompt = PROMPTS_BY_ROLE[role.value]

    if round_num == 1:
        user_content = _round_1_user_content(decision_text, context)
    else:
        assert own_round_1 is not None and other_round_1 is not None
        user_content = _round_2_user_content(
            decision_text, context, own_round_1, other_round_1, relevant_conflicts or [], hitl_note
        )

    # We validate against AgentOutput minus the fields we set ourselves
    # (agent, round) by asking the model for those fields and overwriting
    # afterward — simpler than maintaining a second schema per round.
    parsed, latency_ms = await call_agent(
        system_prompt=system_prompt,
        user_content=user_content,
        output_schema=AgentOutput,
    )
    parsed.agent = role
    parsed.round = round_num  # type: ignore[assignment]
    parsed.latency_ms = latency_ms
    return parsed


async def run_baseline(decision_text: str, context: str | None) -> AgentOutput:
    """Single unconstrained call used only for the efficiency-gain comparison
    (SPEC.md §15) — not part of the council's critical path."""
    parsed, latency_ms = await call_agent(
        system_prompt=BASELINE_PROMPT,
        user_content=_round_1_user_content(decision_text, context),
        output_schema=AgentOutput,
    )
    parsed.agent = AgentRole.RISK  # placeholder role tag; baseline isn't mandate-bound
    parsed.round = 1
    parsed.latency_ms = latency_ms
    return parsed


async def run_synthesizer(
    decision_text: str,
    round_1_outputs: dict[str, AgentOutput],
    round_2_outputs: dict[str, AgentOutput],
    conflicts: list[DetectedConflict],
) -> VulnerabilityReport:
    all_outputs = list(round_1_outputs.values()) + list(round_2_outputs.values())

    lines = [f"Decision under review:\n{decision_text}\n", "All agent findings across both rounds:"]
    for output in all_outputs:
        lines.append(f"\n[{output.agent.value} / round {output.round}] {output.overall_position}")
        for finding in output.findings:
            lines.append(f"  - ({finding.severity}/10) {finding.claim} — {finding.reasoning}")

    if conflicts:
        lines.append("\nDetected direct conflicts:")
        for c in conflicts:
            lines.append(
                f"  - {c.agent_a.value} vs {c.agent_b.value} on \"{c.topic}\" "
                f"(severity gap: {c.delta_severity})"
            )

    # Synthesizer output omits total_latency_ms and single_agent_baseline_comparison
    # (those get filled in by the caller after this returns) — but the schema
    # requires them, so we validate a superset and let the caller patch it.
    parsed, _latency_ms = await call_agent(
        system_prompt=SYNTHESIZER_PROMPT,
        user_content="\n".join(lines),
        output_schema=VulnerabilityReport,
        temperature=0.2,  # arbitration should be more deterministic than advocacy
    )
    return parsed
