import type { AgentOutput, AgentRole, AgentSeatState } from "../types";
import { AGENT_ROLES } from "../types";
import AgentCard from "./AgentCard";

interface Props {
  seatStates: Record<AgentRole, AgentSeatState>;
  outputs?: Partial<Record<AgentRole, AgentOutput>>;
}

// A shallow arc: outer seats sit slightly lower than the center seat,
// like a bench curving toward the decision under review. Purely visual —
// collapses to a flat row on narrow viewports via the grid below.
const ARC_OFFSETS: number[] = [18, 6, 0, 6, 18];

export default function CouncilBoard({ seatStates, outputs }: Props) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3 lg:gap-4 lg:pt-4">
      {AGENT_ROLES.map((role, i) => (
        <AgentCard
          key={role}
          role={role}
          state={seatStates[role]}
          output={outputs?.[role]}
          arcOffset={typeof window !== "undefined" && window.innerWidth >= 1024 ? ARC_OFFSETS[i] : 0}
        />
      ))}
    </div>
  );
}
