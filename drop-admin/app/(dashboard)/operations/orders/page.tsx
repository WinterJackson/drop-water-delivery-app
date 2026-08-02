import { AlarmClock, ClipboardCheck, PauseCircle, Truck, Wallet } from "lucide-react";
import Link from "next/link";

import { Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDuration, formatMoney, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { OrderCard, OrderRow, type BoardOrder } from "./OrderRow";

export const metadata = { title: "Orders" };

const VIEWS = [
  { key: "stuck", label: "Needs attention", blurb: "Sitting too long, paused for review, or paid and undelivered." },
  { key: "paused", label: "Paused", blurb: "Waiting on a decision about bottles or floor level." },
  { key: "active", label: "In flight", blurb: "Everything not yet delivered or cancelled." },
  { key: "cancelled", label: "Cancelled", blurb: "" },
  { key: "all", label: "All", blurb: "" },
] as const;

export default async function OrdersPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string; q?: string }>;
}) {
  const { view = "stuck", q = "" } = await searchParams;
  const active = VIEWS.find((v) => v.key === view)?.key ?? "stuck";

  const query = new URLSearchParams({ view: active });
  if (q.trim()) query.set("search", q.trim());

  type Board = { view: string; items: BoardOrder[]; next_cursor: string | null };
  type Counts = {
    paused: number;
    stale: number;
    active: number;
    unassigned: number;
    oldest_stale_minutes: number | null;
    active_value: string;
    stale_threshold_minutes: number;
    delivered_24h: number;
    cancelled_24h: number;
  };

  let board: Board;
  let me: AdminMe;
  // The counts are context, not the page. A slow aggregate must not blank the
  // board — the stuck order is still the point of opening this screen.
  let counts: Counts | null = null;
  try {
    [board, me, counts] = await Promise.all([
      get<Board>(`/api/admin/orders?${query.toString()}`),
      get<AdminMe>("/api/admin/me"),
      get<Counts>("/api/admin/orders/counts").catch(() => null),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the order board" detail={message} />;
  }

  // A cancellation rate is only meaningful against the day's throughput; with
  // nothing finished today it is not "0%", it is unanswerable.
  const finished24h = counts ? counts.delivered_24h + counts.cancelled_24h : 0;
  const cancelRate =
    counts && finished24h > 0 ? Math.round((counts.cancelled_24h / finished24h) * 100) : null;

  const canIntervene = can(me, PERMISSIONS.ordersIntervene);
  const blurb = VIEWS.find((v) => v.key === active)?.blurb;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Orders</h1>
        <p className="mt-1 text-sm text-muted">
          The board opens on what needs attention, not on everything — four stuck
          orders are invisible inside four hundred healthy ones.
        </p>
      </div>

      {counts ? (
        <section aria-label="Board summary">
          <h2 className="sr-only">Board summary</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Stuck right now"
              value={formatNumber(counts.stale)}
              hint={
                counts.oldest_stale_minutes === null
                  ? `Nothing past ${counts.stale_threshold_minutes} minutes`
                  : `Oldest waiting ${formatDuration(counts.oldest_stale_minutes)}`
              }
              tone={counts.stale > 0 ? "danger" : "neutral"}
              icon={<AlarmClock className="h-4 w-4" />}
            />
            <Stat
              label="Paid, nobody carrying it"
              value={formatNumber(counts.unassigned)}
              hint="Unassigned after payment — dispatch has not found a rider"
              tone={counts.unassigned > 0 ? "warning" : "neutral"}
              icon={<Truck className="h-4 w-4" />}
            />
            <Stat
              label="Awaiting a decision"
              value={formatNumber(counts.paused)}
              hint="Bottle mismatch or floor review — blocked on an administrator"
              tone={counts.paused > 0 ? "warning" : "neutral"}
              icon={<PauseCircle className="h-4 w-4" />}
            />
            <Stat
              label="Value in flight"
              value={formatMoney(counts.active_value)}
              hint={`${formatNumber(counts.active)} orders not yet delivered or cancelled`}
              icon={<Wallet className="h-4 w-4" />}
            />
          </div>

          <p className="mt-3 text-xs text-muted">
            Last 24 hours: {formatNumber(counts.delivered_24h)} delivered,{" "}
            {formatNumber(counts.cancelled_24h)} cancelled
            {cancelRate === null
              ? " — no orders have finished yet, so there is no rate to quote"
              : ` (${cancelRate}% of everything that finished)`}
            .
          </p>
        </section>
      ) : null}

      <nav aria-label="Filter orders" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {VIEWS.map((v) => (
            <li key={v.key}>
              <Link
                href={`/operations/orders?view=${v.key}`}
                aria-current={v.key === active ? "page" : undefined}
                className={
                  v.key === active
                    ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                    : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                }
              >
                {v.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {blurb ? <p className="text-sm text-muted">{blurb}</p> : null}

      <form method="GET" className="flex gap-2">
        <input type="hidden" name="view" value={active} />
        <label htmlFor="q" className="sr-only">Search by order id or phone</label>
        <input
          id="q"
          name="q"
          defaultValue={q}
          placeholder="Order id or customer phone…"
          className="min-w-0 flex-1 rounded-lg border border-default bg-surface px-3 py-2 text-sm"
        />
        <button type="submit" className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)]">
          Search
        </button>
      </form>

      {board.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<ClipboardCheck className="h-8 w-8" />}
            title={active === "stuck" ? "Nothing is stuck" : "No orders here"}
            description={
              active === "stuck"
                ? "Every order is either moving or finished. This is what it should look like."
                : undefined
            }
          />
        </Card>
      ) : (
        <>
          {/* Cards below `md`. A six-column board dragged sideways two columns
              at a time is not a board — and this is the screen most likely to
              be opened on a phone, because it is the one that pages someone. */}
          <ul className="space-y-3 md:hidden">
            {board.items.map((order) => (
              <li key={order.id}>
                <OrderCard order={order} canIntervene={canIntervene} />
              </li>
            ))}
          </ul>

          <Card className="hidden overflow-hidden md:block">
            <div className="scroll-x">
              <table className="w-full min-w-[52rem] text-sm">
                <caption className="sr-only">Orders — {active}</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Order</th>
                  <th scope="col" className="px-4 py-3 font-medium">Vendor / customer</th>
                  <th scope="col" className="px-4 py-3 font-medium">Rider</th>
                  <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  <th scope="col" className="px-4 py-3 font-medium">Value</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                  {board.items.map((order) => (
                    <OrderRow key={order.id} order={order} canIntervene={canIntervene} />
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
