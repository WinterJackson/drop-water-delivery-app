"use client";

import { Loader2, MapPinOff } from "lucide-react";
import { useEffect, useRef } from "react";

import { DARK_MAP_STYLE, LIGHT_MAP_STYLE, useGoogleMaps } from "@/lib/maps/google-maps";

export type PathPoint = {
  lat: number;
  lng: number;
  at: string | null;
  speed: number | null;
  metres_to_destination: number | null;
};

/**
 * The rider's recorded path, drawn once.
 *
 * Nothing here refetches on `idle` — unlike the operations map, this is a fixed
 * set of points for one finished delivery, so the viewport is fitted to the data
 * and then left alone.
 *
 * The proximity circle is the whole argument made visible: if the path never
 * enters it, the rider never reached the door, and that is a claim somebody is
 * about to make about another person's honesty. It is drawn at the same radius
 * the backend used for `reached_destination`, read from the payload rather than
 * duplicated here — a circle that disagreed with the verdict would be worse than
 * no circle.
 */
export function ReplayMap({
  path,
  destination,
  pickup,
  proximityM,
}: {
  path: PathPoint[];
  destination: { lat: number; lng: number } | null;
  pickup: { lat: number; lng: number } | null;
  proximityM: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<google.maps.Map | null>(null);
  const { ready, error: loadError } = useGoogleMaps();

  useEffect(() => {
    if (!ready || !container.current || map.current) return;

    const root = document.documentElement;
    const dark =
      root.dataset.theme === "dark" ||
      (root.dataset.theme !== "light" &&
        window.matchMedia?.("(prefers-color-scheme: dark)").matches);

    const instance = new google.maps.Map(container.current, {
      center: destination ?? path[0] ?? { lat: -1.2921, lng: 36.8219 },
      zoom: 14,
      styles: dark ? DARK_MAP_STYLE : LIGHT_MAP_STYLE,
      streetViewControl: false,
      mapTypeControl: false,
      fullscreenControl: true,
      keyboardShortcuts: true,
      clickableIcons: false,
      gestureHandling: "greedy",
    });
    map.current = instance;

    const bounds = new google.maps.LatLngBounds();

    const first = path.at(0);
    const last = path.at(-1);

    if (first && last) {
      new google.maps.Polyline({
        map: instance,
        path: path.map((point) => ({ lat: point.lat, lng: point.lng })),
        strokeColor: "#3b82f6",
        strokeOpacity: 0.9,
        strokeWeight: 3,
      });
      path.forEach((point) => bounds.extend({ lat: point.lat, lng: point.lng }));

      // Start and end, so the direction of travel is readable without animation.
      const ends: [PathPoint, string, string][] = [
        [first, "Start of the recorded path", "#22c55e"],
        [last, "End of the recorded path", "#ef4444"],
      ];
      for (const [point, title, colour] of ends) {
        new google.maps.Marker({
          map: instance,
          position: { lat: point.lat, lng: point.lng },
          title,
          icon: {
            path: "M 0,-6 A 6,6 0 1,1 0,6 A 6,6 0 1,1 0,-6 Z",
            fillColor: colour,
            fillOpacity: 1,
            strokeColor: "#ffffff",
            strokeWeight: 2,
            scale: 1,
          },
        });
      }
    }

    if (pickup) {
      new google.maps.Marker({
        map: instance,
        position: pickup,
        title: "Store",
        label: { text: "S", color: "#ffffff", fontSize: "11px", fontWeight: "600" },
        icon: {
          path: "M -8,-8 L 8,-8 L 8,8 L -8,8 Z",
          fillColor: "#6366f1",
          fillOpacity: 1,
          strokeColor: "#ffffff",
          strokeWeight: 2,
          scale: 1,
        },
      });
      bounds.extend(pickup);
    }

    if (destination) {
      new google.maps.Marker({
        map: instance,
        position: destination,
        title: "Delivery address",
        label: { text: "D", color: "#ffffff", fontSize: "11px", fontWeight: "600" },
        icon: {
          path: "M 0,-9 L 9,0 L 0,9 L -9,0 Z",
          fillColor: "#f59e0b",
          fillOpacity: 1,
          strokeColor: "#ffffff",
          strokeWeight: 2,
          scale: 1,
        },
      });
      new google.maps.Circle({
        map: instance,
        center: destination,
        radius: proximityM,
        strokeColor: "#f59e0b",
        strokeOpacity: 0.6,
        strokeWeight: 1,
        fillColor: "#f59e0b",
        fillOpacity: 0.1,
      });
      bounds.extend(destination);
    }

    if (!bounds.isEmpty()) {
      instance.fitBounds(bounds, 48);
    }
  }, [ready, path, destination, pickup, proximityM]);

  return (
    <div className="relative overflow-hidden rounded-xl border border-default">
      {loadError ? (
        <div className="flex h-[22rem] flex-col items-center justify-center gap-3 bg-surface-muted px-6 text-center sm:h-[28rem]">
          <MapPinOff className="h-8 w-8 text-muted" aria-hidden />
          <p className="max-w-md text-sm text-muted">{loadError}</p>
          <p className="max-w-md text-xs text-muted">
            The findings above are unaffected — they are computed on the backend
            from the same points, so the closest approach is still the answer
            even with no basemap to draw it on.
          </p>
        </div>
      ) : (
        <div
          ref={container}
          className="h-[22rem] w-full sm:h-[28rem] lg:h-[34rem]"
          role="application"
          aria-label="Map of the rider's recorded path"
        />
      )}

      {!ready && !loadError ? (
        <div className="absolute inset-0 flex items-center justify-center bg-surface/60">
          <Loader2 className="h-6 w-6 animate-spin text-muted" aria-hidden />
        </div>
      ) : null}
    </div>
  );
}
