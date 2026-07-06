"""
Pydantic schemas for RedCouncil.

These are the contract every agent call, the LangGraph state, and the API
responses are validated against. See SPEC.md §5 for the design rationale.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

import json
from pydantic import BaseModel, Field, field_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentRole(str, Enum):
    GROWTH = "growth"
    RISK = "risk"
    LEGAL = "legal"
    TECH_DEBT = "tech_debt"
    CUSTOMER = "customer"
    BASELINE = "baseline"


class DocumentKind(str, Enum):
    PDF = "pdf"
    CSV = "csv"


class UploadedDocument(BaseModel):
    document_id: str
    filename: str
    kind: DocumentKind
    extracted_text: str = Field(..., description="Text injected into agent prompts — truncated/summarized, see §5.1")
    summary_stats: dict | None = Field(None, description="CSV only: per-column numeric statistics")
    row_count: int | None = Field(None, description="CSV only")
    uploaded_at: str
    size_bytes: int


class DecisionInput(BaseModel):
    decision_text: str = Field(..., min_length=10, max_length=2000)
    context: str | None = Field(None, max_length=4000, description="Optional extra background")
    submitted_at: str = Field(default_factory=now_iso)
    supporting_document_ids: list[str] = Field(default_factory=list)


class AgentFinding(BaseModel):
    claim: str = Field(..., description="One specific finding, not a summary")
    severity: int = Field(..., ge=1, le=10)
    reasoning: str = Field(..., description="Why this matters, grounded in the decision text")
    evidence: list[str] = Field(default_factory=list, description="Concrete facts, precedents, or tool-retrieved data")

    @field_validator("evidence", mode="before")
    @classmethod
    def coerce_evidence_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v_stripped = v.strip().lower()
            if v_stripped in ("[]", "none", "", "null", "n/a"):
                return []
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(i) for i in parsed]
            except Exception:
                pass
            return [v]
        if not isinstance(v, list):
            return [str(v)]
        return [str(i) for i in v]


class AgentOutput(BaseModel):
    agent: AgentRole
    round: Literal[1, 2]
    overall_position: str = Field(..., description="One-sentence stance on the decision")
    findings: list[AgentFinding] = Field(..., min_length=1, max_length=5)
    rebuts: list[AgentRole] = Field(default_factory=list, description="Agent roles this output directly rebuts (round 2 only)")
    latency_ms: int = 0

    @field_validator("rebuts", mode="before")
    @classmethod
    def coerce_rebuts_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v_stripped = v.strip().lower()
            if v_stripped in ("[]", "none", "", "null", "n/a"):
                return []
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
            return [v]
        if not isinstance(v, list):
            return [v]
        return v


class DetectedConflict(BaseModel):
    conflict_id: str
    agent_a: AgentRole
    agent_b: AgentRole
    topic: str
    agent_a_position: str
    agent_b_position: str
    delta_severity: int


class ResolvedVulnerability(BaseModel):
    vulnerability_id: str
    title: str
    raised_by: list[AgentRole]
    contested_by: list[AgentRole] = Field(default_factory=list)
    severity_score: int = Field(..., ge=1, le=10, description="Synthesizer's normalized severity")
    consensus: Literal["agreement", "contested", "unresolved"]
    synthesis: str = Field(..., description="Synthesizer's arbitration reasoning")
    agent_positions: dict[str, str] = Field(
        ...,
        description="role -> that agent's stance on this specific vulnerability",
        json_schema_extra={
            "properties": {
                "growth": {"type": "string"},
                "risk": {"type": "string"},
                "legal": {"type": "string"},
                "tech_debt": {"type": "string"},
                "customer": {"type": "string"}
            }
        }
    )

    @field_validator("raised_by", "contested_by", mode="before")
    @classmethod
    def coerce_agent_role_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v_stripped = v.strip().lower()
            if v_stripped in ("[]", "none", "", "null", "n/a"):
                return []
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
            if "," in v:
                return [r.strip() for r in v.split(",") if r.strip()]
            return [v]
        if not isinstance(v, list):
            return [v]
        return v

    @field_validator("agent_positions", mode="before")
    @classmethod
    def coerce_agent_positions_dict(cls, v):
        if v is None:
            return {}
        
        parsed_dict = {}
        
        if isinstance(v, dict):
            # Normalize keys and extract any merged roles from the values
            for k, val in v.items():
                k_clean = str(k).strip().lower().replace(" ", "_")
                val_str = str(val).strip()
                
                if k_clean in [r.value for r in AgentRole]:
                    # Some models cram ", legal: text" inside the value string
                    # We can do a rudimentary split to rescue them if we see ", <role>:"
                    extracted_roles = {k_clean: val_str}
                    for role_enum in AgentRole:
                        r_name = role_enum.value
                        if r_name == k_clean:
                            continue
                        split_marker = f", {r_name}:"
                        if split_marker in val_str:
                            parts = val_str.split(split_marker, 1)
                            extracted_roles[k_clean] = parts[0].strip()
                            extracted_roles[r_name] = parts[1].strip()
                            val_str = parts[0] # continue checking other roles in the remaining part? No, this is rudimentary but helps.
                    
                    for ext_k, ext_v in extracted_roles.items():
                        if ext_k not in parsed_dict:
                            parsed_dict[ext_k] = ext_v
                        else:
                            parsed_dict[ext_k] += " " + ext_v
            
            if parsed_dict:
                return parsed_dict
                
            return v
            
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return cls.coerce_agent_positions_dict(parsed)
            except Exception:
                pass
            
            clean_str = str(v).strip()
            while clean_str.endswith(",") or clean_str.endswith("\\") or clean_str.endswith('"') or clean_str.endswith("]"):
                clean_str = clean_str[:-1].strip()

            for line in clean_str.split('\n'):
                if ':' in line:
                    key, val = line.split(':', 1)
                    key = key.strip().lower().replace(" ", "_")
                    if key in [r.value for r in AgentRole]:
                        parsed_dict[key] = val.strip()
            
            if parsed_dict:
                return parsed_dict
                
            return {"synthesizer": clean_str}
        return {}


class BaselineComparison(BaseModel):
    baseline_findings_count: int
    council_findings_count: int
    baseline_distinct_categories: int
    council_distinct_categories: int
    categories_missed_by_baseline: list[str]


class VulnerabilityReport(BaseModel):
    decision_text: str
    generated_at: str = Field(default_factory=now_iso)
    vulnerabilities: list[ResolvedVulnerability] = Field(default_factory=list)
    mandate_scores: dict[str, float] = Field(default_factory=dict, description="role -> average severity that agent assigned")
    overall_recommendation: Literal["approved", "approved_with_conditions", "blocked"] = Field(default="approved_with_conditions")
    conditions: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list, description="Severity >= 8 items surfaced regardless of consensus status")
    total_latency_ms: int = 0
    single_agent_baseline_comparison: BaselineComparison | None = None

    @field_validator("conditions", "red_flags", mode="before")
    @classmethod
    def coerce_string_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v_stripped = v.strip().lower()
            if v_stripped in ("[]", "none", "", "null", "n/a"):
                return []
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return [str(i) for i in parsed]
            except Exception:
                pass
            if "," in v:
                return [r.strip() for r in v.split(",") if r.strip()]
            return [v]
        if not isinstance(v, list):
            return [str(v)]
        return [str(i) for i in v]

    @field_validator("mandate_scores", mode="before")
    @classmethod
    def coerce_mandate_scores(cls, v):
        if v is None:
            return {}
        if isinstance(v, dict):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
            return {}
        return {}


class DecisionStatus(str, Enum):
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


class DecisionRecord(BaseModel):
    """Row shape for the persistence layer (see store.py)."""

    id: str
    decision_text: str
    context: str | None
    submitted_at: str
    status: DecisionStatus
    report: VulnerabilityReport | None = None
    raw_agent_outputs: list[AgentOutput] = Field(default_factory=list)
    baseline_comparison: BaselineComparison | None = None
    total_latency_ms: int | None = None
    error: str | None = None
    user_id: str | None = None
