import { seriesColour } from "@/components/charts/chart-theme";
import { Card, CardHeader } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";
import { formatMoney, formatNumber } from "@/lib/utils/format";

/**
 * The non-time-series panels.
 *
 * All Server Components: none of them need interactivity, so none of them ship
 * JavaScript. The heatmap in particular would be ~170 DOM nodes of client
 * bundle for something that never changes after render.
 */

/** A horizontal bar list — readable at a glance and free of a charting library. */
export function BarList({
  title,
  description,
  items,
  valueLabel,
}: {
  title: string;
  description?: string;
  items: { label: string; value: number; display: string; hint?: string }[];
  valueLabel?: string;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));

  return (
    <Card>
      <CardHeader title={title} description={description} />
      {items.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-muted">Nothing recorded yet.</p>
      ) : (
        <ul className="space-y-3 px-5 py-4">
          {items.map((item) => (
            <li key={item.label}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="min-w-0 truncate capitalize">{item.label}</span>
                <span className="shrink-0 font-medium tabular-nums">
                  {item.display}
                  {item.hint ? <span className="ml-1.5 text-xs text-muted">{item.hint}</span> : null}
                </span>
              </div>
              <div
                className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-muted"
                role="img"
                aria-label={`${item.label}: ${item.display}${valueLabel ? ` ${valueLabel}` : ""}`}
              >
                <div
                  className="h-full rounded-full bg-[var(--accent)]"
                  style={{ width: `${Math.max(2, (item.value / max) * 100)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/**
 * Orders by hour of week.
 *
 * Rendered as a real `<table>` with row and column headers, so a screen reader
 * announces "Tuesday, 14:00, 6 orders" instead of reading 168 loose numbers.
 * The colour is redundant with the cell's title and text, never the only
 * carrier of the value.
 */
export function DemandHeatmap({
  cells,
  peak,
}: {
  cells: { dow: number; hour: number; orders: number }[];
  peak: number;
}) {
  const grid = new Map(cells.map((c) => [`${c.dow}-${c.hour}`, c.orders]));

  return (
    <Card>
      <CardHeader
        title="When orders arrive"
        description="By hour and weekday. This is what rider shifts should be planned against."
      />
      <div className="scroll-x px-5 py-4">
        <table className="w-max border-separate border-spacing-[2px] text-xs">
          <caption className="sr-only">Orders by day of week and hour of day</caption>
          <thead>
            <tr>
              <th scope="col" className="sr-only">Day</th>
              {Array.from({ length: 24 }, (_, hour) => (
                <th key={hour} scope="col" className="w-5 pb-1 font-normal text-muted">
                  {hour % 6 === 0 ? hour : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {DAYS.map((day, dow) => (
              <tr key={day}>
                <th scope="row" className="pr-2 text-right font-normal text-muted">{day}</th>
                {Array.from({ length: 24 }, (_, hour) => {
                  const orders = grid.get(`${dow}-${hour}`) ?? 0;
                  const intensity = peak > 0 ? orders / peak : 0;
                  return (
                    <td
                      key={hour}
                      title={`${day} ${String(hour).padStart(2, "0")}:00 — ${orders} order${orders === 1 ? "" : "s"}`}
                      className={cn(
                        "h-5 w-5 rounded-[3px]",
                        orders === 0 && "bg-surface-muted",
                      )}
                      style={
                        orders > 0
                          ? {
                              backgroundColor: `color-mix(in oklch, var(--accent) ${Math.round(
                                15 + intensity * 85,
                              )}%, transparent)`,
                            }
                          : undefined
                      }
                    >
                      <span className="sr-only">
                        {day} {hour}:00 — {orders} orders
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {peak === 0 ? (
        <p className="px-5 pb-4 text-sm text-muted">No orders in this window yet.</p>
      ) : null}
    </Card>
  );
}

/** Key/value block — used for supply, customer behaviour and float exposure. */
export function StatList({
  title,
  description,
  rows,
}: {
  title: string;
  description?: string;
  rows: { label: string; value: string; hint?: string; tone?: "warning" | "danger" }[];
}) {
  return (
    <Card>
      <CardHeader title={title} description={description} />
      <dl className="divide-y divide-[var(--border)]">
        {rows.map((row) => (
          <div key={row.label} className="flex items-baseline justify-between gap-4 px-5 py-2.5 text-sm">
            <dt className="text-muted">
              {row.label}
              {row.hint ? <span className="ml-1.5 text-xs">{row.hint}</span> : null}
            </dt>
            <dd
              className={cn(
                "shrink-0 font-medium tabular-nums",
                row.tone === "warning" && "text-[var(--warning)]",
                row.tone === "danger" && "text-[var(--danger)]",
              )}
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/**
 * A composition in a single bar, with the parts named underneath.
 *
 * The right shape for "what is the mix" when there are three or four parts and
 * a donut would be an oversized way to say it — vehicle types, delivery types,
 * order statuses.
 */
export function StackedShareBar({
  items,
  caption,
}: {
  items: { label: string; value: number; display: string }[];
  caption?: string;
}) {
  const total = items.reduce((sum, item) => sum + item.value, 0);

  if (total <= 0) {
    return <p className="px-5 py-8 text-center text-sm text-muted">Nothing recorded yet.</p>;
  }

  return (
    <div className="px-5 py-4">
      <div
        className="flex h-3 w-full overflow-hidden rounded-full bg-surface-muted"
        role="img"
        aria-label={items.map((i) => `${i.label} ${((i.value / total) * 100).toFixed(0)}%`).join(", ")}
      >
        {items.map((item, index) => (
          <div
            key={item.label}
            className="h-full"
            style={{
              width: `${(item.value / total) * 100}%`,
              background: seriesColour(index),
            }}
          />
        ))}
      </div>

      <ul className="mt-3 space-y-2">
        {items.map((item, index) => (
          <li key={item.label} className="flex items-center gap-2.5 text-sm">
            <span
              aria-hidden
              className="h-2.5 w-2.5 shrink-0 rounded-full"
              style={{ background: seriesColour(index) }}
            />
            <span className="min-w-0 flex-1 truncate capitalize">{item.label.replace(/_/g, " ")}</span>
            <span className="shrink-0 font-medium tabular-nums">{item.display}</span>
            <span className="w-12 shrink-0 text-right text-xs tabular-nums text-muted">
              {((item.value / total) * 100).toFixed(1)}%
            </span>
          </li>
        ))}
      </ul>

      {caption ? <p className="mt-3 text-xs text-muted">{caption}</p> : null}
    </div>
  );
}

export { formatMoney, formatNumber };
