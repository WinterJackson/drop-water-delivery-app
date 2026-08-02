import { Store } from "lucide-react";
import Link from "next/link";

import { Card, EmptyState, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
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
  searchParams: Promise<{ view?: string }>;
}) {
  const params = await searchParams;
  const view: View = params.view && params.view in VIEWS ? (params.view as View) : "pending";

  let data: { items: QueueVendor[] };
  let me: AdminMe;
  try {
    [data, me] = await Promise.all([
      get<{ items: QueueVendor[] }>(`/api/admin/people/vendors?status=${view}&limit=100`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the verification queue" detail={message} />;
  }

  const canApprove = can(me, PERMISSIONS.vendorsApprove);

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
    </div>
  );
}
