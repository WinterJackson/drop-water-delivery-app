import Link from "next/link";

import { CohortGrid, type Cohort } from "@/components/charts/CohortGrid";
import { DonutChart } from "@/components/charts/DonutChart";
import { FunnelChart } from "@/components/charts/FunnelChart";
import { GaugeRing } from "@/components/charts/GaugeRing";
import { GrowthChart } from "@/components/charts/GrowthChart";
import { BarList, DemandHeatmap, StackedShareBar, StatList } from "@/components/charts/Panels";
import { RevenueChart, type Point } from "@/components/charts/RevenueChart";
import { Sparkline } from "@/components/charts/Sparkline";
import { Card, CardHeader, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { formatMoney, formatNumber, sumMoney } from "@/lib/utils/format";

export const metadata = { title: "Analytics" };

type Leader = { id: string; name: string | null; orders: number; gmv: string; revenue: string; rating: number | null };

type Summary = {
  timeseries: { grain: string; points: Point[] };
  unit_economics: {
    orders: number; gmv: string; revenue: string; take_rate_pct: string;
    avg_order_value: string; avg_revenue_per_order: string; avg_distance_km: string;
    vendor_net: string; rider_net: string; commission_lost: string; discounts_given: string;
    breakdown: Record<string, string>;
  };
  operations: {
    orders: number; delivered: number; cancelled: number; under_review: number;
    cancellation_rate_pct: string; dispute_rate_pct: string; avg_delivery_minutes: string;
  };
  growth: Record<string, { current: number; previous: number; change_pct: string | null }>;
  top_vendors: { items: Leader[] };
  top_riders: { items: Leader[] };
  status_funnel: { total: number; statuses: { status: string; count: number; pct: string }[] };
  fulfilment: {
    distance_buckets: { bucket: string; orders: number; delivery_fees: string }[];
    vehicles: { vehicle: string; orders: number; avg_minutes: string }[];
    delivery_types: { type: string; orders: number }[];
  };
  supply: {
    riders: {
      total: number; kyc_approved: number; deployable_now: number; marked_available: number;
      suspended: number; delivered_in_window: number; avg_acceptance_rate: string;
      orders_per_active_rider: string;
    };
    vendors: { total: number; online_now: number; suspended: number; verified: number; sold_in_window: number };
  };
  products: {
    products: { id: string; name: string | null; category: string | null; units: number; revenue: string }[];
    categories: { category: string; units: number; revenue: string }[];
  };
  customers: {
    customers_who_ordered: number; repeat_customers: number; repeat_rate_pct: string;
    avg_orders_per_customer: string; avg_spend_per_customer: string;
    top_decile_share_pct: string; welcome_offer_orders: number;
  };
  quality: {
    ratings: { target: string; counts: Record<string, number>; average: string }[];
    disputes: { status: string; count: number }[];
  };
  bottles: {
    entries: { type: string; quantity: number; movements: number }[];
    vendor_inventory: { empty: number; full: number };
    customer_bottle_debt: string;
  };
  /** False when the caller lacks `finance.read` — the two blocks below are then absent. */
  finance_visible: boolean;
  payment_mix?: { methods: { method: string; orders: number; value: string; unpaid: number }[] };
  float_exposure?: {
    vendors: { held: string; arrears: string; accounts_in_arrears: number };
    riders: { held: string; arrears: string; accounts_in_arrears: number };
    customers: { held: string; arrears: string; accounts_in_arrears: number };
    payouts_in_flight: { amount: string; count: number };
  };
};

type Demand = {
  pattern: { peak: number; cells: { dow: number; hour: number; orders: number }[] };
  geography: { cells: { h3: string; orders: number; gmv: string; avg_distance_km: string }[] };
};

const RANGES = [7, 30, 90, 365] as const;

const COMPONENT_LABELS: Record<string, string> = {
  vendor_commissions: "Vendor commission",
  service_fees: "Service fees",
  rider_commissions: "Rider commission",
  delivery_markups: "Delivery markup",
  surge_fees: "Surge fees",
};

/** Section heading — this page is long, and it has to stay skimmable. */
function SectionHeading({ id, title, blurb }: { id: string; title: string; blurb?: string }) {
  return (
    <div>
      <h2 id={id} className="text-lg font-semibold tracking-tight">
        {title}
      </h2>
      {blurb ? <p className="mt-0.5 text-sm text-muted">{blurb}</p> : null}
    </div>
  );
}

export default async function AnalyticsPage({
  searchParams,
}: {
  searchParams: Promise<{ days?: string }>;
}) {
  const params = await searchParams;
  const parsed = Number(params.days);
  const days = RANGES.includes(parsed as (typeof RANGES)[number]) ? parsed : 30;

  let data: Summary;
  let demand: Demand;
  let me: AdminMe;
  try {
    [data, demand, me] = await Promise.all([
      get<Summary>(`/api/admin/analytics/summary?days=${days}`),
      get<Demand>(`/api/admin/analytics/demand?days=${Math.max(days, 30)}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load analytics" detail={message} />;
  }

  // Cohorts are their own request because they want months, not days — the
  // range selector above does not apply to them and pretending otherwise would
  // produce a grid that silently changes meaning. A failure here costs one card.
  let cohorts: Cohort[] = [];
  const cohortResult = await Promise.allSettled([
    get<{ cohorts: Cohort[] }>("/api/admin/analytics/cohorts?months=8"),
  ]);
  if (cohortResult[0].status === "fulfilled") cohorts = cohortResult[0].value.cohorts;

  const { unit_economics: unit, operations: ops, growth } = data;
  const canExport = can(me, PERMISSIONS.dataExport);
  const points = data.timeseries.points;

  const windowDays = Number(growth.window_days ?? days) || days;
  const growthRows = Object.entries(growth)
    .filter(([key]) => key !== "window_days")
    .map(([key, value]) => ({
      label: key.charAt(0).toUpperCase() + key.slice(1),
      current: value.current,
      previous: value.previous,
    }));

  const ratingTotal = (counts: Record<string, number>) =>
    Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
          <p className="mt-1 text-sm text-muted">
            Revenue, unit economics and how the operation is performing.
          </p>
        </div>

        {/* Horizontally scrollable rather than wrapping: four pills that reflow
            to two lines shift the heading above them on every navigation. */}
        <nav aria-label="Date range" className="scroll-x -mx-1 max-w-full px-1">
          <ul className="flex gap-1">
            {RANGES.map((range) => (
              <li key={range}>
                <Link
                  href={`/analytics?days=${range}`}
                  aria-current={range === days ? "page" : undefined}
                  className={
                    range === days
                      ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                      : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                  }
                >
                  {range === 365 ? "1 year" : `${range} days`}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      {/* ── Money ─────────────────────────────────────────────────────── */}

      <section aria-labelledby="money" className="space-y-4">
        <SectionHeading
          id="money"
          title="Money"
          blurb="What the platform earned, and what it kept."
        />

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Revenue"
            value={formatMoney(unit.revenue)}
            hint={`Take rate ${unit.take_rate_pct}%`}
            trend={<Sparkline values={points.map((p) => Number(p.revenue))} label="Daily revenue" tone="success" />}
          />
          <Stat
            label="GMV"
            value={formatMoney(unit.gmv)}
            hint="What customers paid"
            trend={<Sparkline values={points.map((p) => Number(p.gmv))} label="Daily GMV" />}
          />
          <Stat
            label="Paid orders"
            value={formatNumber(unit.orders)}
            hint={`${unit.avg_distance_km} km average delivery`}
            trend={<Sparkline values={points.map((p) => p.orders)} label="Daily paid orders" />}
          />
          <Stat
            label="Average order"
            value={formatMoney(unit.avg_order_value)}
            hint={`${formatMoney(unit.avg_revenue_per_order)} of it to the platform`}
          />
        </div>

        <Card>
          <CardHeader
            title="Revenue, GMV and volume"
            description={`Daily, last ${days} days. Days with no orders are shown as zero, not skipped.`}
            action={
              canExport ? (
                <a
                  href={`/api/export?report=revenue&days=${days}`}
                  className="rounded-lg border border-default px-3 py-1.5 text-sm hover:bg-surface-muted"
                >
                  Export CSV
                </a>
              ) : null
            }
          />
          <div className="p-3 sm:p-5">
            <RevenueChart points={points} />
          </div>
        </Card>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader
              title="Where the revenue comes from"
              description="The platform's own cut, split by line item in the order ledger."
            />
            <DonutChart
              centreLabel="revenue"
              centreValue={formatMoney(unit.revenue)}
              slices={Object.entries(unit.breakdown).map(([key, value]) => ({
                label: COMPONENT_LABELS[key] ?? key.replace(/_/g, " "),
                value: Number(value),
                display: formatMoney(value),
              }))}
            />
          </Card>

          <StatList
            title="Where the money goes"
            description="GMV, less what is owed to everybody else."
            rows={[
              { label: "Paid out to vendors", value: formatMoney(unit.vendor_net) },
              { label: "Paid out to riders", value: formatMoney(unit.rider_net) },
              { label: "Discounts given", value: formatMoney(unit.discounts_given) },
              {
                label: "Commission lost",
                hint: "not collected — e.g. a cancelled cash order",
                value: formatMoney(unit.commission_lost),
                tone: Number(unit.commission_lost) > 0 ? "warning" : undefined,
              },
              { label: "Kept by the platform", value: formatMoney(unit.revenue) },
            ]}
          />
        </div>
      </section>

      {/* ── Health ────────────────────────────────────────────────────── */}

      <section aria-labelledby="health" className="space-y-4">
        <SectionHeading
          id="health"
          title="Health"
          blurb="Whether the platform is working, rather than what it earned."
        />

        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <GaugeRing
            label="Take rate"
            value={unit.take_rate_pct}
            hint="Share of GMV the platform keeps"
            max={40}
            warn={8}
            danger={4}
          />
          <GaugeRing
            label="Cancellation rate"
            value={ops.cancellation_rate_pct}
            hint={`${formatNumber(ops.cancelled)} of ${formatNumber(ops.orders)} orders`}
            invert
            max={50}
            warn={10}
            danger={20}
          />
          <GaugeRing
            label="Repeat rate"
            value={data.customers.repeat_rate_pct}
            hint="Customers who ordered more than once"
            warn={30}
            danger={15}
          />
          <GaugeRing
            label="Dispute rate"
            value={ops.dispute_rate_pct}
            hint={`Average delivery ${ops.avg_delivery_minutes} min`}
            invert
            max={20}
            warn={2}
            danger={5}
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader
              title="Order conversion"
              description="Each step is a subset of the one above it, so the losses are real."
            />
            <FunnelChart
              steps={[
                { label: "Orders placed", value: data.status_funnel.total },
                {
                  label: "Paid",
                  value: unit.orders,
                  note: "abandoned before payment, or the STK push failed",
                },
                {
                  label: "Delivered",
                  value: ops.delivered,
                  note: "cancelled, refunded, or still in flight",
                },
              ]}
            />
          </Card>

          <BarList
            title="Where orders end up"
            description="Every order in the window by its current status — these are siblings, not stages."
            items={data.status_funnel.statuses.map((s) => ({
              label: s.status.replace(/_/g, " "),
              value: s.count,
              display: formatNumber(s.count),
              hint: `${s.pct}%`,
            }))}
          />
        </div>

        <Card>
          <CardHeader
            title="New accounts"
            description={`Last ${windowDays} days against the ${windowDays} before them.`}
          />
          <div className="p-3 sm:p-5">
            <GrowthChart rows={growthRows} windowDays={windowDays} />
          </div>
        </Card>
      </section>

      {/* ── Demand ────────────────────────────────────────────────────── */}

      <section aria-labelledby="demand" className="space-y-4">
        <SectionHeading
          id="demand"
          title="Demand"
          blurb="When and where the orders are, which is what shifts and recruitment are planned against."
        />

        <DemandHeatmap cells={demand.pattern.cells} peak={demand.pattern.peak} />

        <div className="grid gap-6 lg:grid-cols-2">
          <BarList
            title="Busiest areas"
            description="H3 cells, busiest first — where to recruit vendors and station riders."
            items={demand.geography.cells.slice(0, 10).map((c) => ({
              label: c.h3.slice(0, 10),
              value: c.orders,
              display: formatNumber(c.orders),
              hint: formatMoney(c.gmv),
            }))}
          />
          <BarList
            title="Delivery distance"
            description="The mean hides the tail, and the tail is where the fee model wins or loses."
            items={data.fulfilment.distance_buckets.map((b) => ({
              label: b.bucket,
              value: b.orders,
              display: formatNumber(b.orders),
              hint: formatMoney(b.delivery_fees),
            }))}
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader
              title="How orders are fulfilled"
              description="Scheduled against on-demand."
            />
            <StackedShareBar
              items={data.fulfilment.delivery_types.map((t) => ({
                label: t.type,
                value: t.orders,
                display: formatNumber(t.orders),
              }))}
            />
          </Card>

          <Card>
            <CardHeader
              title="Vehicle mix"
              description="With the average minutes each takes to deliver."
            />
            <StackedShareBar
              items={data.fulfilment.vehicles.map((v) => ({
                label: v.vehicle,
                value: v.orders,
                display: `${formatNumber(v.orders)} · ${v.avg_minutes} min`,
              }))}
              caption="A vehicle class that is slower per delivery is a dispatch weighting, not a rider problem."
            />
          </Card>
        </div>
      </section>

      {/* ── Customers ─────────────────────────────────────────────────── */}

      <section aria-labelledby="customers" className="space-y-4">
        <SectionHeading
          id="customers"
          title="Customers"
          blurb="Bottled water is a repeat purchase or it is nothing, so retention is the number that matters."
        />

        <CohortGrid cohorts={cohorts} />

        {/* This grid answers whether customers come back. The next question —
            whether the ones who came back paid back what it cost to get them —
            is a page of its own, and somebody reading retention is exactly who
            wants it. A nav entry alone leaves it to be stumbled upon. */}
        <p className="text-sm text-muted">
          Retention says who came back.{" "}
          <Link href="/analytics/growth" className="font-medium text-[var(--accent)] hover:underline">
            Acquisition
          </Link>{" "}
          says what they cost and when each cohort paid that back.
        </p>

        <div className="grid gap-6 lg:grid-cols-2">
          <StatList
            title="Buying behaviour"
            rows={[
              { label: "Repeat rate", value: `${data.customers.repeat_rate_pct}%` },
              { label: "Ordered at all", value: formatNumber(data.customers.customers_who_ordered) },
              { label: "Ordered more than once", value: formatNumber(data.customers.repeat_customers) },
              { label: "Average orders each", value: data.customers.avg_orders_per_customer },
              { label: "Average spend each", value: formatMoney(data.customers.avg_spend_per_customer) },
              {
                label: "Top 10% share of spend",
                value: `${data.customers.top_decile_share_pct}%`,
                hint: "concentration risk",
                tone: Number(data.customers.top_decile_share_pct) > 60 ? "warning" : undefined,
              },
              { label: "Welcome-offer orders", value: formatNumber(data.customers.welcome_offer_orders) },
            ]}
          />

          <Card>
            <CardHeader
              title="Ratings"
              description="These move before revenue does."
            />
            {data.quality.ratings.length === 0 ? (
              <EmptyState title="No reviews yet" description="Ratings appear once customers start leaving them." />
            ) : (
              <div className="divide-y divide-[var(--border)]">
                {data.quality.ratings.map((rating) => (
                  <div key={rating.target} className="px-5 py-4">
                    <div className="flex items-baseline justify-between gap-3">
                      <p className="text-sm font-medium capitalize">{rating.target}</p>
                      <p className="text-sm tabular-nums">
                        {rating.average}
                        <span className="ml-1.5 text-xs text-muted">
                          {formatNumber(ratingTotal(rating.counts))} reviews
                        </span>
                      </p>
                    </div>
                    <ul className="mt-2 space-y-1">
                      {[5, 4, 3, 2, 1].map((star) => {
                        const count = rating.counts[String(star)] ?? 0;
                        const total = ratingTotal(rating.counts) || 1;
                        return (
                          <li key={star} className="flex items-center gap-2 text-xs">
                            <span className="w-6 shrink-0 tabular-nums text-muted">{star}★</span>
                            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface-muted">
                              <span
                                className="block h-full rounded-full bg-[var(--accent)]"
                                style={{ width: `${(count / total) * 100}%` }}
                              />
                            </span>
                            <span className="w-8 shrink-0 text-right tabular-nums text-muted">{count}</span>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </Card>
        </div>
      </section>

      {/* ── Catalogue ─────────────────────────────────────────────────── */}

      <section aria-labelledby="catalogue" className="space-y-4">
        <SectionHeading id="catalogue" title="Catalogue" blurb="What is actually selling." />

        <div className="grid gap-6 lg:grid-cols-2">
          <BarList
            title="Top products"
            description="By revenue in this window."
            items={data.products.products.slice(0, 10).map((product) => ({
              label: product.name ?? "—",
              value: Number(product.revenue),
              display: formatMoney(product.revenue),
              hint: `${formatNumber(product.units)} units`,
            }))}
          />
          <BarList
            title="Sales by category"
            description="Where the catalogue's revenue is concentrated."
            items={data.products.categories.map((c) => ({
              label: c.category,
              value: Number(c.revenue),
              display: formatMoney(c.revenue),
              hint: `${formatNumber(c.units)} units`,
            }))}
          />
        </div>
      </section>

      {/* ── Supply ────────────────────────────────────────────────────── */}

      <section aria-labelledby="supply" className="space-y-4">
        <SectionHeading
          id="supply"
          title="Supply"
          blurb="Riders who can actually take a job, and stores that are open."
        />

        <div className="grid gap-6 lg:grid-cols-3">
          <StatList
            title="Riders"
            description="Deployable means available, verified and not suspended."
            rows={[
              {
                label: "Deployable now",
                value: formatNumber(data.supply.riders.deployable_now),
                tone: data.supply.riders.deployable_now === 0 ? "danger" : undefined,
              },
              {
                label: "Marked available",
                value: formatNumber(data.supply.riders.marked_available),
                hint: "flag only",
              },
              { label: "KYC approved", value: formatNumber(data.supply.riders.kyc_approved) },
              { label: "Registered", value: formatNumber(data.supply.riders.total) },
              { label: "Delivered in window", value: formatNumber(data.supply.riders.delivered_in_window) },
              { label: "Acceptance rate", value: `${data.supply.riders.avg_acceptance_rate}%` },
              { label: "Orders per active rider", value: data.supply.riders.orders_per_active_rider },
              {
                label: "Suspended",
                value: formatNumber(data.supply.riders.suspended),
                tone: data.supply.riders.suspended > 0 ? "warning" : undefined,
              },
            ]}
          />

          <StatList
            title="Vendors"
            rows={[
              { label: "Open now", value: formatNumber(data.supply.vendors.online_now) },
              { label: "Sold in window", value: formatNumber(data.supply.vendors.sold_in_window) },
              { label: "Verified", value: formatNumber(data.supply.vendors.verified) },
              { label: "Registered", value: formatNumber(data.supply.vendors.total) },
              {
                label: "Suspended",
                value: formatNumber(data.supply.vendors.suspended),
                tone: data.supply.vendors.suspended > 0 ? "warning" : undefined,
              },
            ]}
          />

          <StatList
            title="Bottles"
            description="The platform's physical working capital."
            rows={[
              ...data.bottles.entries.map((entry) => ({
                label: entry.type.replace(/_/g, " "),
                value: formatNumber(entry.quantity),
                hint: `${entry.movements} movements`,
              })),
              { label: "Vendor empties held", value: formatNumber(data.bottles.vendor_inventory.empty) },
              { label: "Vendor full stock", value: formatNumber(data.bottles.vendor_inventory.full) },
              {
                label: "Customer bottle debt",
                value: formatMoney(data.bottles.customer_bottle_debt),
                tone: Number(data.bottles.customer_bottle_debt) > 0 ? "warning" : undefined,
              },
            ]}
          />
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Leaderboard title="Top vendors" items={data.top_vendors.items} hrefBase="/people/vendors" />
          <Leaderboard title="Top riders" items={data.top_riders.items} hrefBase="/people/riders" />
        </div>

        <BarList
          title="Disputes by outcome"
          description="A rider and a vendor disagreeing about the empties."
          items={data.quality.disputes.map((dispute) => ({
            label: dispute.status.replace(/_/g, " "),
            value: dispute.count,
            display: formatNumber(dispute.count),
          }))}
        />
      </section>

      {/* ── Finance ───────────────────────────────────────────────────── */}

      {/* Financial detail is a separate grant. An analyst sees everything above
          and none of this — and gets a working page, rather than a 403 on the
          whole screen that ends with someone being handed `finance.read` just
          to look at charts. */}
      <section aria-labelledby="finance" className="space-y-4">
        <SectionHeading
          id="finance"
          title="Finance"
          blurb="How customers pay, and what the platform is currently holding."
        />

        {data.finance_visible && data.payment_mix && data.float_exposure ? (
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader
                title="Payment methods"
                description="Cash share is the share of revenue the platform fronts."
              />
              <DonutChart
                centreLabel="collected"
                // Summed as decimal strings, not floats. `reduce(+Number(v))`
                // here would put binary floating point back into a total shown
                // to a human, which is the whole reason money crosses the wire
                // as a string.
                centreValue={formatMoney(sumMoney(data.payment_mix.methods.map((m) => m.value)))}
                slices={data.payment_mix.methods.map((method) => ({
                  label: method.method,
                  value: Number(method.value),
                  display: formatMoney(method.value),
                }))}
              />
              <ul className="border-t border-default px-5 py-3 text-xs text-muted">
                {data.payment_mix.methods.map((method) => (
                  <li key={method.method} className="flex justify-between gap-3 py-0.5">
                    <span className="capitalize">{method.method}</span>
                    <span className="tabular-nums">
                      {formatNumber(method.orders)} orders
                      {method.unpaid > 0 ? `, ${formatNumber(method.unpaid)} unpaid` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>

            <StatList
              title="Money on the platform"
              description="Point in time, not a window."
              rows={[
                { label: "Vendor balances held", value: formatMoney(data.float_exposure.vendors.held) },
                { label: "Rider balances held", value: formatMoney(data.float_exposure.riders.held) },
                { label: "Customer balances held", value: formatMoney(data.float_exposure.customers.held) },
                {
                  label: "Vendors in arrears",
                  value: formatMoney(data.float_exposure.vendors.arrears),
                  hint: `${data.float_exposure.vendors.accounts_in_arrears} accounts`,
                  tone: Number(data.float_exposure.vendors.arrears) > 0 ? "danger" : undefined,
                },
                {
                  label: "Riders in arrears",
                  value: formatMoney(data.float_exposure.riders.arrears),
                  hint: `${data.float_exposure.riders.accounts_in_arrears} accounts`,
                  tone: Number(data.float_exposure.riders.arrears) > 0 ? "danger" : undefined,
                },
                {
                  label: "Payouts in flight",
                  value: formatMoney(data.float_exposure.payouts_in_flight.amount),
                  hint: `${data.float_exposure.payouts_in_flight.count} pending`,
                },
              ]}
            />
          </div>
        ) : (
          <Card>
            <EmptyState
              title="This section needs another permission"
              description="Payment mix and balance exposure require “View revenue, payouts and wallets”. Everything else on this page is available to you."
            />
          </Card>
        )}
      </section>
    </div>
  );
}

function Leaderboard({ title, items, hrefBase }: { title: string; items: Leader[]; hrefBase: string }) {
  return (
    <Card>
      <CardHeader title={title} description="By gross merchandise value." />
      {items.length === 0 ? (
        <EmptyState title="Nothing to rank yet" description="Once paid orders come in, the leaders appear here." />
      ) : (
        <ol className="divide-y divide-[var(--border)]">
          {items.map((item, index) => (
            <li key={item.id}>
              <Link
                href={`${hrefBase}/${item.id}`}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3 hover:bg-surface-muted"
              >
                <span className="w-5 shrink-0 text-sm tabular-nums text-muted">{index + 1}</span>
                <span className="min-w-0 flex-1 truncate text-sm font-medium">{item.name ?? "—"}</span>
                <span className="shrink-0 text-xs text-muted">{formatNumber(item.orders)} orders</span>
                <span className="shrink-0 text-sm font-medium tabular-nums">{formatMoney(item.gmv)}</span>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
