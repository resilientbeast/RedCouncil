"""
Deterministic conflict detection between Round 1 agent outputs.

SPEC.md §7.3 specifies embedding-based topic similarity (Qwen
text-embedding). This skeleton ships a zero-dependency fallback
(difflib token-overlap similarity) so the graph is runnable without an
embeddings API call on the critical path, and swaps cleanly to embeddings
later — see `topic_similarity_embeddings` below for the drop-in replacement
once you want higher recall on paraphrased findings.

A conflict is registered between two agents' findings when they're judged to
be about the same topic (similarity above THRESHOLD) and their severities
differ by DELTA_THRESHOLD or more.
"""

from __future__ import annotations

import itertools
import re
import uuid
from difflib import SequenceMatcher

from app.models import AgentOutput, DetectedConflict

THRESHOLD = 0.20  # token-overlap similarity threshold for "same topic" (conflict candidates)
DELTA_THRESHOLD = 4  # severity gap that alone counts as a conflict (see note below)

# Separate, stricter threshold used only for count_distinct_topics (the
# baseline-comparison metric), NOT for conflict detection. These are
# different jobs with different precision/recall needs:
#   - Conflict detection (THRESHOLD=0.20) wants HIGH RECALL: catch anything
#     that might be the same topic so Round 2 can address it. False
#     positives just mean an agent gets slightly redundant context; cheap.
#   - Distinct-category counting (CATEGORY_THRESHOLD=0.45) wants HIGH
#     PRECISION: don't merge genuinely different concerns just because they
#     share vocabulary about the same decision. False merges directly
#     understate the council's output diversity, which is the whole number
#     this metric exists to report honestly.
# Calibrated against 5 real, genuinely-distinct findings from a live run
# (one per mandate) landing at 5 distinct categories only at threshold=0.45
# — 0.20-0.40 under-separated them into 3-4 clusters. See
# count_distinct_topics() for why this is applied to Round 1 findings only.
CATEGORY_THRESHOLD = 0.45

# Calibrated against realistic finding pairs (see tests/test_conflict_detection.py):
# genuine same-topic pairs scored 0.228-0.608 on this metric; unrelated pairs
# scored 0.142-0.146. 0.20 sits in the gap. Re-calibrate if you change the
# blend weights below or swap in embeddings.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with",
    "is", "are", "will", "this", "that", "be", "as", "at", "by", "it",
    "from", "into", "your", "their", "not", "can", "has", "have", "was", "were",
}

# Deliberately crude keyword-count heuristic, not a sentiment model — this is
# a same-topic disambiguator, not a general opinion classifier, and doesn't
# need to be more sophisticated than that. See detect_conflicts() docstring
# for why this exists: severity alone is NOT a reliable conflict signal
# between differently-mandated agents.
_POSITIVE_WORDS = {
    "increase", "increases", "grow", "growth", "opportunity", "gain", "benefit",
    "benefits", "improve", "improves", "revenue", "support", "supports", "upside",
    "strategic", "advantage", "manageable", "save", "savings", "reduce",
    "efficient", "efficiency", "streamline", "consolidate", "consolidation",
}
_NEGATIVE_WORDS = {
    "risk", "risks", "churn", "violate", "violation", "burden", "complex",
    "friction", "confusion", "loss", "decrease", "decreases", "concern", "concerns",
    "exposure", "debt", "delay", "fail", "failure", "unpredictable", "undermine",
    "disruption", "disrupt", "interruption", "interrupt", "outage", "downtime",
    "costly", "liability", "noncompliance", "violates",
}


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def topic_similarity(claim_a: str, claim_b: str) -> float:
    """Cheap, dependency-free similarity. Order-independent token overlap
    blended with a sequence-ratio to catch paraphrase-shaped overlap."""
    tokens_a, tokens_b = _tokens(claim_a), _tokens(claim_b)
    if not tokens_a or not tokens_b:
        return 0.0
    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    ratio = SequenceMatcher(None, claim_a.lower(), claim_b.lower()).ratio()
    return 0.6 * jaccard + 0.4 * ratio


def stance_polarity(text: str) -> int:
    """+1 leans positive/favorable, -1 leans negative/concerned, 0 neutral or
    mixed. A same-topic pair with opposite non-zero polarity is a genuine
    conflict even when both agents rate their own severity near the top of
    the scale — which adversarial agents do routinely, since each is
    instructed to advocate forcefully within its own mandate (see
    agents/prompts.py). Severity is "how strong is MY concern," not a
    shared scale across mandates, so comparing severity deltas across
    differently-postured agents (e.g. Growth vs. Risk) systematically
    under-detects real disagreement — this was diagnosed against a live
    run where every agent scored 9/10 on directly opposed conclusions and
    zero conflicts were flagged as a result."""
    text_lower = text.lower()
    pos = sum(1 for w in _POSITIVE_WORDS if w in text_lower)
    neg = sum(1 for w in _NEGATIVE_WORDS if w in text_lower)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


async def topic_similarity_embeddings(claim_a: str, claim_b: str, embed_fn) -> float:
    """
    Drop-in replacement for topic_similarity once you want embedding-based
    matching (better recall on paraphrased findings that share no tokens).
    `embed_fn` is an async function: list[str] -> list[list[float]].
    """
    import numpy as np

    vecs = await embed_fn([claim_a, claim_b])
    a, b = np.array(vecs[0]), np.array(vecs[1])
    return float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))


def detect_conflicts(outputs: dict[str, AgentOutput]) -> list[DetectedConflict]:
    """
    A conflict is flagged between two same-topic findings when EITHER:
      (a) they take opposing stances (one positive-leaning, one negative-
          leaning) — the primary signal for adversarial agents, who are
          each advocating within a fixed mandate and therefore tend to
          score their own top concern highly regardless of whether they
          actually disagree with another agent; or
      (b) their severities differ by DELTA_THRESHOLD or more — a secondary
          signal that still matters when two agents share the same
          stance direction but disagree sharply on magnitude (e.g. both
          "concerned," one rates it 3/10 and the other 9/10).
    Using severity delta as the ONLY signal (the original design) misses
    (a) entirely: two adversarial agents reaching opposite conclusions will
    typically both self-rate near the top of the scale, producing delta≈0
    despite being in direct opposition. See stance_polarity() docstring for
    the live-run failure this was diagnosed against.
    """
    conflicts: list[DetectedConflict] = []
    roles = list(outputs.keys())

    for role_a, role_b in itertools.combinations(roles, 2):
        out_a, out_b = outputs[role_a], outputs[role_b]
        for finding_a in out_a.findings:
            for finding_b in out_b.findings:
                sim = topic_similarity(finding_a.claim, finding_b.claim)
                if sim < THRESHOLD:
                    continue

                delta = abs(finding_a.severity - finding_b.severity)
                stance_a, stance_b = stance_polarity(finding_a.claim), stance_polarity(finding_b.claim)
                opposing_stance = stance_a != 0 and stance_b != 0 and stance_a != stance_b

                if opposing_stance or delta >= DELTA_THRESHOLD:
                    conflicts.append(
                        DetectedConflict(
                            conflict_id=str(uuid.uuid4())[:8],
                            agent_a=out_a.agent,
                            agent_b=out_b.agent,
                            topic=finding_a.claim,
                            agent_a_position=finding_a.reasoning,
                            agent_b_position=finding_b.reasoning,
                            delta_severity=delta,
                        )
                    )
    return conflicts


def count_distinct_topics(claims: list[str], threshold: float = CATEGORY_THRESHOLD) -> int:
    """
    Greedy single-pass clustering: walks the claims in order, and a claim
    joins an existing cluster if it's similar enough to that cluster's
    representative (the first claim that started it); otherwise it starts a
    new cluster. Used for the baseline-comparison metric so it isn't hostage
    to Synthesizer grouping quality — a live run showed the Synthesizer
    collapsing 5 distinct high-severity findings into 1 vulnerability, which
    made `len(report.vulnerabilities)` a badly misleading proxy for "how
    many distinct things did the council actually find" (see §3 below).

    IMPORTANT — pass Round 1 findings only, not Round 1 + Round 2 combined.
    Round 2 findings are often close paraphrases of an agent's own Round 1
    position (refined after seeing other agents), and those restatements
    scored LOWER similarity against their own Round 1 origin (~0.31 in a
    real observed case) than CATEGORY_THRESHOLD requires to merge — so
    mixing rounds would double-count the same underlying finding as two
    "distinct categories." Round 1 findings are structurally guaranteed
    independent (see the anti-anchoring rule, SPEC.md §4.1: no agent sees
    another's output before Round 1 completes), which makes them the fair,
    apples-to-apples comparison against a single baseline call — Round 2 is
    agents responding to each other, not contributing new independent
    findings, so it doesn't belong in an "independent findings" count.

    O(n^2) similarity comparisons, which is fine at this scale — Round 1 has
    at most 25 findings (5 agents x up to 5 findings each), the baseline at
    most 5.
    """
    clusters: list[str] = []
    for claim in claims:
        if not any(topic_similarity(claim, representative) >= threshold for representative in clusters):
            clusters.append(claim)
    return len(clusters)


def compute_categories_missed_by_baseline(
    vulnerability_titles: list[str], baseline_claims: list[str], threshold: float = CATEGORY_THRESHOLD
) -> list[str]:
    """
    Returns the subset of council vulnerability titles that have no
    similar counterpart among the baseline's own findings — i.e. things the
    single-agent baseline plausibly didn't surface at all.

    Replaces an earlier version of this logic that computed a slice index
    from raw counts (`[: len(vulnerabilities) - len(baseline_claims)]`)
    without ever checking whether the baseline actually covered a given
    topic — which could report "missed" categories that the baseline had, in
    fact, mentioned, or fail to report ones it hadn't, purely based on list
    length arithmetic. This version checks actual topical overlap instead.
    """
    missed = []
    for title in vulnerability_titles:
        covered = any(topic_similarity(title, claim) >= threshold for claim in baseline_claims)
        if not covered:
            missed.append(title)
    return missed
