import { SignInButton, SignUpButton, useAuth } from "@clerk/clerk-react";
import { Navigate } from "react-router-dom";

export default function LandingPage() {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) return null;
  if (isSignedIn) return <Navigate to="/dashboard" replace />;

  return (
    <div className="min-h-screen bg-chamber text-ink-primary font-sans selection:bg-ink-primary selection:text-chamber">
      <header className="px-5 sm:px-8 py-6 flex items-center justify-between max-w-5xl mx-auto">
        <div>
          <h1 className="font-display text-2xl tracking-tight">
            Red<span className="italic text-verdict">Council</span>
          </h1>
        </div>
        <SignInButton mode="modal">
          <button className="text-sm text-ink-secondary hover:text-ink-primary font-medium tracking-wide">
            SIGN IN
          </button>
        </SignInButton>
      </header>

      <main className="max-w-3xl mx-auto px-5 sm:px-8 mt-24 mb-32">
        <section className="text-center">
          <h2 className="text-5xl sm:text-6xl font-display tracking-tight leading-[1.1] mb-6">
            Adversarial intelligence for hard decisions.
          </h2>
          <p className="text-lg text-ink-secondary max-w-2xl mx-auto mb-10 leading-relaxed">
            One advisor is one blind spot. RedCouncil brings together five differently-mandated AI agents to independently analyze, vigorously debate, and synthesize your biggest proposals before you ship them.
          </p>
          <SignUpButton mode="modal">
            <button className="bg-ink-primary text-chamber px-8 py-3.5 rounded-none font-medium tracking-wide hover:bg-white transition-colors">
              START A REVIEW
            </button>
          </SignUpButton>
        </section>

        <div className="h-px w-24 bg-chamber-line mx-auto my-24"></div>

        <section className="space-y-16">
          <div className="grid sm:grid-cols-2 gap-8 items-center">
            <div>
              <h3 className="text-xl font-display mb-3 tracking-tight">Round 1: Independent Review</h3>
              <p className="text-ink-secondary text-sm leading-relaxed">
                Growth, Risk, Legal, Tech Debt, and Customer constraints are fundamentally at odds. Our five agents review your proposal in isolation, preventing groupthink and surfacing their strongest, most biased arguments.
              </p>
            </div>
            <div className="bg-chamber-panel border border-chamber-line p-6 flex flex-col gap-3">
              <div className="h-2 w-1/3 bg-agent-growth rounded-sm"></div>
              <div className="h-2 w-1/2 bg-agent-risk rounded-sm"></div>
              <div className="h-2 w-1/4 bg-agent-legal rounded-sm"></div>
              <div className="h-2 w-2/5 bg-agent-techdebt rounded-sm"></div>
              <div className="h-2 w-1/2 bg-agent-customer rounded-sm"></div>
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-8 items-center">
            <div className="order-2 sm:order-1 bg-chamber-panel border border-chamber-line p-6">
              <div className="flex gap-4">
                <div className="w-1 bg-agent-growth"></div>
                <div className="flex-1 space-y-2 py-1">
                  <div className="h-2 w-full bg-chamber-line rounded-sm"></div>
                  <div className="h-2 w-3/4 bg-chamber-line rounded-sm"></div>
                </div>
              </div>
              <div className="flex gap-4 mt-4 opacity-50">
                <div className="w-1 bg-agent-risk"></div>
                <div className="flex-1 space-y-2 py-1">
                  <div className="h-2 w-full bg-chamber-line rounded-sm"></div>
                  <div className="h-2 w-2/3 bg-chamber-line rounded-sm"></div>
                </div>
              </div>
            </div>
            <div className="order-1 sm:order-2">
              <h3 className="text-xl font-display mb-3 tracking-tight">Round 2: Cross-Examination</h3>
              <p className="text-ink-secondary text-sm leading-relaxed">
                The agents are forced to read each other's work and argue back. Growth must confront Risk's churn model. Product must answer for Tech Debt's on-call burden.
              </p>
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-8 items-center">
            <div>
              <h3 className="text-xl font-display mb-3 tracking-tight">Evidence Grounding</h3>
              <p className="text-ink-secondary text-sm leading-relaxed">
                Attach CSVs or PDFs to your proposal. Agents are instructed to cite specific rows and excerpts to back up their claims, ensuring the debate stays grounded in your actual data.
              </p>
            </div>
            <div className="bg-chamber-panel border border-chamber-line p-6">
              <div className="font-mono text-[10px] text-ink-tertiary uppercase tracking-widest mb-4">Evidence Sources</div>
              <div className="flex items-center gap-3 text-sm border-b border-chamber-line pb-3 mb-3">
                <span className="text-xl">📊</span> market-research.csv
              </div>
              <div className="flex items-center gap-3 text-sm">
                <span className="text-xl">📄</span> q3-strategy-memo.pdf
              </div>
            </div>
          </div>
        </section>

        <div className="mt-32 text-center">
          <SignUpButton mode="modal">
            <button className="bg-ink-primary text-chamber px-8 py-3.5 rounded-none font-medium tracking-wide hover:bg-white transition-colors">
              SEE IT IN ACTION
            </button>
          </SignUpButton>
        </div>
      </main>

      <footer className="text-center text-[11px] text-ink-tertiary font-mono pb-8">
        RedCouncil · adversarial multi-agent review · built on Qwen Cloud
      </footer>
    </div>
  );
}
