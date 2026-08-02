/**
 * A trend line small enough to sit inside a KPI card.
 *
 * Hand-drawn SVG rather than a charting component on purpose: this renders on
 * the server and ships **zero** JavaScript. A Recharts sparkline in every stat
 * card would mean shipping the whole library to draw eight polylines that never
 * change after paint.
 *
 * A number without a direction is half an answer — "revenue is KES 42,000" is
 * only useful next to "and it has been falling for six days".
 */
export function Sparkline({
  values,
  label,
  tone = "accent",
}: {
  values: number[];
  /** Announced instead of the shape, which is meaningless to a screen reader. */
  label: string;
  tone?: "accent" | "success" | "warning" | "danger";
}) {
  if (values.length < 2) return null;

  const colour = `var(--${tone === "accent" ? "accent" : tone})`;
  const max = Math.max(...values);
  const min = Math.min(...values);
  // A flat series would divide by zero and collapse onto the baseline; drawing
  // it through the middle is the honest picture of "nothing changed".
  const span = max - min || 1;

  const width = 100;
  const height = 28;
  const step = width / (values.length - 1);

  const points = values.map((value, index) => {
    const x = index * step;
    const y = height - ((value - min) / span) * (height - 4) - 2;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  const line = points.join(" ");
  const area = `${points[0]!.split(",")[0]},${height} ${line} ${points[points.length - 1]!.split(",")[0]},${height}`;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      // Stretches to the card's width; `none` is deliberate, since the vertical
      // scale is arbitrary anyway and letterboxing would waste the space.
      preserveAspectRatio="none"
      className="h-7 w-full"
      role="img"
      aria-label={label}
    >
      <polygon points={area} fill={colour} opacity={0.12} />
      <polyline
        points={line}
        fill="none"
        stroke={colour}
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
