import { Coins } from "lucide-react";

import { Card, CardHeader } from "@/components/ui/primitives";
import { formatMoney, formatNumber } from "@/lib/utils/format";

/**
 * What the platform owes its customers, aged.
 *
 * The float above is the *rider* side of the bottle economy — empties on their
 * way back to a store. This is the third relationship and the one with real
 * money against it: customers who paid a refundable deposit and are holding a
 * bottle. It was maintained correctly from the day it was built and appeared on
 * no screen, so the platform's largest customer-facing liability could only be
 * read out of a database client.
 *
 * **Aged, not totalled.** One number cannot distinguish a healthy circulating
 * pool of bottles from four hundred sold at cost to people who are never coming
 * back, and those two want opposite responses. The last bucket is the one to
 * read: a deposit untouched for a year is a bottle that is not returning and a
 * liability that will never be called.
 */

export type DepositLiability = {
  total_liability: string;
  total_bottles: number;
  accounts_holding: number;
  buckets: { label: string; amount: string; bottles: number; accounts: number }[];
};

export function DepositLiabilityPanel({ data }: { data: DepositLiability }) {
  const total = Number(data.total_liability) || 0;
  // Bars are for shape at a glance; every figure is also written out. Colour and
  // length never carry meaning on their own here.
  const widest = Math.max(...data.buckets.map((b) => Number(b.amount) || 0), 1);

  return (
    <Card>
      <CardHeader
        title="Customer deposits held"
        description="Refundable deposits customers have paid, by how long they have sat untouched. Returned through a rider collection or from the customer's balances screen."
      />

      <div className="grid gap-4 border-b border-default px-5 pb-4 sm:grid-cols-3">
        <div>
          <p className="text-xs text-muted">Total owed to customers</p>
          <p className="mt-0.5 flex items-center gap-2 text-xl font-semibold tabular-nums">
            <Coins className="h-4 w-4 text-muted" aria-hidden />
            {formatMoney(data.total_liability)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Bottles with customers</p>
          <p className="mt-0.5 text-xl font-semibold tabular-nums">
            {formatNumber(data.total_bottles)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Accounts holding</p>
          <p className="mt-0.5 text-xl font-semibold tabular-nums">
            {formatNumber(data.accounts_holding)}
          </p>
        </div>
      </div>

      {total === 0 ? (
        <p className="px-5 py-6 text-sm text-muted">
          No customer is holding a bottle on deposit. Every deposit taken has
          been returned, or none has been taken yet.
        </p>
      ) : (
        <div className="scroll-x">
          <table className="w-full min-w-[34rem] text-sm">
            <caption className="sr-only">
              Customer bottle deposits by age since the deposit last moved
            </caption>
            <thead>
              <tr className="border-b border-default text-left text-xs text-muted">
                <th scope="col" className="px-5 py-2 font-medium">Untouched for</th>
                <th scope="col" className="px-5 py-2 text-right font-medium">Amount</th>
                <th scope="col" className="px-5 py-2 text-right font-medium">Bottles</th>
                <th scope="col" className="px-5 py-2 text-right font-medium">Accounts</th>
                <th scope="col" className="px-5 py-2 font-medium">Share</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--border)]">
              {data.buckets.map((bucket) => {
                const amount = Number(bucket.amount) || 0;
                const oldest = bucket.label === "over a year" && amount > 0;
                return (
                  <tr key={bucket.label}>
                    <th scope="row" className="px-5 py-2.5 text-left font-normal">
                      {bucket.label}
                      {oldest ? (
                        <span className="ml-2 text-xs text-[var(--warning)]">
                          unlikely to return
                        </span>
                      ) : null}
                    </th>
                    <td className="px-5 py-2.5 text-right tabular-nums">
                      {formatMoney(bucket.amount)}
                    </td>
                    <td className="px-5 py-2.5 text-right tabular-nums">
                      {formatNumber(bucket.bottles)}
                    </td>
                    <td className="px-5 py-2.5 text-right tabular-nums">
                      {formatNumber(bucket.accounts)}
                    </td>
                    <td className="px-5 py-2.5">
                      <div
                        className="h-2 rounded-full bg-surface-muted"
                        role="presentation"
                      >
                        <div
                          className="h-2 rounded-full"
                          style={{
                            width: `${Math.round((amount / widest) * 100)}%`,
                            background: oldest ? "var(--warning)" : "var(--chart-1)",
                          }}
                        />
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <p className="border-t border-default px-5 py-3 text-xs text-muted">
        A deposit untouched for the period set on{" "}
        <span className="font-medium">Pricing &amp; fees</span> becomes wallet
        credit after two warnings. The customer keeps the money as credit they
        can spend on water; what the platform writes off is the bottle.
      </p>
    </Card>
  );
}
