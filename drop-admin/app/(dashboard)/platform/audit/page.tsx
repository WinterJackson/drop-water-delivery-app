import { ScrollText } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDateTime, formatNumber } from "@/lib/utils/format";
import type { QueueStats } from "@/lib/queue-stats";
import { NoAccess } from "@/components/shell/NoAccess";
import { pageAccess } from "@/lib/page-access";

export const metadata = { title: "Audit log" };

type Entry = {
  id: string;
  admin_email: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
  ip: string | null;
  created_at: string | null;
};

/** Anything that reveals personal data or moves money reads differently. */
function toneFor(action: string): "danger" | "warning" | "neutral" {
  if (action.includes("pii")) return "danger";
  if (action.startsWith("payout.") || action.startsWith("admin.")) return "warning";
  return "neutral";
}

/**
 * The action prefixes worth having as one click.
 *
 * `list_audit` matches on `startswith`, so "pii" catches `pii.view` and every
 * future member of that family without this list needing to know them.
 */
const ACTION_FILTERS = [
  { value: "", label: "Everything" },
  { value: "pii", label: "Identity documents" },
  { value: "payout", label: "Payouts" },
  { value: "support", label: "Support" },
  { value: "admin", label: "Administrator changes" },
  { value: "config", label: "Pricing and settings" },
  { value: "order", label: "Orders" },
  { value: "vendor", label: "Stores" },
  { value: "rider", label: "Riders" },
  { value: "review", label: "Reviews" },
] as const;

const PAGE_SIZE = 50;

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<{ action?: string; target?: string; cursor?: string }>;
}) {
  // Gated on the capability `nav-config` declares for `/platform/audit` — the
  // same declaration that hides this entry in the sidebar, so the two can
  // never disagree. The backend enforces it again regardless.
  const access = await pageAccess("/platform/audit");
  if (!access.allowed) return <NoAccess permission={access.permission} />;


  const { action = "", target = "", cursor = "" } = await searchParams;

  // Every one of these was already supported by the endpoint and none of them
  // was ever sent. The screen that answers "who opened this person's national
  // ID" was capped at the newest fifty rows of everything, with no way to ask.
  const query = new URLSearchParams({ limit: String(PAGE_SIZE) });
  if (action) query.set("action", action);
  if (target.trim()) query.set("target_id", target.trim());
  if (cursor) query.set("cursor", cursor);

  let log: { items: Entry[]; next_cursor: string | null };
  let stats: QueueStats = {};
  try {
    [log, stats] = await Promise.all([
      get<{ items: Entry[]; next_cursor: string | null }>(
        `/api/admin/audit?${query.toString()}`,
      ),
      get<QueueStats>("/api/admin/queues/stats").catch(() => ({})),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the audit log" detail={message} />;
  }

  const filtered = Boolean(action || target.trim());
  const nextQuery = new URLSearchParams();
  if (action) nextQuery.set("action", action);
  if (target.trim()) nextQuery.set("target", target.trim());
  if (log.next_cursor) nextQuery.set("cursor", log.next_cursor);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
        <p className="mt-1 text-sm text-muted">
          Every administrative change, and every time someone opened a person&apos;s
          identity documents. Append-only — nothing here can be edited or deleted.
        </p>
      </div>

      {stats.audit ? (
        <section aria-label="Activity">
          <h2 className="sr-only">Activity</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Actions today"
              value={formatNumber(stats.audit.last_24h)}
              hint={
                stats.audit.last_7d === 0
                  ? "Nothing recorded this week, so there is no normal to compare against"
                  : `${stats.audit.daily_average_7d}/day average over the week`
              }
              /* Twice the weekly average is not proof of anything — but it is
                 the only signal a chronological list cannot give you at all. */
              tone={
                stats.audit.last_7d > 0 &&
                stats.audit.last_24h > stats.audit.daily_average_7d * 2
                  ? "warning"
                  : "neutral"
              }
            />
            <Stat
              label="This week"
              value={formatNumber(stats.audit.last_7d)}
              hint={`${formatNumber(stats.audit.total)} recorded in total`}
            />
            <Stat
              label="Busiest administrator"
              value={stats.audit.busiest_admin ?? "—"}
              hint={
                stats.audit.busiest_admin_actions === null
                  ? "No activity this week"
                  : `${formatNumber(stats.audit.busiest_admin_actions)} action(s) in 7 days`
              }
            />
            <Stat
              label="Commonest action"
              value={stats.audit.commonest_action ?? "—"}
              hint={
                stats.audit.commonest_action_count === null
                  ? "No activity this week"
                  : `${formatNumber(stats.audit.commonest_action_count)} time(s) in 7 days`
              }
            />
          </div>
        </section>
      ) : null}

      <form method="GET" className="flex flex-wrap gap-2">
        <label htmlFor="audit-action" className="sr-only">
          Filter by what was done
        </label>
        <select
          id="audit-action"
          name="action"
          defaultValue={action}
          className="rounded-lg border border-default bg-surface px-3 py-2 text-sm"
        >
          {ACTION_FILTERS.map((option) => (
            <option key={option.value || "all"} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <label htmlFor="audit-target" className="sr-only">
          Filter by what it was done to
        </label>
        <input
          id="audit-target"
          name="target"
          defaultValue={target}
          placeholder="Target id — a rider, an order, a ticket…"
          className="min-w-0 flex-1 rounded-lg border border-default bg-surface px-3 py-2 font-mono text-sm"
        />
        <button
          type="submit"
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)]"
        >
          Search
        </button>
        {filtered ? (
          <Link
            href="/platform/audit"
            className="inline-flex items-center rounded-lg px-3 py-2 text-sm text-muted hover:bg-surface-muted"
          >
            Clear
          </Link>
        ) : null}
      </form>

      {log.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<ScrollText className="h-8 w-8" />}
            title={filtered ? "Nothing matches that" : "Nothing recorded yet"}
            description={
              filtered
                ? "No administrator has done this, to this, since the log began."
                : "Approvals, rejections, payout decisions and document views all appear here as they happen."
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <ul>
            {log.items.map((entry) => (
              <li key={entry.id} className="border-b border-default px-5 py-4 last:border-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={toneFor(entry.action)}>{entry.action}</Badge>
                  <span className="text-sm font-medium">{entry.admin_email}</span>
                  <span className="text-sm text-muted">
                    {formatDateTime(entry.created_at)}
                  </span>
                </div>

                {entry.target_type ? (
                  <p className="mt-1.5 text-sm text-muted">
                    {entry.target_type}{" "}
                    <span className="font-mono text-xs">{entry.target_id}</span>
                  </p>
                ) : null}

                {entry.reason ? (
                  <p className="mt-1.5 text-sm">
                    <span className="text-muted">Reason: </span>
                    {entry.reason}
                  </p>
                ) : null}

                {entry.before || entry.after ? (
                  <div className="scroll-x mt-2">
                    <pre className="w-max rounded-lg bg-surface-muted px-3 py-2 font-mono text-xs">
                      {JSON.stringify({ before: entry.before, after: entry.after }, null, 2)}
                    </pre>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {log.next_cursor ? (
        <div className="flex justify-center">
          {/* Keyset, not offset — this table only grows, and the cursor is the
              id of the last row on the page. Without this the log stopped at
              the newest fifty entries and older ones were simply unreachable. */}
          <Link
            href={`/platform/audit?${nextQuery.toString()}`}
            className="rounded-lg border border-default px-4 py-2 text-sm hover:bg-surface-muted"
          >
            Older entries
          </Link>
        </div>
      ) : cursor ? (
        <p className="text-center text-sm text-muted">
          That is the end of the log.{" "}
          <Link href="/platform/audit" className="underline underline-offset-4">
            Back to the newest
          </Link>
        </p>
      ) : null}
    </div>
  );
}
