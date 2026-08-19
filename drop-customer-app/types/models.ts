export interface BasicUser {
  id: string;
  clerk_id: string | null;
  full_name: string | null;
  email: string;
  phone_number: string | null;
  profile_pic: string | null;
  lat: number | null;
  lng: number | null;
  location_address: string | null;
  bottle_purchased_at: string | null;
  bottle_refill_count: number;
  wallet_balance: string;
  /**
   * An unpaid balance carried from an earlier order — most often a staircase
   * surcharge agreed after an M-Pesa order had already been paid.
   *
   * **Not** "any amount above zero blocks checkout", which is what this said
   * and what the platform used to do. It is now charged on the next order as
   * `debt_settlement` and cleared when that order is created; only at
   * `max_customer_debt_before_block` does the platform stop extending credit.
   * The old behaviour locked a customer out permanently over KSH 30.
   */
  debt_balance?: string;
  /**
   * What the platform owes against bottles this customer is holding, and how
   * many. `customer_bottle_service` moves the two together, never one alone.
   */
  bottle_deposit_balance?: string;
  bottles_held?: number;
  /** False until the first-order 30% deposit discount has been consumed. */
  has_used_welcome_offer?: boolean;
  floor_level: number;
  has_elevator: boolean;
  preferences: Record<string, unknown> | null;
  /**
   * Free-form JSONB on the backend. In practice each entry is
   * `{ type, phone, isDefault }`, but it is not schema-enforced, so callers must
   * treat entries defensively. Typed as `string[]` before, which did not match
   * anything the app actually stores.
   */
  payment_methods: PaymentMethodEntry[] | null;
}

export interface PaymentMethodEntry {
  type?: string;
  phone?: string;
  isDefault?: boolean;
  [key: string]: unknown;
}

export interface CartProduct {
  id: string;
  vendor_id: string;
  name: string;
  image_url: string;
  price: string;
  discount: string;
  capacity: number;
  weight_kg: number;
  stock: number;
  stock_quantity: number;
  is_available: boolean;
  unit: string | null;
  description: string | null;
  /** Embedded by `ProductFull` — the pickup point for delivery-fee previews. */
  vendor?: {
    id: string;
    business_name: string;
    vendor_type: string | null;
    location_address: string | null;
    lat: number | null;
    lng: number | null;
    rating: number | null;
    profile_pic: string | null;
  } | null;
}

export interface CartItem {
  id: string;
  cart_id: string;
  vendor_id: string;
  product_id: string;
  quantity: number;
  price: string;
  product: CartProduct | null;
}

/**
 * `GET /api/cart/get_detailed_cart`.
 *
 * Carries the platform's rule metadata (`moq_kg`, `max_units`, …) so the cart
 * screen can show limits up front rather than letting the customer discover them
 * as a checkout error.
 */
export interface DetailedCart {
  id: string;
  customer_id: string;
  items_count: number;
  total_amount: string;
  cart_item: CartItem[];
  service_fee: string;
  welcome_discount_amount: number;
  vendor_type: string | null;
  total_quantity: number;
  total_weight_kg: number;
  moq_kg: number | null;
  moq_met: boolean;
  max_units: number | null;
  is_locked: boolean;
}

export interface Vendor {
  // The shop, not the person who owns it. `owners_name`, `email`,
  // `phone_number`, `preferred_payment_method` and `verification_status` were
  // declared here and are no longer sent: the customer-facing reads return
  // `VendorStorefront`, because that last one is the store's *payout
  // destination* and the set together was an owner-name-plus-phone-plus-till
  // list. Declaring a field the server does not send does not make it arrive —
  // it makes `undefined` render as a blank line nobody can explain.
  id: string;
  business_name: string;
  profile_pic: string | null;
  vendor_type: string | null;
  location_address: string | null;
  lat: number | null;
  lng: number | null;
  shift_start: string;
  shift_end: string;
  rating: number | null;

  // ── Is this store taking orders? ────────────────────────────────────────
  //
  // Stamped on by the server (`vendor_availability.annotate`) on every
  // customer-facing read. Optional on this type only because older cached
  // responses will not carry them; treat absent as open, never as closed.
  //
  // Do **not** derive this from `shift_start`/`shift_end` here. Those are two
  // of five reasons a store may not be trading, and reconstructing the answer
  // in the app is how the list ends up disagreeing with the store page.
  is_accepting_orders?: boolean;
  /** open | paused | offline | closed_hours | suspended */
  store_state?: string;
  /** The server's own sentence, including the store's own note. Render verbatim. */
  store_reason?: string | null;
  reopens_at?: string | null;
  accepts_cash?: boolean;
  min_order_value?: string | null;
}

/** `schemas/product_schemas.py::VendorSnippet` — the store as a product carries it. */
export interface ProductVendorSnippet {
  id: string;
  business_name: string;
  vendor_type?: string | null;
  location_address?: string | null;
  lat?: number | null;
  lng?: number | null;
  rating?: number | null;
  profile_pic?: string | null;
}

/**
 * `schemas/product_schemas.py::ProductFull`.
 *
 * This declared `image` and `category`, neither of which the API sends — the
 * field is `image_url`, and there is no category on a product anywhere in the
 * platform. It also omitted `discount`, `capacity`, `weight_kg` and
 * `minimum_order_qty`, all four of which screens read, so the type described
 * neither what arrives nor what is used.
 *
 * `description`, `unit` and `is_available` are optional because
 * `POST /vendor_details_and_products` serialises the shorter `BaseProduct`;
 * `/get_product` and `/search` return all three.
 *
 * There was a second `Product` in `hooks/queries/useProducts.ts` — the one most
 * screens actually imported — and it declared **`price: number` and
 * `discount: number`**. Money is a decimal string from the database to the
 * screen; a type that says otherwise is an invitation to `a + b` on the two
 * fields the platform is most careful about.
 */
export interface Product {
  id: string;
  vendor_id: string;
  name: string;
  image_url: string;
  capacity: number;
  weight_kg: number;
  minimum_order_qty: number;
  /** Decimal string. */
  price: string;
  /** Decimal string. */
  discount: string;
  stock: number;
  /** Server-side alias for `stock`, kept because screens read this name. */
  stock_quantity: number;
  description?: string | null;
  unit?: string | null;
  is_available?: boolean;
  /** Only on `/get_product` and `/search` (`ProductFull`). */
  vendor?: ProductVendorSnippet | null;
}

/** `schemas/vendor_schemas.py::VendorWithProductsFull` — a storefront and its catalogue. */
export interface VendorWithProducts extends Vendor {
  products: Product[];
}

export type OrderStatus = 
  | "pending" | "confirmed" | "preparing" | "ready" 
  | "picked_up" | "delivered" | "cancelled";

/**
 * `schemas/order_schema.py::OrderItemBase`.
 *
 * This previously declared `product_name`, `unit_price`, `total_price` and an
 * `image` — **none of which the API has ever sent**. Every screen but one was
 * written against the real response and read `item.product`, `item.price` and
 * `item.quantity`; the one written against this type read `subtotal_at_order`
 * and rendered nothing.
 */
export interface OrderItem {
  id: string;
  order_id: string;
  product_id: string;
  quantity: number;
  /** Decimal string: the unit price at the time of the order. */
  price: string;
  /** Decimal string, capitalised on the wire exactly as the schema declares it. */
  Subtotal: string;
  product?: Product | null;
}

/**
 * `schemas/order_schema.py::OrderVendorSnippet` — the store as an order carries
 * it, which is **not** a `Vendor`. This type used to declare `vendor: Vendor`,
 * promising an order carried `shift_start`, `store_state` and the rest; it
 * carries nine fields and none of the trading-status ones.
 */
export interface OrderVendorSnippet {
  id: string;
  business_name: string;
  profile_pic?: string | null;
  vendor_type?: string | null;
  location_address?: string | null;
  lat?: number | null;
  lng?: number | null;
  rating?: number | null;
  phone_number?: string | null;
}

/** `schemas/order_schema.py::OrderDelivererSnippet` — likewise, not a `Rider`. */
export interface OrderDelivererSnippet {
  id: string;
  full_name?: string | null;
  phone_number?: string | null;
  vehicle_details?: string | null;
}

/**
 * `schemas/order_schema.py::BaseOrder`.
 *
 * **This is the only `Order` in the app.** There were two: this one and a
 * second in `hooks/queries/useOrders.ts`, which is the type every screen
 * actually received. They disagreed about eighteen fields — the hook's had the
 * whole money breakdown and the coordinates, this one had `customer_id` and
 * `updated_at` the hook's lacked — and a screen's behaviour depended on which
 * import it happened to reach for. That is the same defect as a second route
 * table, one layer up: two declarations of one wire shape, free to drift, with
 * nothing that resolves them against each other.
 *
 * Every money field is a decimal string. `total_amount` is the frozen figure
 * the customer was charged — never re-derive it from the lines.
 */
export interface Order {
  id: string;
  customer_id?: string;
  order_status: string;
  payment_method: string;
  payment_status?: string;

  // ── Money: decimal strings, all of them ──
  total_amount: string;
  delivery_fee?: string;
  service_fee?: string;
  surge_fee?: string;
  product_subtotal?: string;
  wallet_discount?: string;
  welcome_discount?: string;
  payload_surcharge?: string;
  staircase_surcharge?: string;
  /**
   * Refundable deposit charged on this order, and an earlier unpaid balance
   * collected on it. Both are columns on `Orders` and were on neither app's
   * response schema, so the order breakdown could not add up to `total_amount`
   * on any order that carried one.
   */
  bottle_deposit?: string;
  debt_settlement?: string;
  /** Taken off for paying by M-Pesa rather than cash. */
  mpesa_discount?: string;
  /**
   * Signed. What quantizing to a whole shilling moved. With this and
   * `mpesa_discount` recorded, an order's own lines add up to `total_amount`.
   */
  rounding_adjustment?: string;
  /**
   * What approving an address mismatch would add to this order, computed by the
   * same server function that applies it. The screen quoted a flat "KSh 30" —
   * on the explanation *and* on the approve button — which is right only for a
   * fifth floor with nothing already billed.
   */
  pending_staircase_charge?: string;

  delivery_address?: string | null;
  delivery_time?: number;
  delivery_type?: string;
  vehicle_class?: string;
  distance_km?: number;
  lat?: number;
  lng?: number;
  lat_from?: number;
  lng_from?: number;

  bottle_source?: string;
  customer_note?: string;
  /** True once the customer has reviewed this order. */
  is_rated?: boolean;

  vendor?: OrderVendorSnippet | null;
  deliverer?: OrderDelivererSnippet | null;
  order_item?: OrderItem[];

  created_at: string;
  updated_at?: string;
}

export interface SavedLocation {
  id: string;
  label: string | null;
  address: string;
  lat: number;
  lng: number;
  is_default: boolean;
  use_count: number;
  last_used_at: string | null;
}

/**
 * One GPS breadcrumb from `GET /api/orders/{id}/tracking-logs`
 * (`models/order_tracking_log_model.py::OrderTrackingLog`), which is what the
 * delivery polyline is drawn from.
 */
export interface OrderTrackingLog {
  id: string;
  order_id: string;
  lat: number;
  lng: number;
  heading: number | null;
  speed: number | null;
  created_at: string;
}

export interface MapRegion {
  latitude: number;
  longitude: number;
  latitudeDelta: number;
  longitudeDelta: number;
}

/**
 * What the map screen puts on a marker — built locally from a `Vendor`, not
 * received from the server.
 *
 * `owners_name` was declared here and set by neither of the two places that
 * build these, which is the same defect as the `Vendor` note above one step
 * further downstream: `MiniVendorCard` is handed one of these and drew the
 * shopkeeper's personal name from a field that has never held one.
 */
export interface GeoJSONVendorProperties {
  id: string;
  /** The store's `business_name`. */
  title: string;
  rating: number | null;
  /** The store's `profile_pic`. */
  image: string | null;
  /**
   * The store's `location_address`. `MiniVendorCard` has always rendered this
   * and neither of the two places that build these has ever set it, so the
   * card a customer gets on tapping a shop on the map read "Location not set"
   * for every shop on the platform.
   */
  location_address: string | null;
  cluster?: boolean;
  cluster_id?: number;
  point_count?: number;
}

export interface GeoJSONFeature {
  type: "Feature";
  geometry: {
    type: "Point";
    coordinates: [number, number]; // [lng, lat]
  };
  properties: GeoJSONVendorProperties;
}

export interface Rider {
  id: string;
  clerk_id: string;
  full_name: string;
  email: string;
  phone_number: string | null;
  profile_pic: string | null;
  vehicle_type: string | null;
  lat: number | null;
  lng: number | null;
  is_available: boolean;
  rating: number | null;
}

export interface Coordinates {
  lat: number;
  lng: number;
  location_address?: string;
  floor_level?: number;
  has_elevator?: boolean;
}

export interface PaymentRecord {
  id: string;
  amount: string;
  method: string;
  status: string;
  created_at: string;
  order_id: string;
}
