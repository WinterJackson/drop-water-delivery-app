const BASE_URL = process.env.EXPO_PUBLIC_BACKEND_BASE_URL || "";

/**
 * The single place backend paths are declared.
 *
 * `BackendAPI/tests/test_route_contract.py` parses this file and asserts every
 * path resolves against the live FastAPI route table, so a typo here fails CI
 * instead of shipping as a 404 on a user action. Five such 404s were found in the
 * Phase 1 audit — including "Cancel Order", which could never have worked.
 */

// Legacy export kept for screens not yet migrated to the typed ROUTES table.
export const ApiRoutes = {
    // Auth & Profile
    CreateNewUser: { path: `${BASE_URL}/api/auth/create_user`, method: "POST" },
    GetUserDetails: { path: `${BASE_URL}/api/auth/get_user_details`, method: "GET" },
    UpdateProfilePic: { path: `${BASE_URL}/api/auth/update_profile_pic`, method: "POST" },
    UpdateUserLocation: { path: `${BASE_URL}/api/auth/update_user_location`, method: "POST" },
    RevokeUserLocation: { path: `${BASE_URL}/api/auth/revoke_user_location`, method: "POST" },
    UpdateUser: { path: `${BASE_URL}/api/auth/update_user`, method: "PUT" },
    DeleteAccount: { path: `${BASE_URL}/api/auth/delete_account`, method: "DELETE" },

    // Vendors
    AllVendors: { path: `${BASE_URL}/api/vendors`, method: "GET" },
    NearByVendors: { path: `${BASE_URL}/api/nearby_vendors`, method: "GET" },
    TopRatedVendors: { path: `${BASE_URL}/api/top_rated_vendors`, method: "GET" },
    VendorShopDetails: { path: `${BASE_URL}/api/vendor_details_and_products`, method: "POST" },
    VendorsByType: { path: `${BASE_URL}/api/vendor_by_type`, method: "POST" },
    SearchVendors: { path: `${BASE_URL}/api/search/vendors`, method: "GET" },

    // Products
    TopBrandsVendors: { path: `${BASE_URL}/api/get_top_brands`, method: "GET" },
    ProductDetails: { path: `${BASE_URL}/api/get_product`, method: "POST" },
    ProductsWithOffer: { path: `${BASE_URL}/api/products_with_discount`, method: "GET" },
    RandomPaginatedProducts: { path: `${BASE_URL}/api/random_paginated_products`, method: "POST" },

    // Search
    Search: { path: `${BASE_URL}/api/search`, method: "GET" },

    // Cart
    AddToCart: { path: `${BASE_URL}/api/cart/add_to_cart`, method: "POST" },
    GetCart: { path: `${BASE_URL}/api/cart/get_cart`, method: "GET" },
    GetDetailedCart: { path: `${BASE_URL}/api/cart/get_detailed_cart`, method: "GET" },
    ChangeCartItemQuantity: { path: `${BASE_URL}/api/cart/change_cart_item_quantity`, method: "POST" },
    DeleteCartItem: { path: `${BASE_URL}/api/cart/delete_cart_item`, method: "POST" },
    CartQuote: { path: `${BASE_URL}/api/cart/quote`, method: "POST" },
    Checkout: { path: `${BASE_URL}/api/cart/mpesa_payment`, method: "POST" },
    ConfirmPayment: { path: `${BASE_URL}/api/cart/confirm_payment`, method: "POST" },

    // Orders
    GetOrders: { path: `${BASE_URL}/api/cart/get_orders`, method: "GET" },
    // Order-scoped actions live under /api/cart/orders/{id}/… — see ROUTES below.
    CancelOrder: (id: string) => ({ path: `${BASE_URL}/api/cart/orders/${id}/cancel`, method: "PUT" }),

    // Reviews
    SubmitReview: { path: `${BASE_URL}/api/reviews`, method: "POST" },

    // Favourites
    GetFavorites: { path: `${BASE_URL}/api/favorites`, method: "GET" },
    AddFavorite: { path: `${BASE_URL}/api/favorites/add`, method: "POST" },
    RemoveFavorite: { path: `${BASE_URL}/api/favorites/remove`, method: "POST" },

    // Notifications
    GetNotifications: { path: `${BASE_URL}/api/notifications`, method: "GET" },
    MarkNotificationRead: { path: `${BASE_URL}/api/notifications/read`, method: "POST" },
    MarkAllNotificationsRead: { path: `${BASE_URL}/api/notifications/read-all`, method: "POST" },
    UnreadCount: { path: `${BASE_URL}/api/notifications/unread-count`, method: "GET" },
    DeleteNotification: (id: string) => ({ path: `${BASE_URL}/api/notifications/${id}`, method: "DELETE" }),

    // Push Token
    RegisterPushToken: { path: `${BASE_URL}/api/auth/push-token`, method: "POST" },
    ClearPushToken: { path: `${BASE_URL}/api/auth/push-token`, method: "DELETE" },

    // Saved Locations
    GetSavedLocations: { path: `${BASE_URL}/api/auth/saved-locations`, method: "GET" },
    CreateSavedLocation: { path: `${BASE_URL}/api/auth/saved-locations`, method: "POST" },
    UpdateSavedLocation: (id: string) => ({ path: `${BASE_URL}/api/auth/saved-locations/${id}`, method: "PUT" }),
    DeleteSavedLocation: (id: string) => ({ path: `${BASE_URL}/api/auth/saved-locations/${id}`, method: "DELETE" }),
    UseSavedLocation: (id: string) => ({ path: `${BASE_URL}/api/auth/saved-locations/${id}/use`, method: "POST" }),
};

// Strictly typed routes for React Query
export const ROUTES = {
    // Auth
    CREATE_USER: `${BASE_URL}/api/auth/create_user`,
    GET_USER_DETAILS: `${BASE_URL}/api/auth/get_user_details`,
    UPDATE_PROFILE_PIC: `${BASE_URL}/api/auth/update_profile_pic`,
    UPDATE_LOCATION: `${BASE_URL}/api/auth/update_user_location`,
    REGISTER_PUSH_TOKEN: `${BASE_URL}/api/auth/push-token`,
    CLEAR_PUSH_TOKEN: `${BASE_URL}/api/auth/push-token`,
    UPDATE_USER: `${BASE_URL}/api/auth/update_user`,
    DELETE_ACCOUNT: `${BASE_URL}/api/auth/delete_account`,
    GET_PROFILE_STATUS: (appType: string) => `${BASE_URL}/api/auth/profile-status?app_type=${appType}`,

    // Vendors
    GET_VENDORS: `${BASE_URL}/api/vendors`,
    GET_VENDOR_DIRECTORY: `${BASE_URL}/api/vendors/directory`,
    GET_NEARBY_VENDORS: `${BASE_URL}/api/nearby_vendors`,
    GET_TOP_RATED_VENDORS: `${BASE_URL}/api/top_rated_vendors`,
    GET_VENDOR_DETAILS: `${BASE_URL}/api/vendor_details_and_products`,
    GET_VENDORS_BY_TYPE: `${BASE_URL}/api/vendor_by_type`,
    SEARCH_VENDORS: `${BASE_URL}/api/search/vendors`,

    // Products
    GET_TOP_BRAND_VENDORS: `${BASE_URL}/api/get_top_brands`,
    GET_PRODUCT_DETAILS: `${BASE_URL}/api/get_product`,
    GET_PRODUCTS_WITH_OFFER: `${BASE_URL}/api/products_with_discount`,
    GET_PAGINATED_PRODUCTS: `${BASE_URL}/api/random_paginated_products`,

    // Search
    SEARCH: `${BASE_URL}/api/search`,

    // Cart
    ADD_TO_CART: `${BASE_URL}/api/cart/add_to_cart`,
    GET_CART: `${BASE_URL}/api/cart/get_cart`,
    GET_DETAILED_CART: `${BASE_URL}/api/cart/get_detailed_cart`,
    CHANGE_CART_QTY: `${BASE_URL}/api/cart/change_cart_item_quantity`,
    DELETE_CART_ITEM: `${BASE_URL}/api/cart/delete_cart_item`,
    // Authoritative server-side price for the current cart. The client renders
    // this verbatim rather than recomputing the total locally.
    CART_QUOTE: `${BASE_URL}/api/cart/quote`,
    CHECKOUT: `${BASE_URL}/api/cart/mpesa_payment`,
    CONFIRM_PAYMENT: `${BASE_URL}/api/cart/confirm_payment`,
    GET_DELIVERY_FEE: `${BASE_URL}/api/delivery-fee`,

    // Orders
    GET_ORDERS: `${BASE_URL}/api/cart/get_orders`,
    GET_ACTIVE_ORDER: `${BASE_URL}/api/cart/orders/active`,
    GET_LAST_COMPLETED_ORDER: `${BASE_URL}/api/cart/orders/last-completed`,
    // These three were previously built inline as `/api/orders/{id}/…`, which the
    // backend has never served — cancellation and mismatch resolution 404'd every
    // time. The real prefix is /api/cart.
    CANCEL_ORDER: (orderId: string) => `${BASE_URL}/api/cart/orders/${orderId}/cancel`,
    RESOLVE_MISMATCH: (orderId: string) => `${BASE_URL}/api/cart/orders/${orderId}/resolve-mismatch`,
    ORDER_TRACKING_LOGS: (orderId: string) => `${BASE_URL}/api/cart/orders/${orderId}/tracking-logs`,
    GET_PAYMENT_HISTORY: `${BASE_URL}/api/payments/history`,
    ORDER_CONTACTS: (orderId: string) => `${BASE_URL}/api/contacts/${orderId}`,

    // Favourites
    GET_FAVORITES: `${BASE_URL}/api/favorites`,
    ADD_FAVORITE: `${BASE_URL}/api/favorites/add`,
    REMOVE_FAVORITE: `${BASE_URL}/api/favorites/remove`,

    // Notifications
    GET_NOTIFICATIONS: `${BASE_URL}/api/notifications`,
    MARK_READ: `${BASE_URL}/api/notifications/read`,
    MARK_ALL_READ: `${BASE_URL}/api/notifications/read-all`,
    UNREAD_COUNT: `${BASE_URL}/api/notifications/unread-count`,
    DELETE_NOTIFICATION: (id: string) => `${BASE_URL}/api/notifications/${id}`,

    // Reviews
    SUBMIT_REVIEW: `${BASE_URL}/api/reviews`,
    TARGET_REVIEWS: (targetType: string, targetId: string) => `${BASE_URL}/api/reviews/target/${targetType}/${targetId}`,
    RATING_SUMMARY: (targetType: string, targetId: string) => `${BASE_URL}/api/reviews/summary/${targetType}/${targetId}`,

    // Tracking
    // Customer-scoped: the previous `/api/rider/...` path is guarded by
    // `get_current_rider` and returned 403 for every customer.
    RIDER_LOCATION: (orderId: string) => `${BASE_URL}/api/cart/orders/${orderId}/rider-location`,

    // Categories (Kenya market)
    GET_CATEGORIES: `${BASE_URL}/api/categories`,
    GET_PRODUCTS_BY_CATEGORY: `${BASE_URL}/api/products-by-category`,

    // Vendor Favourites
    GET_VENDOR_FAVORITES: `${BASE_URL}/api/vendor-favorites`,
    ADD_VENDOR_FAVORITE: `${BASE_URL}/api/vendor-favorites/add`,
    REMOVE_VENDOR_FAVORITE: `${BASE_URL}/api/vendor-favorites/remove`,
    CHECK_VENDOR_FAVORITE: (vendorId: string) => `${BASE_URL}/api/vendor-favorites/check/${vendorId}`,
    // Path segments were inverted (`/last-order/{id}` instead of `/{id}/last-order`).
    LAST_ORDER_FROM_VENDOR: (vendorId: string) => `${BASE_URL}/api/vendor-favorites/${vendorId}/last-order`,

    // Saved Locations
    GET_SAVED_LOCATIONS: `${BASE_URL}/api/auth/saved-locations`,
    CREATE_SAVED_LOCATION: `${BASE_URL}/api/auth/saved-locations`,
    UPDATE_SAVED_LOCATION: (id: string) => `${BASE_URL}/api/auth/saved-locations/${id}`,
    DELETE_SAVED_LOCATION: (id: string) => `${BASE_URL}/api/auth/saved-locations/${id}`,
    USE_SAVED_LOCATION: (id: string) => `${BASE_URL}/api/auth/saved-locations/${id}/use`,

    // Wallet
    WALLET_TOP_UP: `${BASE_URL}/api/wallet/top-up`,
    WALLET_WITHDRAW: `${BASE_URL}/api/wallet/withdraw`,
    GET_TRANSACTIONS: `${BASE_URL}/api/wallet/transactions`,

    // Maps — Google web services, proxied.
    // The apps' Maps keys are SDK-restricted and cannot call Places; the server
    // holds the only key that can. See docs/maps-architecture.md.
    PLACES_AUTOCOMPLETE: `${BASE_URL}/api/maps/places/autocomplete`,
    PLACE_DETAILS: `${BASE_URL}/api/maps/places/details`,

    // Misc
    APP_VERSION: `${BASE_URL}/api/app-version`,
} as const;

export default ApiRoutes;
