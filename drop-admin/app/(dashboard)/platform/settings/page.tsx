import { AlertTriangle, Check, X } from "lucide-react";
import Link from "next/link";

import { Badge, Card, CardHeader, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";

export const metadata = { title: "Settings" };

type Settings = {
  switches: { key: string; label: string; enabled: boolean; detail: string }[];
  integrations: { key: string; label: string; configured: boolean }[];
};

/**
 * What this deployment is actually running with.
 *
 * Read-only, and it says so plainly. These are process environment variables:
 * changing one means editing it on the host and restarting. A toggle here that
 * appeared to work and silently did nothing until the next deploy would be far
 * worse than no toggle at all.
 *
 * The **business's** numbers are not here — they live on `/platform/pricing`,
 * where they are rows and genuinely editable. Mixing the two on one screen is
 * how somebody comes to believe a value they can change is one they cannot.
 */
export default async function SettingsPage() {
  let data: Settings;
  try {
    data = await get<Settings>("/api/admin/settings");
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load settings" detail={message} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">
          How this deployment is configured. These are read from the server&apos;s
          environment, so changing one means editing it on the host and
          restarting — there is nothing to save here. The platform&apos;s fees,
          commissions and limits are not environment variables:{" "}
          <Link
            href="/platform/pricing"
            className="text-[var(--accent)] underline underline-offset-4"
          >
            change those on Pricing &amp; fees
          </Link>
          .
        </p>
      </div>

      <Card>
        <CardHeader
          title="Platform switches"
          description="Behaviour that changes what customers, riders and vendors experience."
        />
        <ul className="divide-y divide-[var(--border)]">
          {data.switches.map((item) => (
            <li key={item.key} className="px-5 py-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="font-medium">{item.label}</p>
                  <p className="mt-0.5 font-mono text-xs text-muted">{item.key}</p>
                </div>
                <Badge tone={item.enabled ? "success" : "neutral"}>
                  {item.enabled ? "On" : "Off"}
                </Badge>
              </div>
              <p className="mt-2 max-w-2xl text-sm text-muted">{item.detail}</p>
            </li>
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader
          title="Integrations"
          description="Whether each credential is present. The values themselves are never sent here."
        />
        <ul className="divide-y divide-[var(--border)]">
          {data.integrations.map((item) => (
            <li key={item.key} className="flex flex-wrap items-center justify-between gap-3 px-5 py-3">
              <div className="min-w-0">
                <p className="text-sm font-medium">{item.label}</p>
                <p className="font-mono text-xs text-muted">{item.key}</p>
              </div>
              {item.configured ? (
                <span className="inline-flex shrink-0 items-center gap-1.5 text-sm text-[var(--success)]">
                  <Check className="h-4 w-4" aria-hidden />
                  Configured
                </span>
              ) : (
                <span className="inline-flex shrink-0 items-center gap-1.5 text-sm text-[var(--danger)]">
                  <X className="h-4 w-4" aria-hidden />
                  Not set
                </span>
              )}
            </li>
          ))}
        </ul>
      </Card>

      {data.integrations.some((item) => !item.configured) ? (
        <div
          role="note"
          className="flex gap-3 rounded-xl border border-[var(--warning)] bg-[color-mix(in_oklch,var(--warning)_8%,transparent)] px-5 py-4"
        >
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-[var(--warning)]" aria-hidden />
          <div className="min-w-0 text-sm">
            <p className="font-medium">Something isn&apos;t configured</p>
            <p className="mt-1 text-muted">
              A missing credential fails quietly — document uploads that never
              arrive, pushes that are never delivered. This list is the fastest
              way to find out which.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
