import { Card, CardHeader } from "@/components/ui/primitives";
import { formatNumber } from "@/lib/utils/format";

export type Cohort = {
  /** ISO date of the first day of the month customers were acquired. */
  cohort: string;
  size: number;
  retention: { month: number; customers: number; pct: string }[];
};

/**
 * Do customers come back?
 *
 * For bottled water this is *the* question — it is a repeat purchase or it is
 * nothing. Each row is everyone whose first paid order fell in that month; each
 * column is how many of them ordered again N months later.
 *
 * A real `<table>` with row and column headers, so a screen reader announces
 * "March 2026, month 2, 41%" rather than reading a hundred loose numbers.
 * Shading is redundant with the figure printed in every cell.
 *
 * Read down a column, not across a row: falling numbers down `Month 1` mean the
 * product is getting worse at holding people, and that shows up here months
 * before it shows up in revenue.
 */
export function CohortGrid({ cohorts }: { cohorts: Cohort[] }) {
  const width = Math.max(1, ...cohorts.map((c) => c.retention.length));
  const columns = Array.from({ length: width }, (_, index) => index);

  return (
    <Card>
      <CardHeader
        title="Customer retention"
        description="Each row is the customers who first ordered that month, and how many came back."
      />

      {cohorts.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-muted">
          Not enough history yet. A cohort needs a full month of paid orders before it means
          anything.
        </p>
      ) : (
        <div className="scroll-x px-5 py-4">
          <table className="w-max min-w-full border-separate border-spacing-[2px] text-xs">
            <caption className="sr-only">
              Customer retention by acquisition month and months since first order
            </caption>
            <thead>
              <tr>
                <th scope="col" className="pb-1 pr-3 text-left font-medium text-muted">
                  Cohort
                </th>
                <th scope="col" className="pb-1 pr-3 text-right font-medium text-muted">
                  Size
                </th>
                {columns.map((month) => (
                  <th key={month} scope="col" className="w-14 pb-1 text-center font-medium text-muted">
                    {month === 0 ? "M0" : `M${month}`}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {cohorts.map((cohort) => (
                <tr key={cohort.cohort}>
                  <th scope="row" className="whitespace-nowrap pr-3 text-left font-normal">
                    {new Date(cohort.cohort).toLocaleDateString("en-KE", {
                      month: "short",
                      year: "numeric",
                    })}
                  </th>
                  <td className="pr-3 text-right tabular-nums text-muted">
                    {formatNumber(cohort.size)}
                  </td>

                  {columns.map((month) => {
                    const cell = cohort.retention.find((r) => r.month === month);
                    if (!cell) {
                      return (
                        <td key={month} className="text-center text-muted">
                          {/* This cohort has not lived this long yet. Distinct
                              from 0%, which means they left. */}
                          <span aria-label="not yet">·</span>
                        </td>
                      );
                    }

                    const pct = Number(cell.pct);
                    return (
                      <td
                        key={month}
                        title={`${formatNumber(cell.customers)} of ${formatNumber(cohort.size)} ordered again`}
                        className="rounded-[3px] px-1 py-1.5 text-center tabular-nums"
                        style={{
                          backgroundColor: `color-mix(in oklch, var(--accent) ${Math.round(
                            Math.min(100, pct),
                          )}%, transparent)`,
                        }}
                      >
                        {cell.pct}%
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
