/** F-019 FIX: Converted from JS to TypeScript with proper types */

interface ApiRoute {
  path: string;
  method: "GET" | "POST" | "PUT" | "DELETE";
}

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_BASE_URL ?? "";

// An unset base URL turns every path below into a relative one, which `fetch`
// rejects in React Native with a message that names neither the variable nor the
// cause. Say it once, plainly, at startup.
if (__DEV__ && !BASE_URL) {
  console.warn(
    "[API] EXPO_PUBLIC_BACKEND_BASE_URL is not set — every request will fail. " +
      "Copy .env.example to .env and set it, then restart the bundler with --clear."
  );
}

const RiderApiRoutes = {
  // --- Auth ---
  Register: {
    path: `${BASE_URL}/api/auth/create_rider`,
    method: "POST",
  } as const satisfies ApiRoute,
  // --- KYC ---
  /** Verification status + operational status. Drives the `(screens)` gate. */
  KycStatus: {
    path: `${BASE_URL}/api/deliverer/kyc/status`,
    method: "GET",
  } as const satisfies ApiRoute,
  /** Multipart upload of ID documents; moves the rider to `pending`. */
  KycUpload: {
    path: `${BASE_URL}/api/deliverer/kyc/upload`,
    method: "POST",
  } as const satisfies ApiRoute,
  // --- Profile ---
  GetProfile: {
    path: `${BASE_URL}/api/rider/profile`,
    method: "GET",
  } as const satisfies ApiRoute,
  UpdateProfile: {
    path: `${BASE_URL}/api/rider/profile`,
    method: "PUT",
  } as const satisfies ApiRoute,
  // --- Location ---
  UpdateLocation: {
    path: `${BASE_URL}/api/rider/location`,
    method: "PUT",
  } as const satisfies ApiRoute,
  /**
   * Batched position reports from the background location task.
   *
   * Distinct from `UpdateLocation`, which is the foreground single-point write.
   * This one is the durable path: it survives a backgrounded app and patchy
   * coverage, which the WebSocket cannot. See `services/locationTracking.ts`.
   */
  LocationPing: {
    path: `${BASE_URL}/api/rider/location-ping`,
    method: "POST",
  } as const satisfies ApiRoute,
  // --- Availability ---
  ToggleAvailability: {
    path: `${BASE_URL}/api/rider/availability`,
    method: "PUT",
  } as const satisfies ApiRoute,
  // --- Orders ---
  GetOrders: (status?: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/orders${status ? `?status=${status}` : ''}`,
    method: "GET",
  }),
  /**
   * The same endpoint with its paging arguments supplied.
   *
   * `GET /api/rider/orders` has always accepted `skip`/`limit` (default 50).
   * `GetOrders` passes neither, so every history screen silently stopped at the
   * 50 most recent deliveries with no "load more" and no empty state — it read
   * as data loss rather than a page boundary.
   */
  GetOrdersPaged: (status: string | undefined, skip: number, limit: number): ApiRoute => {
    const params = new URLSearchParams({ skip: String(skip), limit: String(limit) });
    if (status) params.append("status", status);
    return {
      path: `${BASE_URL}/api/rider/orders?${params.toString()}`,
      method: "GET",
    };
  },
  UpdateDeliveryStatus: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/orders/${id}/status`,
    method: "PUT",
  }),
  TripRadar: {
    path: `${BASE_URL}/api/rider/trip-radar`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Earnings ---
  GetEarnings: {
    path: `${BASE_URL}/api/rider/earnings`,
    method: "GET",
  } as const satisfies ApiRoute,
  GetReviews: {
    path: `${BASE_URL}/api/rider/reviews`,
    method: "GET",
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
  // --- Notifications ---
  GetNotifications: {
    path: `${BASE_URL}/api/notifications?user_type=rider`,
    method: "GET",
  } as const satisfies ApiRoute,
  GetUnreadNotificationCount: {
    path: `${BASE_URL}/api/notifications/unread-count?user_type=rider`,
    method: "GET",
  } as const satisfies ApiRoute,
  MarkNotificationRead: {
    path: `${BASE_URL}/api/notifications/read?user_type=rider`,
    method: "POST",
  } as const satisfies ApiRoute,
  MarkAllNotificationsRead: {
    path: `${BASE_URL}/api/notifications/read-all?user_type=rider`,
    method: "POST",
  } as const satisfies ApiRoute,
  DeleteNotification: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/notifications/${id}?user_type=rider`,
    method: "DELETE",
  }),
  /** Phone numbers of the other parties, while the order is still in flight. */
  OrderContacts: (orderId: string): ApiRoute => ({
    path: `${BASE_URL}/api/contacts/${orderId}`,
    method: "GET",
  }),
  // --- Order Actions ---
  RejectDelivery: (orderId: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/orders/${orderId}/reject`,
    method: "PUT",
  }),
  CancelOrder: (orderId: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/orders/${orderId}/cancel`,
    method: "PUT",
  }),
  ReportMismatch: (orderId: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/orders/${orderId}/mismatch`,
    method: "POST",
  }),
  ReportBottleRejection: (orderId: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/orders/${orderId}/bottle-rejection`,
    method: "POST",
  }),
  AcceptDelivery: (orderId: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/orders/${orderId}/accept`,
    method: "POST",
  }),
  // --- Vendor Registry ---
  DiscoverVendors: (lat: number, lng: number, searchQuery: string = ""): ApiRoute => {
    const params = new URLSearchParams();
    params.append('lat', lat.toString());
    params.append('lng', lng.toString());
    if (searchQuery) params.append('search_query', searchQuery);
    
    return {
      path: `${BASE_URL}/api/rider/discover-vendors?${params.toString()}`,
      method: "GET",
    };
  },
  RegisteredVendors: (searchQuery: string = ""): ApiRoute => {
    const params = new URLSearchParams();
    if (searchQuery) params.append('search_query', searchQuery);
    
    return {
      path: `${BASE_URL}/api/rider/registered-vendors${searchQuery ? '?' + params.toString() : ''}`,
      method: "GET",
    };
  },
  WithdrawApplication: (vendorId: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/vendor-application/${vendorId}`,
    method: "DELETE",
  }),
  ApplyVendor: {
    path: `${BASE_URL}/api/rider/apply-vendor`,
    method: "POST",
  } as const satisfies ApiRoute,
  /**
   * Balance, float committed to open cash orders, and what may actually be
   * withdrawn. `wallet_balance` alone is misleading: a rider carrying cash orders
   * holds money that settles the vendor and platform cuts on delivery.
   */
  // Whether this rider may take cash orders, and how far off they are. Every
  // threshold comes back measured against the requirement, so the app never
  // states a number of its own — the same rule the withdrawal terms follow.
  CashEligibility: {
    path: `${BASE_URL}/api/rider/cash-eligibility`,
    method: "GET",
  } as const satisfies ApiRoute,
  WalletSummary: {
    path: `${BASE_URL}/api/rider/wallet-summary`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Bottle debt ---
  /** Empties this rider is holding, grouped by vendor. */
  BottleDebt: {
    path: `${BASE_URL}/api/rider/bottle-debt`,
    method: "GET",
  } as const satisfies ApiRoute,
  /** This rider's bottle movement history (accruals and confirmed returns). */
  BottleLedger: (limit = 50, offset = 0): ApiRoute => ({
    path: `${BASE_URL}/api/rider/bottle-ledger?limit=${limit}&offset=${offset}`,
    method: "GET",
  }),
  // --- Deposit collections ---
  // Collecting a customer's bottles so their deposit can be returned. The
  // rider's confirmation is one of the two counts that release the money, and
  // it also makes them the holder of those bottles on the ledger above — which
  // is why this needs a destination store, not just a number.
  /** Unclaimed collections, plus anything this rider has already taken on. */
  BottleCollections: {
    path: `${BASE_URL}/api/rider/bottle-returns`,
    method: "GET",
  } as const satisfies ApiRoute,
  ClaimBottleCollection: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/bottle-returns/${id}/claim`,
    method: "POST",
  }),
  ConfirmBottleCollection: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/rider/bottle-returns/${id}/confirm`,
    method: "POST",
  }),
  // --- Maps ---
  /**
   * Road route between two points, proxied by the backend.
   *
   * Never call Google Directions from the client: the shipped Maps key is
   * restricted to the Maps SDK for this package, so a direct call is rejected,
   * and a key that *would* work from JS could be lifted straight out of the APK.
   * The server holds an IP-restricted key and caches identical legs.
   */
  Directions: (
    originLat: number,
    originLng: number,
    destLat: number,
    destLng: number,
    mode: "driving" | "walking" | "bicycling" | "two_wheeler" = "driving"
  ): ApiRoute => {
    const params = new URLSearchParams({
      origin_lat: String(originLat),
      origin_lng: String(originLng),
      dest_lat: String(destLat),
      dest_lng: String(destLng),
      mode,
    });
    return {
      path: `${BASE_URL}/api/maps/directions?${params.toString()}`,
      method: "GET",
    };
  },
  // Maps — Google web services, proxied. The app's Maps key is SDK-restricted
  // and cannot call Places; the server holds the only key that can.
  PlacesAutocomplete: {
    path: `${BASE_URL}/api/maps/places/autocomplete`,
    method: "GET",
  } as const satisfies ApiRoute,
  PlaceDetails: {
    path: `${BASE_URL}/api/maps/places/details`,
    method: "GET",
  } as const satisfies ApiRoute,
  /** Multipart proof-of-delivery / bottle-rejection photo. Returns an S3 key. */
  UploadProof: {
    path: `${BASE_URL}/api/rider/upload_proof`,
    method: "POST",
  } as const satisfies ApiRoute,
  // --- Push ---
  /** Register this device's Expo push token against the signed-in rider. */
  RegisterPushToken: {
    path: `${BASE_URL}/api/auth/push-token`,
    method: "POST",
  } as const satisfies ApiRoute,
  /** Detach it. Must run *before* sign-out — the endpoint is authenticated. */
  /**
   * `?app_type=rider` is not optional. The endpoint defaults to `customer`,
   * looks up a `User` row by this clerk id, finds none — a rider has no `User`
   * row — clears nothing, commits and answers 200. So the call *looked* like it
   * worked while `Deliverer.push_token` stayed registered, and on a shared
   * device the next rider to sign in kept receiving the previous rider's
   * delivery offers. The vendor app hit the same default and fixed it; this
   * copy stayed broken.
   */
  DeletePushToken: {
    path: `${BASE_URL}/api/auth/push-token?app_type=rider`,
    method: "DELETE",
  } as const satisfies ApiRoute,
  /** Whether this Clerk account already has a rider profile. */
  ProfileStatus: {
    path: `${BASE_URL}/api/auth/profile-status?app_type=rider`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Support ---
  //
  // `user_type` is a query parameter on every one of these, exactly as it is on
  // the notification routes and for the same reason: one Clerk identity can be
  // a rider *and* a customer, so the account being acted on is stated rather
  // than guessed. The server resolves it by `clerk_id` and will only ever
  // return tickets that account raised.
  /** Raise a ticket. The requester comes from the token, never from the body. */
  CreateSupportTicket: {
    path: `${BASE_URL}/api/support/tickets?user_type=rider`,
    method: "POST",
  } as const satisfies ApiRoute,
  /** Every ticket this rider has raised, newest first. */
  GetSupportTickets: {
    path: `${BASE_URL}/api/support/tickets?user_type=rider`,
    method: "GET",
  } as const satisfies ApiRoute,
  /** One ticket and its thread. Internal notes are stripped by the server. */
  GetSupportTicket: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/support/tickets/${id}?user_type=rider`,
    method: "GET",
  }),
  /** A follow-up. Reopens the ticket if support had marked it resolved. */
  ReplyToSupportTicket: (id: string): ApiRoute => ({
    path: `${BASE_URL}/api/support/tickets/${id}/reply?user_type=rider`,
    method: "POST",
  }),
  SupportCategories: {
    path: `${BASE_URL}/api/support/categories`,
    method: "GET",
  } as const satisfies ApiRoute,
  // --- Account ---
  DeleteAccount: {
    path: `${BASE_URL}/api/auth/delete_account`,
    method: "DELETE",
  } as const satisfies ApiRoute,
};

/**
 * The socket origin, derived from the one BASE_URL.
 *
 * `useWebSocket` used to derive this itself, by splitting a REST path on
 * `/api/` and calling `.replace('http', 'ws')` unanchored. Both halves are
 * traps: a base URL that stops containing `/api/` silently yields the whole
 * REST URL, and the unanchored replace rewrites the first `http` anywhere in
 * the string. One declaration, next to the paths it shares an origin with.
 */
export const WS_BASE_URL =
  process.env.EXPO_PUBLIC_WS_BASE_URL || BASE_URL.replace(/^http/, "ws");

export default RiderApiRoutes;
