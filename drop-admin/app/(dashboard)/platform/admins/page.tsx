import { ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import type { AdminMe } from "@/lib/permissions";
import { AdminManager, type AdminRow, type Catalogue } from "./AdminManager";

export const metadata = { title: "Administrators" };

type Roster = { items: AdminRow[] } & Catalogue;

export default async function AdminsPage() {
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Administrators</h1>
        <p className="mt-1 text-sm text-muted">
          Who can use this console, and exactly what each of them can do.
        </p>
      </div>

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
