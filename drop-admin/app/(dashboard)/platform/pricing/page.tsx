import Link from "next/link";

import { Badge, Card, CardHeader, EmptyState, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDateTime } from "@/lib/utils/format";
import { PricingEditor, type Setting } from "./PricingEditor";
import { NoAccess } from "@/components/shell/NoAccess";
import { pageAccess } from "@/lib/page-access";

export const metadata = { title: "Pricing & business rules" };

type ConfigResponse = { settings: Setting[]; version: number };

type HistoryEntry = {
  id: string;
  key: string;
  label: string;
  before: unknown;
  after: unknown;
  reason: string | null;
  changed_by: string;
  created_at: string | null;
};

function describe(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "on" : "off";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export default async function PricingPage() {
  // Gated on the capability `nav-config` declares for `/platform/pricing` — the
  // same declaration that hides this entry in the sidebar, so the two can
  // never disagree. The backend enforces it again regardless.
  const access = await pageAccess("/platform/pricing");
  if (!access.allowed) return <NoAccess permission={access.permission} />;


  let config: ConfigResponse;
  let history: { items: HistoryEntry[] };
  try {
    [config, history] = await Promise.all([
      get<ConfigResponse>("/api/admin/config"),
      get<{ items: HistoryEntry[] }>("/api/admin/config/history?limit=25"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the business rules" detail={message} />;
  }

  const customised = config.settings.filter((setting) => !setting.is_default).length;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pricing &amp; business rules</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">
          Every fee, commission and limit the platform charges. These used to be
          constants in the code, changeable only by a developer and a deploy.
        </p>
      </div>

      <div
        role="note"
        className="max-w-3xl rounded-xl border border-default bg-surface-muted px-5 py-4 text-sm"
      >
        <p className="font-medium">How a change reaches the apps</p>
        <p className="mt-1 text-muted">
          The customer app renders the server&apos;s quote verbatim, so a change
          here is live on the <strong>next order priced</strong> in all three apps —
          nothing is released and no one has to update anything.
        </p>
        <p className="mt-2 text-muted">
          Orders already placed are unaffected. Each one records its own
          economics when it is created, and settlement pays vendors and riders
          from that record — so raising a commission today cannot change what is
          owed on yesterday&apos;s deliveries.
        </p>
      </div>

      <PricingEditor settings={config.settings} />

      <Card>
        <CardHeader
          title="Change history"
          description="Append-only. Every value, with who changed it and why."
          action={
            customised > 0 ? (
              <Badge tone="accent">
                {customised} value{customised === 1 ? "" : "s"} customised
              </Badge>
            ) : (
              <Badge>all at shipped defaults</Badge>
            )
          }
        />
        {history.items.length === 0 ? (
          <EmptyState
            title="Nothing has been changed yet"
            description="The platform is running on the values it shipped with."
          />
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {history.items.map((entry) => (
              <li key={entry.id} className="px-5 py-3.5">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <p className="text-sm font-medium">{entry.label}</p>
                  <p className="text-xs text-muted">
                    {entry.changed_by} · {formatDateTime(entry.created_at)}
                  </p>
                </div>
                <p className="mt-1 text-sm tabular-nums">
                  <span className="text-muted line-through">{describe(entry.before)}</span>
                  <span className="mx-2 text-muted" aria-label="changed to">
                    →
                  </span>
                  <span className="font-medium">{describe(entry.after)}</span>
                </p>
                {entry.reason ? (
                  <p className="mt-1 text-sm text-muted">{entry.reason}</p>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Card>

      <p className="text-sm text-muted">
        Deployment-level configuration — credentials and switches read from the
        server&apos;s environment — is on the{" "}
        <Link href="/platform/settings" className="text-[var(--accent)] underline underline-offset-4">
          settings page
        </Link>
        .
      </p>
    </div>
  );
}
