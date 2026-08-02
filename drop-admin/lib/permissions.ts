/**
 * Capability names, mirrored from `BackendAPI/models/admin_model.py`.
 *
 * These exist so navigation and controls can be hidden from someone who cannot
 * use them. **Hiding is courtesy, not access control** — every one of these is
 * enforced again by `require_admin` on the server, and the server is the only
 * thing that decides. A build of this app with the checks deleted would gain
 * nothing.
 *
 * `drop-admin/lib/__tests__` is not where drift is caught: the backend ships
 * the authoritative list on `/api/admin/me` and `/api/admin/admins`, and the
 * roster screen renders from that response rather than from this file. This
 * constant is only for the places where a route has to decide before any data
 * has loaded.
 */

export const PERMISSIONS = {
  ridersRead: "riders.read",
  ridersKycReview: "riders.kyc_review",
  ridersSuspend: "riders.suspend",

  vendorsRead: "vendors.read",
  vendorsApprove: "vendors.approve",
  vendorsSuspend: "vendors.suspend",

  customersRead: "customers.read",
  customersSuspend: "customers.suspend",
  customersErase: "customers.erase",

  ordersRead: "orders.read",
  ordersIntervene: "orders.intervene",

  financeRead: "finance.read",
  financePayoutApprove: "finance.payout_approve",
  financeRefundApprove: "finance.refund_approve",

  disputesRead: "disputes.read",
  disputesResolve: "disputes.resolve",

  supportRead: "support.read",
  supportRespond: "support.respond",
  broadcastSend: "broadcast.send",

  //: Crediting or debiting a wallet by hand. Held by super admin alone — it is
  //: the one action with no upstream obligation to check it against.
  financeAdjust: "finance.adjust",

  //: Seeing where riders, vendors and demand actually are.
  geoView: "geo.view",

  analyticsRead: "analytics.read",
  piiView: "pii.view",
  dataExport: "data.export",
  adminsManage: "admins.manage",
  settingsManage: "settings.manage",
} as const;

export type Permission = (typeof PERMISSIONS)[keyof typeof PERMISSIONS];

export type AdminMe = {
  id: string;
  email: string;
  name: string | null;
  role: string;
  permissions: string[];
  permission_labels: Record<string, string>;
};

export function can(me: Pick<AdminMe, "permissions"> | null, permission: Permission): boolean {
  return Boolean(me?.permissions.includes(permission));
}

/** True when the admin holds *any* of these — for a nav section with several children. */
export function canAny(me: Pick<AdminMe, "permissions"> | null, ...permissions: Permission[]): boolean {
  return permissions.some((p) => can(me, p));
}
