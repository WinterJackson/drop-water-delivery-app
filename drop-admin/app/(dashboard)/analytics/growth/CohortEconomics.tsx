import { AlertTriangle, Check } from "lucide-react";

import { Badge, Card, CardHeader, EmptyState } from "@/components/ui/primitives";
import { formatMoney, formatNumber } from "@/lib/utils/format";

/**
 * Whether acquiring these customers paid for itself.
 *
 * The retention grid on `/analytics` answers *do customers come back*. This
 * answers what a business acts on: **did the ones who came back pay back what
 * it cost to get them**, and in which month.
 *
 * Two rules this component exists to keep:
 *
 * 1. **Measured and entered acquisition cost never merge silently.** The
 *    platform can prove the first from its own order rows and cannot see the
 *    second at all. A cohort with nothing entered is marked as such rather than
 *    rendering a flatteringly small CAC as though it were the answer.
 * 2. **Nothing here is projected.** Every figure is money that has already
 *    moved. An LTV extrapolated from four months of data is a guess wearing a
 *    number's clothes, and it is the number people raise budgets against.
 */

export type Cohort = {
  cohort: string;
  size: number;
  cac: {
    measured: string;
    entered: string | null;
    blended: string;
    has_entered_spend: boolean;
  };
  realised_per_customer: string;
  payback_month: number | null;
  months: {
    month: number;
    customers: number;
    retention_pct: string;
    net: string;
    cumulative_net: string;
    cumulative_per_customer: string;
  }[];
};

function monthLabel(iso: string) {
  const date = new Date(`${iso}T00:00:00Z`);
  return date.toLocaleDateString(undefined, {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function CohortEconomics({ cohorts }: { cohorts: Cohort[] }) {
  if (cohorts.length === 0) {
    return (
      <Card>
        <CardHeader
          title="Cohort economics"
          description="Nothing to show yet — a cohort appears once its first delivery lands."
        />
        <EmptyState
          title="No delivered orders"
          description="Cohorts are built from delivered orders, not signups: an account that never received water was not acquired."
        />
      </Card>
    );
  }

  const widest = Math.max(...cohorts.map((c) => c.months.length));
  const offsets = Array.from({ length: widest }, (_, i) => i);

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Cohort economics"
        description="Cumulative platform contribution per acquired customer, by months since their first delivery. The cell turns green when the cohort has covered what it cost to acquire."
      />

      <div className="scroll-x">
        <table className="w-full min-w-[52rem] text-sm">
          <caption className="sr-only">
            Cumulative contribution per customer by cohort and month offset,
            against that cohort&apos;s acquisition cost
          </caption>
          <thead>
            <tr className="border-b border-default bg-surface-muted text-left text-xs">
              <th scope="col" className="px-4 py-2.5 font-medium">Cohort</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Customers</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">CAC</th>
              <th scope="col" className="px-4 py-2.5 text-right font-medium">Payback</th>
              {offsets.map((offset) => (
                <th key={offset} scope="col" className="px-3 py-2.5 text-right font-medium">
                  M{offset}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cohorts.map((cohort) => {
              const cac = Number(cohort.cac.blended);
              return (
                <tr key={cohort.cohort} className="border-b border-default last:border-0">
                  <th scope="row" className="whitespace-nowrap px-4 py-2.5 text-left font-medium">
                    {monthLabel(cohort.cohort)}
                  </th>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {formatNumber(cohort.size)}
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {formatMoney(cohort.cac.blended)}
                    {/* Said plainly rather than implied by a footnote. A CAC
                        built only from the discount the platform can measure is
                        not the cost of acquiring anybody, and the number is
                        small enough to be believed. */}
                    {!cohort.cac.has_entered_spend ? (
                      <p className="text-[11px] text-muted">measured only</p>
                    ) : null}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {cohort.payback_month === null ? (
                      <span className="text-muted">—</span>
                    ) : (
                      <Badge tone="success">
                        <Check className="h-3 w-3" aria-hidden />
                        M{cohort.payback_month}
                      </Badge>
                    )}
                  </td>
                  {offsets.map((offset) => {
                    const cell = cohort.months[offset];
                    if (!cell) {
                      return (
                        <td key={offset} className="px-3 py-2.5 text-right text-muted">
                          {/* Not zero — this cohort has not lived this long
                              yet, which is a different fact from earning
                              nothing, and colouring them alike would make every
                              young cohort look like a failure. */}
                          ·
                        </td>
                      );
                    }
                    const value = Number(cell.cumulative_per_customer);
                    const covered = cac > 0 && value >= cac;
                    return (
                      <td
                        key={offset}
                        className="px-3 py-2.5 text-right tabular-nums"
                        style={
                          covered
                            ? {
                                backgroundColor:
                                  "color-mix(in oklch, var(--success) 12%, transparent)",
                              }
                            : undefined
                        }
                        title={`${cell.customers} of ${cohort.size} ordered · ${cell.retention_pct}% retained`}
                      >
                        {formatMoney(cell.cumulative_per_customer)}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="border-t border-default px-5 py-3 text-xs text-muted">
        Contribution is <code>platform_net</code> — the platform&apos;s cut after the
        M-Pesa or cash-handling tariff — frozen on each order when it was placed, so
        changing a commission today cannot restate what an old cohort earned.
      </p>
    </Card>
  );
}

/** The honest headline: what is measured, what was entered, and what neither covers. */
export function AcquisitionSummary({
  summary,
}: {
  summary: {
    customers_acquired: number;
    measured_spend: string;
    entered_spend: string;
    unattributed_spend: string;
    measured_cac: string | null;
    blended_cac: string | null;
    months_with_entered_spend: number;
    months_covered: number;
    cohorts_paid_back: number;
    median_payback_month: number | null;
  };
}) {
  const blank = summary.months_with_entered_spend === 0;
  const unattributed = Number(summary.unattributed_spend);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Figure
          label="Customers acquired"
          value={formatNumber(summary.customers_acquired)}
          hint={`across ${summary.months_covered} cohort${summary.months_covered === 1 ? "" : "s"}`}
        />
        <Figure
          label="Measured CAC"
          value={summary.measured_cac ? formatMoney(summary.measured_cac) : "—"}
          hint="welcome discount the platform absorbed"
        />
        <Figure
          label="Blended CAC"
          value={summary.blended_cac ? formatMoney(summary.blended_cac) : "—"}
          hint={blank ? "no off-platform spend recorded" : "including entered spend"}
          tone={blank ? "warning" : "neutral"}
        />
        <Figure
          label="Median payback"
          value={
            summary.median_payback_month === null
              ? "—"
              : `M${summary.median_payback_month}`
          }
          hint={`${summary.cohorts_paid_back} cohort${summary.cohorts_paid_back === 1 ? "" : "s"} have paid back`}
        />
      </div>

      {blank ? (
        <div
          role="status"
          className="flex items-start gap-3 rounded-xl border border-[var(--warning)] bg-[color-mix(in_oklch,var(--warning)_8%,transparent)] px-5 py-4"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" aria-hidden />
          <div>
            <p className="font-medium">This CAC counts only what the platform can see.</p>
            <p className="mt-1 text-sm text-muted">
              The welcome discount is real acquisition spend and it is recorded on every
              order — but posters, a branded boda, ads and referrals are not in this
              database and never will be. Until they are entered below, the blended CAC
              is the measured one under a different name, and it makes acquisition look
              cheaper than it is.
            </p>
          </div>
        </div>
      ) : null}

      {unattributed > 0 ? (
        <div
          role="status"
          className="flex items-start gap-3 rounded-xl border border-default px-5 py-4"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-muted" aria-hidden />
          <div>
            <p className="font-medium">
              {formatMoney(summary.unattributed_spend)} was spent in months that acquired
              nobody.
            </p>
            <p className="mt-1 text-sm text-muted">
              It is counted in the blended CAC above rather than dropped, because a month
              with spend and no customers is the clearest signal acquisition is not
              working — and the arithmetic that hides it is the arithmetic that flatters.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function Figure({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "warning";
}) {
  return (
    <Card className="p-5">
      <p className="text-xs text-muted">{label}</p>
      <p
        className="mt-1 text-2xl font-semibold tabular-nums"
        style={tone === "warning" ? { color: "var(--warning)" } : undefined}
      >
        {value}
      </p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </Card>
  );
}
