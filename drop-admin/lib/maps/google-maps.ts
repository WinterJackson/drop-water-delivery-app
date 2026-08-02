"use client";

import { useEffect, useState } from "react";

/**
 * Loads the Google Maps JavaScript API, once per page.
 *
 * ## Why a browser key here does not break the platform's rule
 *
 * "Never call a Google web service from the client" is about **web services** —
 * Directions, Places, Geocoding — whose keys can be used from anywhere by
 * anyone who extracts them. Those stay behind `routes/maps_routes.py` with the
 * single IP-restricted server key.
 *
 * The Maps **JavaScript API** is an SDK, not a web service, and it is the same
 * arrangement the three mobile apps already use: a key that can only draw a map,
 * locked to one caller. There it is the package/bundle id; here it is the HTTP
 * referrer. It has to reach the browser — the browser is what renders the map —
 * so it is `NEXT_PUBLIC_`, and the restriction is what makes that safe.
 *
 * ## Restricting it (do this before the key ever ships)
 *
 * In the Google Cloud console, on this key alone:
 *
 * - **Application restrictions → Websites**, listing exactly the console's
 *   origins (`https://your-console.vercel.app/*`, `http://localhost:3000/*`).
 * - **API restrictions → Maps JavaScript API** only. Not Directions, not
 *   Places, not Geocoding — an unrestricted key lifted from this page would bill
 *   the project for whatever the finder likes.
 *
 * An unrestricted browser key is the single most commonly abused credential in
 * a mapping stack, and the abuse arrives as an invoice.
 */

/** Extra libraries are deliberately not requested — this map draws markers. */
const SCRIPT_ID = "google-maps-js-api";

type State = { ready: boolean; error: string | null };

export const GOOGLE_MAPS_BROWSER_KEY =
  process.env.NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY ?? "";

export function useGoogleMaps(): State {
  const [state, setState] = useState<State>(() => ({
    // Already loaded by an earlier mount — a second <script> would re-execute
    // the API and warn about being included twice.
    ready: typeof window !== "undefined" && Boolean(window.google?.maps),
    error: null,
  }));

  useEffect(() => {
    if (state.ready) return;

    if (!GOOGLE_MAPS_BROWSER_KEY) {
      setState({
        ready: false,
        error:
          "NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY is not set on this deployment, so the map cannot load.",
      });
      return;
    }

    const existing = document.getElementById(SCRIPT_ID) as HTMLScriptElement | null;
    if (existing) {
      // Mounted twice before the first load finished. Wait on the same tag
      // rather than adding a second one.
      existing.addEventListener("load", () => setState({ ready: true, error: null }));
      existing.addEventListener("error", () =>
        setState({ ready: false, error: "Google Maps failed to load." }),
      );
      return;
    }

    const script = document.createElement("script");
    script.id = SCRIPT_ID;
    script.async = true;
    script.defer = true;
    // `loading=async` is what Google asks for; without it the API logs a
    // performance warning on every page view.
    script.src =
      `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(GOOGLE_MAPS_BROWSER_KEY)}` +
      `&loading=async&v=quarterly`;

    script.addEventListener("load", () => setState({ ready: true, error: null }));
    script.addEventListener("error", () =>
      setState({
        ready: false,
        // The commonest cause by far, and the one nobody guesses: the key is
        // fine and the *referrer restriction* does not include this origin.
        error:
          "Google Maps failed to load. Check that this origin is listed in the key's website restrictions.",
      }),
    );

    document.head.appendChild(script);
  }, [state.ready]);

  return state;
}

/**
 * Map styling that follows the console's theme.
 *
 * Two hand-tuned styles rather than one: a bright basemap under a dark console
 * is the thing everybody notices and nobody can unsee, and Google's own dark
 * scheme is only available through a cloud-configured `mapId`, which is another
 * piece of infrastructure to keep in step with this repository.
 */
export const DARK_MAP_STYLE: google.maps.MapTypeStyle[] = [
  { elementType: "geometry", stylers: [{ color: "#1f2429" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#1f2429" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#8b949e" }] },
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
  { featureType: "road", elementType: "geometry", stylers: [{ color: "#2b3238" }] },
  { featureType: "road", elementType: "labels.text.fill", stylers: [{ color: "#9aa4ae" }] },
  { featureType: "road.highway", elementType: "geometry", stylers: [{ color: "#3a434b" }] },
  { featureType: "water", elementType: "geometry", stylers: [{ color: "#141a1f" }] },
  { featureType: "administrative", elementType: "geometry.stroke", stylers: [{ color: "#3a434b" }] },
];

export const LIGHT_MAP_STYLE: google.maps.MapTypeStyle[] = [
  // Points of interest are noise on an operations map: every café in Nairobi
  // competing for attention with the rider who has been idle for an hour.
  { featureType: "poi", stylers: [{ visibility: "off" }] },
  { featureType: "transit", stylers: [{ visibility: "off" }] },
];
