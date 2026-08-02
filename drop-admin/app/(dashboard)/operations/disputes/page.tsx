import { PackageCheck } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
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
  searchParams: Promise<{ status?: string }>;
}) {
  const { status = "pending_review" } = await searchParams;
  const active = TABS.find((t) => t.key === status)?.key ?? "pending_review";

  type DisputeList = { items: Dispute[] };
  let data: DisputeList;
  let me: AdminMe;
  try {
    [data, me] = await Promise.all([
      get<DisputeList>(`/api/admin/disputes?status=${active}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load disputes" detail={message} />;
  }

  const canResolve = can(me, PERMISSIONS.disputesResolve);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Bottle disputes</h1>
        <p className="mt-1 text-sm text-muted">
          A rider reported the empties were short or damaged. Until this is
          decided, the order is paused and neither side is settled.
        </p>
      </div>

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
    </div>
  );
}
