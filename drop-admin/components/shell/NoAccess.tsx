import { Lock } from "lucide-react";
import Link from "next/link";

import type { Permission } from "@/lib/permissions";

/**
 * What a caller sees when they open a page their role does not cover.
 *
 * Twelve pages used to render their heading, fire their queries and show
 * "Couldn't load — 403 Forbidden". That reads as the console being broken, and
 * the person's next move is to report an outage rather than to ask for the
 * capability. This says which capability is missing, by name, so the request
 * they make to whoever administers the platform is a specific one.
 *
 * It is not a security boundary — the backend refused the data either way.
 */
export function NoAccess({ permission }: { permission: Permission }) {
  return (
    <div
      role="alert"
      className="mx-auto max-w-md rounded-xl border border-default bg-surface px-6 py-10 text-center"
    >
      <Lock aria-hidden className="mx-auto h-8 w-8 text-muted" />
      <h1 className="mt-4 text-lg font-semibold tracking-tight">
        You don&apos;t have access to this page
      </h1>
      <p className="mt-2 text-sm text-muted">
        It needs the{" "}
        <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-xs">
          {permission}
        </code>{" "}
        capability, which your account does not currently hold. Ask an
        administrator to grant it if you need this.
      </p>
      <Link
        href="/"
        className="mt-6 inline-block text-sm text-[var(--accent)] underline underline-offset-4"
      >
        Back to the dashboard
      </Link>
    </div>
  );
}
