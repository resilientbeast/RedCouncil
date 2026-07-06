import type { VulnerabilityReport } from "../types";

const STAMP: Record<VulnerabilityReport["overall_recommendation"], { label: string; color: string }> = {
  approved: { label: "Approved", color: "#4FA87A" },
  approved_with_conditions: { label: "Approved — Conditions", color: "#E8A33D" },
  blocked: { label: "Blocked", color: "#FF4E3A" },
};

interface Props {
  report: VulnerabilityReport;
}

export default function RecommendationBanner({ report }: Props) {
  const stamp = STAMP[report.overall_recommendation];

  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-4 sm:gap-6 py-4">
      <div
        className="docket-stamp animate-stamp-in self-start"
        style={{ color: stamp.color, borderColor: stamp.color }}
      >
        {stamp.label}
      </div>

      <div className="flex-1 flex flex-wrap gap-x-6 gap-y-1 text-xs font-mono text-ink-tertiary">
        <span>{(report.total_latency_ms / 1000).toFixed(1)}s · 5 agents · 2 rounds</span>
        <span>{report.vulnerabilities.length} vulnerabilities identified</span>
        <span>{report.red_flags.length} red {report.red_flags.length === 1 ? "flag" : "flags"}</span>
      </div>

      {report.conditions.length > 0 && (
        <div className="w-full sm:w-auto">
          <p className="text-xs font-mono uppercase tracking-widest text-ink-tertiary mb-1">Conditions</p>
          <ul className="text-sm text-ink-secondary list-disc list-inside space-y-0.5">
            {report.conditions.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
