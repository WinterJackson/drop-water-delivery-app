import { Bike, Link2, Store, TriangleAlert, UserPlus } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatNumber } from "@/lib/utils/format";

export const metadata = { title: "Fleet" };

/**
 * Who is registered to deliver for whom.
 *
 * `VendorRiderRegistry` decides dispatch priority — an approved in-house rider
 * is offered an order before the radar goes out to any nearby gig rider — and no
 * screen showed it. A store saying "no riders are being assigned to me" could
 * not be checked, and the answer is usually one number.
 */

type Summary = {
  approved_links: number;
  pending_requests: number;
  stale_requests: number;
  stale_request_days: number;
  vendors_total: number;
  vendors_with_rider: number;
  vendors_without_rider: number;
  riders_total: number;
  riders_registered: number;
  riders_unattached: number;
  riders_in_house: number;
  legacy_table_rows: number;
};

type VendorGap = { id: string; name: string | null; active: boolean; days_trading: number | null };

type Pending = {
  rider_id: string;
  rider_name: string | null;
  rider_kyc: string | null;
  vendor_id: string;
  vendor_name: string | null;
  distance_km: number | null;
  days_waiting: number | null;
  stale: boolean;
};

type LinkRow = {
  rider_id: string;
  rider_name: string | null;
  rider_kyc: string | null;
  rider_suspended: boolean;
  employment: string | null;
  vendor_id: string;
  vendor_name: string | null;
  status: string;
  priority: number | null;
  distance_km: number | null;
  pending_10L: number;
  pending_20L: number;
  approved_at: string | null;
};

type Unattached = {
  id: string;
  name: string | null;
  employment: string | null;
  kyc: string | null;
  misconfigured: boolean;
  can_work: boolean;
};

type Payload = {
  summary: Summary;
  vendors_without_riders: VendorGap[];
  pending: Pending[];
  links: LinkRow[];
  unattached: Unattached[];
};

export default async function FleetPage() {
  let data: Payload;
  try {
    data = await get<Payload>("/api/admin/fleet");
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the fleet" detail={message} />;
  }

  const { summary, vendors_without_riders: gaps, pending, links, unattached } = data;
  const misconfigured = unattached.filter((rider) => rider.misconfigured);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Fleet</h1>
        <p className="mt-1 text-sm text-muted">
          Which riders are registered with which stores. This is what decides
          dispatch priority: a store&apos;s own approved rider is offered an
          order before the radar goes out to anyone nearby.
        </p>
      </div>

      <section aria-label="Fleet summary">
        <h2 className="sr-only">Fleet summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Stores with no rider"
            value={formatNumber(summary.vendors_without_rider)}
            hint={`of ${formatNumber(summary.vendors_total)} — every order they take goes to the gig radar`}
            tone={summary.vendors_without_rider > 0 ? "warning" : "neutral"}
            icon={<Store className="h-4 w-4" />}
          />
          <Stat
            label="Approved registrations"
            value={formatNumber(summary.approved_links)}
            hint={`${formatNumber(summary.riders_registered)} riders across ${formatNumber(summary.vendors_with_rider)} stores`}
            icon={<Link2 className="h-4 w-4" />}
          />
          <Stat
            label="Requests waiting"
            value={formatNumber(summary.pending_requests)}
            hint={
              summary.stale_requests > 0
                ? `${formatNumber(summary.stale_requests)} over ${summary.stale_request_days} days — nobody is looking`
                : "Nothing has been left unanswered"
            }
            tone={summary.stale_requests > 0 ? "warning" : "neutral"}
            icon={<UserPlus className="h-4 w-4" />}
          />
          <Stat
            label="Riders with no store"
            value={formatNumber(summary.riders_unattached)}
            hint={
              misconfigured.length > 0
                ? `${formatNumber(misconfigured.length)} of them are in-house, which is a contradiction`
                : "Normal for gig riders — the radar is how they work"
            }
            tone={misconfigured.length > 0 ? "danger" : "neutral"}
            icon={<Bike className="h-4 w-4" />}
          />
        </div>
      </section>

      {misconfigured.length > 0 ? (
        <Card className="border-[color-mix(in_oklch,var(--danger)_40%,transparent)] p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <TriangleAlert className="h-4 w-4 text-[var(--danger)]" aria-hidden />
            {formatNumber(misconfigured.length)} in-house rider
            {misconfigured.length === 1 ? "" : "s"} belong to no store
          </h2>
          <p className="mt-1 text-sm text-muted">
            An in-house rider is meant to be somebody&apos;s own fleet. With no
            approved registration they are never given priority for anyone, so
            they compete on the open radar with the employment terms of a staff
            member — the worst of both arrangements.
          </p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {misconfigured.map((rider) => (
              <li key={rider.id}>
                <Link
                  href={`/people/riders/${rider.id}`}
                  className="rounded-lg border border-default px-2.5 py-1 text-sm hover:bg-surface-muted"
                >
                  {rider.name ?? "Unnamed"}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {pending.length > 0 ? (
        <Card className="overflow-hidden">
          <div className="border-b border-default px-4 py-3">
            <h2 className="text-sm font-semibold">Riders waiting on a store</h2>
            <p className="mt-0.5 text-xs text-muted">
              The store has to approve these. A store that never opens the app
              leaves the request sitting there, and neither side can tell.
            </p>
          </div>
          <div className="scroll-x">
            <table className="w-full min-w-[42rem] text-sm">
              <caption className="sr-only">Pending registration requests</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Rider</th>
                  <th scope="col" className="px-4 py-3 font-medium">Store</th>
                  <th scope="col" className="px-4 py-3 font-medium">Distance</th>
                  <th scope="col" className="px-4 py-3 font-medium">Waiting</th>
                </tr>
              </thead>
              <tbody>
                {pending.map((row) => (
                  <tr
                    key={`${row.rider_id}-${row.vendor_id}`}
                    className="border-b border-default last:border-0"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/people/riders/${row.rider_id}`}
                        className="font-medium hover:underline"
                      >
                        {row.rider_name ?? "Unnamed"}
                      </Link>
                      {row.rider_kyc !== "approved" ? (
                        <span className="block text-xs text-muted">
                          KYC {row.rider_kyc ?? "—"} — cannot deliver yet either way
                        </span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">{row.vendor_name ?? "—"}</td>
                    <td className="px-4 py-3">
                      {row.distance_km === null ? "—" : `${row.distance_km} km`}
                    </td>
                    <td className="px-4 py-3">
                      <Badge tone={row.stale ? "warning" : "neutral"}>
                        {row.days_waiting === null ? "—" : `${row.days_waiting}d`}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {gaps.length > 0 ? (
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Stores relying entirely on the radar</h2>
          <p className="mt-1 text-sm text-muted">
            No approved rider of their own, so every order goes out to whoever is
            nearby. That works in a dense area and fails silently outside one.
          </p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {gaps.slice(0, 24).map((vendor) => (
              <li key={vendor.id}>
                <Link
                  href={`/people/vendors/${vendor.id}`}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-default px-2.5 py-1 text-sm hover:bg-surface-muted"
                >
                  {vendor.name ?? "Unnamed"}
                  {vendor.active ? null : (
                    <span className="text-xs text-muted">closed</span>
                  )}
                </Link>
              </li>
            ))}
          </ul>
          {gaps.length > 24 ? (
            <p className="mt-2 text-xs text-muted">
              and {formatNumber(gaps.length - 24)} more.
            </p>
          ) : null}
        </Card>
      ) : null}

      <Card className="overflow-hidden">
        <div className="border-b border-default px-4 py-3">
          <h2 className="text-sm font-semibold">Every registration</h2>
        </div>
        {links.length === 0 ? (
          <EmptyState
            icon={<Link2 className="h-8 w-8" />}
            title="No rider is registered with any store"
            description="Every order on the platform is going out to the open radar. Riders request a registration from their app and the store approves it."
          />
        ) : (
          <div className="scroll-x">
            <table className="w-full min-w-[48rem] text-sm">
              <caption className="sr-only">Rider and store registrations</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Rider</th>
                  <th scope="col" className="px-4 py-3 font-medium">Store</th>
                  <th scope="col" className="px-4 py-3 font-medium">State</th>
                  <th scope="col" className="px-4 py-3 font-medium">Priority</th>
                  <th scope="col" className="px-4 py-3 font-medium">Bottles held</th>
                </tr>
              </thead>
              <tbody>
                {links.map((row) => (
                  <tr
                    key={`${row.rider_id}-${row.vendor_id}`}
                    className="border-b border-default last:border-0"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/people/riders/${row.rider_id}`}
                        className="font-medium hover:underline"
                      >
                        {row.rider_name ?? "Unnamed"}
                      </Link>
                      <span className="block text-xs text-muted">
                        {row.employment === "in_house" ? "in-house" : "gig"}
                        {row.rider_suspended ? " · suspended" : ""}
                        {row.rider_kyc === "approved" ? "" : ` · KYC ${row.rider_kyc ?? "—"}`}
                      </span>
                    </td>
                    <td className="px-4 py-3">{row.vendor_name ?? "—"}</td>
                    <td className="px-4 py-3">
                      <Badge
                        tone={
                          row.status === "approved"
                            ? "success"
                            : row.status === "pending"
                              ? "warning"
                              : "danger"
                        }
                      >
                        {row.status}
                      </Badge>
                    </td>
                    <td className="px-4 py-3">{row.priority ?? "—"}</td>
                    <td className="px-4 py-3">
                      {row.pending_10L + row.pending_20L === 0 ? (
                        <span className="text-muted">none</span>
                      ) : (
                        <Link href="/operations/bottles" className="hover:underline">
                          {row.pending_10L > 0 ? `${row.pending_10L} × 10L ` : ""}
                          {row.pending_20L > 0 ? `${row.pending_20L} × 20L` : ""}
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {summary.legacy_table_rows > 0 ? (
        <p className="text-xs text-muted">
          There is a second table for this relationship, `Deliverer_Vendors`,
          holding {formatNumber(summary.legacy_table_rows)} rows that nothing on
          the platform reads or writes. Nothing here uses it — this screen is
          drawn entirely from `VendorRiderRegistry`, which is what dispatch and
          both apps use.
        </p>
      ) : null}
    </div>
  );
}
