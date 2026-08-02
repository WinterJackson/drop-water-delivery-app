import { cn } from "@/lib/utils/cn";
import { formatNumber } from "@/lib/utils/format";

export type FunnelStep = {
  label: string;
  value: number;
  /** Why this step loses orders — shown under the drop-off figure. */
  note?: string;
};

/**
 * A conversion funnel across genuinely **nested** sets.
 *
 * The steps must each be a subset of the one before, or the drop-off numbers
 * are fiction. That rules out charting "orders by current status" this way —
 * those are siblings, not stages, and a delivered order is not a subset of a
 * cancelled one. Use `BarList` for a distribution and this for a sequence.
 *
 * The loss between steps is the reason the chart exists, so it is stated in
 * words and figures rather than left to be estimated from two bar widths.
 */
export function FunnelChart({ steps }: { steps: FunnelStep[] }) {
  const top = steps[0]?.value ?? 0;

  if (top <= 0) {
    return <p className="px-5 py-10 text-center text-sm text-muted">No orders in this period.</p>;
  }

  return (
    <ol className="px-5 py-4">
      {steps.map((step, index) => {
        const previous = index === 0 ? null : steps[index - 1]!;
        const lost = previous ? previous.value - step.value : 0;
        const lostPct = previous && previous.value > 0 ? (lost / previous.value) * 100 : 0;
        const share = (step.value / top) * 100;

        return (
          <li key={step.label}>
            {previous ? (
              <div className="flex items-center gap-2 py-1.5 pl-1 text-xs">
                <span aria-hidden className="h-4 w-px bg-[var(--border)]" />
                <span className={cn(lost > 0 ? "text-[var(--danger)]" : "text-muted")}>
                  {lost > 0
                    ? `−${formatNumber(lost)} (${lostPct.toFixed(1)}%)`
                    : "no drop-off"}
                </span>
                {step.note ? <span className="min-w-0 truncate text-muted">{step.note}</span> : null}
              </div>
            ) : null}

            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className="min-w-0 truncate font-medium">{step.label}</span>
              <span className="shrink-0 tabular-nums">
                {formatNumber(step.value)}
                <span className="ml-2 text-xs text-muted">{share.toFixed(1)}%</span>
              </span>
            </div>

            <div
              className="mt-1.5 h-2.5 overflow-hidden rounded-full bg-surface-muted"
              role="img"
              aria-label={`${step.label}: ${formatNumber(step.value)}, ${share.toFixed(1)}% of ${steps[0]!.label.toLowerCase()}`}
            >
              <div
                className="h-full rounded-full bg-[var(--accent)]"
                // A 0.3% step would otherwise render as an invisible sliver and
                // read as "none", which is a different fact.
                style={{ width: `${Math.max(1.5, share)}%` }}
              />
            </div>
          </li>
        );
      })}
    </ol>
  );
}
