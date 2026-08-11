import { Eye, KeyRound, MailQuestion, Wallet } from "lucide-react";

import { ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, type AdminMe } from "@/lib/permissions";
import { formatNumber, timeAgo } from "@/lib/utils/format";
import { AdminManager, type AdminRow, type Catalogue } from "./AdminManager";
import { NoAccess } from "@/components/shell/NoAccess";
import { pageAccess } from "@/lib/page-access";

export const metadata = { title: "Administrators" };

type Roster = { items: AdminRow[] } & Catalogue;

/** Thirty days without a sign-in, on a console that can reveal a national ID. */
const DORMANT_DAYS = 30;

export default async function AdminsPage() {
  // Gated on the capability `nav-config` declares for `/platform/admins` — the
  // same declaration that hides this entry in the sidebar, so the two can
  // never disagree. The backend enforces it again regardless.
  const access = await pageAccess("/platform/admins");
  if (!access.allowed) return <NoAccess permission={access.permission} />;


  let roster: Roster;
  let me: AdminMe;
  try {
    [roster, me] = await Promise.all([
      get<Roster>("/api/admin/admins"),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load administrators" detail={message} />;
  }

  // Counted here rather than fetched: the roster already carries the
  // authoritative permission list per row, so a second endpoint could only
  // disagree with what is rendered directly below it.
  const active = roster.items.filter((admin) => admin.is_active);
  const holds = (permission: string) =>
    active.filter((admin) => admin.permissions.includes(permission)).length;

  const dormantCutoff = Date.now() - DORMANT_DAYS * 24 * 60 * 60 * 1000;
  const dormant = active.filter(
    (admin) =>
      !admin.is_pending &&
      admin.last_seen_at !== null &&
      new Date(admin.last_seen_at).getTime() < dormantCutoff,
  );
  const oldest = dormant
    .map((admin) => admin.last_seen_at)
    .sort()
    .at(0);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Administrators</h1>
        <p className="mt-1 text-sm text-muted">
          Who can use this console, and exactly what each of them can do.
        </p>
      </div>

      {/* Not decoration. The roster answers "what can this person do"; these
          answer "how many people can do the dangerous things", which is the
          question an access review actually asks and which reading a list of
          expandable rows one at a time does not. */}
      <section aria-label="Access summary">
        <h2 className="sr-only">Access summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Active administrators"
            value={formatNumber(active.length)}
            hint={
              roster.items.length === active.length
                ? "Nobody has been revoked"
                : `${formatNumber(roster.items.length - active.length)} revoked`
            }
            icon={<KeyRound className="h-4 w-4" />}
          />
          <Stat
            label="Can reveal identity documents"
            value={formatNumber(holds(PERMISSIONS.piiView))}
            hint="pii.view — every use is audited with a stated reason"
            tone={holds(PERMISSIONS.piiView) > 2 ? "warning" : "neutral"}
            icon={<Eye className="h-4 w-4" />}
          />
          <Stat
            label="Can credit a balance"
            value={formatNumber(holds(PERMISSIONS.financeAdjust))}
            hint="finance.adjust — the only capability that creates money from nothing"
            tone={holds(PERMISSIONS.financeAdjust) > 1 ? "warning" : "neutral"}
            icon={<Wallet className="h-4 w-4" />}
          />
          <Stat
            label={`Not seen in ${DORMANT_DAYS} days`}
            value={formatNumber(dormant.length)}
            hint={
              oldest
                ? `Longest absent since ${timeAgo(oldest)}`
                : "Everyone active has signed in recently"
            }
            tone={dormant.length > 0 ? "warning" : "neutral"}
            icon={<MailQuestion className="h-4 w-4" />}
          />
        </div>
      </section>

      {/* The catalogue ships with the roster, so this screen can never offer a
          permission the server has dropped, nor miss one it has added. */}
      <AdminManager
        admins={roster.items}
        catalogue={{
          permissions: roster.permissions,
          groups: roster.groups,
          roles: roster.roles,
        }}
        currentAdminId={me.id}
      />
    </div>
  );
}
