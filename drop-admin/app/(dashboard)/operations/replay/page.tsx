import { CircleHelp, Footprints, MapPin, Route, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatNumber, timeAgo } from "@/lib/utils/format";
import { ReplayMap, type PathPoint } from "./ReplayMap";

export const metadata = { title: "Delivery replay" };

/**
 * Replay a delivery from the rider's own breadcrumbs.
 *
 * `Order_Tracking_Logs` was written on every location ping and read by nothing,
 * so "the rider says they delivered it, the customer says they didn't" was
 * unanswerable while the platform held the evidence.
 *
 * The verdict is three-valued and the page renders all three. "No tracking data"
 * is not "never arrived" — tracking depends on the rider app having permission,
 * signal and battery, and rendering an absence of evidence as evidence of
 * absence on the screen used to decide whether somebody is stealing would be the
 * worst thing this page could do.
 */

type ListItem = {
  id: string;
  status: string;
  delivery_address: string | null;
  rider: string | null;
  customer: string | null;
  points: number;
  disputed: boolean;
  has_proof: boolean;
  created_at: string | null;
};

type Replay = {
  order: {
    id: string;
    status: string;
    delivery_type: string | null;
    delivery_address: string | null;
    created_at: string | null;
    customer: string | null;
    rider: string | null;
    rider_id: string | null;
    vendor: string | null;
    vendor_id: string | null;
    has_proof: boolean;
    destination: { lat: number; lng: number } | null;
    pickup: { lat: number; lng: number } | null;
  };
  path: PathPoint[];
  findings: {
    points: number;
    first_ping: string | null;
    last_ping: string | null;
    tracked_minutes: number | null;
    distance_travelled_km: number | null;
    closest_approach_m: number | null;
    proximity_m: number;
    reached_destination: boolean | null;
    pings_at_destination: number;
    largest_gap_minutes: number | null;
    signal_gap_minutes: number;
    has_gap: boolean;
    no_verdict_because: string | null;
  };
};

export default async function ReplayPage({
  searchParams,
}: {
  searchParams: Promise<{ order?: string }>;
}) {
  const { order: orderId } = await searchParams;

  let list: { items: ListItem[] };
  let replay: Replay | null = null;
  try {
    list = await get<{ items: ListItem[] }>("/api/admin/orders/replayable");
    if (orderId) {
      replay = await get<Replay>(`/api/admin/orders/${orderId}/replay`);
    }
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the replay" detail={message} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Delivery replay</h1>
        <p className="mt-1 text-sm text-muted">
          Where the rider actually went, from the location pings their app sent
          during the delivery. This is what settles &ldquo;I delivered
          it&rdquo; against &ldquo;no you didn&apos;t&rdquo;.
        </p>
      </div>

      {replay ? <Findings replay={replay} /> : null}

      <Card className="overflow-hidden">
        <div className="border-b border-default px-4 py-3">
          <h2 className="text-sm font-semibold">Orders with a recorded path</h2>
          <p className="mt-0.5 text-xs text-muted">
            Contested orders first — that is what somebody came here to settle.
          </p>
        </div>

        {list.items.length === 0 ? (
          <EmptyState
            icon={<Route className="h-8 w-8" />}
            title="No delivery has been tracked yet"
            description="Paths appear here once riders start running deliveries with the app open."
          />
        ) : (
          <div className="scroll-x">
            <table className="w-full min-w-[44rem] text-sm">
              <caption className="sr-only">Orders with tracking data</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Order</th>
                  <th scope="col" className="px-4 py-3 font-medium">Rider</th>
                  <th scope="col" className="px-4 py-3 font-medium">State</th>
                  <th scope="col" className="px-4 py-3 font-medium">Points</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">
                    <span className="sr-only">Replay</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {list.items.map((item) => (
                  <tr
                    key={item.id}
                    className={
                      item.id === orderId
                        ? "border-b border-default bg-surface-muted last:border-0"
                        : "border-b border-default last:border-0"
                    }
                  >
                    <td className="px-4 py-3">
                      <span className="font-medium">{item.customer ?? "Unnamed"}</span>
                      <span className="block text-xs text-muted">
                        {item.delivery_address ?? "no address"} · {timeAgo(item.created_at)}
                      </span>
                    </td>
                    <td className="px-4 py-3">{item.rider ?? "unassigned"}</td>
                    <td className="px-4 py-3">
                      <Badge tone={item.disputed ? "danger" : "neutral"}>{item.status}</Badge>
                      {item.has_proof ? (
                        <span className="ml-1 text-xs text-muted">photo</span>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      {item.points === 0 ? (
                        <span className="text-xs text-muted">none</span>
                      ) : (
                        formatNumber(item.points)
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/operations/replay?order=${item.id}`}
                        className="rounded-lg border border-default px-3 py-1.5 text-sm hover:bg-surface-muted"
                      >
                        Replay
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Findings({ replay }: { replay: Replay }) {
  const { order, findings, path } = replay;
  const verdict = findings.reached_destination;

  return (
    <>
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold">
              {order.customer ?? "Unnamed customer"} · {order.status}
            </h2>
            <p className="mt-0.5 text-sm text-muted">
              {order.delivery_address ?? "No address recorded"}
              {order.rider ? (
                <>
                  {" · delivered by "}
                  {order.rider_id ? (
                    <Link href={`/people/riders/${order.rider_id}`} className="hover:underline">
                      {order.rider}
                    </Link>
                  ) : (
                    order.rider
                  )}
                </>
              ) : null}
            </p>
          </div>
          <Verdict verdict={verdict} findings={findings} />
        </div>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Closest approach"
          value={
            findings.closest_approach_m === null
              ? "—"
              : findings.closest_approach_m >= 1000
                ? `${(findings.closest_approach_m / 1000).toFixed(2)} km`
                : `${formatNumber(findings.closest_approach_m)} m`
          }
          hint={`Anything within ${findings.proximity_m} m counts as at the door`}
          tone={verdict === false ? "danger" : "neutral"}
          icon={<MapPin className="h-4 w-4" />}
        />
        <Stat
          label="Points recorded"
          value={formatNumber(findings.points)}
          hint={
            findings.tracked_minutes === null
              ? "Nothing was recorded"
              : `over ${findings.tracked_minutes} minutes`
          }
          icon={<Footprints className="h-4 w-4" />}
        />
        <Stat
          label="Distance travelled"
          value={
            findings.distance_travelled_km === null
              ? "—"
              : `${findings.distance_travelled_km} km`
          }
          hint="Summed between consecutive pings, so a gap understates it"
          icon={<Route className="h-4 w-4" />}
        />
        <Stat
          label="Largest gap"
          value={
            findings.largest_gap_minutes === null
              ? "—"
              : `${findings.largest_gap_minutes} min`
          }
          hint={
            findings.has_gap
              ? `Over ${findings.signal_gap_minutes} min — the path has a hole in it`
              : "No meaningful break in the record"
          }
          tone={findings.has_gap ? "warning" : "neutral"}
          icon={<TriangleAlert className="h-4 w-4" />}
        />
      </div>

      {findings.has_gap ? (
        <p className="text-xs text-muted">
          A path with a {findings.largest_gap_minutes}-minute hole in it is not
          one path, it is two, and what happened in between is not in this data.
          Signal drops, batteries die and riders close the app; treat the gap as
          unknown rather than as evidence either way.
        </p>
      ) : null}

      {path.length > 0 || order.destination ? (
        <ReplayMap
          path={path}
          destination={order.destination}
          pickup={order.pickup}
          proximityM={findings.proximity_m}
        />
      ) : null}
    </>
  );
}

/** The verdict, including the honest refusal to give one. */
function Verdict({
  verdict,
  findings,
}: {
  verdict: boolean | null;
  findings: Replay["findings"];
}) {
  if (verdict === null) {
    return (
      <div className="shrink-0 text-right">
        <Badge tone="neutral">
          <CircleHelp className="mr-1 inline h-3.5 w-3.5" aria-hidden />
          No verdict
        </Badge>
        <p className="mt-1 max-w-[16rem] text-xs text-muted">
          {findings.no_verdict_because}. This is not evidence the rider stayed
          away — it is an absence of evidence either way.
        </p>
      </div>
    );
  }

  if (verdict) {
    return (
      <div className="shrink-0 text-right">
        <Badge tone="success">Reached the address</Badge>
        <p className="mt-1 max-w-[16rem] text-xs text-muted">
          {formatNumber(findings.pings_at_destination)} ping
          {findings.pings_at_destination === 1 ? "" : "s"} within{" "}
          {findings.proximity_m} m of the delivery point.
        </p>
      </div>
    );
  }

  return (
    <div className="shrink-0 text-right">
      <Badge tone="danger">Never reached the address</Badge>
      <p className="mt-1 max-w-[16rem] text-xs text-muted">
        The nearest recorded point was{" "}
        {findings.closest_approach_m === null
          ? "—"
          : `${formatNumber(findings.closest_approach_m)} m`}{" "}
        away. Check the gap before acting on this.
      </p>
    </div>
  );
}
