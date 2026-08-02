import { AlertTriangle, MapPin } from "lucide-react";
import Link from "next/link";

import { BarList } from "@/components/charts/Panels";
import { Card, CardHeader, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { formatMoney, formatNumber } from "@/lib/utils/format";
import { OperationsMap } from "./OperationsMap";

export const metadata = { title: "Map" };

type Bootstrap = {
  centre: { lat: number; lng: number; zoom: number; derived: boolean };
  coverage: {
    vendors: { total: number; located: number; missing_location: number };
    riders: {
      total: number;
      located: number;
      missing_location: number;
      deployable_located: number;
    };
    customers: { located: number };
    uncovered_vendors: {
      count: number;
      radius_km: number;
      items: { id: string; name: string | null }[];
    };
  };
};

type Demand = {
  cells: {
    h3: string;
    orders: number;
    gmv: string;
    avg_distance_km: number;
    avg_minutes: number;
  }[];
  window_days: number;
  suppressed_note: string;
};

export default async function MapPage() {
  let data: Bootstrap;
  let me: AdminMe;
  let demand: Demand | null = null;

  try {
    [data, me] = await Promise.all([
      get<Bootstrap>("/api/admin/map/bootstrap"),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the map" detail={message} />;
  }

  const [demandResult] = await Promise.allSettled([
    get<Demand>("/api/admin/map/demand?days=90"),
  ]);
  if (demandResult.status === "fulfilled") demand = demandResult.value;

  const { coverage } = data;
  const uncovered = coverage.uncovered_vendors;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Map</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Where the riders, the stores and the live orders are. Customer demand
          is shown as areas rather than pins — a single delivery inside one cell
          would identify a household.
        </p>
      </div>

      {uncovered.count > 0 ? (
        <div
          role="alert"
          className="flex gap-3 rounded-xl border border-[var(--danger)] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)] px-5 py-4"
        >
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[var(--danger)]" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium text-[var(--danger)]">
              {formatNumber(uncovered.count)} store
              {uncovered.count === 1 ? " has" : "s have"} no rider who could serve
              {uncovered.count === 1 ? " it" : " them"}
            </p>
            <p className="mt-1 text-sm text-muted">
              No verified, available, unsuspended rider is within{" "}
              {uncovered.radius_km}km. These stores can take orders that nobody
              can pick up.
            </p>
            {uncovered.items.length > 0 ? (
              <p className="mt-2 text-sm">
                {uncovered.items.slice(0, 5).map((vendor, index) => (
                  <span key={vendor.id}>
                    {index > 0 ? ", " : ""}
                    <Link
                      href={`/people/vendors/${vendor.id}`}
                      className="underline underline-offset-4"
                    >
                      {vendor.name ?? "unnamed"}
                    </Link>
                  </span>
                ))}
                {uncovered.count > 5 ? ` and ${uncovered.count - 5} more` : ""}
              </p>
            ) : null}
          </div>
        </div>
      ) : null}

      <OperationsMap
        centre={{ lat: data.centre.lat, lng: data.centre.lng, zoom: data.centre.zoom }}
        canSeeOrders={can(me, PERMISSIONS.ordersRead)}
      />

      <section aria-labelledby="coverage" className="space-y-3">
        <h2 id="coverage" className="text-sm font-medium text-muted">
          Coverage
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Riders who can work"
            value={formatNumber(coverage.riders.deployable_located)}
            hint={`of ${formatNumber(coverage.riders.total)} registered`}
            tone={coverage.riders.deployable_located === 0 ? "danger" : "neutral"}
            icon={<MapPin className="h-4 w-4" />}
          />
          <Stat
            label="Stores on the map"
            value={formatNumber(coverage.vendors.located)}
            hint={
              coverage.vendors.missing_location > 0
                ? `${formatNumber(coverage.vendors.missing_location)} have no location set`
                : "all located"
            }
            tone={coverage.vendors.missing_location > 0 ? "warning" : "neutral"}
          />
          <Stat
            label="Riders with no location"
            value={formatNumber(coverage.riders.missing_location)}
            hint="Invisible to dispatch until they open the app"
            tone={coverage.riders.missing_location > 0 ? "warning" : "neutral"}
          />
          <Stat
            label="Customers with a saved address"
            value={formatNumber(coverage.customers.located)}
          />
        </div>
      </section>

      {demand ? (
        demand.cells.length > 0 ? (
          <BarList
            title={`Where the orders come from (${demand.window_days} days)`}
            description={demand.suppressed_note}
            items={demand.cells.slice(0, 12).map((cell) => ({
              label: cell.h3.slice(0, 10),
              value: cell.orders,
              display: formatNumber(cell.orders),
              hint: `${formatMoney(cell.gmv)} · ${cell.avg_minutes} min avg`,
            }))}
          />
        ) : (
          <Card>
            <CardHeader title="Where the orders come from" />
            <EmptyState
              title="Not enough orders to map demand yet"
              description="Areas appear here once a cell has more than one delivery — a single order in a 460m cell would point at somebody's home."
            />
          </Card>
        )
      ) : null}
    </div>
  );
}
