"use client";

import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { AXIS, compact, TOOLTIP } from "@/components/charts/chart-theme";
import { formatMoney, formatNumber } from "@/lib/utils/format";

export type Point = { date: string; revenue: string; gmv: string; orders: number };

/**
 * Revenue, GMV and order volume on one time axis.
 *
 * The values arrive as decimal *strings* and are parsed to numbers **only**
 * here, for pixel positions. Nothing rendered as text goes through that
 * conversion — the tooltip formats the original string — so the chart cannot
 * disagree with the ledger even by a rounding step.
 *
 * Order count shares the plot on its own axis because the three answer one
 * question together: revenue falling while orders hold means the mix changed,
 * and revenue falling *with* orders means demand did. Two charts side by side
 * make that comparison something you do by eye, badly.
 *
 * Zero days are present in the data (the backend gap-fills), which matters: a
 * chart that omits them draws a straight line across an outage.
 */
export function RevenueChart({ points }: { points: Point[] }) {
  const data = points.map((point) => ({
    date: point.date,
    revenueValue: Number(point.revenue),
    gmvValue: Number(point.gmv),
    ordersValue: point.orders,
    revenue: point.revenue,
    gmv: point.gmv,
    orders: point.orders,
  }));

  const allZero = data.every((d) => d.gmvValue === 0 && d.ordersValue === 0);

  if (allZero) {
    return (
      <div className="flex h-56 items-center justify-center text-sm text-muted sm:h-72">
        No paid orders in this period yet.
      </div>
    );
  }

  return (
    <div className="h-56 w-full sm:h-64 lg:h-72">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -16 }}>
          <defs>
            <linearGradient id="gmvFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.28} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--success)" stopOpacity={0.3} />
              <stop offset="100%" stopColor="var(--success)" stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
          <XAxis
            dataKey="date"
            {...AXIS}
            minTickGap={24}
            // "2026-07-14" → "07-14". The year is in the range selector above.
            tickFormatter={(value: string) => value.slice(5)}
          />
          <YAxis yAxisId="money" {...AXIS} width={52} tickFormatter={compact} />
          <YAxis
            yAxisId="orders"
            orientation="right"
            {...AXIS}
            width={32}
            allowDecimals={false}
            tickFormatter={compact}
          />

          <Tooltip
            contentStyle={TOOLTIP.contentStyle}
            labelStyle={TOOLTIP.labelStyle}
            cursor={TOOLTIP.cursor}
            formatter={(_value, name, item) => {
              const row = item.payload as (typeof data)[number];
              if (name === "GMV") return [formatMoney(row.gmv), "GMV"];
              if (name === "Revenue") return [formatMoney(row.revenue), "Revenue"];
              return [formatNumber(row.orders), "Orders"];
            }}
          />
          <Legend
            wrapperStyle={{ fontSize: 12, color: "var(--foreground-muted)", paddingTop: 4 }}
          />

          {/* Volume sits behind the money lines, and muted, so it reads as
              context rather than competing for attention with revenue. */}
          <Bar
            yAxisId="orders"
            dataKey="ordersValue"
            name="Orders"
            fill="var(--chart-6)"
            fillOpacity={0.35}
            radius={[3, 3, 0, 0]}
            isAnimationActive={false}
          />
          <Area
            yAxisId="money"
            type="monotone"
            dataKey="gmvValue"
            name="GMV"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="url(#gmvFill)"
            isAnimationActive={false}
          />
          <Area
            yAxisId="money"
            type="monotone"
            dataKey="revenueValue"
            name="Revenue"
            stroke="var(--success)"
            strokeWidth={2}
            fill="url(#revenueFill)"
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
