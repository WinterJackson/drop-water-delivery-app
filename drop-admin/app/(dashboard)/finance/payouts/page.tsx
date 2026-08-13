import { AlarmClock, Banknote, CircleAlert, TrendingUp, Wallet } from "lucide-react";
import Link from "next/link";

import { Pagination, sizeHrefFactory } from "@/components/table/Pagination";
import { TableToolbar } from "@/components/table/TableToolbar";
import { Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDuration, formatMoney, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import type { QueueStats } from "@/lib/queue-stats";
import { pageLinks, readPageState, type SearchParams } from "@/lib/table/query";
import { PayoutCard, PayoutRow, type Payout } from "./PayoutRow";

export const metadata = { title: "Payouts" };

type PayoutList = { items: Payout[]; next_cursor: string | null };

const TABS = [
  { key: "pending", label: "Awaiting approval" },
  { key: "processing", label: "Processing" },
  { key: "completed", label: "Completed" },
  { key: "failed", label: "Failed" },
] as const;

export default async function PayoutsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const state = readPageState(params);
  const status = typeof params.status === "string" ? params.status : "pending";
  const active = TABS.find((tab) => tab.key === status)?.key ?? "pending";

  const query = new URLSearchParams({ status: active, limit: String(state.per) });
  if (state.q) query.set("search", state.q);
  if (state.cursor) query.set("cursor", state.cursor);

  let list: PayoutList;
  let me: AdminMe;
  // Context, in its own catch — a slow aggregate must not hide the payout
  // somebody opened this page to approve.
  let stats: QueueStats = {};
  try {
    [list, me, stats] = await Promise.all([
      get<PayoutList>(`/api/admin/payouts?${query.toString()}`),
      get<AdminMe>("/api/admin/me"),
      get<QueueStats>("/api/admin/queues/stats").catch(() => ({})),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load payouts" detail={message} />;
  }

  const links = pageLinks({
    pathname: "/finance/payouts",
    filters: { status: active, q: state.q },
    state,
    nextCursor: list.next_cursor,
    count: list.items.length,
  });
  const pager = (
    <Pagination
      links={links}
      noun="payouts"
      perPage={state.per}
      sizeHref={sizeHrefFactory("/finance/payouts", { status: active, q: state.q })}
    />
  );

  const canDecide = can(me, PERMISSIONS.financePayoutApprove);
  const canSeeDestination = can(me, PERMISSIONS.piiView);
  const payouts = stats.payouts;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Payouts</h1>
        <p className="mt-1 text-sm text-muted">
          Money leaving the platform to vendors and riders.
        </p>
      </div>

      {payouts ? (
        <section aria-label="Payout position">
          <h2 className="sr-only">Payout position</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Awaiting approval"
              value={formatMoney(payouts.waiting_value)}
              hint={`${formatNumber(payouts.waiting)} request(s) · largest ${formatMoney(payouts.largest_pending)}`}
              tone={payouts.waiting > 0 ? "warning" : "neutral"}
              icon={<Wallet className="h-4 w-4" />}
            />
            <Stat
              label="Oldest request"
              value={
                payouts.oldest_wait_minutes === null
                  ? "—"
                  : formatDuration(payouts.oldest_wait_minutes)
              }
              hint={
                payouts.oldest_wait_minutes === null
                  ? "Nothing waiting"
                  : "Somebody has been waiting to be paid this long"
              }
              tone={
                payouts.oldest_wait_minutes !== null && payouts.oldest_wait_minutes > 2880
                  ? "danger"
                  : "neutral"
              }
              icon={<AlarmClock className="h-4 w-4" />}
            />
            <Stat
              label="Paid in 24h"
              value={formatMoney(payouts.paid_24h_value)}
              hint={`${formatNumber(payouts.paid_24h)} settled · ${formatNumber(payouts.processing)} in flight`}
              icon={<TrendingUp className="h-4 w-4" />}
            />
            <Stat
              label="Failed"
              value={formatMoney(payouts.failed_value)}
              hint={
                payouts.failed > 0
                  ? `${formatNumber(payouts.failed)} people believe they were paid and were not`
                  : "Nothing has failed"
              }
              tone={payouts.failed > 0 ? "danger" : "neutral"}
              icon={<CircleAlert className="h-4 w-4" />}
            />
          </div>
        </section>
      ) : null}

      <nav aria-label="Filter by status" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {TABS.map((tab) => {
            const selected = tab.key === active;
            return (
              <li key={tab.key}>
                <Link
                  href={`/finance/payouts?status=${tab.key}`}
                  aria-current={selected ? "page" : undefined}
                  className={
                    selected
                      ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                      : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                  }
                >
                  {tab.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {active === "processing" ? (
        <p className="rounded-lg border border-[var(--warning)] bg-[color-mix(in_oklch,var(--warning)_10%,transparent)] px-4 py-3 text-sm">
          Safaricom accepted these into its queue and hasn&apos;t reported back.
          Anything here for more than a day needs reconciling by hand against
          the Daraja portal — the balance is already debited.
        </p>
      ) : null}

      {!canSeeDestination ? (
        <p className="text-sm text-muted">
          Destination numbers are masked. Seeing them in full needs the
          &ldquo;Reveal identity documents and payout details&rdquo; permission.
        </p>
      ) : null}

      <TableToolbar
        placeholder="Search by M-Pesa receipt, failure reason or provider id"
        keep={{ status: active }}
      >
      {list.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Banknote className="h-8 w-8" />}
            title={active === "pending" ? "No payouts waiting" : `No ${active} payouts`}
            description={
              active === "pending"
                ? "Withdrawal requests from vendors and riders will appear here for approval."
                : undefined
            }
          />
        </Card>
      ) : (
        <>
          {/* Cards below `md`, a table above it. Approving a payout is a
              money-moving decision and it must be equally clear on a phone —
              not a five-column grid dragged sideways. */}
          <ul className="space-y-3 md:hidden">
            {list.items.map((payout) => (
              <li key={payout.id}>
                <PayoutCard payout={payout} canDecide={canDecide} />
              </li>
            ))}
          </ul>

          <Card className="hidden overflow-hidden md:block">
            <div className="scroll-x">
              <table className="w-full min-w-[46rem] text-sm">
              <caption className="sr-only">
                {active} payouts, newest first
              </caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Amount</th>
                  <th scope="col" className="px-4 py-3 font-medium">Recipient</th>
                  <th scope="col" className="px-4 py-3 font-medium">Destination</th>
                  <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((payout) => (
                  <PayoutRow key={payout.id} payout={payout} canDecide={canDecide} />
                ))}
                </tbody>
              </table>
            </div>
            {pager}
          </Card>

          {/* The table is not rendered below `md`, so its pager is not either. */}
          <Card className="md:hidden">{pager}</Card>
        </>
      )}
      </TableToolbar>
    </div>
  );
}
