import { ShieldAlert } from "lucide-react";

import { Header } from "@/components/shell/Header";
import { IdleTimeout } from "@/components/shell/IdleTimeout";
import { MobileNav } from "@/components/shell/MobileNav";
import { Sidebar } from "@/components/shell/Sidebar";
import { SignOutButton } from "@/components/shell/SignOutButton";
import { ApiError, NotAnAdminError, get } from "@/lib/api/server";
import { NO_COUNTS, type NavCounts } from "@/lib/nav-counts";
import type { AdminMe } from "@/lib/permissions";

/**
 * Resolves who the caller is before a single screen renders.
 *
 * This is the one place the console asks "are you an administrator at all".
 * Because the platform shares a Clerk instance with the customer, rider and
 * vendor apps, anyone with an account can sign in and land here — so the
 * answer has to come from the backend's `Admin_Users` table, not from the
 * session.
 *
 * The result is passed down as the nav's capability list. Every route it links
 * to is still enforced server-side; hiding a link only avoids offering someone
 * an action that would refuse them.
 */
export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  let me: AdminMe;

  try {
    me = await get<AdminMe>("/api/admin/me");
  } catch (error) {
    if (error instanceof NotAnAdminError) return <NoAccess />;
    if (error instanceof ApiError && error.type === "two_factor_required") {
      return <TwoFactorRequired message={error.message} />;
    }
    if (error instanceof ApiError) {
      return <Unavailable message={error.message} />;
    }
    throw error;
  }

  // Badges are decoration on top of a working console, so a failure here must
  // not take the whole shell down with it. Everything renders unbadged instead.
  let counts: NavCounts = NO_COUNTS;
  try {
    counts = await get<NavCounts>("/api/admin/nav/counts");
  } catch {
    counts = NO_COUNTS;
  }

  return (
    <div className="flex min-h-dvh">
      <Sidebar me={me} counts={counts} />

      {/* `min-w-0` all the way down, or a wide table forces the whole page to
          scroll sideways instead of scrolling inside its own container. This is
          the single most common cause of a "responsive" console that still
          shudders horizontally on a phone. */}
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />

        <main className="min-w-0 flex-1 px-4 py-6 pb-tabbar lg:px-6 lg:py-8 lg:pb-8">
          {children}
        </main>
      </div>

      <MobileNav me={me} counts={counts} />

      {/* Mounted once for the whole console rather than per page, so navigating
          does not reset the clock by remounting the timer. */}
      <IdleTimeout />
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-dvh items-center justify-center px-4 py-12">
      <div className="w-full max-w-md text-center">{children}</div>
    </main>
  );
}

function NoAccess() {
  return (
    <Shell>
      <ShieldAlert className="mx-auto mb-4 h-10 w-10 text-muted" aria-hidden />
      <h1 className="text-xl font-semibold">You don&apos;t have access to this console</h1>
      <p className="mt-2 text-sm text-muted">
        Your account is signed in, but it isn&apos;t registered as a Drop
        administrator. If you think that&apos;s wrong, ask an existing
        administrator to add you.
      </p>
      {/* Deliberately no "request access" button: an unauthenticated-to-admin
          self-service path is the last thing this console should offer.

          A real sign-out, not a link to `/sign-in` — Clerk sees the existing
          session and sends the caller straight back to this same refusal, which
          is a loop with no exit but clearing cookies. */}
      <p className="mt-6 text-sm">
        <SignOutButton label="Sign in with a different account" />
      </p>
    </Shell>
  );
}

function TwoFactorRequired({ message }: { message: string }) {
  return (
    <Shell>
      <ShieldAlert className="mx-auto mb-4 h-10 w-10 text-[var(--warning)]" aria-hidden />
      <h1 className="text-xl font-semibold">Two-factor authentication required</h1>
      <p className="mt-2 text-sm text-muted">{message}</p>
      <p className="mt-4 text-sm text-muted">
        This console can read identity documents and move money, so a password
        on its own isn&apos;t enough. Enable two-factor authentication on your
        account, then sign in again — the claim is set when the session is
        established, so an existing session will not pick it up.
      </p>
      <p className="mt-6 text-sm">
        <SignOutButton label="Sign out and start a new session" />
      </p>
    </Shell>
  );
}

function Unavailable({ message }: { message: string }) {
  return (
    <Shell>
      <h1 className="text-xl font-semibold">The console can&apos;t load right now</h1>
      <p className="mt-2 text-sm text-muted">{message}</p>
    </Shell>
  );
}
