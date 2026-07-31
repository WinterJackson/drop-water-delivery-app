/** F-019 FIX: Converted from JS to TypeScript with proper types */

interface ApiRoute {
  path: string;
  method: "GET" | "POST" | "PUT" | "DELETE";
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
  AssignStaff: (email: string): ApiRoute => ({
    path: `${BASE_URL}/api/vendor/staff?email=${encodeURIComponent(email)}`,
    method: "PUT",
  }),
};

export default VendorApiRoutes;
