// Mirrors backend/app/models.py. Keep these in sync manually for now — if
// the schema grows, consider generating this file from the FastAPI OpenAPI
// spec (e.g. via openapi-typescript) instead of hand-maintaining it.

export type AgentRole = "growth" | "risk" | "legal" | "tech_debt" | "customer";

export const AGENT_ROLES: AgentRole[] = ["growth", "risk", "legal", "tech_debt", "customer"];

export const AGENT_LABELS: Record<AgentRole, string> = {
  growth: "Growth",
  risk: "Risk",
  legal: "Legal",
  tech_debt: "TechDebt",
  customer: "Customer",
};

export interface AgentFinding {
  claim: string;
  severity: number;
  reasoning: string;
  evidence: string[];
}

export type DocumentKind = "pdf" | "csv";

export interface UploadedDocument {
  document_id: string;
  filename: string;
  kind: DocumentKind;
  extracted_text: string;
  summary_stats: Record<string, Record<string, number>> | null;
  row_count: number | null;
  uploaded_at: string;
  size_bytes: number;
}

export interface AgentOutput {
  agent: AgentRole;
  round: 1 | 2;
  overall_position: string;
  findings: AgentFinding[];
  rebuts: AgentRole[];
  latency_ms: number;
}

export interface ResolvedVulnerability {
  vulnerability_id: string;
  title: string;
  raised_by: AgentRole[];
  contested_by: AgentRole[];
  severity_score: number;
  consensus: "agreement" | "contested" | "unresolved";
  synthesis: string;
  agent_positions: Record<string, string>;
}

export interface BaselineComparison {
  baseline_findings_count: number;
  council_findings_count: number;
  baseline_distinct_categories: number;
  council_distinct_categories: number;
  categories_missed_by_baseline: string[];
}

export interface VulnerabilityReport {
  decision_text: string;
  generated_at: string;
  vulnerabilities: ResolvedVulnerability[];
  mandate_scores: Record<string, number>;
  overall_recommendation: "approved" | "approved_with_conditions" | "blocked";
  conditions: string[];
  red_flags: string[];
  total_latency_ms: number;
  single_agent_baseline_comparison: BaselineComparison | null;
}

// --- SSE event shapes, see backend SPEC.md §8.2 ---

export type SseEventType =
  | "validation_complete"
  | "documents_attached"
  | "agent_started"
  | "agent_completed"
  | "conflict_detected"
  | "round_2_started"
  | "synthesis_started"
  | "report_ready"
  | "baseline_ready"
  | "error";

export interface SseEvent {
  type: SseEventType;
  timestamp: number;
  // agent_started: {agent, round}
  // agent_completed: {agent, round, latency_ms, output: AgentOutput}
  // conflict_detected: {count}
  // report_ready: {report: VulnerabilityReport}
  // error: {message}
  payload: Record<string, any>;
}

export type AgentSeatState = "idle" | "thinking_r1" | "done_r1" | "thinking_r2" | "done_r2";
