import type { BaselineComparison } from "../types";

interface Props {
  comparison: BaselineComparison;
}

export default function BaselineComparisonPanel({ comparison }: Props) {
  const gain = comparison.council_distinct_categories - comparison.baseline_distinct_categories;

  return (
    <div className="mt-6 rounded-lg border border-chamber-line px-5 py-4">
      <h3 className="font-mono text-xs uppercase tracking-widest text-ink-tertiary mb-3">
        vs. single-agent baseline
      </h3>

      <div className="flex gap-8">
        <div>
          <p className="text-2xl font-display text-ink-primary">{comparison.baseline_distinct_categories}</p>
          <p className="text-xs text-ink-tertiary">baseline findings</p>
        </div>
        <div>
          <p className="text-2xl font-display" style={{ color: "#4FA87A" }}>
            {comparison.council_distinct_categories}
          </p>
          <p className="text-xs text-ink-tertiary">council findings</p>
        </div>
        {gain > 0 && (
          <div>
            <p className="text-2xl font-display" style={{ color: "#FF4E3A" }}>
              +{gain}
            </p>
            <p className="text-xs text-ink-tertiary">blind spots surfaced</p>
          </div>
        )}
      </div>

      {comparison.categories_missed_by_baseline.length > 0 && (
        <div className="mt-3 pt-3 border-t border-chamber-line">
          <p className="text-xs text-ink-tertiary mb-1">Missed by a single-agent review:</p>
          <ul className="text-sm text-ink-secondary list-disc list-inside space-y-0.5">
            {comparison.categories_missed_by_baseline.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
