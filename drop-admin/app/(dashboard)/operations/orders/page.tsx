import { ClipboardCheck } from "lucide-react";
import Link from "next/link";

import { Card, EmptyState, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
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
  let board: Board;
  let me: AdminMe;
  try {
    [board, me] = await Promise.all([
      get<Board>(`/api/admin/orders?${query.toString()}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the order board" detail={message} />;
  }

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
