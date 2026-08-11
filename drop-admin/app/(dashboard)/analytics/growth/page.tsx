import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { AcquisitionSummary, CohortEconomics, type Cohort } from "./CohortEconomics";
import { SpendEditor, type SpendEntry } from "./SpendEditor";

export const metadata = { title: "Acquisition" };

const RANGES = [6, 12, 24] as const;

type Growth = {
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
    best_cohort: string | null;
  };
  cohorts: Cohort[];
  basis: { status: string; contribution: string; measured_spend: string };
};

/**
 * What a customer costs, and whether they pay it back.
 *
 * `/analytics` carries the retention grid: *do customers come back*. This page
 * carries the question a business acts on — **did the ones who came back pay
 * back what it cost to get them** — which the platform has had every input for
 * on every order since the first one, and had never once added up.
 *
 * Its own page rather than a card on `/analytics` because it is measured in
 * months while that screen is measured in days, and because it is the only
 * screen in the console that *takes input from the business itself*: the half
 * of acquisition cost no query here can find.
 */
export default async function GrowthPage({
  searchParams,
}: {
  searchParams: Promise<{ months?: string }>;
}) {
  const params = await searchParams;
  const parsed = Number(params.months);
  const months = RANGES.includes(parsed as (typeof RANGES)[number]) ? parsed : 12;

  let growth: Growth;
  let spend: { items: SpendEntry[]; total: string };
  let me: AdminMe;
  try {
    [growth, spend, me] = await Promise.all([
      get<Growth>(`/api/admin/growth/cohorts?months=${months}`),
      get<{ items: SpendEntry[]; total: string }>(`/api/admin/growth/spend?months=${months}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load acquisition data" detail={message} />;
  }

  return (
    <div className="space-y-8">
      <Link
        href="/analytics"
        className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-[var(--foreground)]"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        Analytics
      </Link>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Acquisition</h1>
          <p className="mt-1 text-sm text-muted">
            What a customer costs to acquire, and how long they take to pay it back.
            Every figure is money that has already moved — nothing here is projected.
          </p>
        </div>

        <nav aria-label="Window" className="scroll-x -mx-1 max-w-full px-1">
          <ul className="flex gap-1">
            {RANGES.map((range) => (
              <li key={range}>
                <Link
                  href={`/analytics/growth?months=${range}`}
                  aria-current={range === months ? "page" : undefined}
                  className={
                    range === months
                      ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                      : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                  }
                >
                  {range} months
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      <AcquisitionSummary summary={growth.summary} />

      <CohortEconomics cohorts={growth.cohorts} />

      <SpendEditor
        entries={spend.items}
        canEdit={can(me, PERMISSIONS.settingsManage)}
      />
    </div>
  );
}
