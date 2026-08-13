import { AlertTriangle, Receipt } from "lucide-react";
import Link from "next/link";

import { BarList } from "@/components/charts/Panels";
import { Badge, Card, CardHeader, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDateTime, formatMoney, formatNumber, timeAgo } from "@/lib/utils/format";
import { NoAccess } from "@/components/shell/NoAccess";
import { pageAccess } from "@/lib/page-access";
import { Pagination, sizeHrefFactory } from "@/components/table/Pagination";
import { TableToolbar } from "@/components/table/TableToolbar";
import { pageLinks, readPageState, type SearchParams } from "@/lib/table/query";

export const metadata = { title: "Transactions" };

type Bucket = { amount: string; count: number };

type Summary = {
  window_days: number;
  collections: { paid: Bucket; failed: Bucket; refunded: Bucket; unresolved: Bucket };
  payouts: {
    pending: Bucket;
    processing: Bucket;
    stuck: Bucket;
    completed: Bucket;
    failed: Bucket;
  };
  ledger: { transaction_type: string; amount: string; count: number }[];
};

type Transaction = {
  id: string;
  user_id: string;
  user_type: string;
  transaction_type: string;
  amount: string;
  status: string;
  description: string | null;
  mpesa_receipt: string | null;
  created_at: string | null;
};

type Payment = {
  id: string;
  order_id: string | null;
  phone: string | null;
  amount: string;
  status: string;
  mpesa_receipt: string | null;
  failure_reason: string | null;
  created_at: string | null;
  unresolved_for_minutes: number | null;
};

const TABS = [
  { key: "ledger", label: "Wallet ledger" },
  { key: "payments", label: "M-Pesa collections" },
] as const;

const STATUS_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  completed: "success",
  paid: "success",
  pending: "warning",
  processing: "warning",
  failed: "danger",
  refunded: "neutral",
};

export default async function TransactionsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  // Gated on the capability `nav-config` declares for `/finance/transactions` — the
  // same declaration that hides this entry in the sidebar, so the two can
  // never disagree. The backend enforces it again regardless.
  const access = await pageAccess("/finance/transactions");
  if (!access.allowed) return <NoAccess permission={access.permission} />;


  const params = await searchParams;
  const state = readPageState(params);
  const tab = TABS.find((t) => t.key === params.tab)?.key ?? "ledger";
  const q = state.q;
  const type = typeof params.type === "string" ? params.type : "";
  const days = Number(params.days) > 0 ? Number(params.days) : 30;

  const query = new URLSearchParams({ days: String(days), limit: String(state.per) });
  if (q) query.set("search", q);
  if (type) query.set("transaction_type", type);
  if (state.cursor) query.set("cursor", state.cursor);

  type Page<T> = { items: T[]; next_cursor: string | null };
  let summary: Summary;
  let ledger: Page<Transaction> = { items: [], next_cursor: null };
  let payments: Page<Payment> = { items: [], next_cursor: null };

  try {
    if (tab === "ledger") {
      [summary, ledger] = await Promise.all([
        get<Summary>(`/api/admin/finance/summary?days=${days}`),
        get<Page<Transaction>>(`/api/admin/finance/transactions?${query.toString()}`),
      ]);
    } else {
      [summary, payments] = await Promise.all([
        get<Summary>(`/api/admin/finance/summary?days=${days}`),
        get<Page<Payment>>(`/api/admin/finance/payments?${query.toString()}`),
      ]);
    }
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load transactions" detail={message} />;
  }

  const unresolved = summary.collections.unresolved;
  const stuck = summary.payouts.stuck;

  const shown = tab === "ledger" ? ledger : payments;
  const links = pageLinks({
    pathname: "/finance/transactions",
    filters: { tab, q, days: String(days) },
    state,
    nextCursor: shown.next_cursor,
    count: shown.items.length,
  });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Transactions</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Every balance movement and every M-Pesa collection, over the last {days}{" "}
          days.
        </p>
      </div>

      {/* The two numbers on this page that mean somebody has to do something. */}
      {unresolved.count > 0 || stuck.count > 0 ? (
        <div
          role="alert"
          className="flex gap-3 rounded-xl border border-[var(--warning)] bg-[color-mix(in_oklch,var(--warning)_8%,transparent)] px-5 py-4"
        >
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[var(--warning)]" aria-hidden />
          <div className="min-w-0 space-y-1 text-sm">
            {unresolved.count > 0 ? (
              <p>
                <strong>{formatNumber(unresolved.count)} collections never resolved</strong>{" "}
                ({formatMoney(unresolved.amount)}). An STK push that has been pending
                for over an hour was either ignored — or paid without the callback
                arriving, which means a customer has been charged for an order the
                platform does not know about.
              </p>
            ) : null}
            {stuck.count > 0 ? (
              <p>
                <strong>{formatNumber(stuck.count)} payouts stuck in processing</strong>{" "}
                ({formatMoney(stuck.amount)}) for over a day. The balances are already
                debited —{" "}
                <Link href="/finance/payouts?status=processing" className="underline underline-offset-4">
                  reconcile them by hand
                </Link>
                .
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Collected"
          value={formatMoney(summary.collections.paid.amount)}
          hint={`${formatNumber(summary.collections.paid.count)} payments`}
        />
        <Stat
          label="Refunded"
          value={formatMoney(summary.collections.refunded.amount)}
          hint={`${formatNumber(summary.collections.refunded.count)} refunds`}
        />
        <Stat
          label="Paid out"
          value={formatMoney(summary.payouts.completed.amount)}
          hint={`${formatNumber(summary.payouts.completed.count)} withdrawals`}
        />
        <Stat
          label="Awaiting approval"
          value={formatMoney(summary.payouts.pending.amount)}
          hint={`${formatNumber(summary.payouts.pending.count)} requests`}
          tone={summary.payouts.pending.count > 0 ? "warning" : "neutral"}
        />
      </div>

      {summary.ledger.length > 0 ? (
        <BarList
          title="Where the balance movements come from"
          description="Completed wallet transactions in this window, by type."
          items={summary.ledger.map((row) => ({
            label: row.transaction_type.replace(/_/g, " "),
            value: Math.abs(Number(row.amount)),
            display: formatMoney(row.amount),
            hint: `${formatNumber(row.count)}`,
          }))}
        />
      ) : null}

      <nav aria-label="Transaction view" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {TABS.map((t) => (
            <li key={t.key}>
              <Link
                href={`/finance/transactions?tab=${t.key}&days=${days}`}
                aria-current={t.key === tab ? "page" : undefined}
                className={
                  t.key === tab
                    ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                    : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                }
              >
                {t.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {/* One pager, for whichever list is on screen. The two tabs are separate
          result sets but only one renders at a time, so a second set of links
          would be a Next button paging the list nobody is looking at. */}
      <TableToolbar
        placeholder={
          tab === "ledger"
            ? "Search receipt, reference or description"
            : "Search receipt, checkout id or phone"
        }
        keep={{ tab }}
        filters={[
          {
            name: "days",
            label: "Period",
            value: String(days),
            options: [
              { value: "7", label: "7 days" },
              { value: "30", label: "30 days" },
              { value: "90", label: "90 days" },
              { value: "365", label: "1 year" },
            ],
          },
        ]}
      >
      {tab === "ledger" ? (
        ledger.items.length === 0 ? (
          <Card>
            <EmptyState
              icon={<Receipt className="h-8 w-8" />}
              title="No balance movements"
              description="Wallet credits, debits, order payments and refunds appear here."
            />
          </Card>
        ) : (
          <>
            <ul className="space-y-3 md:hidden">
              {ledger.items.map((row) => (
                <li key={row.id}>
                  <Card className="p-4">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-sm font-medium capitalize">
                          {row.transaction_type.replace(/_/g, " ")}
                        </p>
                        <p className="text-xs capitalize text-muted">
                          {row.user_type} · {timeAgo(row.created_at)}
                        </p>
                      </div>
                      <p
                        className={
                          Number(row.amount) < 0
                            ? "shrink-0 tabular-nums text-[var(--danger)]"
                            : "shrink-0 tabular-nums text-[var(--success)]"
                        }
                      >
                        {formatMoney(row.amount)}
                      </p>
                    </div>
                    {row.description ? (
                      <p className="mt-2 text-xs text-muted">{row.description}</p>
                    ) : null}
                  </Card>
                </li>
              ))}
            </ul>

            <Card className="hidden overflow-hidden md:block">
              <div className="scroll-x">
                <table className="w-full min-w-[52rem] text-sm">
                  <caption className="sr-only">Wallet ledger, newest first</caption>
                  <thead>
                    <tr className="border-b border-default bg-surface-muted text-left">
                      <th scope="col" className="px-4 py-3 font-medium">Type</th>
                      <th scope="col" className="px-4 py-3 font-medium">Account</th>
                      <th scope="col" className="px-4 py-3 font-medium">Amount</th>
                      <th scope="col" className="px-4 py-3 font-medium">Status</th>
                      <th scope="col" className="px-4 py-3 font-medium">Description</th>
                      <th scope="col" className="px-4 py-3 font-medium">When</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ledger.items.map((row) => (
                      <tr key={row.id} className="border-b border-default last:border-0">
                        <td className="px-4 py-3 capitalize">
                          {row.transaction_type.replace(/_/g, " ")}
                        </td>
                        <td className="px-4 py-3 capitalize">{row.user_type}</td>
                        <td
                          className={
                            Number(row.amount) < 0
                              ? "px-4 py-3 tabular-nums text-[var(--danger)]"
                              : "px-4 py-3 tabular-nums text-[var(--success)]"
                          }
                        >
                          {formatMoney(row.amount)}
                        </td>
                        <td className="px-4 py-3">
                          <Badge tone={STATUS_TONE[row.status] ?? "neutral"}>{row.status}</Badge>
                        </td>
                        <td className="max-w-[22rem] truncate px-4 py-3 text-muted">
                          {row.description ?? "—"}
                        </td>
                        <td className="px-4 py-3 text-muted">{formatDateTime(row.created_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <Pagination
                links={links}
                noun="movements"
                perPage={state.per}
                sizeHref={sizeHrefFactory("/finance/transactions", {
                  tab,
                  q,
                  days: String(days),
                })}
              />
            </Card>
          </>
        )
      ) : payments.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Receipt className="h-8 w-8" />}
            title="No collections"
            description="M-Pesa STK pushes and their outcomes appear here."
          />
        </Card>
      ) : (
        <>
          <ul className="space-y-3 md:hidden">
            {payments.items.map((row) => (
              <li key={row.id}>
                <Card className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="font-medium tabular-nums">{formatMoney(row.amount)}</p>
                      <p className="font-mono text-xs text-muted">{row.phone ?? "—"}</p>
                    </div>
                    <Badge tone={STATUS_TONE[row.status] ?? "neutral"}>{row.status}</Badge>
                  </div>
                  <p className="mt-2 text-xs text-muted">
                    {row.mpesa_receipt ?? "no receipt"} · {timeAgo(row.created_at)}
                  </p>
                  {row.unresolved_for_minutes !== null ? (
                    <p className="mt-1 text-xs text-[var(--warning)]">
                      unresolved for {row.unresolved_for_minutes} min
                    </p>
                  ) : null}
                </Card>
              </li>
            ))}
          </ul>

          <Card className="hidden overflow-hidden md:block">
            <div className="scroll-x">
              <table className="w-full min-w-[52rem] text-sm">
                <caption className="sr-only">M-Pesa collections, newest first</caption>
                <thead>
                  <tr className="border-b border-default bg-surface-muted text-left">
                    <th scope="col" className="px-4 py-3 font-medium">Amount</th>
                    <th scope="col" className="px-4 py-3 font-medium">Phone</th>
                    <th scope="col" className="px-4 py-3 font-medium">Receipt</th>
                    <th scope="col" className="px-4 py-3 font-medium">Status</th>
                    <th scope="col" className="px-4 py-3 font-medium">When</th>
                  </tr>
                </thead>
                <tbody>
                  {payments.items.map((row) => (
                    <tr key={row.id} className="border-b border-default last:border-0">
                      <td className="px-4 py-3 tabular-nums">{formatMoney(row.amount)}</td>
                      <td className="px-4 py-3 font-mono text-xs">{row.phone ?? "—"}</td>
                      <td className="px-4 py-3 font-mono text-xs">{row.mpesa_receipt ?? "—"}</td>
                      <td className="px-4 py-3">
                        <Badge tone={STATUS_TONE[row.status] ?? "neutral"}>{row.status}</Badge>
                        {row.unresolved_for_minutes !== null ? (
                          <p className="mt-1 text-xs text-[var(--warning)]">
                            {row.unresolved_for_minutes} min
                          </p>
                        ) : null}
                        {row.failure_reason ? (
                          <p className="mt-1 max-w-[16rem] text-xs text-muted">
                            {row.failure_reason}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 text-muted">{formatDateTime(row.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <Pagination
              links={links}
              noun="payments"
              perPage={state.per}
              sizeHref={sizeHrefFactory("/finance/transactions", {
                tab,
                q,
                days: String(days),
              })}
            />
          </Card>
        </>
      )}
      </TableToolbar>
    </div>
  );
}
