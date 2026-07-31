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
  wallet_balance: number;
  /** Outstanding bottle-deposit debt. Any amount above zero blocks checkout. */
  debt_balance?: number;
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
  price: number;
  discount: number;
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
  price: number;
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
  total_amount: number;
  cart_item: CartItem[];
  service_fee: number;
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
  id: string;
  business_name: string;
  owners_name: string;
  email: string;
  phone_number: string | null;
  profile_pic: string | null;
  vendor_type: string | null;
  location_address: string | null;
  lat: number | null;
  lng: number | null;
  delivery_radius: number | null;
  shift_start: string;
  shift_end: string;
  verification_status: string;
  rating: number | null;
  preferred_payment_method: string[] | null;
}

export interface Product {
  id: string;
  name: string;
  price: number;
  description: string | null;
  image: string | null;
  stock_quantity: number;
  vendor_id: string;
  category: string | null;
}

export type OrderStatus = 
  | "pending" | "confirmed" | "preparing" | "ready" 
  | "picked_up" | "delivered" | "cancelled";

export interface OrderItem {
  id: string;
  product_id: string;
  product_name: string;
  quantity: number;
  unit_price: number;
  total_price: number;
  image: string | null;
}

export interface Order {
  id: string;
  order_status: string;
  total_amount: number;
  delivery_fee: number;
  service_fee: number;
  order_item: OrderItem[];
  vendor: Vendor;
  customer_id: string;
  deliverer?: Rider | null;
  is_rated?: boolean;
  delivery_address: string | null;
  created_at: string;
  updated_at: string;
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

export interface MapRegion {
  latitude: number;
  longitude: number;
  latitudeDelta: number;
  longitudeDelta: number;
}

export interface GeoJSONVendorProperties {
  id: string;
  title: string;
  owners_name: string;
  rating: number | null;
  image: string | null;
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
  amount: number;
  method: string;
  status: string;
  created_at: string;
  order_id: string;
}
