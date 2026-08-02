# Maps architecture

How the three apps, the admin console and the backend divide up Google Maps.
Every map on this platform is Google — there is no OpenStreetMap basemap
anywhere. The short rule:

> **Client keys draw maps. They never call an API.**
> Anything that is an HTTP request to Google goes through the backend.

## Why it is split this way

A Google API key embedded in a mobile binary is extractable — `unzip`, read
`AndroidManifest.xml`, done. The only thing that makes that acceptable is an
*application restriction*: Android package + SHA-1, or iOS bundle id. Google
enforces those for the **Maps SDK**, so a lifted key is useless outside the app it
was minted for.

Web services (Directions, Places, Geocoding, Distance Matrix) are different. They
are plain HTTPS calls with the key in the query string, and an app restriction does
not meaningfully protect them. A key that can call Directions from JavaScript is a
key anyone can call Directions with, on your bill.

So there are two classes of key, and they are not interchangeable:

| | Where it lives | Restriction | Can call |
|---|---|---|---|
| **6 mobile keys** | `AndroidManifest.xml` / `Info.plist`, injected at build time | package+SHA-1 / bundle id, **Maps SDK only** | tile rendering, nothing else |
| **1 browser key** | the admin console's JS bundle | **HTTP referrer**, **Maps JavaScript API only** | tile rendering, nothing else |
| **1 server key** | `BackendAPI/.env`, never leaves the server | **IP address**, Directions API only | Directions (and any web service added later) |

The browser key sits in the same class as the six mobile ones: it is an **SDK**
key whose only job is to draw a map, made safe by an application restriction
rather than by secrecy. The restriction mechanism differs because the caller
does — package id for an APK, HTTP referrer for a web origin — but the rule it
enforces is identical, and neither may ever be granted a web service.

## Client keys — six of them

One per app per platform. A key carries exactly *one* application restriction, so a
key shared between Android and iOS cannot be restricted at all — which is precisely
how the original key ended up unrestricted and committed.

| App | Package / bundle | Env vars |
|---|---|---|
| drop-customer-app | `com.drop.customer` | `GOOGLE_MAPS_ANDROID_API_KEY`, `GOOGLE_MAPS_IOS_API_KEY` |
| drop-rider-app | `com.drop.rider` | same names, different values |
| drop-vendor-app | `com.drop.vendor` | same names, different values |

Each app has an `app.config.js` that reads those two variables and injects them into
`android.config.googleMaps.apiKey` / `ios.config.googleMapsApiKey`. `app.json` holds
no key. The variables are deliberately **not** `EXPO_PUBLIC_*`: they are consumed at
build time and belong in the native manifest, not the JS bundle.

Set them in each app's gitignored `.env` locally, and as EAS secrets for builds:

```bash
npx eas-cli secret:create --scope project --name GOOGLE_MAPS_ANDROID_API_KEY --value "…"
npx eas-cli secret:create --scope project --name GOOGLE_MAPS_IOS_API_KEY     --value "…"
```

Verify with `npx expo config --type prebuild` — **not** `--type public`, which
scrubs Maps keys out of the manifest. That scrubbing is also why nothing can read
the key back at runtime through `Constants.expoConfig`; three screens used to try
and were silently reading `undefined`.

Full Console walkthrough: [security/google-api-key-rotation.md](./security/google-api-key-rotation.md).

## Browser key — one, for the admin console

`/operations/map` in `drop-admin` draws riders, vendors, live orders, coverage
and demand on a Google map. It uses the **Maps JavaScript API**, loaded once per
page by `drop-admin/lib/maps/google-maps.ts`.

Env var: `NEXT_PUBLIC_GOOGLE_MAPS_BROWSER_API_KEY`, in `drop-admin/.env.local`
locally and in the hosting provider's environment (Vercel) for the deployment.

The `NEXT_PUBLIC_` prefix is not an oversight. The browser is what renders the
map, so the key has to reach it; there is no arrangement in which a JavaScript
map keeps its key private. What makes that acceptable is the same thing that
makes the six mobile keys acceptable — the restriction. In the Google Cloud
console, on this key alone:

- **Application restrictions → Websites**, listing exactly the console's origins:

  ```
  http://localhost:3000/*
  https://drop-admin-five.vercel.app/*
  https://drop-admin-five-*.vercel.app/*   # only if you use preview deployments
  ```

- **API restrictions → Maps JavaScript API**. Nothing else. Not Directions, not
  Places, not Geocoding.

An unrestricted browser key is the most commonly abused credential in a mapping
stack, and the abuse arrives as an invoice. Set both restrictions **before** the
key is ever deployed.

Everything the map draws comes from `GET /api/admin/map/*` on the backend —
the console's browser never calls Google for data, only for tiles.

## Server key — one

`GOOGLE_MAPS_SERVER_API_KEY` in `BackendAPI/.env` and in the Render service's
environment. Named `drop-backend-directions` in the Console, restricted to the
**Directions API** and to Render's outbound ranges:

```
74.220.51.0/24
74.220.59.0/24
```

Without it, `GET /api/maps/directions` returns 503 and the apps fall back to no
polyline.

> **Known limitation.** Render states those ranges are *shared with other Render
> services in the same region* — they are not unique to this workspace. So the IP
> restriction narrows the blast radius to "some Render tenant" rather than to this
> service alone. That is acceptable only because the key never leaves the server:
> exploiting it requires a separate leak of the key itself. If this key ever ends
> up somewhere less private, buy a Render **Dedicated IP** and narrow the
> restriction to it.

Verify the restriction is live by calling Google with the key from anywhere else —
a correct setup returns `REQUEST_DENIED` with *"This IP, site or mobile application
is not authorized"*. A different error means the restriction is not what you think:
`API not activated` means the Directions API is off; `OK` means the key is
unrestricted.

## `GET /api/maps/directions`

`BackendAPI/routes/maps_routes.py`. Authenticated; 60 requests/minute per client.

```
GET /api/maps/directions?origin_lat=&origin_lng=&dest_lat=&dest_lng=&mode=driving
→ { polyline, distance_meters, duration_seconds, cached }
```

Four things it does that a direct client call could not:

- **Holds the only web-service key**, IP-restricted, never shipped.
- **Caches in Redis for an hour**, keyed on coordinates rounded to 4 decimals
  (~11 m). A rider's GPS jitters constantly; without rounding, every tick would be
  a cache miss.
- **Reduces the payload** to the three fields the client draws. Google's response is
  large and carries quota metadata.
- **Swallows upstream error text.** Google's `error_message` names the project and
  sometimes the key; it is logged, never returned. The client sees a generic 502.

Failures are non-fatal by design: markers still render, only the polyline is
missing. A route lookup must never block a delivery in progress.

`tests/test_maps_directions.py` pins the key never appearing in a response, the
cache short-circuit, the coordinate rounding, and the error-message redaction.

## Rider route redraw

`ActiveDelivery.tsx` watches location at 5 s / 10 m. Requesting a route on every
tick was ~12 Directions calls per minute per active rider — enough to exhaust the
daily quota with a handful of riders, for a polyline that barely moves.

It now refetches only when the destination changes (pickup → dropoff on status
change) or the rider has moved more than `ROUTE_REFETCH_DISTANCE_M` (150 m).
Combined with the server cache, a full delivery costs a handful of upstream calls.

## Address search

`PlacesAutocomplete.tsx` (customer and rider) calls **Google Places, through the
proxy** — `GET /api/maps/places/autocomplete` and `/api/maps/places/details`.

It used to geocode against **Photon** (`photon.komoot.io`, OpenStreetMap), which
needs no key. That was a stopgap with three problems: no availability guarantee
from a free community endpoint, thin coverage of Kenyan estates and informal
addresses, and the platform's address quality resting on a third party nobody
has a contract with. Address quality is not cosmetic here — a mis-resolved
address is a failed delivery.

Switching to Google did **not** mean calling Google from the apps. The embedded
keys are Maps-SDK-restricted and Places rejects them outright, and a key
permissive enough to work from JS would be extractable from the APK. So the
component takes no `apiKey` prop at all any more; it sends the user's Clerk
token to the proxy, and the server key does the rest.

### Session tokens

Google bills autocomplete per *request* unless the keystrokes and the final
Details lookup share a **session token**, in which case the whole search is one
billable unit. The component mints one per search and rotates it the moment a
prediction is resolved, which is where the session genuinely ends.

The token is generated from `Date.now()` + `Math.random()`, not `uuid` —
`crypto.getRandomValues()` throws on React Native without a polyfill, which the
original component was already working around. Collision resistance is
irrelevant: it only needs to be unique among in-flight searches on one device.

Server-side it is validated (8–64 chars, alphanumeric plus `-_`) before being
forwarded, because it is client-supplied and ends up in a URL the server builds.
`tests/test_places_proxy.py` covers the injection shapes.

### Cost controls

| Control | Why |
|---|---|
| 2-character minimum | A shorter prefix matches half of Nairobi; the call is pure cost |
| 300 ms debounce (client) | One request per pause, not per keystroke |
| 5-minute prediction cache | Absorbs a user's own backtracking; short because this is not a warehouse for Google's data |
| 24-hour details cache | Coordinates do not move; place ids may be cached indefinitely, other fields only temporarily |
| `fields` mask on Details | Places Details is billed by SKU — asking for everything silently moves the request to a dearer tier |
| `components=country:ke` | Stops "Westlands" resolving to another continent |
| 60/minute rate limit | One user cannot burn the quota |

### Map tiles

Already Google. Every `MapView` uses `provider={PROVIDER_GOOGLE}`; the CartoDB
`UrlTile` overlays are commented out throughout. The "FREE OPEN SOURCE MVP MODE"
comments next to them describe the inactive branch.

### Reverse geocoding

`Location.reverseGeocodeAsync` (expo-location) is the **OS** geocoder — Google's
own on Android, Apple's on iOS. No key, no quota, no OpenStreetMap. Leave it.

## Adding another Google web service

1. New endpoint in `routes/maps_routes.py`, reusing `_server_key()`.
2. Cache it, with a TTL matching how fast the underlying data actually changes.
3. Reduce the response; never forward Google's payload verbatim.
4. Log upstream `error_message`, return a generic error.
5. Enable the API on the **server** key only. The six mobile keys stay
   Maps-SDK-only and the browser key stays Maps-JavaScript-API-only.
