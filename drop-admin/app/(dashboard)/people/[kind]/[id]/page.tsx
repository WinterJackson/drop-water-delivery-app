import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge, Card, CardHeader, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe, type Permission } from "@/lib/permissions";
import { formatDateTime, formatMoney, formatNumber, timeAgo } from "@/lib/utils/format";
import { AccountActions } from "./AccountActions";

const KINDS = {
  customers: { kind: "customer", label: "Customer", suspend: PERMISSIONS.customersSuspend },
  riders: { kind: "rider", label: "Rider", suspend: PERMISSIONS.ridersSuspend },
  vendors: { kind: "vendor", label: "Vendor", suspend: PERMISSIONS.vendorsSuspend },
} as const satisfies Record<string, { kind: string; label: string; suspend: Permission }>;

type Slug = keyof typeof KINDS;

type Detail = {
  id: string;
  name: string | null;
  email: string | null;
  phone_number: string | null;
  is_suspended: boolean;
  suspension_reason: string | null;
  suspended_at: string | null;
  created_at: string | null;
  location_address: string | null;
  kyc_status?: string | null;
  vendor_type?: string | null;
  verification_status?: string | null;
  plate_number?: string | null;
  rating?: number | null;
  wallet_balance?: string;
  debt_balance?: string;
  orders: { paid_count: number; lifetime_value: string; last_order_at: string | null };
  recent_orders: {
    id: string; status: string; payment_status: string; total: string; created_at: string | null;
  }[];
};

type Ledger = {
  balance: string;
  items: {
    id: string;
    transaction_type: string;
    amount: string;
    status: string;
    description: string | null;
    created_at: string | null;
  }[];
};

type Ticket = {
  id: string;
  subject: string;
  status: string;
  priority: string;
  created_at: string | null;
};

export default async function PersonPage({
  params,
}: {
  params: Promise<{ kind: string; id: string }>;
}) {
  const { kind: slug, id } = await params;
  const config = KINDS[slug as Slug];
  if (!config) notFound();

  let person: Detail;
  let me: AdminMe;
  try {
    [person, me] = await Promise.all([
      get<Detail>(`/api/admin/people/${config.kind}s/${id}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load this account" detail={message} />;
  }

  // Two supplementary panels, each behind its own capability and each allowed to
  // fail on its own. An admin opening this page to suspend somebody must not be
  // blocked because the ledger query was slow — the account is still the point.
  const [ledgerResult, ticketsResult] = await Promise.allSettled([
    can(me, PERMISSIONS.financeRead)
      ? get<Ledger>(`/api/admin/finance/${config.kind}s/${id}/ledger?limit=8`)
      : Promise.resolve(null),
    can(me, PERMISSIONS.supportRead)
      ? get<{ items: Ticket[] }>(`/api/admin/support/accounts/${config.kind}/${id}`)
      : Promise.resolve(null),
  ]);
  const ledger = ledgerResult.status === "fulfilled" ? ledgerResult.value : null;
  const tickets = ticketsResult.status === "fulfilled" ? ticketsResult.value : null;

  return (
    <div className="space-y-6">
      <Link
        href={`/people/${slug}`}
        className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-[var(--foreground)]"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        All {slug}
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-semibold tracking-tight">
            {person.name ?? config.label}
          </h1>
          <p className="mt-1 text-sm text-muted">
            {config.label} · joined {timeAgo(person.created_at)}
            {person.plate_number ? ` · ${person.plate_number}` : ""}
            {person.vendor_type ? ` · ${person.vendor_type}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {person.is_suspended ? <Badge tone="danger">Suspended</Badge> : <Badge tone="success">Active</Badge>}
          {person.kyc_status ? (
            <Badge tone={person.kyc_status === "approved" ? "success" : "warning"}>
              KYC {person.kyc_status}
            </Badge>
          ) : null}
        </div>
      </div>

      {person.is_suspended ? (
        <div
          role="status"
          className="rounded-xl border border-[var(--danger)] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)] px-5 py-4"
        >
          <p className="font-medium text-[var(--danger)]">
            Suspended {person.suspended_at ? timeAgo(person.suspended_at) : ""}
          </p>
          {person.suspension_reason ? (
            <p className="mt-1 text-sm text-muted">{person.suspension_reason}</p>
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-4 sm:grid-cols-3">
        <Stat label="Paid orders" value={formatNumber(person.orders.paid_count)} />
        <Stat label="Lifetime value" value={formatMoney(person.orders.lifetime_value)} />
        <Stat
          label="Wallet balance"
          value={formatMoney(person.wallet_balance)}
          hint={
            person.debt_balance && Number(person.debt_balance) > 0
              ? `Owes ${formatMoney(person.debt_balance)}`
              : undefined
          }
          tone={person.debt_balance && Number(person.debt_balance) > 0 ? "warning" : "neutral"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-[2fr_1fr]">
        <Card className="overflow-hidden">
          <CardHeader
            title="Recent orders"
            description={
              person.orders.last_order_at
                ? `Last order ${timeAgo(person.orders.last_order_at)}.`
                : "No paid orders yet."
            }
          />
          {person.recent_orders.length === 0 ? (
            <EmptyState title="No orders yet" />
          ) : (
            <div className="scroll-x">
              <table className="w-full min-w-[32rem] text-sm">
                <caption className="sr-only">Ten most recent orders</caption>
                <thead>
                  <tr className="border-b border-default bg-surface-muted text-left">
                    <th scope="col" className="px-4 py-2.5 font-medium">Order</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Status</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Total</th>
                    <th scope="col" className="px-4 py-2.5 font-medium">Placed</th>
                  </tr>
                </thead>
                <tbody>
                  {person.recent_orders.map((order) => (
                    <tr key={order.id} className="border-b border-default last:border-0">
                      <td className="px-4 py-2.5 font-mono text-xs">{order.id.slice(0, 8)}</td>
                      <td className="px-4 py-2.5">
                        <Badge tone={order.status === "delivered" ? "success" : order.status === "cancelled" ? "danger" : "neutral"}>
                          {order.status}
                        </Badge>
                      </td>
                      <td className="px-4 py-2.5 tabular-nums">{formatMoney(order.total)}</td>
                      <td className="px-4 py-2.5 text-muted">{formatDateTime(order.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <AccountActions
          kind={config.kind}
          slug={slug}
          id={person.id}
          isSuspended={person.is_suspended}
          canSuspend={can(me, config.suspend)}
          canViewPii={can(me, PERMISSIONS.piiView)}
          canAdjust={can(me, PERMISSIONS.financeAdjust)}
          walletBalance={person.wallet_balance ?? "0.00"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {ledger ? (
          <Card>
            <CardHeader
              title="Wallet movements"
              description={`Balance ${formatMoney(ledger.balance)}. Newest first.`}
            />
            {ledger.items.length === 0 ? (
              <EmptyState
                title="Nothing has moved"
                description="No credits, debits, payouts or refunds on this wallet yet."
              />
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {ledger.items.map((entry) => {
                  const debit = entry.amount.trim().startsWith("-");
                  return (
                    <li key={entry.id} className="flex flex-wrap items-baseline gap-2 px-5 py-3">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {entry.transaction_type.replace(/_/g, " ")}
                        </p>
                        {entry.description ? (
                          <p className="mt-0.5 truncate text-xs text-muted">{entry.description}</p>
                        ) : null}
                        <p className="mt-0.5 text-xs text-muted">
                          {formatDateTime(entry.created_at)}
                          {entry.status !== "completed" ? ` · ${entry.status}` : ""}
                        </p>
                      </div>
                      <span
                        className={
                          debit
                            ? "shrink-0 tabular-nums text-sm text-[var(--danger)]"
                            : "shrink-0 tabular-nums text-sm text-[var(--success)]"
                        }
                      >
                        {formatMoney(entry.amount)}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        ) : null}

        {tickets ? (
          <Card>
            <CardHeader
              title="Support history"
              description="Somebody on their fourth ticket about the same thing is a different conversation."
            />
            {tickets.items.length === 0 ? (
              <EmptyState
                title="They have never asked for help"
                description="Tickets raised from the app appear here."
              />
            ) : (
              <ul className="divide-y divide-[var(--border)]">
                {tickets.items.map((ticket) => (
                  <li key={ticket.id}>
                    <Link
                      href={`/support/${ticket.id}`}
                      className="flex flex-wrap items-baseline justify-between gap-2 px-5 py-3 hover:bg-surface-muted"
                    >
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{ticket.subject}</p>
                        <p className="mt-0.5 text-xs text-muted">
                          {formatDateTime(ticket.created_at)}
                        </p>
                      </div>
                      <Badge
                        tone={
                          ticket.status === "open"
                            ? "warning"
                            : ticket.status === "resolved"
                              ? "success"
                              : "neutral"
                        }
                      >
                        {ticket.status}
                      </Badge>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        ) : null}
      </div>
    </div>
  );
}
