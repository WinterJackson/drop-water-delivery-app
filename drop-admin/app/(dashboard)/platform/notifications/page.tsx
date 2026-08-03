import { BellRing, BellOff, Eye, Send, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatNumber, timeAgo } from "@/lib/utils/format";

export const metadata = { title: "Notifications" };

/**
 * What the platform has been telling people, and whether it could reach them.
 *
 * Every event writes a `Notification` row **and** may send a push, and the two
 * are not the same. The row always exists; the push needs a `push_token` and the
 * recipient's own preference. An account with no token gets every row and no
 * interruption — fine for a promotion, close to fatal for "your order has been
 * assigned to you".
 *
 * No recipient is named anywhere on this page. Who was told what is a support
 * question and belongs on the ticket, not on a platform-wide feed.
 */

type Summary = {
  total: number;
  last_n_days: number;
  days: number;
  read: number;
  read_rate: number | null;
  accounts: number;
  unreachable_accounts: number;
  reachable_rate: number | null;
};

type Reach = {
  audience: string;
  accounts: number;
  with_token: number;
  without_token: number;
  rate: number | null;
};

type Breakdown = {
  message_type?: string;
  audience?: string;
  sent: number;
  read: number;
  read_rate: number | null;
};

type Channel = { channel: string; sent: number };

type Recent = {
  id: string;
  title: string;
  preview: string;
  message_type: string;
  audience: string;
  channel: string;
  read: boolean;
  order_id: string | null;
  created_at: string | null;
};

type Payload = {
  summary: Summary;
  reachability: Reach[];
  by_type: Breakdown[];
  by_audience: Breakdown[];
  by_channel: Channel[];
  recent: Recent[];
};

const AUDIENCE_LABEL: Record<string, string> = {
  customer: "Customers",
  rider: "Riders",
  vendor: "Stores",
};

export default async function NotificationsPage() {
  let data: Payload;
  try {
    data = await get<Payload>("/api/admin/notifications");
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load notifications" detail={message} />;
  }

  const { summary, reachability, by_type: byType, by_audience: byAudience, by_channel: byChannel, recent } = data;
  const pushed = byChannel.find((row) => row.channel === "push")?.sent ?? 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Notifications</h1>
        <p className="mt-1 text-sm text-muted">
          What the platform has been telling people. Sending and arriving are
          different things, and only one of them was ever visible.
        </p>
      </div>

      {summary.unreachable_accounts > 0 && pushed > 0 ? (
        <Card className="border-[color-mix(in_oklch,var(--danger)_40%,transparent)] p-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <TriangleAlert className="h-4 w-4 text-[var(--danger)]" aria-hidden />
            {formatNumber(summary.unreachable_accounts)} account
            {summary.unreachable_accounts === 1 ? "" : "s"} cannot receive a push
            at all
          </h2>
          <p className="mt-1 text-sm text-muted">
            {formatNumber(pushed)} notification{pushed === 1 ? " was" : "s were"}{" "}
            recorded as sent by push in this window. A device registers its token
            when the app is opened and permission is granted; until then the row
            is written, the history is correct, and nobody is interrupted. On a
            platform where a rider learns about an order from a push, that is the
            difference between &ldquo;they ignored it&rdquo; and &ldquo;they were
            never told&rdquo;.
          </p>
        </Card>
      ) : null}

      <section aria-label="Delivery summary">
        <h2 className="sr-only">Delivery summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label={`Sent in ${summary.days} days`}
            value={formatNumber(summary.last_n_days)}
            hint={`${formatNumber(summary.total)} in total`}
            icon={<Send className="h-4 w-4" />}
          />
          <Stat
            label="Can receive a push"
            value={
              summary.reachable_rate === null ? "—" : `${summary.reachable_rate}%`
            }
            hint={`${formatNumber(summary.accounts - summary.unreachable_accounts)} of ${formatNumber(summary.accounts)} accounts have a device token`}
            tone={
              summary.reachable_rate !== null && summary.reachable_rate < 50
                ? "danger"
                : "neutral"
            }
            icon={<BellRing className="h-4 w-4" />}
          />
          <Stat
            label="No device token"
            value={formatNumber(summary.unreachable_accounts)}
            hint="They get the in-app history and nothing else"
            tone={summary.unreachable_accounts > 0 ? "warning" : "neutral"}
            icon={<BellOff className="h-4 w-4" />}
          />
          <Stat
            label="Opened"
            value={summary.read_rate === null ? "—" : `${summary.read_rate}%`}
            hint="is_read is the only outcome the schema carries — there are no delivery receipts"
            icon={<Eye className="h-4 w-4" />}
          />
        </div>
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Reach, by audience</h2>
          <p className="mt-1 text-sm text-muted">
            The proportion of each group whose device the platform can actually
            reach.
          </p>
          <ul className="mt-3 space-y-2">
            {reachability.map((row) => (
              <li key={row.audience} className="text-sm">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="font-medium">
                    {AUDIENCE_LABEL[row.audience] ?? row.audience}
                  </span>
                  <span className="text-muted">
                    {row.rate === null
                      ? "no accounts"
                      : `${row.with_token} of ${row.accounts} · ${row.rate}%`}
                  </span>
                </div>
                <div
                  className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-muted"
                  role="presentation"
                >
                  <div
                    className="h-full rounded-full bg-[var(--accent)]"
                    style={{ width: `${row.rate ?? 0}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <Card className="p-5">
          <h2 className="text-sm font-semibold">Volume, by kind</h2>
          {byType.length === 0 ? (
            <p className="mt-2 text-sm text-muted">Nothing sent in this window.</p>
          ) : (
            <ul className="mt-3 space-y-2">
              {byType.map((row) => (
                <li
                  key={row.message_type}
                  className="flex flex-wrap items-baseline justify-between gap-2 border-b border-default pb-2 text-sm last:border-0 last:pb-0"
                >
                  <span className="font-medium">{row.message_type}</span>
                  <span className="text-muted">
                    {formatNumber(row.sent)} sent
                    {row.read_rate === null ? "" : ` · ${row.read_rate}% opened`}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {byAudience.length > 0 ? (
            <p className="mt-3 text-xs text-muted">
              By audience:{" "}
              {byAudience
                .map(
                  (row) =>
                    `${AUDIENCE_LABEL[row.audience ?? ""] ?? row.audience} ${formatNumber(row.sent)}`,
                )
                .join(" · ")}
              .
            </p>
          ) : null}
        </Card>
      </div>

      <Card className="overflow-hidden">
        <div className="border-b border-default px-4 py-3">
          <h2 className="text-sm font-semibold">Recent</h2>
          <p className="mt-0.5 text-xs text-muted">
            No recipient is named. Who was told what belongs on their support
            ticket, not on a feed everyone with analytics access can read.
          </p>
        </div>
        {recent.length === 0 ? (
          <EmptyState
            icon={<BellRing className="h-8 w-8" />}
            title="Nothing has been sent"
            description="Notifications appear here as orders, payments and verifications start moving."
          />
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {recent.map((item) => (
              <li key={item.id} className="px-4 py-3">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="min-w-0 text-sm font-medium">{item.title}</span>
                  <span className="shrink-0 text-xs text-muted">
                    {AUDIENCE_LABEL[item.audience] ?? item.audience} ·{" "}
                    {timeAgo(item.created_at)}
                  </span>
                </div>
                <p className="mt-0.5 text-sm text-muted">{item.preview}</p>
                <p className="mt-1 flex flex-wrap items-center gap-1.5">
                  <Badge tone="neutral">{item.message_type}</Badge>
                  <span className="text-xs text-muted">via {item.channel}</span>
                  {item.read ? <span className="text-xs text-muted">· opened</span> : null}
                  {item.order_id ? (
                    <Link
                      href={`/operations/orders?q=${item.order_id}`}
                      className="text-xs text-muted hover:underline"
                    >
                      · the order
                    </Link>
                  ) : null}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
