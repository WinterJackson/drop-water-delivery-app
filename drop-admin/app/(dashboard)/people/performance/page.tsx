import { Gauge, PackageCheck, Store, TrendingUp, Users } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatMoney, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";

export const metadata = { title: "Performance" };

/**
 * Who is actually working, and how well.
 *
 * Deactivating somebody's income is the most consequential thing this console
 * does to an individual, and it was being done from a roster showing a name and
 * a phone number. This is what that decision should rest on.
 *
 * Every rate carries its denominator and nothing is ranked below the backend's
 * minimum sample. A league table that puts a one-order rider at the top is worse
 * than no league table — it is confidently wrong, and somebody acts on it.
 */

type RiderRow = {
  id: string;
  name: string | null;
  kyc_status: string | null;
  suspended: boolean;
  orders: number;
  delivered: number;
  cancelled: number;
  completion_rate: number | null;
  gmv: string;
  ranked: boolean;
};

type VendorRow = {
  id: string;
  name: string | null;
  verification_status: string | null;
  active: boolean;
  orders: number;
  delivered: number;
  cancelled: number;
  fulfilment_rate: number | null;
  gmv: string;
  ranked: boolean;
};

type Riders = {
  items: RiderRow[];
  min_orders_for_ranking: number;
  ranked_count: number;
  total: number;
  approved: number;
  with_any_order: number;
};

type Vendors = {
  items: VendorRow[];
  min_orders_for_ranking: number;
  ranked_count: number;
  total: number;
  selling: number;
  never_sold: number;
};

export default async function PerformancePage({
  searchParams,
}: {
  searchParams: Promise<{ kind?: string }>;
}) {
  const { kind = "riders" } = await searchParams;
  const active = kind === "vendors" ? "vendors" : "riders";

  let me: AdminMe;
  try {
    me = await get<AdminMe>("/api/admin/me");
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load performance" detail={message} />;
  }

  const mayRiders = can(me, PERMISSIONS.ridersRead);
  const mayVendors = can(me, PERMISSIONS.vendorsRead);

  // The tab the caller asked for may not be one they hold. Fall back rather
  // than render a refusal — the other half of the page is still theirs.
  const view = active === "vendors" && !mayVendors ? "riders" : active;
  if (view === "riders" && !mayRiders) {
    return (
      <ErrorState
        title="Not available"
        detail="Reading rider or store performance needs riders.read or vendors.read."
      />
    );
  }

  let riders: Riders | null = null;
  let vendors: Vendors | null = null;
  try {
    if (view === "riders") {
      riders = await get<Riders>("/api/admin/performance/riders");
    } else {
      vendors = await get<Vendors>("/api/admin/performance/vendors");
    }
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load performance" detail={message} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Performance</h1>
        <p className="mt-1 text-sm text-muted">
          Throughput and reliability, with the sample size beside every rate.
          Nothing is ranked on fewer than{" "}
          {riders?.min_orders_for_ranking ?? vendors?.min_orders_for_ranking ?? 5}{" "}
          finished orders, because one delivery and one cancellation is a 100%
          failure rate and means nothing.
        </p>
      </div>

      <nav aria-label="Choose population" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {[
            { key: "riders", label: "Riders", allowed: mayRiders },
            { key: "vendors", label: "Stores", allowed: mayVendors },
          ]
            .filter((tab) => tab.allowed)
            .map((tab) => (
              <li key={tab.key}>
                <Link
                  href={`/people/performance?kind=${tab.key}`}
                  aria-current={tab.key === view ? "page" : undefined}
                  className={
                    tab.key === view
                      ? "inline-flex rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                      : "inline-flex rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                  }
                >
                  {tab.label}
                </Link>
              </li>
            ))}
        </ul>
      </nav>

      {riders ? <RiderView data={riders} /> : null}
      {vendors ? <VendorView data={vendors} /> : null}
    </div>
  );
}

function RiderView({ data }: { data: Riders }) {
  const working = data.items.filter((rider) => rider.orders > 0);

  return (
    <>
      <section aria-label="Rider summary">
        <h2 className="sr-only">Rider summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label="Riders" value={formatNumber(data.total)} icon={<Users className="h-4 w-4" />} />
          <Stat
            label="Approved to work"
            value={formatNumber(data.approved)}
            hint="Passed KYC — the rest cannot accept a delivery"
            tone={data.approved === 0 ? "danger" : "neutral"}
            icon={<PackageCheck className="h-4 w-4" />}
          />
          <Stat
            label="Have taken an order"
            value={formatNumber(data.with_any_order)}
            hint="Ever assigned anything at all"
            icon={<TrendingUp className="h-4 w-4" />}
          />
          <Stat
            label="Enough data to rank"
            value={formatNumber(data.ranked_count)}
            hint={`${data.min_orders_for_ranking}+ finished orders`}
            icon={<Gauge className="h-4 w-4" />}
          />
        </div>
      </section>

      {working.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Users className="h-8 w-8" />}
            title="No rider has been assigned an order yet"
            description="Performance appears here once deliveries start being dispatched."
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="scroll-x">
            <table className="w-full min-w-[44rem] text-sm">
              <caption className="sr-only">Rider performance</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Rider</th>
                  <th scope="col" className="px-4 py-3 font-medium">Assigned</th>
                  <th scope="col" className="px-4 py-3 font-medium">Delivered</th>
                  <th scope="col" className="px-4 py-3 font-medium">Cancelled</th>
                  <th scope="col" className="px-4 py-3 font-medium">Completion</th>
                  <th scope="col" className="px-4 py-3 font-medium">Value delivered</th>
                </tr>
              </thead>
              <tbody>
                {working.map((rider) => (
                  <tr key={rider.id} className="border-b border-default last:border-0">
                    <td className="px-4 py-3">
                      <Link href={`/people/riders/${rider.id}`} className="font-medium hover:underline">
                        {rider.name ?? "Unnamed"}
                      </Link>
                      <span className="block text-xs text-muted">
                        KYC {rider.kyc_status ?? "—"}
                        {rider.suspended ? " · suspended" : ""}
                      </span>
                    </td>
                    <td className="px-4 py-3">{formatNumber(rider.orders)}</td>
                    <td className="px-4 py-3">{formatNumber(rider.delivered)}</td>
                    <td className="px-4 py-3">{formatNumber(rider.cancelled)}</td>
                    <td className="px-4 py-3">
                      <RateCell rate={rider.completion_rate} minimum={data.min_orders_for_ranking} />
                    </td>
                    <td className="px-4 py-3">{formatMoney(rider.gmv)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <p className="text-xs text-muted">
        A cancellation counts against whoever the order was assigned to at the
        time, which is imperfect on purpose — an order the customer cancelled
        before the rider moved is not the rider&apos;s fault. Treat this as the
        start of a conversation, not a verdict.
      </p>
    </>
  );
}

function VendorView({ data }: { data: Vendors }) {
  const selling = data.items.filter((vendor) => vendor.orders > 0);

  return (
    <>
      <section aria-label="Store summary">
        <h2 className="sr-only">Store summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat label="Stores" value={formatNumber(data.total)} icon={<Store className="h-4 w-4" />} />
          <Stat
            label="Have sold something"
            value={formatNumber(data.selling)}
            hint="Taken at least one order"
            icon={<TrendingUp className="h-4 w-4" />}
          />
          <Stat
            label="Never sold anything"
            value={formatNumber(data.never_sold)}
            hint="Supply acquired and not activated — the most actionable vendor number on a young platform"
            tone={data.never_sold > data.total / 2 ? "warning" : "neutral"}
            icon={<Store className="h-4 w-4" />}
          />
          <Stat
            label="Enough data to rank"
            value={formatNumber(data.ranked_count)}
            hint={`${data.min_orders_for_ranking}+ finished orders`}
            icon={<Gauge className="h-4 w-4" />}
          />
        </div>
      </section>

      {selling.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Store className="h-8 w-8" />}
            title="No store has taken an order yet"
            description="Volume and fulfilment appear here once orders start being placed."
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <div className="scroll-x">
            <table className="w-full min-w-[44rem] text-sm">
              <caption className="sr-only">Store performance</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Store</th>
                  <th scope="col" className="px-4 py-3 font-medium">Orders</th>
                  <th scope="col" className="px-4 py-3 font-medium">Delivered</th>
                  <th scope="col" className="px-4 py-3 font-medium">Cancelled</th>
                  <th scope="col" className="px-4 py-3 font-medium">Fulfilment</th>
                  <th scope="col" className="px-4 py-3 font-medium">Value delivered</th>
                </tr>
              </thead>
              <tbody>
                {selling.map((vendor) => (
                  <tr key={vendor.id} className="border-b border-default last:border-0">
                    <td className="px-4 py-3">
                      <Link href={`/people/vendors/${vendor.id}`} className="font-medium hover:underline">
                        {vendor.name ?? "Unnamed"}
                      </Link>
                      <span className="block text-xs text-muted">
                        {vendor.verification_status ?? "unverified"}
                        {vendor.active ? "" : " · closed"}
                      </span>
                    </td>
                    <td className="px-4 py-3">{formatNumber(vendor.orders)}</td>
                    <td className="px-4 py-3">{formatNumber(vendor.delivered)}</td>
                    <td className="px-4 py-3">{formatNumber(vendor.cancelled)}</td>
                    <td className="px-4 py-3">
                      <RateCell rate={vendor.fulfilment_rate} minimum={data.min_orders_for_ranking} />
                    </td>
                    <td className="px-4 py-3">{formatMoney(vendor.gmv)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

/** A rate, or an honest refusal to quote one. */
function RateCell({ rate, minimum }: { rate: number | null; minimum: number }) {
  if (rate === null) {
    return (
      <span className="text-xs text-muted">
        under {minimum} orders
      </span>
    );
  }
  return (
    <Badge tone={rate >= 90 ? "success" : rate >= 70 ? "warning" : "danger"}>{rate}%</Badge>
  );
}
