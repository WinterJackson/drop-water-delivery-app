import { AlarmClock, BadgeCheck, Store, StoreIcon } from "lucide-react";
import Link from "next/link";

import { Pagination, sizeHrefFactory } from "@/components/table/Pagination";
import { TableToolbar } from "@/components/table/TableToolbar";
import { Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDuration, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import type { QueueStats } from "@/lib/queue-stats";
import { pageLinks, readPageState, type SearchParams } from "@/lib/table/query";
import { VerificationCard, type QueueVendor } from "./VerificationCard";

export const metadata = { title: "Vendor verification" };

const VIEWS = {
  pending: { label: "Awaiting review", blurb: "Stores that have not been checked yet." },
  rejected: { label: "Rejected", blurb: "Told what was missing. They can resubmit." },
  verified: { label: "Verified", blurb: "Paperwork confirmed." },
} as const;

type View = keyof typeof VIEWS;

export default async function VendorVerificationPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const state = readPageState(params);
  const raw = typeof params.view === "string" ? params.view : "";
  const view: View = raw && raw in VIEWS ? (raw as View) : "pending";

  const query = new URLSearchParams({ status: view, limit: String(state.per) });
  if (state.q) query.set("search", state.q);
  if (state.cursor) query.set("cursor", state.cursor);

  let data: { items: QueueVendor[]; next_cursor: string | null };
  let me: AdminMe;
  let stats: QueueStats = {};
  try {
    [data, me, stats] = await Promise.all([
      get<{ items: QueueVendor[]; next_cursor: string | null }>(
        `/api/admin/people/vendors?${query.toString()}`,
      ),
      get<AdminMe>("/api/admin/me"),
      get<QueueStats>("/api/admin/queues/stats").catch(() => ({})),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the verification queue" detail={message} />;
  }

  const links = pageLinks({
    pathname: "/operations/vendors",
    filters: { view, q: state.q },
    state,
    nextCursor: data.next_cursor,
    count: data.items.length,
  });

  const canApprove = can(me, PERMISSIONS.vendorsApprove);
  const vendors = stats.vendor_verification;

  const header = vendors ? (
    <section aria-label="Queue health">
      <h2 className="sr-only">Queue health</h2>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Awaiting review"
          value={formatNumber(vendors.waiting)}
          hint={
            vendors.oldest_wait_minutes === null
              ? "No wait time recorded"
              : `Oldest waiting ${formatDuration(vendors.oldest_wait_minutes)}`
          }
          tone={vendors.waiting > 0 ? "warning" : "neutral"}
          icon={<AlarmClock className="h-4 w-4" />}
        />
        <Stat
          label="Verified"
          value={formatNumber(vendors.approved)}
          hint={`Of ${formatNumber(vendors.total)} stores on the platform`}
          icon={<BadgeCheck className="h-4 w-4" />}
        />
        <Stat
          label="Approval rate"
          value={vendors.approval_rate === null ? "—" : `${vendors.approval_rate}%`}
          hint={
            vendors.approval_rate === null
              ? "Nothing decided yet, so there is no rate"
              : `${formatNumber(vendors.approved)} approved · ${formatNumber(vendors.rejected)} rejected`
          }
          icon={<StoreIcon className="h-4 w-4" />}
        />
        <Stat
          label="Suspended"
          value={formatNumber(vendors.suspended)}
          hint="Deactivated stores — invisible to customers"
          tone={vendors.suspended > 0 ? "warning" : "neutral"}
          icon={<Store className="h-4 w-4" />}
        />
      </div>
    </section>
  ) : null;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Vendor verification</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          Confirming a store&apos;s paperwork. This is separate from suspension:
          rejecting a store records that its documents are not in order, it does
          not stop it trading.
        </p>
      </div>

      {/* Whether verification actually gates discovery is a deployment switch,
          and someone working this queue needs to know which world they are in —
          otherwise "verified" feels either urgent or pointless, and they cannot
          tell which. */}
      {can(me, PERMISSIONS.settingsManage) ? (
        <p className="rounded-lg bg-surface-muted px-4 py-3 text-sm text-muted">
          Whether unverified stores can be found by customers is controlled by{" "}
          <Link href="/platform/settings" className="text-[var(--accent)] underline underline-offset-4">
            a deployment setting
          </Link>
          .
        </p>
      ) : null}

      {header}

      <nav aria-label="Verification status" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {(Object.keys(VIEWS) as View[]).map((key) => (
            <li key={key}>
              <Link
                href={`/operations/vendors?view=${key}`}
                aria-current={key === view ? "page" : undefined}
                className={
                  key === view
                    ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                    : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                }
              >
                {VIEWS[key].label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <p className="text-sm text-muted">{VIEWS[view].blurb}</p>

      <TableToolbar
        placeholder="Search stores by name, owner, email or phone"
        keep={{ view }}
      >
      {data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Store className="h-8 w-8" />}
            title={
              view === "pending"
                ? "Every store has been reviewed"
                : `No ${VIEWS[view].label.toLowerCase()} stores`
            }
            description={
              view === "pending"
                ? "New stores appear here as they sign up."
                : undefined
            }
          />
        </Card>
      ) : (
        <div className="grid gap-4 xl:grid-cols-2">
          {data.items.map((vendor) => (
            <VerificationCard key={vendor.id} vendor={vendor} canApprove={canApprove} />
          ))}
        </div>
      )}

      <Card>
        <Pagination
          links={links}
          noun="stores"
          perPage={state.per}
          sizeHref={sizeHrefFactory("/operations/vendors", { view, q: state.q })}
          className="border-t-0"
        />
      </Card>
      </TableToolbar>
    </div>
  );
}
