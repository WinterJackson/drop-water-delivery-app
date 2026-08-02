import { ScrollText } from "lucide-react";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDateTime, formatNumber } from "@/lib/utils/format";
import type { QueueStats } from "@/lib/queue-stats";

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

export default async function AuditPage() {
  let log: { items: Entry[]; next_cursor: string | null };
  let stats: QueueStats = {};
  try {
    [log, stats] = await Promise.all([
      get<{ items: Entry[]; next_cursor: string | null }>("/api/admin/audit"),
      get<QueueStats>("/api/admin/queues/stats").catch(() => ({})),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the audit log" detail={message} />;
  }

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

      {log.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<ScrollText className="h-8 w-8" />}
            title="Nothing recorded yet"
            description="Approvals, rejections, payout decisions and document views all appear here as they happen."
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
    </div>
  );
}
