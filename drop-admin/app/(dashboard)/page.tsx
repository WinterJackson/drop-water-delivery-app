import {
  AlertTriangle,
  BadgeCheck,
  Banknote,
  LifeBuoy,
  PackageSearch,
  Store,
  Truck,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { redirect } from "next/navigation";

import { visibleSections } from "@/components/shell/nav-config";
import { GaugeRing } from "@/components/charts/GaugeRing";
import { RevenueChart, type Point } from "@/components/charts/RevenueChart";
import { Sparkline } from "@/components/charts/Sparkline";
import { Badge, Card, CardHeader, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import type { NavCounts } from "@/lib/nav-counts";
import type { AdminMe } from "@/lib/permissions";
import { formatMoney, formatNumber } from "@/lib/utils/format";

export const metadata = { title: "Dashboard" };

type Overview = {
  needs_attention: { pending_kyc: number; pending_payouts: number; stuck_payouts: number };
  last_7_days: { revenue: string; gmv: string; orders: number };
  totals: { customers: number; vendors: number; riders: number; active_vendors: number };
};

/** Only the slice of `/analytics/summary` this page draws. */
type Pulse = {
  timeseries: { points: Point[] };
  unit_economics: { revenue: string; gmv: string; orders: number; avg_order_value: string; take_rate_pct: string };
  operations: { cancellation_rate_pct: string; dispute_rate_pct: string; avg_delivery_minutes: string; under_review: number };
  growth: Record<string, { current: number; previous: number; change_pct: string | null }>;
  supply: {
    riders: { deployable_now: number; marked_available: number; kyc_approved: number; total: number };
    vendors: { online_now: number; total: number };
  };
  customers: { repeat_rate_pct: string };
};

const WINDOW_DAYS = 30;

export default async function OverviewPage() {
  let data: Overview;
  try {
    data = await get<Overview>("/api/admin/overview");
  } catch (error) {
    // A support agent holds no `analytics.read` — this page is not theirs, and
    // it is also the URL they land on when they sign in. Showing them a refusal
    // on arrival reads as "you have no access" rather than "wrong page", so send
    // them to the first screen they *can* work instead.
    if (error instanceof ApiError && error.type === "permission_required") {
      const me = await get<AdminMe>("/api/admin/me").catch(() => null);
      const landing = me
        ? visibleSections(me.permissions)[0]?.items[0]?.href
        : undefined;
      if (landing && landing !== "/") redirect(landing);
    }
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the dashboard" detail={message} />;
  }

  // The charts are the *second* thing this page is for. If the analytics roll-up
  // is slow or rate-limited, the queues that need working still render — a
  // dashboard that goes blank because a chart failed is a dashboard that hides
  // the payout nobody has approved.
  let pulse: Pulse | null = null;
  let counts: NavCounts = {};
  const [pulseResult, countsResult] = await Promise.allSettled([
    get<Pulse>(`/api/admin/analytics/summary?days=${WINDOW_DAYS}`),
    get<NavCounts>("/api/admin/nav/counts"),
  ]);
  if (pulseResult.status === "fulfilled") pulse = pulseResult.value;
  if (countsResult.status === "fulfilled") counts = countsResult.value;

  const { needs_attention: attention, last_7_days: week, totals } = data;

  const queue = [
    {
      href: "/operations/kyc",
      label: "Riders waiting for verification",
      count: attention.pending_kyc,
      // Riders cannot work at all until this is done, so it is the one queue
      // that blocks supply rather than merely ageing.
      hint: "They can't accept deliveries until you review them",
      icon: BadgeCheck,
      tone: attention.pending_kyc > 0 ? ("warning" as const) : ("neutral" as const),
    },
    {
      href: "/operations/orders",
      label: "Orders stuck",
      count: counts.orders_stuck ?? 0,
      hint: "Paused for a decision, or accepted and never dispatched",
      icon: AlertTriangle,
      tone: (counts.orders_stuck ?? 0) > 0 ? ("warning" as const) : ("neutral" as const),
    },
    {
      href: "/operations/disputes",
      label: "Bottle disputes open",
      count: counts.disputes ?? 0,
      hint: "A rider and a vendor disagree about the empties",
      icon: PackageSearch,
      tone: (counts.disputes ?? 0) > 0 ? ("warning" as const) : ("neutral" as const),
    },
    {
      href: "/support",
      // `counts.support` is `open` tickets only — a ticket an administrator has
      // already replied to is `pending` and waiting on the requester, so it is
      // not something anyone here can act on this morning.
      label: "Support tickets unanswered",
      count: counts.support ?? 0,
      hint: "Nobody has replied to these yet",
      icon: LifeBuoy,
      tone: (counts.support ?? 0) > 0 ? ("warning" as const) : ("neutral" as const),
    },
    {
      href: "/operations/vendors",
      label: "Stores awaiting verification",
      count: counts.vendor_verification ?? 0,
      hint: "Confirm the paperwork before they trade at scale",
      icon: Store,
      tone: (counts.vendor_verification ?? 0) > 0 ? ("warning" as const) : ("neutral" as const),
    },
    {
      href: "/finance/payouts",
      label: "Payouts awaiting approval",
      count: attention.pending_payouts,
      hint: "Vendors and riders waiting to be paid",
      icon: Banknote,
      tone: attention.pending_payouts > 0 ? ("warning" as const) : ("neutral" as const),
    },
    {
      href: "/finance/payouts?status=processing",
      label: "Payouts stuck in processing",
      count: attention.stuck_payouts,
      hint: "Debited over a day ago with no result from Safaricom — reconcile by hand",
      icon: AlertTriangle,
      tone: attention.stuck_payouts > 0 ? ("danger" as const) : ("neutral" as const),
    },
  ];

  const waiting = queue.filter((item) => item.count > 0);
  const points = pulse?.timeseries.points ?? [];

  // Sparklines are drawn from the same gap-filled series the chart uses, so a
  // day with no orders pulls the line to zero rather than being skipped.
  const revenueSeries = points.map((p) => Number(p.revenue));
  const gmvSeries = points.map((p) => Number(p.gmv));
  const orderSeries = points.map((p) => p.orders);

  const growth = pulse?.growth ?? {};
  const delta = (key: string) => {
    const change = growth[key]?.change_pct;
    return change === null || change === undefined ? undefined : Number(change);
  };

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-muted">
          What needs attention, and how the platform has been running.
        </p>
      </div>

      <section aria-labelledby="attention" className="space-y-3">
        <h2 id="attention" className="text-sm font-medium text-muted">
          Needs attention
        </h2>

        {waiting.length === 0 ? (
          <Card>
            <EmptyState
              icon={<BadgeCheck className="h-8 w-8" />}
              title="Nothing needs attention"
              description="No riders waiting for verification, no stuck orders, no payouts pending. This is what a good morning looks like."
            />
          </Card>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {waiting.map((item) => {
              const Icon = item.icon;
              return (
                <Link key={item.href} href={item.href} className="group">
                  <Card className="h-full p-5 transition-colors group-hover:border-[var(--accent)]">
                    <div className="flex items-start justify-between gap-3">
                      <Icon
                        className={
                          item.tone === "danger"
                            ? "h-5 w-5 text-[var(--danger)]"
                            : "h-5 w-5 text-[var(--warning)]"
                        }
                        aria-hidden
                      />
                      <Badge tone={item.tone === "danger" ? "danger" : "warning"}>
                        {formatNumber(item.count)}
                      </Badge>
                    </div>
                    <p className="mt-3 font-medium">{item.label}</p>
                    <p className="mt-1 text-sm text-muted">{item.hint}</p>
                  </Card>
                </Link>
              );
            })}
          </div>
        )}
      </section>

      <section aria-labelledby="week" className="space-y-3">
        <h2 id="week" className="text-sm font-medium text-muted">
          Last 7 days
          <span className="ml-2 font-normal">
            (the trend line and change are over {WINDOW_DAYS} days)
          </span>
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Platform revenue"
            value={formatMoney(week.revenue)}
            hint="Commission, fees and markups"
            trend={<Sparkline values={revenueSeries} label={`Daily revenue over ${WINDOW_DAYS} days`} tone="success" />}
          />
          <Stat
            label="Gross merchandise value"
            value={formatMoney(week.gmv)}
            hint="Total customers paid"
            trend={<Sparkline values={gmvSeries} label={`Daily GMV over ${WINDOW_DAYS} days`} />}
          />
          <Stat
            label="Paid orders"
            value={formatNumber(week.orders)}
            hint={pulse ? `${formatNumber(pulse.unit_economics.orders)} in ${WINDOW_DAYS} days` : undefined}
            trend={<Sparkline values={orderSeries} label={`Daily paid orders over ${WINDOW_DAYS} days`} />}
          />
          <Stat
            label="Average order"
            value={formatMoney(pulse?.unit_economics.avg_order_value)}
            hint={pulse ? `Take rate ${pulse.unit_economics.take_rate_pct}%` : undefined}
          />
        </div>
      </section>

      {pulse ? (
        <>
          <Card>
            <CardHeader
              title="Revenue, GMV and volume"
              description={`Daily over the last ${WINDOW_DAYS} days. Days with no orders are shown as zero, not skipped.`}
              action={
                <Link
                  href="/analytics"
                  className="rounded-lg border border-default px-3 py-1.5 text-sm hover:bg-surface-muted"
                >
                  Full analytics
                </Link>
              }
            />
            <div className="p-3 sm:p-5">
              <RevenueChart points={points} />
            </div>
          </Card>

          <section aria-labelledby="health" className="space-y-3">
            <h2 id="health" className="text-sm font-medium text-muted">
              Health
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <GaugeRing
                label="Orders delivered"
                value={(100 - Number(pulse.operations.cancellation_rate_pct)).toFixed(2)}
                hint={`${pulse.operations.cancellation_rate_pct}% cancelled`}
                warn={90}
                danger={80}
              />
              <GaugeRing
                label="Repeat customers"
                value={pulse.customers.repeat_rate_pct}
                hint="Water is a repeat purchase or it is nothing"
                warn={30}
                danger={15}
              />
              <GaugeRing
                label="Riders deployable"
                value={
                  pulse.supply.riders.total > 0
                    ? ((pulse.supply.riders.deployable_now / pulse.supply.riders.total) * 100).toFixed(1)
                    : "0.0"
                }
                hint={`${formatNumber(pulse.supply.riders.deployable_now)} of ${formatNumber(pulse.supply.riders.total)} verified, available and not suspended`}
                warn={20}
                danger={5}
              />
              <GaugeRing
                label="Orders disputed"
                value={pulse.operations.dispute_rate_pct}
                hint={`Average delivery ${pulse.operations.avg_delivery_minutes} min`}
                invert
                warn={2}
                danger={5}
                max={20}
              />
            </div>
          </section>
        </>
      ) : (
        <Card>
          <EmptyState
            title="Charts couldn't load"
            description="The analytics roll-up didn't answer in time. The queues above are live — try the Analytics page for the detail."
          />
        </Card>
      )}

      <section aria-labelledby="totals" className="space-y-3">
        <h2 id="totals" className="text-sm font-medium text-muted">
          Platform
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Customers"
            value={formatNumber(totals.customers)}
            delta={delta("customers")}
            hint={pulse ? `${formatNumber(growth.customers?.current ?? 0)} new in ${WINDOW_DAYS} days` : undefined}
            icon={<UserRound className="h-4 w-4" />}
          />
          <Stat
            label="Riders"
            value={formatNumber(totals.riders)}
            delta={delta("riders")}
            hint={
              pulse
                ? `${formatNumber(pulse.supply.riders.kyc_approved)} verified`
                : undefined
            }
            icon={<Truck className="h-4 w-4" />}
          />
          <Stat
            label="Vendors"
            value={formatNumber(totals.vendors)}
            delta={delta("vendors")}
            hint={pulse ? `${formatNumber(pulse.supply.vendors.online_now)} open right now` : undefined}
            icon={<Store className="h-4 w-4" />}
          />
          <Stat
            label="Trading vendors"
            value={formatNumber(totals.active_vendors)}
            hint={
              totals.vendors - totals.active_vendors > 0
                ? `${formatNumber(totals.vendors - totals.active_vendors)} suspended`
                : "All trading"
            }
            tone={totals.vendors - totals.active_vendors > 0 ? "warning" : "neutral"}
            icon={<Store className="h-4 w-4" />}
          />
        </div>
      </section>
    </div>
  );
}
