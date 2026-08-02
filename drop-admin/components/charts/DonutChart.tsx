"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { seriesColour, TOOLTIP } from "@/components/charts/chart-theme";

export type Slice = {
  label: string;
  /** Drives the geometry only. */
  value: number;
  /** What the legend shows — money as its original decimal string. */
  display: string;
};

/**
 * A composition, drawn as a ring with the total in the middle.
 *
 * Used only where the parts genuinely sum to a meaningful whole — payment
 * methods, delivery types, vehicle mix. A donut of unrelated quantities is a
 * pie chart, and pie charts are how six similar slices become unreadable.
 *
 * The legend beside it is the real data table: every slice is named, valued and
 * given its share in text, so nothing here depends on telling two colours
 * apart.
 */
export function DonutChart({
  slices,
  centreLabel,
  centreValue,
}: {
  slices: Slice[];
  centreLabel: string;
  centreValue: string;
}) {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0);

  if (total <= 0) {
    return (
      <p className="px-5 py-10 text-center text-sm text-muted">Nothing recorded in this period.</p>
    );
  }

  return (
    <div className="flex flex-col items-center gap-5 px-5 py-4 sm:flex-row sm:gap-6">
      <div className="relative h-40 w-40 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie
              data={slices}
              dataKey="value"
              nameKey="label"
              innerRadius="62%"
              outerRadius="100%"
              paddingAngle={slices.length > 1 ? 2 : 0}
              strokeWidth={0}
              // The ring is a static summary, and a 400ms sweep on every
              // navigation is noise in an operations console.
              isAnimationActive={false}
            >
              {slices.map((slice, index) => (
                <Cell key={slice.label} fill={seriesColour(index)} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={TOOLTIP.contentStyle}
              labelStyle={TOOLTIP.labelStyle}
              formatter={(_value, _name, item) => {
                const slice = item.payload as Slice;
                return [slice.display, slice.label];
              }}
            />
          </PieChart>
        </ResponsiveContainer>

        {/* Centred over the hole. `pointer-events-none` so it never steals the
            hover that drives the tooltip. */}
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
          <span className="text-lg font-semibold tabular-nums leading-tight">{centreValue}</span>
          <span className="text-[11px] text-muted">{centreLabel}</span>
        </div>
      </div>

      <ul className="w-full min-w-0 space-y-2">
        {slices.map((slice, index) => (
          <li key={slice.label} className="flex items-center gap-2.5 text-sm">
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: seriesColour(index) }}
            />
            <span className="min-w-0 flex-1 truncate capitalize">{slice.label}</span>
            <span className="shrink-0 font-medium tabular-nums">{slice.display}</span>
            <span className="w-12 shrink-0 text-right text-xs tabular-nums text-muted">
              {((slice.value / total) * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
