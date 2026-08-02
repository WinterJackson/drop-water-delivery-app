/** F-019 FIX: Converted from JS to TypeScript with proper types */

interface ApiRoute {
  path: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
}

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_BASE_URL ?? "";

const VendorApiRoutes = {
  // --- Auth ---
  Register: {
    path: `${BASE_URL}/api/auth/create_vendor`,
    method: "POST",
  } as const satisfies ApiRoute,
  // --- Stores ---
  GetStores: {
    path: `${BASE_URL}/api/vendor/stores`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Profile ---
  GetProfile: {
    path: `${BASE_URL}/api/vendor/profile`,
    method: "GET",
  } as const satisfies ApiRoute,
  UpdateProfile: {
    path: `${BASE_URL}/api/vendor/profile`,
    method: "PUT",
  } as const satisfies ApiRoute,
  // --- Products ---
  GetProducts: {
    path: `${BASE_URL}/api/vendor/products`,
    method: "GET",
  } as const satisfies ApiRoute,
  CreateProduct: {
    path: `${BASE_URL}/api/vendor/products`,
    method: "POST",
  } as const satisfies ApiRoute,
  UpdateProduct: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/products/${id}`,
    method: "PUT",
  }),
  DeleteProduct: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/products/${id}`,
    method: "DELETE",
  }),
  GetProduct: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/products/${id}`,
    method: "GET",
  }),
  // --- Orders ---
  GetOrders: {
    path: `${BASE_URL}/api/vendor/orders`,
    method: "GET",
  } as const satisfies ApiRoute,
  /**
   * One order with its items, customer and rider.
   *
   * `OrderDetail` used to find its order by scanning the list `GetOrders` had
   * already returned, so anything past the first page rendered "Order not
   * found" — including live orders reached from a search result.
   */
  GetOrder: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/orders/${id}`,
    method: "GET",
  }),
  /**
   * Why an order is parked in `pending_review` or `mismatch_pending` — the
   * rider's stated reason and their photographs. Neither state appeared
   * anywhere in this app before; the order showed a blank pill and the vendor
   * had no way to see what was being reviewed.
   */
  GetOrderReview: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/orders/${id}/review`,
    method: "GET",
  }),
  UpdateOrderStatus: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/orders/${id}/status`,
    method: "PUT",
  }),
  CancelOrder: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/orders/${id}/cancel`,
    method: "PUT",
  }),
  AssignRider: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/orders/${id}/assign-rider`,
    method: "PUT",
  }),
  // --- Uploads ---
  /**
   * Product photos and the store avatar. Replaces an unsigned Cloudinary preset
   * that shipped in the app bundle, where anyone who unzipped the APK could
   * upload arbitrary files to the account. Returns an S3 key, which the backend
   * presigns on the way out.
   */
  UploadImage: {
    path: `${BASE_URL}/api/vendor/upload-image`,
    method: "POST",
  } as const satisfies ApiRoute,
  // --- Wallet summary ---
  /**
   * Balance, float committed to open cash orders, and what is actually
   * withdrawable. The app used to show the raw `wallet_balance`, so a refusal
   * from `POST /api/wallet/withdraw` read as the platform withholding money it
   * had just displayed.
   */
  GetWalletSummary: {
    path: `${BASE_URL}/api/vendor/wallet-summary`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Dashboard ---
  GetDashboard: {
    path: `${BASE_URL}/api/vendor/dashboard`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Payouts ---
  RequestPayout: {
    path: `${BASE_URL}/api/payouts/request`,
    method: "POST",
  } as const satisfies ApiRoute,
  GetPayouts: {
    path: `${BASE_URL}/api/payouts`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Notifications ---
  GetNotifications: {
    path: `${BASE_URL}/api/notifications?user_type=vendor`,
    method: "GET",
  } as const satisfies ApiRoute,
  GetUnreadNotificationCount: {
    path: `${BASE_URL}/api/notifications/unread-count?user_type=vendor`,
    method: "GET",
  } as const satisfies ApiRoute,
  // `user_type` is not cosmetic: the backend resolves the caller's row from the
  // matching table, so without it these three ran against `customer` and either
  // 404'd (no User row for a vendor's clerk_id) or silently matched nothing.
  MarkNotificationRead: {
    path: `${BASE_URL}/api/notifications/read?user_type=vendor`,
    method: "POST",
  } as const satisfies ApiRoute,
  MarkAllNotificationsRead: {
    path: `${BASE_URL}/api/notifications/read-all?user_type=vendor`,
    method: "POST",
  } as const satisfies ApiRoute,
  DeleteNotification: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/notifications/${id}?user_type=vendor`,
    method: "DELETE",
  }),
  // --- Rider Management ---
  GetMyRiders: {
    path: `${BASE_URL}/api/vendor/my-riders`,
    method: "GET",
  } as const satisfies ApiRoute,
  ManageRider: {
    path: `${BASE_URL}/api/vendor/rider-action`,
    method: "PUT",
  } as const satisfies ApiRoute,
  ReceiveBottles: {
    path: `${BASE_URL}/api/vendor/receive-bottles`,
    method: "POST",
  } as const satisfies ApiRoute,
  /**
   * Riders holding this vendor's empties, sourced from the bottle ledger.
   *
   * Not the same as the rider registry: radar dispatch lets a rider take an order
   * from a vendor they never registered with, so they owe bottles while having no
   * registry row at all. Reconciliation must read from here or those riders — and
   * their bottles — stay invisible.
   */
  BottleDebtors: {
    path: `${BASE_URL}/api/vendor/bottle-debtors`,
    method: "GET",
  } as const satisfies ApiRoute,
  BottleLedger: (limit = 50, offset = 0): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/bottle-ledger?limit=${limit}&offset=${offset}`,
    method: "GET",
  }),
  // --- Account ---
  DeleteAccount: {
    path: `${BASE_URL}/api/auth/delete_account`,
    method: "DELETE",
  } as const satisfies ApiRoute,
  // --- Wallet ---
  WalletTopUp: {
    path: `${BASE_URL}/api/wallet/top-up`,
    method: "POST",
  } as const satisfies ApiRoute,
  WalletWithdraw: {
    path: `${BASE_URL}/api/wallet/withdraw`,
    method: "POST",
  } as const satisfies ApiRoute,
  GetTransactions: {
    path: `${BASE_URL}/api/wallet/transactions`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Staff Management ---
  /**
   * Staff are `Vendor_Staff` rows now, not `Vendor.staff_clerk_id`.
   *
   * That column held one id and was UNIQUE platform-wide, so a store could have
   * one staff member, adding a second silently replaced the first, and one
   * person could work for exactly one store on the whole platform — behind a
   * screen called "Manage Staff". Access was also all-or-nothing: handing
   * someone the till handed them the catalogue and the wallet balance.
   */
  GetStaff: {
    path: `${BASE_URL}/api/vendor/staff`,
    method: "GET",
  } as const satisfies ApiRoute,
  InviteStaff: {
    path: `${BASE_URL}/api/vendor/staff`,
    method: "POST",
  } as const satisfies ApiRoute,
  UpdateStaffPermissions: (staffId: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/staff/${staffId}`,
    method: "PATCH",
  }),
  RevokeStaff: (staffId: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/staff/${staffId}`,
    method: "DELETE",
  }),
  // --- Support ---
  //
  // `user_type=vendor` names the account being acted on, exactly as the
  // notification routes do. The *store* comes from the `X-Store-Id` header the
  // API client already sends, so an owner with two branches files against the
  // one they are looking at — and a staff member, who holds no `clerk_id` on any
  // Vendor row, resolves through the same store membership every other vendor
  // route uses rather than being told they have no account.
  CreateSupportTicket: {
    path: `${BASE_URL}/api/support/tickets?user_type=vendor`,
    method: "POST",
  } as const satisfies ApiRoute,
  GetSupportTickets: {
    path: `${BASE_URL}/api/support/tickets?user_type=vendor`,
    method: "GET",
  } as const satisfies ApiRoute,
  GetSupportTicket: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/support/tickets/${id}?user_type=vendor`,
    method: "GET",
  }),
  ReplyToSupportTicket: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/support/tickets/${id}/reply?user_type=vendor`,
    method: "POST",
  }),
  SupportCategories: {
    path: `${BASE_URL}/api/support/categories`,
    method: "GET",
  } as const satisfies ApiRoute,
};

export default VendorApiRoutes;
