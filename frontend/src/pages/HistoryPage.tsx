import { useState, useEffect } from "react";
import { useAuth } from "@clerk/clerk-react";
import { useNavigate, Link } from "react-router-dom";
import { ArrowLeftIcon } from "lucide-react";

const API_BASE = import.meta.env.VITE_API_BASE || "";

interface DecisionRecord {
  id: string;
  decision_text: string;
  submitted_at: string;
  status: "running" | "complete" | "error";
  error: string | null;
}

export default function HistoryPage() {
  const { getToken } = useAuth();
  const navigate = useNavigate();
  const [cases, setCases] = useState<DecisionRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    getToken().then((token) => {
      fetch(`${API_BASE}/api/v1/decisions`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      })
      .then(res => res.json())
      .then(data => {
        if (mounted) {
          setCases(data);
          setLoading(false);
        }
      })
      .catch(() => {
        if (mounted) setLoading(false);
      });
    });
    return () => { mounted = false; };
  }, [getToken]);

  const handleCaseClick = (id: string) => {
    sessionStorage.setItem("redcouncil_decision_id", id);
    navigate("/dashboard");
  };

  return (
    <div className="min-h-screen px-5 sm:px-8 py-2 max-w-4xl mx-auto">
      <header className="flex items-center gap-4 py-6 border-b border-chamber-line mb-8">
        <Link to="/dashboard" className="text-ink-tertiary hover:text-ink-primary transition-colors">
          <ArrowLeftIcon size={20} />
        </Link>
        <h1 className="font-display text-2xl tracking-tight">Case History</h1>
      </header>

      <main>
        {loading ? (
          <p className="text-sm text-ink-tertiary animate-pulse-seat">Loading archives...</p>
        ) : cases.length === 0 ? (
          <p className="text-sm text-ink-tertiary">No cases found in your history.</p>
        ) : (
          <div className="flex flex-col gap-4">
            {cases.map((c) => (
              <div
                key={c.id}
                onClick={() => handleCaseClick(c.id)}
                className="group cursor-pointer border border-chamber-line rounded p-4 hover:border-verdict transition-colors bg-chamber"
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-mono text-ink-tertiary">
                    {new Date(c.submitted_at).toLocaleString()}
                  </span>
                  <span className={`text-[10px] font-mono uppercase px-2 py-0.5 rounded-full ${
                    c.status === "complete" ? "bg-verdict/10 text-verdict" :
                    c.status === "running" ? "bg-blue-500/10 text-blue-400" :
                    "bg-red-500/10 text-red-400"
                  }`}>
                    {c.status}
                  </span>
                </div>
                <p className="text-sm text-ink-secondary line-clamp-2">
                  {c.decision_text}
                </p>
                {c.error && (
                  <p className="text-xs text-red-400 mt-2">Error: {c.error}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  );
}
