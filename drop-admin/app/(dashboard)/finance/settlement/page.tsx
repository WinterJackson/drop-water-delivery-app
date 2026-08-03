import { AlertTriangle, Banknote, HandCoins, RotateCcw, Wallet } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatMoney, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { SettleButton } from "./SettleButton";

export const metadata = { title: "Settlement" };

/**
 * Refunds, payouts and cash exposure — the three things that move money without
 * anybody pressing a button, none of which had a reader.
 *
 * The figure that matters most here is `unrefunded_failures`. A payout is
 * debited from the wallet before the M-Pesa call goes out, so a failure that
 * was never returned is money the platform took and did not give back. It was
 * an invariant declared in a docstring and checked by nothing.
 */

type RefundItem = {
  order_id: string;
  status: string;
  amount: string;
  customer: string | null;
  phone: string | null;
  order_status: string | null;
  hours_since_update: number | null;
  stuck: boolean;
  created_at: string | null;
};

type PayoutRow = {
  id: string;
  provider_type: string;
  provider_id: string;
  provider_name: string | null;
  amount: string;
  status: string;
  has_receipt: boolean;
  conversation_id: string | null;
  failure_reason: string | null;
  hours_since_update: number | null;
};

type Payload = {
  refunds: {
    summary: {
      pending: number;
      processing: number;
      failed: number;
      refunded: number;
      stuck_processing: number;
      stuck_after_hours: number;
      outstanding_amount: string;
      failed_amount: string;
      refunded_amount: string;
    };
    items: RefundItem[];
  };
  payouts: {
    summary: {
      pending: number;
      processing: number;
      completed: number;
      failed: number;
      completed_amount: string;
      in_flight_amount: string;
      stuck: number;
      stuck_after_hours: number;
      unreceipted: number;
      unrefunded_failures: number;
      unrefunded_amount: string;
    };
    stuck: PayoutRow[];
    unreceipted: PayoutRow[];
    unrefunded: PayoutRow[];
  };
  cash: {
    rider_float: string;
    riders_carrying: number;
    open_cash_orders: number;
    vendor_float: string;
    vendors_carrying: number;
    total_float: string;
    riders_in_debt: number;
    debt_total: string;
    wallet_liability: string;
  };
};

const REFUND_LABEL: Record<string, string> = {
  refund_pending: "Waiting to be sent",
  refund_processing: "Sent, unconfirmed",
  refund_failed: "Failed",
};

export default async function SettlementPage() {
  let data: Payload;
  let me: AdminMe;
  try {
    [data, me] = await Promise.all([
      get<Payload>("/api/admin/settlement"),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load settlement" detail={message} />;
  }

  const { refunds, payouts, cash } = data;
  const maySettle = can(me, PERMISSIONS.financeRefundApprove);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settlement</h1>
        <p className="mt-1 text-sm text-muted">
          Money that moves on a schedule rather than a click: refunds owed to
          customers, disbursements to riders and stores, and the cash sitting in
          people&apos;s hands right now.
        </p>
      </div>

      {payouts.summary.unrefunded_failures > 0 ? (
        <Card className="border-[color-mix(in_oklch,var(--danger)_40%,transparent)] p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <AlertTriangle className="h-4 w-4 text-[var(--danger)]" aria-hidden />
            {formatNumber(payouts.summary.unrefunded_failures)} failed payout
            {payouts.summary.unrefunded_failures === 1 ? "" : "s"} worth{" "}
            {formatMoney(payouts.summary.unrefunded_amount)} were never returned
          </h2>
          <p className="mt-1 text-sm text-muted">
            A payout is taken out of the wallet before the M-Pesa call goes out,
            so the money cannot be spent twice while it is in flight. That makes
            returning it on failure mandatory — and these did not get returned.
            The rider or store is short by this amount and has no way to see why.
          </p>
          <ul className="mt-3 space-y-2">
            {payouts.unrefunded.map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-baseline justify-between gap-2 border-b border-default pb-2 text-sm last:border-0 last:pb-0"
              >
                <Link
                  href={`/people/${row.provider_type === "vendor" ? "vendors" : "riders"}/${row.provider_id}`}
                  className="min-w-0 font-medium hover:underline"
                >
                  {row.provider_name ?? "Unnamed"}
                </Link>
                <span className="shrink-0">
                  <span className="font-medium">{formatMoney(row.amount)}</span>
                  <span className="text-muted"> — {row.failure_reason ?? "no reason recorded"}</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <section aria-label="Refunds">
        <h2 className="text-sm font-semibold">Refunds</h2>
        <p className="mt-1 mb-3 text-sm text-muted">
          Cancelled orders the customer had already paid for. A failed refund is
          somebody who paid for water they never got and did not get their money
          back — they do not write in, they leave.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Owed to customers"
            value={formatMoney(refunds.summary.outstanding_amount)}
            hint={`${formatNumber(refunds.summary.pending + refunds.summary.processing + refunds.summary.failed)} orders not yet settled`}
            tone={refunds.summary.failed > 0 ? "danger" : "neutral"}
            icon={<RotateCcw className="h-4 w-4" />}
          />
          <Stat
            label="Failed"
            value={formatNumber(refunds.summary.failed)}
            hint={
              refunds.summary.failed > 0
                ? `${formatMoney(refunds.summary.failed_amount)} — needs a person`
                : "Nothing has failed"
            }
            tone={refunds.summary.failed > 0 ? "danger" : "neutral"}
            icon={<AlertTriangle className="h-4 w-4" />}
          />
          <Stat
            label="Sent, unconfirmed"
            value={formatNumber(refunds.summary.processing)}
            hint={`${formatNumber(refunds.summary.stuck_processing)} over ${refunds.summary.stuck_after_hours}h — the callback probably never arrived`}
            tone={refunds.summary.stuck_processing > 0 ? "warning" : "neutral"}
            icon={<Banknote className="h-4 w-4" />}
          />
          <Stat
            label="Refunded"
            value={formatNumber(refunds.summary.refunded)}
            hint={`${formatMoney(refunds.summary.refunded_amount)} returned in full`}
            icon={<Wallet className="h-4 w-4" />}
          />
        </div>
      </section>

      {refunds.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<RotateCcw className="h-8 w-8" />}
            title="No refund is outstanding"
            description="Every cancelled paid order has had its money returned."
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="scroll-x">
            <table className="w-full min-w-[46rem] text-sm">
              <caption className="sr-only">Outstanding refunds</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Customer</th>
                  <th scope="col" className="px-4 py-3 font-medium">Amount</th>
                  <th scope="col" className="px-4 py-3 font-medium">State</th>
                  <th scope="col" className="px-4 py-3 font-medium">Waiting</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {refunds.items.map((item) => (
                  <tr key={item.order_id} className="border-b border-default last:border-0">
                    <td className="px-4 py-3">
                      <span className="font-medium">{item.customer ?? "Unnamed"}</span>
                      <Link
                        href={`/operations/orders?q=${item.order_id}`}
                        className="block text-xs text-muted hover:underline"
                      >
                        the order
                      </Link>
                    </td>
                    <td className="px-4 py-3 font-medium">{formatMoney(item.amount)}</td>
                    <td className="px-4 py-3">
                      <Badge
                        tone={
                          item.status === "refund_failed"
                            ? "danger"
                            : item.stuck
                              ? "warning"
                              : "neutral"
                        }
                      >
                        {REFUND_LABEL[item.status] ?? item.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">
                      {item.hours_since_update === null
                        ? "—"
                        : `${Math.round(item.hours_since_update)}h`}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {maySettle ? (
                        <SettleButton orderId={item.order_id} amount={formatMoney(item.amount)} />
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <p className="text-xs text-muted">
        There is no retry button, on purpose. A reversal that succeeded but lost
        its callback looks exactly like one that failed, and sending a second
        pays the customer twice out of the platform&apos;s own money with no way
        to claw it back. Settle it in the M-Pesa portal and record that here.
      </p>

      <section aria-label="Payouts">
        <h2 className="text-sm font-semibold">Payouts</h2>
        <p className="mt-1 mb-3 text-sm text-muted">
          Disbursements to riders and stores, and the two ways one goes wrong
          without anybody noticing.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Paid out"
            value={formatMoney(payouts.summary.completed_amount)}
            hint={`${formatNumber(payouts.summary.completed)} disbursements completed`}
            icon={<HandCoins className="h-4 w-4" />}
          />
          <Stat
            label="In flight"
            value={formatMoney(payouts.summary.in_flight_amount)}
            hint={`${formatNumber(payouts.summary.stuck)} stuck over ${payouts.summary.stuck_after_hours}h`}
            tone={payouts.summary.stuck > 0 ? "warning" : "neutral"}
            icon={<Banknote className="h-4 w-4" />}
          />
          <Stat
            label="Paid with no receipt"
            value={formatNumber(payouts.summary.unreceipted)}
            hint="Recorded as completed with nothing to evidence it"
            tone={payouts.summary.unreceipted > 0 ? "warning" : "neutral"}
            icon={<AlertTriangle className="h-4 w-4" />}
          />
          <Stat
            label="Failed and not returned"
            value={formatNumber(payouts.summary.unrefunded_failures)}
            hint={
              payouts.summary.unrefunded_failures > 0
                ? `${formatMoney(payouts.summary.unrefunded_amount)} taken and not given back`
                : "Every failure was returned to the wallet"
            }
            tone={payouts.summary.unrefunded_failures > 0 ? "danger" : "neutral"}
            icon={<Wallet className="h-4 w-4" />}
          />
        </div>
      </section>

      {payouts.stuck.length > 0 || payouts.unreceipted.length > 0 ? (
        <Card className="overflow-hidden">
          <div className="scroll-x">
            <table className="w-full min-w-[44rem] text-sm">
              <caption className="sr-only">Payouts needing attention</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Who</th>
                  <th scope="col" className="px-4 py-3 font-medium">Amount</th>
                  <th scope="col" className="px-4 py-3 font-medium">Problem</th>
                  <th scope="col" className="px-4 py-3 font-medium">Age</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ...payouts.stuck.map((row) => ({ row, problem: "Sent, never confirmed" })),
                  ...payouts.unreceipted.map((row) => ({ row, problem: "Completed with no receipt" })),
                ].map(({ row, problem }) => (
                  <tr key={`${problem}-${row.id}`} className="border-b border-default last:border-0">
                    <td className="px-4 py-3">
                      <Link
                        href={`/people/${row.provider_type === "vendor" ? "vendors" : "riders"}/${row.provider_id}`}
                        className="font-medium hover:underline"
                      >
                        {row.provider_name ?? "Unnamed"}
                      </Link>
                      <span className="block text-xs text-muted">
                        {row.provider_type === "vendor" ? "store" : "rider"}
                        {row.conversation_id ? ` · ${row.conversation_id}` : ""}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-medium">{formatMoney(row.amount)}</td>
                    <td className="px-4 py-3">
                      <Badge tone="warning">{problem}</Badge>
                    </td>
                    <td className="px-4 py-3">
                      {row.hours_since_update === null
                        ? "—"
                        : `${Math.round(row.hours_since_update)}h`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : (
        <Card>
          <EmptyState
            icon={<HandCoins className="h-8 w-8" />}
            title="Every payout is accounted for"
            description="Nothing is stuck in flight and every completed disbursement carries an M-Pesa receipt."
          />
        </Card>
      )}

      <section aria-label="Cash exposure">
        <h2 className="text-sm font-semibold">Cash in people&apos;s hands</h2>
        <p className="mt-1 mb-3 text-sm text-muted">
          On a cash order the customer pays the rider in notes, and the
          platform&apos;s and store&apos;s share is taken from the rider&apos;s
          wallet on delivery. Until then it is money the platform is owed and
          cannot see. This is the same arithmetic that gates every withdrawal,
          added up.
        </p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Committed cash float"
            value={formatMoney(cash.total_float)}
            hint={`${formatNumber(cash.open_cash_orders)} open cash orders`}
            tone={cash.open_cash_orders > 0 ? "warning" : "neutral"}
            icon={<HandCoins className="h-4 w-4" />}
          />
          <Stat
            label="Riders carrying it"
            value={formatNumber(cash.riders_carrying)}
            hint={`${formatMoney(cash.rider_float)} between them`}
            icon={<Banknote className="h-4 w-4" />}
          />
          <Stat
            label="Riders in debt"
            value={formatNumber(cash.riders_in_debt)}
            hint={
              cash.riders_in_debt > 0
                ? `${formatMoney(cash.debt_total)} owed — usually cash collected and not remitted`
                : "No negative balances"
            }
            tone={cash.riders_in_debt > 0 ? "danger" : "neutral"}
            icon={<AlertTriangle className="h-4 w-4" />}
          />
          <Stat
            label="Owed to riders and stores"
            value={formatMoney(cash.wallet_liability)}
            hint="Positive wallet balances — the platform's liability if everyone withdrew today"
            icon={<Wallet className="h-4 w-4" />}
          />
        </div>
      </section>
    </div>
  );
}
