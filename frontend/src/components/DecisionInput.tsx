import { FormEvent, useState } from "react";
import { useDocumentUpload } from "../hooks/useDocumentUpload";
import EvidenceUpload from "./EvidenceUpload";

interface Props {
  onSubmit: (decisionText: string, context?: string, documentIds?: string[]) => void;
  disabled: boolean;
}

const EXAMPLES = [
  "Launch a $49/mo subscription tier with no free trial for new users.",
  "Sunset the legacy API in 60 days with no migration tooling provided.",
  "Acquire a 6-person competitor to absorb their customer base.",
];

export default function DecisionInput({ onSubmit, disabled }: Props) {
  const [decisionText, setDecisionText] = useState("");
  const [context, setContext] = useState("");
  const [showContext, setShowContext] = useState(false);
  const evidence = useDocumentUpload();

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (decisionText.trim().length < 10) return;
    onSubmit(
      decisionText.trim(),
      context.trim() || undefined,
      evidence.documents.map((d) => d.document_id)
    );
  };

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-2xl mx-auto">
      <div className="flex items-baseline justify-between mb-2">
        <label htmlFor="decision" className="font-mono text-xs uppercase tracking-widest text-ink-secondary">
          Case brief — decision under review
        </label>
        <span className="font-mono text-xs text-ink-secondary">{decisionText.length}/2000</span>
      </div>

      <textarea
        id="decision"
        value={decisionText}
        onChange={(e) => setDecisionText(e.target.value.slice(0, 2000))}
        placeholder="Describe the business decision you want the council to review..."
        rows={4}
        disabled={disabled}
        className="w-full resize-none rounded-md bg-chamber-panel border border-chamber-line px-4 py-3 text-ink-primary placeholder:text-ink-secondary font-body text-[15px] leading-relaxed disabled:opacity-50"
      />

      <div className="flex flex-wrap gap-2 mt-3">
        {EXAMPLES.map((example) => (
          <button
            key={example}
            type="button"
            disabled={disabled}
            onClick={() => setDecisionText(example)}
            className="text-xs px-3 py-1.5 rounded-full border border-chamber-line text-ink-secondary hover:border-ink-tertiary hover:text-ink-primary transition-colors disabled:opacity-40"
          >
            {example.length > 44 ? example.slice(0, 44) + "…" : example}
          </button>
        ))}
      </div>

      {showContext ? (
        <div className="mt-3">
          <label htmlFor="context" className="font-mono text-xs uppercase tracking-widest text-ink-secondary mb-1 block">
            Additional context (optional)
          </label>
          <textarea
            id="context"
            value={context}
            onChange={(e) => setContext(e.target.value.slice(0, 4000))}
            rows={2}
            disabled={disabled}
            className="w-full resize-none rounded-md bg-chamber-panel border border-chamber-line px-4 py-2 text-sm text-ink-primary placeholder:text-ink-secondary disabled:opacity-50"
            placeholder="Company size, market, prior context the council should know..."
          />
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setShowContext(true)}
          className="mt-3 text-xs text-ink-secondary hover:text-ink-primary underline underline-offset-2"
        >
          + add context
        </button>
      )}

      <EvidenceUpload
        documents={evidence.documents}
        uploading={evidence.uploading}
        error={evidence.error}
        maxDocuments={evidence.maxDocuments}
        disabled={disabled}
        onUpload={evidence.upload}
        onRemove={evidence.remove}
      />

      <button
        type="submit"
        disabled={disabled || decisionText.trim().length < 10}
        className="mt-5 w-full sm:w-auto px-6 py-2.5 rounded-md bg-verdict text-chamber font-semibold text-sm tracking-wide uppercase disabled:opacity-40 disabled:cursor-not-allowed hover:brightness-110 transition-[filter]"
      >
        Submit to council
      </button>
    </form>
  );
}
