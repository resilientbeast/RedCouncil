import type { AgentOutput, AgentRole } from "../types";
import { AGENT_LABELS } from "../types";

const ACCENT: Record<AgentRole, string> = {
  growth: "#E8A33D",
  risk: "#D64545",
  legal: "#5B6EE8",
  tech_debt: "#4FA8A0",
  customer: "#C15FC1",
};

interface Props {
  conflictCount: number;
  round2Active: boolean;
  round1Outputs: Partial<Record<AgentRole, AgentOutput>>;
  round2Outputs: Partial<Record<AgentRole, AgentOutput>>;
}

export default function DebateRound2({ conflictCount, round2Active, round1Outputs, round2Outputs }: Props) {
  if (!round2Active) return null;

  const entries = Object.entries(round2Outputs) as [AgentRole, AgentOutput][];

  return (
    <div className="mt-6 rounded-lg border border-chamber-line bg-chamber-panel/60 px-5 py-4">
      <div className="flex items-baseline justify-between mb-3">
        <h3 className="font-mono text-xs uppercase tracking-widest text-ink-tertiary">
          Round 2 — cross-examination
        </h3>
        <span className="font-mono text-xs text-verdict">
          {conflictCount} direct {conflictCount === 1 ? "conflict" : "conflicts"} flagged
        </span>
      </div>

      {entries.length === 0 ? (
        <p className="text-sm text-ink-tertiary italic">Agents are reviewing each other's Round 1 positions...</p>
      ) : (
        <div className="flex flex-col gap-3">
          {entries.map(([role, output]) => (
            <div key={role} className="border-l-2 pl-3" style={{ borderColor: ACCENT[role] }}>
              <div className="flex items-center gap-2 mb-1">
                <span className="font-display italic text-sm" style={{ color: ACCENT[role] }}>
                  {AGENT_LABELS[role]}
                </span>
                {output.rebuts.length > 0 && (
                  <span className="text-[10px] font-mono uppercase tracking-wide text-ink-tertiary">
                    rebuts {output.rebuts.map((r) => AGENT_LABELS[r]).join(", ")}
                  </span>
                )}
              </div>

              {/* The claim being overturned, shown redlined — case-file
                  markup rather than a chat bubble, per the design brief. */}
              {output.rebuts.map((rebuttedRole) => {
                const originalClaim = round1Outputs[rebuttedRole]?.findings[0]?.claim;
                if (!originalClaim) return null;
                return (
                  <p key={rebuttedRole} className="redline-strike text-xs text-ink-tertiary mb-1">
                    {AGENT_LABELS[rebuttedRole]}: {originalClaim}
                  </p>
                );
              })}

              <p className="text-sm text-ink-secondary leading-snug">{output.overall_position}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
