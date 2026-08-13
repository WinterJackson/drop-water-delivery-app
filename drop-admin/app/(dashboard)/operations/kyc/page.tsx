import { AlarmClock, BadgeCheck, GaugeCircle, UserRoundX, Users } from "lucide-react";
import Link from "next/link";

import { Pagination, sizeHrefFactory } from "@/components/table/Pagination";
import { TableToolbar } from "@/components/table/TableToolbar";
import { Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDuration, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import type { QueueStats } from "@/lib/queue-stats";
import { pageLinks, readPageState, type SearchParams } from "@/lib/table/query";
import { ReviewCard, type QueueRider } from "./ReviewCard";

export const metadata = { title: "Rider verification" };

type Queue = { items: QueueRider[]; next_cursor: string | null };

const TABS = [
  { key: "pending", label: "Waiting" },
  { key: "rejected", label: "Rejected" },
  { key: "approved", label: "Approved" },
] as const;

export default async function KycQueuePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const state = readPageState(params);
  const status = typeof params.status === "string" ? params.status : "pending";
  const active = TABS.find((tab) => tab.key === status)?.key ?? "pending";

  const query = new URLSearchParams({ status: active, limit: String(state.per) });
  if (state.q) query.set("search", state.q);
  if (state.cursor) query.set("cursor", state.cursor);

  let queue: Queue;
  let me: AdminMe;
  // Header figures are context. Wrapped in their own catch so a slow aggregate
  // cannot blank the queue somebody opened this page to work.
  let stats: QueueStats = {};
  try {
    // Three calls, one round trip each way — they do not depend on each other.
    [queue, me, stats] = await Promise.all([
      get<Queue>(`/api/admin/kyc/queue?${query.toString()}`),
      get<AdminMe>("/api/admin/me"),
      get<QueueStats>("/api/admin/queues/stats").catch(() => ({})),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the verification queue" detail={message} />;
  }

  const links = pageLinks({
    pathname: "/operations/kyc",
    filters: { status: active, q: state.q },
    state,
    nextCursor: queue.next_cursor,
    count: queue.items.length,
  });

  const canReview = can(me, PERMISSIONS.ridersKycReview);
  const canViewPii = can(me, PERMISSIONS.piiView);
  const kyc = stats.rider_kyc;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Rider verification</h1>
        <p className="mt-1 text-sm text-muted">
          Riders can&apos;t accept a single delivery until their documents are
          approved. Oldest first.
        </p>
      </div>

      {kyc ? (
        <section aria-label="Queue health">
          <h2 className="sr-only">Queue health</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Waiting for review"
              value={formatNumber(kyc.waiting)}
              hint={
                kyc.oldest_wait_minutes === null
                  ? "Queue is clear"
                  : `Oldest waiting ${formatDuration(kyc.oldest_wait_minutes)}`
              }
              tone={kyc.waiting > 0 ? "warning" : "neutral"}
              icon={<AlarmClock className="h-4 w-4" />}
            />
            <Stat
              label="Decided in 24h"
              value={formatNumber(kyc.decided_24h)}
              hint="Throughput — read the queue depth against this"
              icon={<GaugeCircle className="h-4 w-4" />}
            />
            <Stat
              label="Approval rate"
              value={kyc.approval_rate === null ? "—" : `${kyc.approval_rate}%`}
              hint={
                kyc.approval_rate === null
                  ? "Nothing decided yet, so there is no rate"
                  : `${formatNumber(kyc.approved)} approved · ${formatNumber(kyc.rejected)} rejected`
              }
              icon={<BadgeCheck className="h-4 w-4" />}
            />
            <Stat
              label="Signed up, never applied"
              value={formatNumber(kyc.never_submitted)}
              hint={`Of ${formatNumber(kyc.total)} riders — acquired and then lost`}
              tone={kyc.never_submitted > kyc.total / 2 ? "warning" : "neutral"}
              icon={<UserRoundX className="h-4 w-4" />}
            />
          </div>

          {kyc.never_submitted === kyc.total && kyc.total > 0 ? (
            <p className="mt-3 flex items-start gap-2 text-xs text-[var(--warning)]">
              <Users className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
              <span>
                Every rider on the platform has signed up and submitted nothing.
                No rider can accept a delivery, so every store reads as uncovered
                on the live map — that is the same fact, not two problems.
              </span>
            </p>
          ) : null}
        </section>
      ) : null}

      <nav aria-label="Filter by status" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {TABS.map((tab) => {
            const selected = tab.key === active;
            return (
              <li key={tab.key}>
                <Link
                  href={`/operations/kyc?status=${tab.key}`}
                  aria-current={selected ? "page" : undefined}
                  className={
                    selected
                      ? "inline-flex rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                      : "inline-flex rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                  }
                >
                  {tab.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {!canReview ? (
        <p className="rounded-lg bg-surface-muted px-4 py-3 text-sm text-muted">
          You can see this queue but not decide on it. Approving or rejecting a
          rider needs the &ldquo;Approve or reject rider KYC&rdquo; permission.
        </p>
      ) : null}

      <TableToolbar
        placeholder="Search by rider name, plate or phone"
        keep={{ status: active }}
      >
      {queue.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<BadgeCheck className="h-8 w-8" />}
            title={
              active === "pending"
                ? "No riders waiting"
                : `No ${active} riders`
            }
            description={
              active === "pending"
                ? "Every rider who has submitted documents has been reviewed. New submissions appear here straight away."
                : undefined
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {queue.items.map((rider) => (
            <ReviewCard
              key={rider.id}
              rider={rider}
              canReview={canReview}
              canViewPii={canViewPii}
            />
          ))}
        </div>
      )}

      {/* "Load more" replaced by a real pager. Append-only paging cannot go
          back, cannot be linked to, and grows the DOM without bound on a queue
          somebody works through for an hour. */}
      <Card>
        <Pagination
          links={links}
          noun="riders"
          perPage={state.per}
          sizeHref={sizeHrefFactory("/operations/kyc", { status: active, q: state.q })}
          className="border-t-0"
        />
      </Card>
      </TableToolbar>
    </div>
  );
}
