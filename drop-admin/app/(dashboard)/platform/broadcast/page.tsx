import { Megaphone } from "lucide-react";

import { Badge, Card, CardHeader, EmptyState, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDateTime, formatNumber } from "@/lib/utils/format";
import { Composer, type Audience } from "./Composer";
import { NoAccess } from "@/components/shell/NoAccess";
import { pageAccess } from "@/lib/page-access";

export const metadata = { title: "Broadcast" };

type Campaign = {
  id: string;
  channel: string;
  audience_label: string;
  subject: string;
  body: string;
  status: string;
  transactional: boolean;
  recipient_count: number;
  sent_count: number;
  failed_count: number;
  error: string | null;
  created_by: string;
  created_at: string | null;
  completed_at: string | null;
};

const STATUS_TONE: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  queued: "warning",
  sending: "warning",
  sent: "success",
  failed: "danger",
};

export default async function BroadcastPage() {
  // Gated on the capability `nav-config` declares for `/platform/broadcast` — the
  // same declaration that hides this entry in the sidebar, so the two can
  // never disagree. The backend enforces it again regardless.
  const access = await pageAccess("/platform/broadcast");
  if (!access.allowed) return <NoAccess permission={access.permission} />;


  let audiences: { audiences: Audience[] };
  let campaigns: { items: Campaign[] };
  try {
    [audiences, campaigns] = await Promise.all([
      get<{ audiences: Audience[] }>("/api/admin/broadcast/audiences"),
      get<{ items: Campaign[] }>("/api/admin/broadcast/campaigns?limit=25"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load broadcast" detail={message} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Broadcast</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Message a segment of the platform. Every message writes an in-app
          notification that stays in their history; the push and the email are
          best-effort on top of that.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <Composer audiences={audiences.audiences} />

        <Card className="lg:self-start">
          <CardHeader
            title="Sent"
            description="Counts update as a campaign runs, so a failure shows how far it got."
          />
          {campaigns.items.length === 0 ? (
            <EmptyState
              icon={<Megaphone className="h-8 w-8" />}
              title="Nothing sent yet"
              description="Campaigns appear here with their delivery counts."
            />
          ) : (
            <ul className="divide-y divide-[var(--border)]">
              {campaigns.items.map((campaign) => (
                <li key={campaign.id} className="px-5 py-3.5">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="min-w-0 flex-1 truncate text-sm font-medium">
                      {campaign.subject}
                    </p>
                    <Badge tone={STATUS_TONE[campaign.status] ?? "neutral"}>
                      {campaign.status}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    {campaign.audience_label} · {campaign.channel.replace("_", "-")}
                    {campaign.transactional ? " · preferences overridden" : ""}
                  </p>
                  <p className="mt-1 text-xs tabular-nums text-muted">
                    {formatNumber(campaign.sent_count)} of{" "}
                    {formatNumber(campaign.recipient_count)} sent
                    {campaign.failed_count > 0 ? (
                      <span className="text-[var(--danger)]">
                        {" "}
                        · {formatNumber(campaign.failed_count)} failed
                      </span>
                    ) : null}
                  </p>
                  <p className="mt-0.5 text-xs text-muted">
                    {campaign.created_by} · {formatDateTime(campaign.created_at)}
                  </p>
                  {campaign.error ? (
                    <p className="mt-1 text-xs text-[var(--danger)]">{campaign.error}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
