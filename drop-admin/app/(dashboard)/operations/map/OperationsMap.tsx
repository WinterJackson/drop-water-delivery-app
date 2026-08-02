"use client";

import { Loader2, MapPinOff } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  DARK_MAP_STYLE,
  LIGHT_MAP_STYLE,
  useGoogleMaps,
} from "@/lib/maps/google-maps";
import { cn } from "@/lib/utils/cn";
import { formatMoney } from "@/lib/utils/format";
import { loadLayers, type Layers } from "./map-actions";

/**
 * The operations map.
 *
 * **Google Maps JavaScript API**, with a browser key restricted by HTTP referrer
 * to this console's origins and to that one API. That is the same arrangement
 * the three mobile apps use for their Maps SDK keys, and it does not weaken the
 * platform's rule about Google *web services* — Directions, Places and Geocoding
 * still go through `routes/maps_routes.py` on the server key, because those are
 * the ones a lifted key can bill against from anywhere.
 *
 * **Data follows the viewport.** Every pan refetches the visible rectangle,
 * because "select every rider" is a table scan that gets slower precisely as the
 * platform succeeds.
 *
 * **Riders are coloured by whether they can actually work**, not by
 * `is_available` — that flag defaults to true at sign-up, so colouring by it
 * paints a healthy fleet on a platform where nobody has passed KYC.
 *
 * **`google.maps.Marker`, not `AdvancedMarkerElement`.** The newer class needs a
 * cloud-configured `mapId`, and a map with a `mapId` ignores `styles` entirely —
 * the dark basemap would have to be built and kept in step in the Google console
 * instead of in this repository. Marker is legacy but supported, and it takes an
 * SVG path directly, which is what carries shape as a second channel alongside
 * colour.
 */

type Selected =
  | { kind: "rider"; data: Layers["riders"]["points"][number] }
  | { kind: "vendor"; data: Layers["vendors"]["points"][number] }
  | { kind: "order"; data: NonNullable<Layers["orders"]>["points"][number] }
  | null;

/** Marker geometry. Shape carries the meaning as well as colour — see `symbol`. */
const SHAPES = {
  circle: "M 0,-7 A 7,7 0 1,1 0,7 A 7,7 0 1,1 0,-7 Z",
  square: "M -6,-6 L 6,-6 L 6,6 L -6,6 Z",
  diamond: "M 0,-8 L 8,0 L 0,8 L -8,0 Z",
} as const;

export function OperationsMap({
  centre,
  canSeeOrders,
}: {
  centre: { lat: number; lng: number; zoom: number };
  canSeeOrders: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<google.maps.Map | null>(null);
  const markers = useRef<google.maps.Marker[]>([]);

  const { ready, error: loadError } = useGoogleMaps();

  const [layers, setLayers] = useState<Layers | null>(null);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<Selected>(null);
  const [show, setShow] = useState({
    riders: true,
    vendors: true,
    orders: canSeeOrders,
    onlyDeployable: false,
  });

  const showRef = useRef(show);
  showRef.current = show;

  const refetch = useCallback(async () => {
    const instance = map.current;
    if (!instance) return;

    const bounds = instance.getBounds();
    if (!bounds) return;

    const sw = bounds.getSouthWest();
    const ne = bounds.getNorthEast();

    setLoading(true);
    try {
      const data = await loadLayers(
        {
          minLat: sw.lat(),
          minLng: sw.lng(),
          maxLat: ne.lat(),
          maxLng: ne.lng(),
        },
        {
          onlyDeployable: showRef.current.onlyDeployable,
          includeOrders: canSeeOrders && showRef.current.orders,
        },
      );
      setLayers(data);
    } finally {
      setLoading(false);
    }
  }, [canSeeOrders]);

  // Create the map once the API is available.
  useEffect(() => {
    if (!ready || !container.current || map.current) return;

    // Read the theme the console is actually rendering in, rather than the OS
    // preference: the explicit toggle writes `data-theme` and must win.
    const root = document.documentElement;
    const dark =
      root.dataset.theme === "dark" ||
      (root.dataset.theme !== "light" &&
        window.matchMedia?.("(prefers-color-scheme: dark)").matches);

    const instance = new google.maps.Map(container.current, {
      center: { lat: centre.lat, lng: centre.lng },
      zoom: centre.zoom,
      styles: dark ? DARK_MAP_STYLE : LIGHT_MAP_STYLE,
      // Street View and the map-type switcher are noise on an operations map;
      // the fullscreen control genuinely helps when triaging a busy area.
      streetViewControl: false,
      mapTypeControl: false,
      fullscreenControl: true,
      // Keyboard users must be able to pan and zoom without dragging.
      keyboardShortcuts: true,
      clickableIcons: false,
      gestureHandling: "greedy",
    });

    // `idle`, not `bounds_changed`: the latter fires on every animation frame of
    // a drag, which is a request per frame.
    instance.addListener("idle", () => void refetch());

    map.current = instance;
  }, [ready, centre.lat, centre.lng, centre.zoom, refetch]);

  // Redraw markers whenever the data or the visible layers change.
  useEffect(() => {
    const instance = map.current;
    if (!instance || !layers) return;

    for (const marker of markers.current) marker.setMap(null);
    markers.current = [];

    const add = (
      lat: number,
      lng: number,
      options: { colour: string; shape: keyof typeof SHAPES; label: string; onClick: () => void },
    ) => {
      const marker = new google.maps.Marker({
        map: instance,
        position: { lat, lng },
        title: options.label,
        // The accessible name a screen reader announces for the marker's
        // focusable element. The panel below repeats everything as text, since
        // a map canvas is not navigable in any useful way.
        optimized: false,
        icon: {
          path: SHAPES[options.shape],
          fillColor: options.colour,
          fillOpacity: 1,
          strokeColor: "#ffffff",
          strokeWeight: 2,
          scale: 1,
        },
      });
      marker.addListener("click", options.onClick);
      markers.current.push(marker);
    };

    if (show.vendors) {
      for (const vendor of layers.vendors.points) {
        add(vendor.lat, vendor.lng, {
          // Resolved hex rather than `var(--…)`: these are painted onto a canvas
          // by the Maps API, which never sees the stylesheet.
          colour: vendor.suspended ? "#dc2626" : vendor.online ? "#16a34a" : "#94a3b8",
          shape: "square",
          label: `Store: ${vendor.name ?? "unnamed"}`,
          onClick: () => setSelected({ kind: "vendor", data: vendor }),
        });
      }
    }

    if (show.riders) {
      for (const rider of layers.riders.points) {
        add(rider.lat, rider.lng, {
          colour: rider.suspended ? "#dc2626" : rider.deployable ? "#2563eb" : "#f59e0b",
          shape: "circle",
          label: `Rider: ${rider.name ?? "unnamed"}`,
          onClick: () => setSelected({ kind: "rider", data: rider }),
        });
      }
    }

    if (show.orders && layers.orders) {
      for (const order of layers.orders.points) {
        add(order.lat, order.lng, {
          colour: (order.waiting_minutes ?? 0) > 90 ? "#dc2626" : "#7c3aed",
          shape: "diamond",
          label: `Order ${order.id.slice(0, 8)}`,
          onClick: () => setSelected({ kind: "order", data: order }),
        });
      }
    }
  }, [layers, show]);

  useEffect(() => {
    void refetch();
  }, [show.onlyDeployable, show.orders, refetch]);

  const counts = {
    riders: layers?.riders.points.length ?? 0,
    deployable: layers?.riders.points.filter((r) => r.deployable).length ?? 0,
    vendors: layers?.vendors.points.length ?? 0,
    orders: layers?.orders?.points.length ?? 0,
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
        <Toggle
          checked={show.riders}
          onChange={(value) => setShow((s) => ({ ...s, riders: value }))}
          colour="#2563eb"
          label={`Riders (${counts.deployable} of ${counts.riders} deployable)`}
        />
        <Toggle
          checked={show.vendors}
          onChange={(value) => setShow((s) => ({ ...s, vendors: value }))}
          colour="#16a34a"
          label={`Stores (${counts.vendors})`}
        />
        {canSeeOrders ? (
          <Toggle
            checked={show.orders}
            onChange={(value) => setShow((s) => ({ ...s, orders: value }))}
            colour="#7c3aed"
            label={`Orders in flight (${counts.orders})`}
          />
        ) : null}
        <Toggle
          checked={show.onlyDeployable}
          onChange={(value) => setShow((s) => ({ ...s, onlyDeployable: value }))}
          colour="#94a3b8"
          label="Only riders who can work"
        />
        {loading ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            Loading
          </span>
        ) : null}
      </div>

      <div className="relative overflow-hidden rounded-xl border border-default">
        {loadError ? (
          // A blank rectangle reads as broken software. Say what is wrong and
          // what fixes it — this failure is always configuration.
          <div className="flex h-[24rem] flex-col items-center justify-center gap-3 bg-surface-muted px-6 text-center sm:h-[32rem]">
            <MapPinOff className="h-8 w-8 text-muted" aria-hidden />
            <p className="max-w-md text-sm text-muted">{loadError}</p>
            <p className="max-w-md text-xs text-muted">
              Everything else on this screen is unaffected — the coverage figures
              below come from the backend, not from Google.
            </p>
          </div>
        ) : (
          <div
            ref={container}
            className="h-[24rem] w-full sm:h-[32rem] lg:h-[38rem]"
            // The canvas is not reachable by a screen reader in any useful way,
            // so the panel below carries the same information as text.
            role="application"
            aria-label="Map of riders, stores and orders"
          />
        )}

        {!ready && !loadError ? (
          <div className="absolute inset-0 flex items-center justify-center bg-surface/60">
            <Loader2 className="h-6 w-6 animate-spin text-muted" aria-hidden />
          </div>
        ) : null}

        {selected ? (
          <div className="absolute inset-x-3 bottom-3 max-w-sm rounded-xl border border-default bg-surface p-4 shadow-2xl sm:inset-x-auto sm:left-3">
            <div className="flex items-start justify-between gap-3">
              <Detail selected={selected} />
              <button
                type="button"
                onClick={() => setSelected(null)}
                aria-label="Close details"
                className="shrink-0 rounded-lg px-2 py-1 text-muted hover:bg-surface-muted"
              >
                ✕
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {layers?.riders.truncated || layers?.vendors.truncated ? (
        <p className="text-xs text-muted">
          Showing the first results in this area only — zoom in to see everything.
        </p>
      ) : null}
    </div>
  );
}

function Detail({ selected }: { selected: NonNullable<Selected> }) {
  if (selected.kind === "rider") {
    const rider = selected.data;
    return (
      <div className="min-w-0">
        <p className="text-xs uppercase tracking-wide text-muted">Rider</p>
        <Link href={`/people/riders/${rider.id}`} className="font-medium hover:underline">
          {rider.name ?? "Unnamed"}
        </Link>
        <p className="mt-1 text-sm text-muted">
          {rider.vehicle ?? "no vehicle"} · KYC {rider.kyc_status ?? "—"}
        </p>
        <p
          className={cn(
            "mt-1 text-sm font-medium",
            rider.deployable ? "text-[var(--success)]" : "text-[var(--warning)]",
          )}
        >
          {rider.deployable
            ? "Can accept deliveries"
            : rider.suspended
              ? "Suspended"
              : rider.marked_available
                ? "Marked available but not verified"
                : "Not available"}
        </p>
      </div>
    );
  }

  if (selected.kind === "vendor") {
    const vendor = selected.data;
    return (
      <div className="min-w-0">
        <p className="text-xs uppercase tracking-wide text-muted">Store</p>
        <Link href={`/people/vendors/${vendor.id}`} className="font-medium hover:underline">
          {vendor.name ?? "Unnamed"}
        </Link>
        <p className="mt-1 text-sm text-muted">
          {vendor.vendor_type ?? "—"} · {vendor.verification_status ?? "unverified"}
        </p>
        <p className="mt-1 text-sm">{vendor.online ? "Open now" : "Closed"}</p>
      </div>
    );
  }

  const order = selected.data;
  return (
    <div className="min-w-0">
      <p className="text-xs uppercase tracking-wide text-muted">Order</p>
      <Link href="/operations/orders" className="font-mono text-sm hover:underline">
        {order.id.slice(0, 8)}
      </Link>
      <p className="mt-1 text-sm text-muted">
        {order.vendor ?? "—"} → {order.rider ?? "unassigned"}
      </p>
      <p className="mt-1 text-sm">
        {formatMoney(order.total)} · {order.status} ·{" "}
        <span className={(order.waiting_minutes ?? 0) > 90 ? "text-[var(--danger)]" : ""}>
          {order.waiting_minutes ?? "—"} min
        </span>
      </p>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  colour,
  label,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  colour: string;
  label: string;
}) {
  return (
    <label className="inline-flex items-center gap-2">
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="h-4 w-4"
      />
      <span aria-hidden className="h-2.5 w-2.5 rounded-full" style={{ background: colour }} />
      {label}
    </label>
  );
}
