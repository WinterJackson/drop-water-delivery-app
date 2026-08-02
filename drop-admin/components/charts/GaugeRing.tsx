import { Card } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";

/**
 * One rate, drawn as a ring.
 *
 * Used for the four figures that are bounded percentages and are read as
 * "how close to the target" rather than "how big" — take rate, cancellation
 * rate, repeat rate, dispute rate. A bar chart of one value is a bar; a ring
 * makes the ceiling visible, which is the whole point of a rate.
 *
 * Server-rendered SVG, no library.
 */
export function GaugeRing({
  label,
  /** Percentage as a decimal string, exactly as the backend sent it. */
  value,
  hint,
  /**
   * Where the ring changes colour.
   *
   * By default higher is better, so crossing *below* `warn` is amber and below
   * `danger` is red — a 62% delivery rate is the alarming direction. Set
   * `invert` for a metric where a *rise* is the bad news (disputes,
   * cancellations) and the comparisons flip.
   */
  warn,
  danger,
  invert = false,
  /** A 4% rate on a 0–100 ring is an invisible arc, so the axis can be capped. */
  max = 100,
}: {
  label: string;
  value: string;
  hint?: string;
  warn?: number;
  danger?: number;
  invert?: boolean;
  max?: number;
}) {
  const numeric = Number(value);
  const safe = Number.isFinite(numeric) ? numeric : 0;
  const fraction = Math.max(0, Math.min(1, safe / max));

  const breached = (threshold: number) => (invert ? safe > threshold : safe < threshold);

  const tone =
    danger !== undefined && breached(danger)
      ? "danger"
      : warn !== undefined && breached(warn)
        ? "warning"
        : "accent";

  const colour = tone === "accent" ? "var(--accent)" : `var(--${tone})`;

  // r=44 in a 100-box leaves room for the 8-wide stroke without clipping.
  const radius = 44;
  const circumference = 2 * Math.PI * radius;

  return (
    <Card className="flex items-center gap-4 p-5">
      <svg viewBox="0 0 100 100" className="h-16 w-16 shrink-0 -rotate-90" aria-hidden>
        <circle cx="50" cy="50" r={radius} fill="none" stroke="var(--surface-muted)" strokeWidth="8" />
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke={colour}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - fraction)}
        />
      </svg>

      <div className="min-w-0">
        <p className="text-sm text-muted">{label}</p>
        {/* The ring is decoration; this is the value. Colour is never the only
            thing carrying the reading. */}
        <p
          className={cn(
            "mt-0.5 text-2xl font-semibold tabular-nums tracking-tight",
            tone === "warning" && "text-[var(--warning)]",
            tone === "danger" && "text-[var(--danger)]",
          )}
        >
          {value}%
        </p>
        {hint ? <p className="mt-0.5 text-xs text-muted">{hint}</p> : null}
      </div>
    </Card>
  );
}
