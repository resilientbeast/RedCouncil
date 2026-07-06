import { useState, useEffect } from "react";
import { UserButton, useAuth } from "@clerk/clerk-react";
import { Link } from "react-router-dom";
import { useDecisionStream } from "../hooks/useDecisionStream";
import DecisionInput from "../components/DecisionInput";
import CouncilBoard from "../components/CouncilBoard";
import DebateRound2 from "../components/DebateRound2";
import VulnerabilityReportView from "../components/VulnerabilityReport";

const API_BASE = import.meta.env.VITE_API_BASE || "";

function DocketHeader({ refreshTrigger }: { refreshTrigger?: string }) {
  const today = new Date();
  const caseId = `RC-${today.getFullYear()}${String(today.getMonth() + 1).padStart(2, "0")}${String(
    today.getDate()
  ).padStart(2, "0")}`;

  const { getToken } = useAuth();
  const [usage, setUsage] = useState<any>(null);

  useEffect(() => {
    let mounted = true;
    getToken().then((token) => {
      fetch(`${API_BASE}/api/v1/usage`, {
        headers: { Authorization: `Bearer ${token}` }
      })
      .then(res => res.json())
      .then(data => {
        if (mounted && data && !data.detail) {
          setUsage(data);
        }
      })
      .catch(() => {});
    });
    return () => { mounted = false; };
  }, [getToken, refreshTrigger]);

  return (
    <header className="flex items-center justify-between py-6 border-b border-chamber-line mb-8">
      <div>
        <h1 className="font-display text-2xl tracking-tight">
          Red<span className="italic text-verdict">Council</span>
        </h1>
        <p className="text-xs text-ink-tertiary mt-0.5">Five mandates. Two rounds. One verdict.</p>
      </div>
      <div className="flex items-center gap-6">
        <Link to="/history" className="text-xs text-ink-tertiary hover:text-ink-primary underline underline-offset-2 hidden sm:inline-block">
          History
        </Link>
        <span className="docket-stamp text-ink-tertiary border-chamber-line hidden sm:inline-block">
          Docket {caseId}
        </span>
        {usage && !usage.unlimited && (
          <span className="text-xs font-mono text-ink-tertiary hidden sm:inline-block">
            {usage.user_used}/{usage.user_limit} reviews used today
          </span>
        )}
        <UserButton afterSignOutUrl="/" />
      </div>
    </header>
  );
}

export default function Dashboard() {
  const { state, submit, reset } = useDecisionStream();

  const showBoard = state.phase === "running" || state.phase === "complete";

  return (
    <div className="min-h-screen px-5 sm:px-8 py-2 max-w-5xl mx-auto">
      <DocketHeader refreshTrigger={state.phase} />

      <main>
        {state.phase === "idle" || state.phase === "error" || state.phase === "submitting" ? (
          <div className="flex flex-col items-center justify-center min-h-[60vh] max-w-3xl mx-auto w-full">
            <div className="w-full">
              <DecisionInput onSubmit={submit} disabled={state.phase === "submitting"} />
            </div>
            {state.phase === "error" && (
              <p className="mt-4 text-sm text-verdict text-center">{state.errorMessage ?? "Something went wrong."}</p>
            )}
          </div>
        ) : null}

        {showBoard && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <p className="font-mono text-xs uppercase tracking-widest text-ink-tertiary">
                Round 1 — independent review
                {state.attachedFilenames.length > 0 && (
                  <span className="text-ink-tertiary normal-case tracking-normal">
                    {" "}
                    · evidence: {state.attachedFilenames.join(", ")}
                  </span>
                )}
              </p>
              {state.phase === "complete" && (
                <button
                  onClick={reset}
                  className="text-xs text-ink-tertiary hover:text-ink-primary underline underline-offset-2"
                >
                  new case
                </button>
              )}
            </div>

            <CouncilBoard seatStates={state.seatStates} outputs={{ ...state.round1Outputs, ...state.round2Outputs }} />

            <DebateRound2
              conflictCount={state.conflictCount}
              round2Active={state.round2Active}
              round1Outputs={state.round1Outputs}
              round2Outputs={state.round2Outputs}
            />

            {state.synthesisActive && !state.report && (
              <p className="mt-6 text-sm text-ink-tertiary italic animate-pulse-seat">
                Synthesizer is weighing the arguments...
              </p>
            )}

            {state.report && <VulnerabilityReportView report={state.report} />}
          </div>
        )}
      </main>

      <footer className="mt-16 mb-6 text-center text-[11px] text-ink-tertiary font-mono">
        RedCouncil · adversarial multi-agent review · built on Qwen Cloud
      </footer>
    </div>
  );
}
