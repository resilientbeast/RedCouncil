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

import logging

from app.agents.prompts import BASELINE_PROMPT, PROMPTS_BY_ROLE, SYNTHESIZER_PROMPT
from app.agents.qwen_client import call_agent
from app.ingestion import build_evidence_block
from app.models import AgentOutput, AgentRole, DetectedConflict, ResolvedVulnerability, UploadedDocument, VulnerabilityReport
from app.security import wrap_as_data_block, wrap_evidence_as_data_block

logger = logging.getLogger("redcouncil.synthesis")


def _round_1_user_content(decision_text: str, context: str | None, documents: list[UploadedDocument] | None = None) -> str:
    parts = [wrap_as_data_block(decision_text)]
    if context:
        parts.append(f"\nAdditional context:\n{context}")
    evidence_block = wrap_evidence_as_data_block(build_evidence_block(documents or []))
    if evidence_block:
        parts.append(f"\n{evidence_block}")
    return "\n".join(parts)


def _round_2_user_content(
    decision_text: str,
    context: str | None,
    own_round_1: AgentOutput,
    other_round_1: dict[AgentRole, AgentOutput],
    relevant_conflicts: list[DetectedConflict],
    hitl_note: str | None,
    documents: list[UploadedDocument] | None = None,
) -> str:
    lines = [
        _round_1_user_content(decision_text, context, documents),
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
    documents: list[UploadedDocument] | None = None,
    own_round_1: AgentOutput | None = None,
    other_round_1: dict[AgentRole, AgentOutput] | None = None,
    relevant_conflicts: list[DetectedConflict] | None = None,
    hitl_note: str | None = None,
) -> AgentOutput:
    system_prompt = PROMPTS_BY_ROLE[role.value]

    if round_num == 1:
        user_content = _round_1_user_content(decision_text, context, documents)
    else:
        assert own_round_1 is not None and other_round_1 is not None
        user_content = _round_2_user_content(
            decision_text, context, own_round_1, other_round_1, relevant_conflicts or [], hitl_note, documents
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


async def run_baseline(
    decision_text: str, context: str | None, documents: list[UploadedDocument] | None = None
) -> AgentOutput:
    """Single unconstrained call used only for the efficiency-gain comparison
    (SPEC.md §15) — not part of the council's critical path. Sees the same
    evidence as the council agents so the comparison is apples-to-apples."""
    parsed, latency_ms = await call_agent(
        system_prompt=BASELINE_PROMPT,
        user_content=_round_1_user_content(decision_text, context, documents),
        output_schema=AgentOutput,
    )
    parsed.agent = AgentRole.BASELINE
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

    user_content = "\n".join(lines)

    # Synthesizer output omits total_latency_ms and single_agent_baseline_comparison
    # (those get filled in by the caller after this returns) — but the schema
    # requires them, so we validate a superset and let the caller patch it.
    report, _latency_ms = await call_agent(
        system_prompt=SYNTHESIZER_PROMPT,
        user_content=user_content,
        output_schema=VulnerabilityReport,
        temperature=0.2,  # arbitration should be more deterministic than advocacy
    )

    # Structural safety net, not a substitute for prompt quality. A live run
    # showed the Synthesizer collapse 5 distinct 9/10-severity findings (one
    # per mandate) into a single vulnerability, silently dropping Legal's
    # and TechDebt's top-severity findings from the report entirely. The
    # prompt already asks for "typically 4-8" vulnerabilities, but a soft
    # instruction alone didn't hold up against messy real input — this
    # checks compliance directly and bounded-retries for coverage, the
    # same pattern qwen_client.py uses for schema validation failures.
    missing_roles = check_synthesis_coverage(round_1_outputs, round_2_outputs, report)
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        if not missing_roles:
            break
        retry_correction = (
            f"{user_content}\n\n"
            "Your previous report did not include a distinct vulnerability covering these "
            f"mandates: {', '.join(missing_roles)}. "
            "Revise your report: either add a distinct vulnerability for each missing mandate's "
            "top concern, or fold it into an existing vulnerability and add that mandate's role to "
            "raised_by or contested_by so it isn't silently dropped from the report."
        )
        retried_report, _latency_ms = await call_agent(
            system_prompt=SYNTHESIZER_PROMPT,
            user_content=retry_correction,
            output_schema=VulnerabilityReport,
            temperature=0.2,
        )
        still_missing = check_synthesis_coverage(round_1_outputs, round_2_outputs, retried_report)
        logger.info(
            "Synthesis coverage retry attempt %d/%d: missing=%s -> still_missing=%s",
            attempt, max_retries, missing_roles, still_missing,
        )
        if len(still_missing) <= len(missing_roles):
            report = retried_report
            missing_roles = still_missing

    # Deterministic correction, not another LLM call. The Synthesizer's own
    # prompt rule states "red_flags must list every vulnerability with
    # severity_score >= 8, regardless of consensus status" -- a live run
    # showed this followed inconsistently (reports with 4-5 vulnerabilities
    # scored >=8 carried only 2 entries in red_flags). This is pure
    # arithmetic over data already in the report, so there's no reason to
    # leave it to chance the way the vulnerability grouping itself
    # necessarily is.
    recompute_red_flags(report)

    return report


def recompute_red_flags(report: VulnerabilityReport, severity_threshold: int = 8) -> None:
    """
    Overwrites report.red_flags in place from the vulnerabilities' own
    severity scores, rather than trusting the model to have correctly
    applied its own stated rule. Mutates report directly (matches how
    total_latency_ms and single_agent_baseline_comparison are already
    patched onto the report after the fact in graph.py's node_synthesize).
    """
    report.red_flags = [v.title for v in report.vulnerabilities if v.severity_score >= severity_threshold]


def check_synthesis_coverage(
    round_1_outputs: dict[str, AgentOutput],
    round_2_outputs: dict[str, AgentOutput],
    report: VulnerabilityReport,
    severity_threshold: int = 1,
) -> list[str]:
    """
    Returns agent roles that raised a finding scoring >= severity_threshold
    in either round but don't appear in raised_by or contested_by of ANY
    vulnerability in the final report — i.e. mandates whose perspective was
    silently dropped during synthesis rather than merged or contested.
    """
    high_severity_roles: set[AgentRole] = set()
    for output in list(round_1_outputs.values()) + list(round_2_outputs.values()):
        if any(f.severity >= severity_threshold for f in output.findings):
            high_severity_roles.add(output.agent)

    covered_roles: set[AgentRole] = set()
    for vuln in report.vulnerabilities:
        covered_roles.update(vuln.raised_by)
        covered_roles.update(vuln.contested_by)

    return sorted(role.value for role in (high_severity_roles - covered_roles))
