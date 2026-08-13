import { Eye, KeyRound, MailQuestion, Wallet } from "lucide-react";

import { ErrorState, Stat } from "@/components/ui/primitives";
import { Pagination, sizeHrefFactory } from "@/components/table/Pagination";
import { TableToolbar } from "@/components/table/TableToolbar";
import { Card } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { pageLinks, readPageState, type SearchParams } from "@/lib/table/query";
import type { AdminMe } from "@/lib/permissions";
import { formatNumber, timeAgo } from "@/lib/utils/format";
import { AdminManager, type AdminRow, type Catalogue } from "./AdminManager";
import { NoAccess } from "@/components/shell/NoAccess";
import { pageAccess } from "@/lib/page-access";

export const metadata = { title: "Administrators" };

type RosterSummary = {
  total: number;
  active: number;
  revoked: number;
  pii_view: number;
  finance_adjust: number;
  dormant: number;
  dormant_after_days: number;
  oldest_dormant_seen_at: string | null;
};

type Roster = {
  items: AdminRow[];
  next_cursor: string | null;
  /** Rows matching the current search — the access summary counts everyone. */
  total: number;
  /** Counted over every administrator, never over the page. */
  summary: RosterSummary;
} & Catalogue;

export default async function AdminsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  // Gated on the capability `nav-config` declares for `/platform/admins` — the
  // same declaration that hides this entry in the sidebar, so the two can
  // never disagree. The backend enforces it again regardless.
  const access = await pageAccess("/platform/admins");
  if (!access.allowed) return <NoAccess permission={access.permission} />;


  const params = await searchParams;
  const state = readPageState(params);
  const role = typeof params.role === "string" ? params.role : "";

  const query = new URLSearchParams({ limit: String(state.per) });
  if (state.q) query.set("search", state.q);
  if (role) query.set("role", role);
  if (state.cursor) query.set("cursor", state.cursor);

  let roster: Roster;
  let me: AdminMe;
  try {
    [roster, me] = await Promise.all([
      get<Roster>(`/api/admin/admins?${query.toString()}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load administrators" detail={message} />;
  }

  // Counted on the server, over the whole roster. It used to be counted here
  // from `roster.items`, which was every administrator until this list was
  // paged — at which point "how many people can reveal a national ID" would
  // have quietly become "…on this page", and would have shrunk further the
  // moment somebody typed in the search box. An access review is exactly the
  // screen where a reassuring wrong number is worst.
  const summary = roster.summary;
  const oldest = summary.oldest_dormant_seen_at;

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
            value={formatNumber(summary.active)}
            hint={
              summary.revoked === 0
                ? "Nobody has been revoked"
                : `${formatNumber(summary.revoked)} revoked`
            }
            icon={<KeyRound className="h-4 w-4" />}
          />
          <Stat
            label="Can reveal identity documents"
            value={formatNumber(summary.pii_view)}
            hint="pii.view — every use is audited with a stated reason"
            tone={summary.pii_view > 2 ? "warning" : "neutral"}
            icon={<Eye className="h-4 w-4" />}
          />
          <Stat
            label="Can credit a balance"
            value={formatNumber(summary.finance_adjust)}
            hint="finance.adjust — the only capability that creates money from nothing"
            tone={summary.finance_adjust > 1 ? "warning" : "neutral"}
            icon={<Wallet className="h-4 w-4" />}
          />
          <Stat
            label={`Not seen in ${summary.dormant_after_days} days`}
            value={formatNumber(summary.dormant)}
            hint={
              oldest
                ? `Longest absent since ${timeAgo(oldest)}`
                : "Everyone active has signed in recently"
            }
            tone={summary.dormant > 0 ? "warning" : "neutral"}
            icon={<MailQuestion className="h-4 w-4" />}
          />
        </div>
      </section>

      {/* The catalogue ships with the roster, so this screen can never offer a
          permission the server has dropped, nor miss one it has added. */}
      <TableToolbar
        placeholder="Search administrators by name or email"
        filters={[
          {
            name: "role",
            label: "Filter by role",
            value: role,
            options: [
              { value: "", label: "Any role" },
              ...roster.roles.map((entry) => ({
                value: entry.key,
                label: entry.label,
              })),
            ],
          },
        ]}
      >
      <AdminManager
        admins={roster.items}
        catalogue={{
          permissions: roster.permissions,
          groups: roster.groups,
          roles: roster.roles,
        }}
        currentAdminId={me.id}
      />

      <Card>
        <Pagination
          links={pageLinks({
            pathname: "/platform/admins",
            filters: { q: state.q, role },
            state,
            nextCursor: roster.next_cursor,
            count: roster.items.length,
          })}
          noun="administrators"
          total={roster.total}
          perPage={state.per}
          sizeHref={sizeHrefFactory("/platform/admins", { q: state.q, role })}
          className="border-t-0"
        />
      </Card>
      </TableToolbar>
    </div>
  );
}
