import { BadgeCheck } from "lucide-react";
import Link from "next/link";

import { Card, EmptyState, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
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
  searchParams: Promise<{ status?: string }>;
}) {
  const { status = "pending" } = await searchParams;
  const active = TABS.find((tab) => tab.key === status)?.key ?? "pending";

  let queue: Queue;
  let me: AdminMe;
  try {
    // Two calls, one round trip each way — they do not depend on each other.
    [queue, me] = await Promise.all([
      get<Queue>(`/api/admin/kyc/queue?status=${active}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the verification queue" detail={message} />;
  }

  const canReview = can(me, PERMISSIONS.ridersKycReview);
  const canViewPii = can(me, PERMISSIONS.piiView);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Rider verification</h1>
        <p className="mt-1 text-sm text-muted">
          Riders can&apos;t accept a single delivery until their documents are
          approved. Oldest first.
        </p>
      </div>

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

      {queue.next_cursor ? (
        <div className="flex justify-center">
          <Link
            href={`/operations/kyc?status=${active}&cursor=${queue.next_cursor}`}
            className="rounded-lg border border-default px-4 py-2 text-sm hover:bg-surface-muted"
          >
            Load more
          </Link>
        </div>
      ) : null}
    </div>
  );
}
