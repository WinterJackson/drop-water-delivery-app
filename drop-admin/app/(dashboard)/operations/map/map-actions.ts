"use server";

import { ApiError, get } from "@/lib/api/server";

/**
 * The map's data, fetched through Server Actions rather than by the browser.
 *
 * Same rule as everywhere else in this console: the API token never reaches the
 * client. The map is inherently interactive — it refetches as you pan — so it
 * has to be a Client Component, which means it cannot import the server API
 * client. These actions are the bridge.
 */

export type RiderPoint = {
  id: string;
  name: string | null;
  lat: number;
  lng: number;
  vehicle: string | null;
  rating: number | null;
  kyc_status: string | null;
  suspended: boolean;
  marked_available: boolean;
  deployable: boolean;
  last_seen: string | null;
};

export type VendorPoint = {
  id: string;
  name: string | null;
  lat: number;
  lng: number;
  vendor_type: string | null;
  verification_status: string | null;
  online: boolean;
  suspended: boolean;
  rating: number | null;
};

export type OrderPoint = {
  id: string;
  status: string;
  vendor: string | null;
  rider: string | null;
  lat: number;
  lng: number;
  total: string;
  waiting_minutes: number | null;
};

export type Layers = {
  riders: { points: RiderPoint[]; truncated: boolean };
  vendors: { points: VendorPoint[]; truncated: boolean };
  orders: { points: OrderPoint[]; truncated: boolean } | null;
};

function bbox(view: {
  minLat: number;
  minLng: number;
  maxLat: number;
  maxLng: number;
}): string {
  return new URLSearchParams({
    min_lat: String(view.minLat),
    min_lng: String(view.minLng),
    max_lat: String(view.maxLat),
    max_lng: String(view.maxLng),
  }).toString();
}

/**
 * One call per pan, not three.
 *
 * The order layer is permissioned separately (it needs `orders.read` as well as
 * `geo.view`), so a refusal there returns `null` and the rest of the map still
 * draws — rather than one missing capability blanking the screen.
 */
export async function loadLayers(
  view: { minLat: number; minLng: number; maxLat: number; maxLng: number },
  options: { onlyDeployable: boolean; includeOrders: boolean },
): Promise<Layers> {
  const query = bbox(view);

  const [riders, vendors, orders] = await Promise.all([
    get<Layers["riders"]>(
      `/api/admin/map/riders?${query}&only_deployable=${options.onlyDeployable}`,
    ),
    get<Layers["vendors"]>(`/api/admin/map/vendors?${query}`),
    options.includeOrders
      ? get<NonNullable<Layers["orders"]>>(`/api/admin/map/orders?${query}`).catch(
          (error: unknown) => {
            if (error instanceof ApiError) return null;
            throw error;
          },
        )
      : Promise.resolve(null),
  ]);

  return { riders, vendors, orders };
}
