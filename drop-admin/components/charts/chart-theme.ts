/**
 * Everything the Recharts components share, in one place.
 *
 * The colours are CSS variables rather than literals, which is what makes the
 * charts theme-aware for free: Recharts writes the string straight into an SVG
 * `fill`/`stroke`, so switching `data-theme` restyles them with no JavaScript
 * and no re-render.
 */

/** Categorical series colours, defined in `globals.css` for both themes. */
export const SERIES = [
  "var(--chart-1)",
  "var(--chart-2)",
  "var(--chart-3)",
  "var(--chart-4)",
  "var(--chart-5)",
  "var(--chart-6)",
] as const;

export function seriesColour(index: number): string {
  return SERIES[index % SERIES.length]!;
}

export const AXIS = {
  tick: { fontSize: 11, fill: "var(--foreground-muted)" },
  tickLine: false,
  axisLine: false,
} as const;

export const TOOLTIP = {
  contentStyle: {
    background: "var(--surface)",
    border: "1px solid var(--border)",
    borderRadius: 10,
    fontSize: 12,
    color: "var(--foreground)",
    boxShadow: "0 8px 24px rgb(0 0 0 / 0.12)",
  },
  labelStyle: { color: "var(--foreground-muted)", marginBottom: 4 },
  // The default is a translucent grey block that reads as a selection on a
  // dark surface. A hairline is enough to say which column is being described.
  cursor: { fill: "color-mix(in oklch, var(--foreground) 6%, transparent)" },
} as const;

/** Compact axis labels: 12,400 → 12.4k. Never used for a figure read as money. */
export function compact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(value);
}
