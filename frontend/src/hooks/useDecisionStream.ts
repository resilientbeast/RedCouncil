import { useCallback, useReducer, useRef, useEffect, useState } from "react";
import { useAuth } from "@clerk/clerk-react";
import type { AgentOutput, AgentRole, AgentSeatState, SseEvent, VulnerabilityReport } from "../types";
import { AGENT_ROLES } from "../types";

interface StreamState {
  phase: "idle" | "submitting" | "running" | "complete" | "error";
  decisionText: string;
  attachedFilenames: string[];
  seatStates: Record<AgentRole, AgentSeatState>;
  round1Outputs: Partial<Record<AgentRole, AgentOutput>>;
  round2Outputs: Partial<Record<AgentRole, AgentOutput>>;
  conflictCount: number;
  round2Active: boolean;
  synthesisActive: boolean;
  report: VulnerabilityReport | null;
  errorMessage: string | null;
}

const initialSeatStates: Record<AgentRole, AgentSeatState> = Object.fromEntries(
  AGENT_ROLES.map((r) => [r, "idle"])
) as Record<AgentRole, AgentSeatState>;

const initialState: StreamState = {
  phase: "idle",
  decisionText: "",
  attachedFilenames: [],
  seatStates: { ...initialSeatStates },
  round1Outputs: {},
  round2Outputs: {},
  conflictCount: 0,
  round2Active: false,
  synthesisActive: false,
  report: null,
  errorMessage: null,
};

type Action =
  | { type: "SUBMIT_START"; decisionText: string }
  | { type: "SSE_EVENT"; event: SseEvent }
  | { type: "SUBMIT_ERROR"; message: string }
  | { type: "HYDRATE_STATE"; statePayload: any }
  | { type: "RESET" };

function reducer(state: StreamState, action: Action): StreamState {
  switch (action.type) {
    case "SUBMIT_START":
      return { ...initialState, phase: "submitting", decisionText: action.decisionText };

    case "SUBMIT_ERROR":
      if (state.phase === "complete") return state; // Don't override if already complete
      return { ...state, phase: "error", errorMessage: action.message };

    case "RESET":
      return { ...initialState };
      
    case "HYDRATE_STATE": {
      const p = action.statePayload;
      const r1 = p.round_1_outputs || {};
      const r2 = p.round_2_outputs || {};
      const newSeatStates = { ...initialSeatStates };
      
      let round2Active = false;
      let synthesisActive = false;
      let phase: StreamState["phase"] = 
        (p.status === "COMPLETE" || p.status === "complete") ? "complete" : 
        (p.status === "ERROR" || p.status === "error") ? "error" : "running";
      
      // Determine seat states
      AGENT_ROLES.forEach(role => {
        if (r2[role]) {
          newSeatStates[role] = "done_r2";
          round2Active = true;
          synthesisActive = true;
        } else if (r1[role]) {
          newSeatStates[role] = "done_r1";
        }
      });
      
      // Fill in "thinking" gaps if we are mid-run
      if (phase === "running") {
         const allR1Done = AGENT_ROLES.every(r => !!r1[r]);
         if (allR1Done) {
             round2Active = true;
         }
         AGENT_ROLES.forEach(role => {
            if (!r1[role]) newSeatStates[role] = "thinking_r1";
            else if (round2Active && !r2[role]) newSeatStates[role] = "thinking_r2";
         });
      }

      return {
        ...state,
        phase,
        seatStates: newSeatStates,
        round1Outputs: r1,
        round2Outputs: r2,
        conflictCount: p.conflict_count || 0,
        round2Active: round2Active,
        synthesisActive: !!p.report || synthesisActive,
        report: p.report || null,
        errorMessage: p.status === "ERROR" ? "Error occurred" : null,
      };
    }

    case "SSE_EVENT": {
      const { event } = action;
      switch (event.type) {
        case "documents_attached":
          return { ...state, attachedFilenames: event.payload.filenames as string[] };
        case "agent_started": {
          const role = event.payload.agent as AgentRole;
          const round = event.payload.round as number;
          return {
            ...state,
            phase: "running",
            seatStates: { ...state.seatStates, [role]: round === 1 ? "thinking_r1" : "thinking_r2" },
          };
        }
        case "agent_completed": {
          const role = event.payload.agent as AgentRole;
          const round = event.payload.round as number;
          const output = event.payload.output as AgentOutput;
          
          const newR1 = round === 1 ? { ...state.round1Outputs, [role]: output } : state.round1Outputs;
          const newR2 = round === 2 ? { ...state.round2Outputs, [role]: output } : state.round2Outputs;
          
          const synthesisStartsNow = Object.keys(newR2).length === AGENT_ROLES.length;

          return {
            ...state,
            seatStates: { ...state.seatStates, [role]: round === 1 ? "done_r1" : "done_r2" },
            round1Outputs: newR1,
            round2Outputs: newR2,
            synthesisActive: state.synthesisActive || synthesisStartsNow,
          };
        }
        case "conflict_detected":
          return { ...state, conflictCount: event.payload.count as number };
        case "round_2_started":
          return { ...state, round2Active: true };
        case "synthesis_started":
          return { ...state, synthesisActive: true };
        case "report_ready":
          return {
            ...state,
            phase: "complete",
            report: event.payload.report as VulnerabilityReport,
          };
        case "error":
          return { ...state, phase: "error", errorMessage: event.payload.message as string };
        default:
          return state;
      }
    }

    default:
      return state;
  }
}

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export function useDecisionStream() {
  const { getToken } = useAuth();
  const [state, dispatch] = useReducer(reducer, initialState);
  const eventSourceRef = useRef<EventSource | null>(null);
  const [hydrated, setHydrated] = useState(false);

  const connectStream = useCallback((decisionId: string, token: string | null) => {
    eventSourceRef.current?.close();
    const tokenQuery = token ? `?token=${encodeURIComponent(token)}` : "";
    const es = new EventSource(`${API_BASE}/api/v1/decisions/${decisionId}/stream${tokenQuery}`);
    eventSourceRef.current = es;

    es.onmessage = (msg) => {
      const event: SseEvent = JSON.parse(msg.data);
      dispatch({ type: "SSE_EVENT", event });
      if (event.type === "report_ready" || event.type === "error") {
        es.close();
      }
    };

    es.onerror = () => {
      dispatch({ type: "SUBMIT_ERROR", message: "Connection to the council was lost." });
    };
  }, []);

  useEffect(() => {
    if (hydrated) return;
    const activeId = sessionStorage.getItem("redcouncil_decision_id");
    if (!activeId) {
      setHydrated(true);
      return;
    }

    let mounted = true;
    getToken().then(async (token) => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/decisions/${activeId}/state`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {}
        });
        if (!res.ok) throw new Error("Failed to load state");
        const data = await res.json();
        
        if (mounted) {
           dispatch({ type: "HYDRATE_STATE", statePayload: data });
           if (data.status === "RUNNING") {
             connectStream(activeId, token);
           }
        }
      } catch (err) {
         sessionStorage.removeItem("redcouncil_decision_id");
      } finally {
        if (mounted) setHydrated(true);
      }
    });
    return () => { mounted = false; };
  }, [getToken, connectStream, hydrated]);


  const submit = useCallback(async (decisionText: string, context?: string, documentIds?: string[]) => {
    dispatch({ type: "SUBMIT_START", decisionText });

    try {
      const token = await getToken();
      const res = await fetch(`${API_BASE}/api/v1/decisions`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: JSON.stringify({
          decision_text: decisionText,
          context: context ?? null,
          supporting_document_ids: documentIds ?? [],
        }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail ?? `Request failed (${res.status})`);
      }

      const { decision_id } = await res.json();
      sessionStorage.setItem("redcouncil_decision_id", decision_id);
      
      connectStream(decision_id, token);

    } catch (err) {
      dispatch({ type: "SUBMIT_ERROR", message: err instanceof Error ? err.message : "Unknown error" });
    }
  }, [getToken, connectStream]);

  const reset = useCallback(() => {
    eventSourceRef.current?.close();
    sessionStorage.removeItem("redcouncil_decision_id");
    dispatch({ type: "RESET" });
  }, []);

  return { state, submit, reset };
}
