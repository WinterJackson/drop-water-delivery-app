import { Inbox } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import type { QueueStats } from "@/lib/queue-stats";
import { cn } from "@/lib/utils/cn";
import { formatDuration, formatNumber, timeAgo } from "@/lib/utils/format";
import { NoAccess } from "@/components/shell/NoAccess";
import { pageAccess } from "@/lib/page-access";
import { Pagination, sizeHrefFactory } from "@/components/table/Pagination";
import { TableToolbar } from "@/components/table/TableToolbar";
import { pageLinks, readPageState, type SearchParams } from "@/lib/table/query";

export const metadata = { title: "Support" };

type Ticket = {
  id: string;
  subject: string;
  requester_type: string;
  requester_id: string;
  category: string;
  priority: string;
  status: string;
  assigned_to: string | null;
  reply_count: number;
  related_order_id: string | null;
  created_at: string | null;
  age_hours: number | null;
  awaiting_first_reply: boolean;
  /** They spoke last on an unfinished ticket — it is our turn, whatever the status says. */
  awaiting_us: boolean;
};

const VIEWS = [
  { key: "open", label: "Open" },
  { key: "pending", label: "Waiting on them" },
  { key: "resolved", label: "Resolved" },
  { key: "closed", label: "Closed" },
  { key: "all", label: "All" },
] as const;

const PRIORITY_TONE: Record<string, "neutral" | "warning" | "danger"> = {
  low: "neutral",
  normal: "neutral",
  high: "warning",
  urgent: "danger",
};

/** Past this with nobody having replied, the queue is failing the person. */
const FIRST_REPLY_TARGET_HOURS = 4;

export default async function SupportPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  // Gated on the capability `nav-config` declares for `/support` — the
  // same declaration that hides this entry in the sidebar, so the two can
  // never disagree. The backend enforces it again regardless.
  const access = await pageAccess("/support");
  if (!access.allowed) return <NoAccess permission={access.permission} />;


  const params = await searchParams;
  const state = readPageState(params);
  const text = (name: string) =>
    typeof params[name] === "string" ? (params[name] as string) : "";
  const view = text("view");
  const q = state.q;
  const priority = text("priority");
  const category = text("category");
  const requester = text("requester");
  const active = VIEWS.find((v) => v.key === view)?.key ?? "open";

  const query = new URLSearchParams({ status: active, limit: String(state.per) });
  if (q) query.set("search", q);
  if (priority) query.set("priority", priority);
  if (category) query.set("category", category);
  if (requester) query.set("requester_type", requester);
  if (state.cursor) query.set("cursor", state.cursor);

  let data: { items: Ticket[]; next_cursor: string | null };
  let counts: Record<string, number>;
  let stats: QueueStats = {};
  // Categories come from the backend rather than a copy here, so the filter
  // cannot offer one `create_ticket` would silently rewrite to "other".
  let meta: { categories: string[]; priorities: string[] } = {
    categories: [],
    priorities: [],
  };
  try {
    [data, counts, stats, meta] = await Promise.all([
      get<{ items: Ticket[]; next_cursor: string | null }>(
        `/api/admin/support/tickets?${query.toString()}`,
      ),
      get<Record<string, number>>("/api/admin/support/counts"),
      get<QueueStats>("/api/admin/queues/stats").catch(() => ({})),
      get<{ categories: string[]; priorities: string[] }>(
        "/api/admin/support/meta",
      ).catch(() => meta),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the support queue" detail={message} />;
  }

  const links = pageLinks({
    pathname: "/support",
    filters: { view: active, q, priority, category, requester },
    state,
    nextCursor: data.next_cursor,
    count: data.items.length,
  });

  const unanswered = data.items.filter(
    (ticket) => ticket.awaiting_first_reply && (ticket.age_hours ?? 0) > FIRST_REPLY_TARGET_HOURS,
  ).length;
  const support = stats.support;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Support</h1>
        <p className="mt-1 text-sm text-muted">
          Oldest first — a queue sorted newest first buries the person who has
          been waiting three days.
        </p>
      </div>

      {unanswered > 0 ? (
        <p
          role="status"
          className="rounded-lg border border-[var(--warning)] bg-[color-mix(in_oklch,var(--warning)_10%,transparent)] px-4 py-3 text-sm"
        >
          {formatNumber(unanswered)} ticket{unanswered === 1 ? " has" : "s have"} had no
          reply for over {FIRST_REPLY_TARGET_HOURS} hours.
        </p>
      ) : null}


      {support ? (
        <section aria-label="Queue health">
          <h2 className="sr-only">Queue health</h2>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Open"
              value={formatNumber(support.waiting)}
              hint={
                support.oldest_wait_minutes === null
                  ? "Nothing waiting"
                  : `Oldest open ${formatDuration(support.oldest_wait_minutes)}`
              }
              tone={support.waiting > 0 ? "warning" : "neutral"}
            />
            <Stat
              label="Nobody has picked up"
              value={formatNumber(support.unassigned)}
              hint="Open and unassigned — the ones that fall between people"
              tone={support.unassigned > 0 ? "danger" : "neutral"}
            />
            <Stat
              label="Waiting on the requester"
              value={formatNumber(support.awaiting_requester)}
              hint="Replied to. Deliberately not counted as open — nobody can act on these"
            />
            <Stat
              label="Closed in 24h"
              value={formatNumber(support.resolved_24h)}
              hint={`Of ${formatNumber(support.total)} tickets ever raised`}
            />
          </div>
        </section>
      ) : null}

      <nav aria-label="Filter tickets" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {VIEWS.map((v) => {
            const count = v.key === "open" ? counts.open_total : counts[v.key];
            // Carry the filters across. Switching tab used to reset them, so
            // "urgent, from riders" became "everything" on the second click.
            const href = new URLSearchParams({ view: v.key });
            if (q.trim()) href.set("q", q.trim());
            if (priority) href.set("priority", priority);
            if (category) href.set("category", category);
            if (requester) href.set("requester", requester);
            return (
              <li key={v.key}>
                <Link
                  href={`/support?${href.toString()}`}
                  aria-current={v.key === active ? "page" : undefined}
                  className={
                    v.key === active
                      ? "inline-flex items-center gap-2 whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                      : "inline-flex items-center gap-2 whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                  }
                >
                  {v.label}
                  {count ? <span className="tabular-nums">{count}</span> : null}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      <TableToolbar
        placeholder="Search subject, assignee or ticket id"
        keep={{ view: active }}
        filters={[
          {
            name: "priority",
            label: "Filter by priority",
            value: priority,
            options: [
              { value: "", label: "Any priority" },
              { value: "urgent", label: "Urgent" },
              { value: "high", label: "High" },
              { value: "normal", label: "Normal" },
              { value: "low", label: "Low" },
            ],
          },
          {
            name: "category",
            label: "Filter by category",
            value: category,
            // From the backend rather than a copy here, so the filter cannot
            // offer one `create_ticket` would silently rewrite to "other".
            options: [
              { value: "", label: "Any subject" },
              ...meta.categories.map((name) => ({ value: name, label: name })),
            ],
          },
          {
            name: "requester",
            label: "Filter by who raised it",
            value: requester,
            options: [
              { value: "", label: "Anyone" },
              { value: "customer", label: "Customers" },
              { value: "rider", label: "Riders" },
              { value: "vendor", label: "Stores" },
            ],
          },
        ]}
      >
      {data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Inbox className="h-8 w-8" />}
            title={active === "open" ? "Nothing waiting" : "No tickets here"}
            description={
              active === "open"
                ? "Every ticket has been answered. Tickets raised from the customer, rider and vendor apps land here."
                : undefined
            }
          />
        </Card>
      ) : (
        <ul className="space-y-3">
          {data.items.map((ticket) => {
            const overdue =
              ticket.awaiting_first_reply && (ticket.age_hours ?? 0) > FIRST_REPLY_TARGET_HOURS;
            return (
              <li key={ticket.id}>
                <Link href={`/support/${ticket.id}`} className="group block">
                  <Card
                    className={cn(
                      "p-4 transition-colors group-hover:border-[var(--accent)]",
                      overdue && "border-[var(--warning)]",
                    )}
                  >
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <p className="min-w-0 flex-1 truncate font-medium">{ticket.subject}</p>
                      <div className="flex shrink-0 flex-wrap items-center gap-2">
                        {ticket.priority !== "normal" ? (
                          <Badge tone={PRIORITY_TONE[ticket.priority] ?? "neutral"}>
                            {ticket.priority}
                          </Badge>
                        ) : null}
                        {ticket.awaiting_first_reply ? (
                          <Badge tone={overdue ? "danger" : "warning"}>no reply yet</Badge>
                        ) : ticket.awaiting_us ? (
                          // Distinct from "no reply yet": we answered, they came
                          // back, and the ball is ours again. Without this a
                          // ticket someone replied to a minute ago is
                          // indistinguishable from one legitimately parked.
                          <Badge tone="warning">they replied</Badge>
                        ) : null}
                        <Badge>{ticket.status}</Badge>
                      </div>
                    </div>

                    <p className="mt-1.5 text-sm text-muted">
                      <span className="capitalize">{ticket.requester_type}</span> ·{" "}
                      {ticket.category} · raised {timeAgo(ticket.created_at)}
                      {ticket.reply_count > 0
                        ? ` · ${ticket.reply_count} repl${ticket.reply_count === 1 ? "y" : "ies"}`
                        : ""}
                      {ticket.assigned_to ? ` · ${ticket.assigned_to}` : " · unassigned"}
                    </p>
                  </Card>
                </Link>
              </li>
            );
          })}
        </ul>
      )}

      <Card>
        <Pagination
          links={links}
          noun="tickets"
          perPage={state.per}
          sizeHref={sizeHrefFactory("/support", {
            view: active,
            q,
            priority,
            category,
            requester,
          })}
          className="border-t-0"
        />
      </Card>
      </TableToolbar>
    </div>
  );
}
