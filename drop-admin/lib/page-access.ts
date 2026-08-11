import "server-only";

import { NAV_ITEMS } from "@/components/shell/nav-config";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe, type Permission } from "@/lib/permissions";

/**
 * Whether the signed-in administrator may open this page, and who they are.
 *
 * **This is not the access control.** Every route is enforced again by
 * `require_admin(...)` on the backend, and that check is the only one that
 * decides anything — a caller who edits the JS still gets a 403 from the API.
 * What this fixes is the *experience* of not having a capability: a dozen pages
 * rendered their heading, fired their fetch, and showed "Couldn't load — 403
 * Forbidden", which reads as the console being broken rather than as a
 * permission the caller does not hold.
 *
 * The permission is read from `nav-config`, not passed in. Every destination
 * already declares one there so the sidebar can hide it, and a page repeating
 * that declaration is a second copy free to disagree — the exact failure the
 * nav config exists to prevent, one layer down. A page hidden from the sidebar
 * and openable by URL is the same bug as a page shown and then refused.
 */
export type PageAccess =
  | { allowed: true; me: AdminMe; permission: Permission | null }
  | { allowed: false; me: AdminMe | null; permission: Permission };

/** The permission `nav-config` declares for a path, if it declares one. */
export function permissionForPath(pathname: string): Permission | undefined {
  // Longest match wins: `/analytics/growth` must not resolve to `/analytics`.
  const match = NAV_ITEMS.filter((item) => item.href === pathname).at(0);
  return match?.permission;
}

/**
 * Fetch the caller and check them against this page's declared permission.
 *
 * `me` failing to load is **not** treated as permission. It returns
 * `allowed: false`, which renders the refusal rather than the page — the same
 * direction the backend's own gates fail, and the opposite of the vendor app's
 * `CapabilityGate`, which fails open because it only decides whether to show a
 * form the server refuses anyway. Here, failing open would mean firing a page's
 * worth of queries on behalf of somebody we could not identify.
 */
export async function pageAccess(pathname: string): Promise<PageAccess> {
  const permission = permissionForPath(pathname) ?? null;

  let me: AdminMe | null = null;
  try {
    me = await get<AdminMe>("/api/admin/me");
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    me = null;
  }

  if (!me) {
    return { allowed: false, me: null, permission: permission ?? PERMISSIONS.analyticsRead };
  }
  if (permission && !can(me, permission)) {
    return { allowed: false, me, permission };
  }
  return { allowed: true, me, permission };
}
