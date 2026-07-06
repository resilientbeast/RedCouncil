import type { AgentOutput, AgentRole, AgentSeatState } from "../types";
import { AGENT_LABELS } from "../types";

const ACCENT: Record<AgentRole, string> = {
  growth: "#E8A33D",
  risk: "#D64545",
  legal: "#5B6EE8",
  tech_debt: "#4FA8A0",
  customer: "#C15FC1",
};

const MANDATE_LINE: Record<AgentRole, string> = {
  growth: "argues the opportunity",
  risk: "stress-tests failure modes",
  legal: "flags regulatory exposure",
  tech_debt: "assesses engineering cost",
  customer: "represents user friction",
};

interface Props {
  role: AgentRole;
  state: AgentSeatState;
  output?: AgentOutput;
  /** Vertical offset in px to fake a gentle bench arc on desktop. */
  arcOffset?: number;
}

function statusLabel(state: AgentSeatState): string {
  switch (state) {
    case "idle":
      return "awaiting session";
    case "thinking_r1":
      return "reviewing — round 1";
    case "done_r1":
      return "position filed";
    case "thinking_r2":
      return "rebuttal in progress";
    case "done_r2":
      return "rebuttal filed";
  }
}

export default function AgentCard({ role, state, output, arcOffset = 0 }: Props) {
  const accent = ACCENT[role];
  const isThinking = state === "thinking_r1" || state === "thinking_r2";
  const isIdle = state === "idle";

  return (
    <div
      className="rounded-lg bg-chamber-panel border-t-[3px] px-4 py-4 flex flex-col gap-2 min-h-[168px] transition-transform"
      style={{
        borderTopColor: accent,
        transform: `translateY(${arcOffset}px)`,
        opacity: isIdle ? 0.55 : 1,
      }}
    >
      <div className="flex items-center justify-between">
        <span className="font-display italic text-lg" style={{ color: accent }}>
          {AGENT_LABELS[role]}
        </span>
        <span
          className={`w-2 h-2 rounded-full ${isThinking ? "animate-pulse-seat" : ""}`}
          style={{ backgroundColor: accent }}
        />
      </div>

      <p className="text-[11px] font-mono uppercase tracking-wide text-ink-tertiary">
        {MANDATE_LINE[role]}
      </p>

      <p className="text-xs text-ink-secondary">{statusLabel(state)}</p>

      {output && (
        <div className="mt-1 pt-2 border-t border-chamber-line">
          <p className="text-sm text-ink-primary leading-snug">{output.overall_position}</p>
          {output.findings[0] && (
            <div className="mt-1.5 flex flex-col gap-1">
              <p className="text-xs text-ink-secondary leading-snug">
                <span className="font-mono" style={{ color: accent }}>
                  {output.findings[0].severity}/10
                </span>{" "}
                {output.findings[0].claim}
              </p>
              {output.findings[0].evidence && output.findings[0].evidence.length > 0 && (
                <div className="mt-1 pl-2 border-l-2 border-chamber-line">
                  {output.findings[0].evidence.map((ev, i) => (
                    <p key={i} className="text-[11px] text-ink-tertiary italic leading-snug break-words">
                      "{ev}"
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
