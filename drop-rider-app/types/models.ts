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
  floor_level: number;
  has_elevator: boolean;
  preferences: Record<string, unknown> | null;
  payment_methods: string[] | null;
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
  shift_start: string;
  shift_end: string;
  verification_status: string;
  rating: number | null;
  preferred_payment_method: string[] | null;
}

export interface Product {
  id: string;
  name: string;
  price: string;
  description: string | null;
  image: string | null;
  stock_quantity: number;
  vendor_id: string;
  category: string | null;
}

export type OrderStatus = 
  | "unassigned" | "pending" | "accepted" | "preparing" | "ready" 
  | "picked_up" | "delivered" | "cancelled" | "rejected"
  | "pending_review" | "mismatch_pending";

export interface OrderItem {
  id: string;
  product_id: string;
  product_name: string;
  quantity: number;
  unit_price: string;
  total_price: string;
  image: string | null;
}

export interface Order {
  id: string;
  order_id: string;
  order_status: OrderStatus;
  total_amount: string;
  delivery_fee: string;
  service_fee: string;
  items: OrderItem[];
  vendor_id: string;
  customer_id: string;
  rider_id: string | null;
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
  amount: string;
  method: string;
  status: string;
  created_at: string;
  order_id: string;
}
