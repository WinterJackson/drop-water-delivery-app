/**
 * The shapes the backend actually sends this app.
 *
 * Mirrored field-for-field from `BackendAPI/schemas/order_schema.py` and
 * `product_schemas.py`, which are the contract. The vendor app was the only one
 * of the three with no domain types at all — the customer and rider apps each
 * have a `types/models.ts` — so every order flowing through it was `any[]`, and
 * a screen reading `order.totalAmount` or `order.status` would have compiled
 * happily and rendered `undefined` to a shop counter.
 *
 * **Money is a decimal string, never a number.** `"1234.50"`, straight from a
 * Postgres `NUMERIC`. Typing these as `number` would invite `a + b` on figures
 * the platform goes out of its way to keep exact — see `utils/money.ts`, which
 * is the only place digits are touched.
 *
 * Optionality mirrors the schema rather than being guessed: a field the server
 * declares `| None` is optional here, and one it always sends is not. Marking
 * everything optional would be the same abdication as `any`, one step quieter.
 */

/** Every status the backend can put on an order. See `constants/orderStatus.ts`. */
export type VendorOrderStatus =
    | 'pending'
    | 'unassigned'
    | 'accepted'
    | 'preparing'
    | 'ready'
    | 'picked_up'
    | 'delivered'
    | 'cancelled'
    | 'rejected'
    | 'pending_review'
    | 'mismatch_pending';

/** `schemas/product_schemas.py::BaseProduct`. */
export interface OrderProduct {
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
    description?: string | null;
    unit?: string | null;
    is_available?: boolean;
}

/** `schemas/order_schema.py::OrderItemBase`. */
export interface VendorOrderItem {
    id: string;
    order_id: string;
    product_id: string;
    quantity: number;
    /** Decimal string. */
    price: string;
    /**
     * Decimal string. Capitalised on the wire — the schema declares `Subtotal`,
     * and renaming it here would only move the mismatch somewhere harder to see.
     */
    Subtotal: string;
    product?: OrderProduct | null;
}

/** `schemas/order_schema.py::OrderVendorSnippet`. */
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

/** `schemas/order_schema.py::OrderDelivererSnippet`. */
export interface OrderDelivererSnippet {
    id: string;
    full_name?: string | null;
    phone_number?: string | null;
    vehicle_details?: string | null;
}

/** `schemas/user_schemas.py::CustomerPublicProfile`. */
export interface OrderCustomerSnippet {
    id: string;
    full_name?: string | null;
    phone_number?: string | null;
    location_address?: string | null;
    floor_level?: number | null;
    has_elevator?: boolean | null;
    profile_pic?: string | null;
}

/**
 * `schemas/order_schema.py::BaseOrder`, as the vendor app receives it.
 *
 * Every money field is a decimal string. `total_amount` in particular is the
 * frozen figure the customer was charged — never re-derive it by summing the
 * lines, which is how the store's copy of an order came to disagree with the
 * customer's and with the M-Pesa message.
 */
export interface VendorOrder {
    id: string;
    customer_id: string;
    vendor_id: string;
    deliverer_id?: string | null;

    order_status?: VendorOrderStatus | null;
    payment_status?: string | null;
    payment_method?: string | null;

    delivery_address?: string | null;
    phone?: string | null;
    lat_from?: number | null;
    lng_from?: number | null;
    lat?: number | null;
    lng?: number | null;
    delivery_type?: string | null;
    delivery_time?: number | null;
    distance_km?: number | null;
    vehicle_class?: string | null;

    // ── Money: decimal strings, all of them ──
    total_amount?: string | null;
    delivery_fee?: string | null;
    product_subtotal: string;
    service_fee: string;
    surge_fee: string;
    delivery_markup: string;
    platform_total: string;
    vendor_net: string;
    vendor_commission: string;
    rider_net: string;
    rider_commission: string;
    payload_surcharge: string;
    staircase_surcharge: string;
    wallet_discount: string;
    welcome_discount: string;
    /**
     * Refundable deposit charged on this order — the largest single line on a
     * `new_bottle` order, and it was on the response schema of neither app.
     */
    bottle_deposit?: string;
    /** An earlier unpaid balance collected on this order. */
    debt_settlement?: string;
    /** Taken off for paying by M-Pesa rather than cash. */
    mpesa_discount?: string;
    /** Signed — what quantizing to a whole shilling moved. */
    rounding_adjustment?: string;

    bottle_source?: string | null;
    is_welcome_offer?: boolean | null;
    customer_note?: string | null;
    proof_url?: string | null;
    is_rated: boolean;

    vendor?: OrderVendorSnippet | null;
    deliverer?: OrderDelivererSnippet | null;
    user?: OrderCustomerSnippet | null;
    order_item: VendorOrderItem[];

    created_at: string;
    updated_at?: string | null;
}
