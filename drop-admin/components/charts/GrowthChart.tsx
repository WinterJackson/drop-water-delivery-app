"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AXIS, compact, TOOLTIP } from "@/components/charts/chart-theme";

export type GrowthRow = { label: string; current: number; previous: number };

/**
 * New accounts this period against the one before it, side by side.
 *
 * Paired bars rather than a percentage: "+300%" reads as a triumph when the
 * numbers are 1 and 4, and this console is being used on a platform where they
 * frequently are. Seeing both absolute values is what stops that.
 */
export function GrowthChart({ rows, windowDays }: { rows: GrowthRow[]; windowDays: number }) {
  if (rows.every((row) => row.current === 0 && row.previous === 0)) {
    return (
      <div className="flex h-56 items-center justify-center text-sm text-muted">
        No sign-ups in either period.
      </div>
    );
  }

  return (
    // Shorter on a phone, taller at a desk. A fixed 16rem chart is either
    // cramped on a monitor or half the viewport on a handset.
    <div className="h-56 w-full sm:h-64">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: -16 }} barGap={4}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis dataKey="label" {...AXIS} />
          <YAxis {...AXIS} width={44} allowDecimals={false} tickFormatter={compact} />
          <Tooltip
            contentStyle={TOOLTIP.contentStyle}
            labelStyle={TOOLTIP.labelStyle}
            cursor={TOOLTIP.cursor}
          />
          <Legend
            wrapperStyle={{ fontSize: 12, color: "var(--foreground-muted)", paddingTop: 4 }}
          />
          <Bar
            dataKey="previous"
            name={`Previous ${windowDays} days`}
            fill="var(--chart-6)"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
          <Bar
            dataKey="current"
            name={`Last ${windowDays} days`}
            fill="var(--chart-1)"
            radius={[4, 4, 0, 0]}
            isAnimationActive={false}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
