import { AlarmClock, GaugeCircle, PackageCheck, Scale } from "lucide-react";
import Link from "next/link";

import { Pagination, sizeHrefFactory } from "@/components/table/Pagination";
import { TableToolbar } from "@/components/table/TableToolbar";
import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDuration, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import type { QueueStats } from "@/lib/queue-stats";
import { pageLinks, readPageState, type SearchParams } from "@/lib/table/query";
import { DisputeCard, type Dispute } from "./DisputeCard";

export const metadata = { title: "Disputes" };

const TABS = [
  { key: "pending_review", label: "Awaiting decision" },
  { key: "approved", label: "Upheld" },
  { key: "denied", label: "Not upheld" },
] as const;

export default async function DisputesPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const state = readPageState(params);
  const status = typeof params.status === "string" ? params.status : "pending_review";
  const active = TABS.find((t) => t.key === status)?.key ?? "pending_review";

  const query = new URLSearchParams({ status: active, limit: String(state.per) });
  if (state.q) query.set("search", state.q);
  if (state.cursor) query.set("cursor", state.cursor);

  type DisputeList = { items: Dispute[]; next_cursor: string | null };
  let data: DisputeList;
  let me: AdminMe;
  let stats: QueueStats = {};
  try {
    [data, me, stats] = await Promise.all([
      get<DisputeList>(`/api/admin/disputes?${query.toString()}`),
      get<AdminMe>("/api/admin/me"),
      get<QueueStats>("/api/admin/queues/stats").catch(() => ({})),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load disputes" detail={message} />;
  }

  const links = pageLinks({
    pathname: "/operations/disputes",
    filters: { status: active, q: state.q },
    state,
    nextCursor: data.next_cursor,
    count: data.items.length,
  });

  const canResolve = can(me, PERMISSIONS.disputesResolve);
  const disputes = stats.disputes;

  const header = disputes ? (
    <section aria-label="Queue health">
      <h2 className="sr-only">Queue health</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Awaiting a decision"
          value={formatNumber(disputes.waiting)}
          hint={
            disputes.oldest_wait_minutes === null
              ? "Nothing waiting"
              : `Oldest waiting ${formatDuration(disputes.oldest_wait_minutes)}`
          }
          tone={disputes.waiting > 0 ? "warning" : "neutral"}
          icon={<AlarmClock className="h-4 w-4" />}
        />
        <Stat
          label="Decided in 24h"
          value={formatNumber(disputes.decided_24h)}
          hint="Throughput — read the queue depth against this"
          icon={<GaugeCircle className="h-4 w-4" />}
        />
        <Stat
          label="Upheld"
          value={disputes.uphold_rate === null ? "—" : `${disputes.uphold_rate}%`}
          hint={
            disputes.uphold_rate === null
              ? "Nothing decided yet, so there is no rate"
              : `${formatNumber(disputes.upheld)} for the rider · ${formatNumber(disputes.denied)} for the vendor`
          }
          icon={<Scale className="h-4 w-4" />}
        />
        <Stat
          label="Raised in total"
          value={formatNumber(disputes.total)}
          hint="Every bottle rejection ever escalated"
          icon={<PackageCheck className="h-4 w-4" />}
        />
      </div>
      {disputes.uphold_rate !== null && (disputes.uphold_rate >= 90 || disputes.uphold_rate <= 10) ? (
        <p className="mt-3 text-xs text-[var(--warning)]">
          Decisions are landing almost entirely on one side. That is either a real
          pattern in the evidence or a reviewer applying a shortcut — worth reading
          a handful of the last decisions before trusting the rate.
        </p>
      ) : null}
    </section>
  ) : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Bottle disputes</h1>
        <p className="mt-1 text-sm text-muted">
          A rider reported the empties were short or damaged. Until this is
          decided, the order is paused and neither side is settled.
        </p>
      </div>

      {header}

      <nav aria-label="Filter by status" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {TABS.map((tab) => (
            <li key={tab.key}>
              <Link
                href={`/operations/disputes?status=${tab.key}`}
                aria-current={tab.key === active ? "page" : undefined}
                className={
                  tab.key === active
                    ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                    : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                }
              >
                {tab.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {!canResolve ? (
        <p className="rounded-lg bg-surface-muted px-4 py-3 text-sm text-muted">
          You can read disputes but not decide them.
        </p>
      ) : null}

      <TableToolbar
        placeholder="Search by rider name, reason or ticket id"
        keep={{ status: active }}
      >
      {data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<PackageCheck className="h-8 w-8" />}
            title={active === "pending_review" ? "No disputes waiting" : "Nothing here"}
            description={
              active === "pending_review"
                ? "Riders and vendors agree on every bottle count so far."
                : undefined
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {data.items.map((dispute) => (
            <DisputeCard key={dispute.id} dispute={dispute} canResolve={canResolve} />
          ))}
        </div>
      )}

      <Card>
        <Pagination
          links={links}
          noun="disputes"
          perPage={state.per}
          sizeHref={sizeHrefFactory("/operations/disputes", { status: active, q: state.q })}
          className="border-t-0"
        />
      </Card>
      </TableToolbar>
    </div>
  );
}
