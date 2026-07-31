/** F-019 FIX: Converted from JS to TypeScript with proper types */

interface ApiRoute {
  path: string;
  method: "GET" | "POST" | "PUT" | "DELETE";
}

const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_BASE_URL ?? "";

const RiderApiRoutes = {
  // --- Auth ---
  Register: {
    path: `${BASE_URL}/api/auth/create_rider`,
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
  // --- Account ---
  DeleteAccount: {
    path: `${BASE_URL}/api/auth/delete_account`,
    method: "DELETE",
  } as const satisfies ApiRoute,
};

export default RiderApiRoutes;
