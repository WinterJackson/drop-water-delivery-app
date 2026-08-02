/**
 * Background location reporting for an in-progress delivery.
 *
 * **Why this exists.** Location used to be watched with
 * `Location.watchPositionAsync` inside `ActiveDelivery`'s effect, and each fix
 * was pushed over the WebSocket. Both halves of that fail in the normal case:
 *
 *  - The effect only runs while the screen is mounted and the app foregrounded.
 *    The rider taps "Navigate" and switches to their maps app for the whole
 *    delivery, so tracking stopped at the moment tracking started mattering.
 *  - A socket send with no socket was swallowed by a `try/catch` that only
 *    logged, so every coordinate produced in patchy coverage was simply lost.
 *
 * The customer app builds a whole WebSocket + REST fallback for *reading* the
 * rider's position. There was nothing writing it.
 *
 * **The design.** An `expo-task-manager` task receives fixes from the OS —
 * backed by an Android foreground service and the iOS `location` background
 * mode, so it keeps running with the app backgrounded and the screen locked.
 * Every fix is written to SQLite first and only then POSTed in a batch to
 * `POST /api/rider/location-ping`. Nothing is dropped because the network was
 * down or a token had expired; the buffer drains on the next successful flush.
 * The WebSocket stays as the low-latency path when a socket happens to be open.
 *
 * **The token.** A background task has no React context, so it cannot call
 * Clerk's `getToken()` directly. `useRiderLocationTracking` publishes the
 * provider into this module while the app is mounted, which covers the case
 * that matters: the JS runtime stays alive for as long as the foreground
 * service does. If the OS relaunches the app headlessly the provider is unset,
 * and fixes accumulate in SQLite until the rider next opens the app — which is
 * exactly what the buffer is for.
 */
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import AsyncStorage from "@react-native-async-storage/async-storage";

import { apiFetch } from "@/API/apiFetch";
import { ApiError } from "@/API/errors";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { getDB } from "@/config/database";

export const RIDER_LOCATION_TASK = "drop-rider-location";

/** Which order these fixes belong to. Survives a headless relaunch. */
const TRACKED_ORDER_KEY = "drop-rider:tracked-order-id";

/** Matches `MAX_LOCATION_PINGS_PER_BATCH` on the server. */
const MAX_PINGS_PER_FLUSH = 120;

/**
 * `Balanced` + 25 m, not `High` + 10 m every 5 s. High accuracy keeps the GPS
 * radio hot continuously, which is the single largest battery cost in the app,
 * and a delivery dot on a city map cannot show the difference. 25 m is roughly
 * a quarter of a block.
 */
const TRACKING_OPTIONS: Location.LocationTaskOptions = {
  accuracy: Location.Accuracy.Balanced,
  timeInterval: 15_000,
  distanceInterval: 25,
  // A stationary rider (waiting at the vendor, in traffic) should not keep
  // producing fixes; the OS batches them until they actually move.
  deferredUpdatesInterval: 30_000,
  deferredUpdatesDistance: 50,
  pausesUpdatesAutomatically: false,
  activityType: Location.ActivityType.AutomotiveNavigation,
  // iOS: the blue bar. Required for honest disclosure and by App Review.
  showsBackgroundLocationIndicator: true,
  foregroundService: {
    notificationTitle: "Delivery in progress",
    notificationBody: "Drop is sharing your location with the customer.",
    notificationColor: "#1e88e5",
  },
};

// ── Token bridge ─────────────────────────────────────────────────────────────

type TokenProvider = () => Promise<string | null>;

let tokenProvider: TokenProvider | null = null;

/** Called by `useRiderLocationTracking` while the app is mounted. */
export function setLocationTokenProvider(provider: TokenProvider | null) {
  tokenProvider = provider;
}

// ── The on-disk buffer ───────────────────────────────────────────────────────

let bufferReady = false;

async function getBuffer() {
  const db = await getDB();
  if (!db) return null;
  if (!bufferReady) {
    try {
      await db.execAsync(`
        CREATE TABLE IF NOT EXISTS location_pings (
          row_id INTEGER PRIMARY KEY AUTOINCREMENT,
          lat REAL NOT NULL,
          lng REAL NOT NULL,
          heading REAL,
          speed REAL,
          order_id TEXT,
          ts REAL NOT NULL
        );
      `);
      bufferReady = true;
    } catch (e) {
      if (__DEV__) console.warn("[locationTracking] buffer init failed:", e);
      return null;
    }
  }
  return db;
}

interface BufferedPing {
  row_id: number;
  lat: number;
  lng: number;
  heading: number | null;
  speed: number | null;
  order_id: string | null;
  ts: number;
}

async function bufferPings(locations: Location.LocationObject[], orderId: string | null) {
  const db = await getBuffer();
  if (!db) return;
  try {
    for (const loc of locations) {
      // A fix at exactly (0,0) is "no fix", not the Gulf of Guinea. The server
      // rejects these too; dropping them here saves the round trip.
      if (!loc?.coords) continue;
      const { latitude, longitude } = loc.coords;
      if (latitude === 0 && longitude === 0) continue;
      await db.runAsync(
        `INSERT INTO location_pings (lat, lng, heading, speed, order_id, ts) VALUES (?, ?, ?, ?, ?, ?)`,
        [
          latitude,
          longitude,
          loc.coords.heading ?? null,
          loc.coords.speed ?? null,
          orderId,
          (loc.timestamp ?? Date.now()) / 1000,
        ]
      );
    }
  } catch (e) {
    if (__DEV__) console.warn("[locationTracking] buffer write failed:", e);
  }
}

/**
 * Trim the buffer so a rider who spends a long shift offline cannot fill the
 * device. Oldest first: a stale position is worth less than a recent one.
 */
const MAX_BUFFERED_PINGS = 2_000;

async function trimBuffer() {
  const db = await getBuffer();
  if (!db) return;
  try {
    await db.runAsync(
      `DELETE FROM location_pings WHERE row_id NOT IN (
         SELECT row_id FROM location_pings ORDER BY row_id DESC LIMIT ?
       )`,
      [MAX_BUFFERED_PINGS]
    );
  } catch {
    /* trimming is housekeeping; never let it break a delivery */
  }
}

// ── Flushing ─────────────────────────────────────────────────────────────────

let flushing = false;
let lastFlushAt = 0;

/**
 * Don't POST on every fix. The foreground watcher can produce one every few
 * seconds in traffic, and the server coalesces them anyway — batching costs
 * nothing in freshness and saves the rider's data and battery.
 */
const MIN_FLUSH_INTERVAL_MS = 10_000;

/**
 * Send everything buffered. Safe to call from anywhere and at any time — the
 * mutex means two callers (the task and the app foregrounding) cannot double-send.
 *
 * Pass `force` when the pings must go now rather than at the next interval: the
 * end of a delivery, or the app returning to the foreground with a backlog.
 *
 * Returns the number of pings accepted by the server.
 */
export async function flushLocationPings(options?: { force?: boolean }): Promise<number> {
  if (flushing) return 0;
  if (!tokenProvider) return 0;
  if (!options?.force && Date.now() - lastFlushAt < MIN_FLUSH_INTERVAL_MS) return 0;
  lastFlushAt = Date.now();

  const db = await getBuffer();
  if (!db) return 0;

  flushing = true;
  let sent = 0;
  try {
    // Loop so a long offline stretch drains rather than trickling one batch per
    // fix, but stop at the first failure — retrying immediately would just fail
    // the same way.
    for (;;) {
      const rows = (await db.getAllAsync(
        `SELECT * FROM location_pings ORDER BY row_id ASC LIMIT ?`,
        [MAX_PINGS_PER_FLUSH]
      )) as BufferedPing[];
      if (!rows || rows.length === 0) break;

      const token = await tokenProvider();
      if (!token) break;

      try {
        await apiFetch(RiderApiRoutes.LocationPing.path, {
          method: "POST",
          token,
          body: {
            pings: rows.map((r) => ({
              lat: r.lat,
              lng: r.lng,
              heading: r.heading,
              speed: r.speed,
              order_id: r.order_id,
              timestamp: r.ts,
            })),
          },
        });
      } catch (e) {
        const status = e instanceof ApiError ? e.status : 0;

        // 4xx is a refusal, not a dropped packet: the server will say the same
        // thing next time, so holding these forever would wedge the buffer. 401
        // is the exception — the token was stale, and the next flush gets a
        // fresh one, so keep the data. So is 403, which is what an unapproved
        // rider gets and which approval will fix.
        if (status >= 400 && status < 500 && status !== 401 && status !== 403 && status !== 429) {
          await db.runAsync(
            `DELETE FROM location_pings WHERE row_id <= ?`,
            [rows[rows.length - 1].row_id]
          );
          if (__DEV__) console.warn(`[locationTracking] dropped ${rows.length} pings: ${status}`);
        }
        break;
      }

      await db.runAsync(
        `DELETE FROM location_pings WHERE row_id <= ?`,
        [rows[rows.length - 1].row_id]
      );
      sent += rows.length;
      if (rows.length < MAX_PINGS_PER_FLUSH) break;
    }
  } catch (e) {
    // Offline. The buffer keeps them; the next flush sends them.
    if (__DEV__) console.warn("[locationTracking] flush failed:", e);
  } finally {
    flushing = false;
  }
  return sent;
}

// ── The task ─────────────────────────────────────────────────────────────────
//
// Defined at module scope. A task must be registered before the OS delivers to
// it, including on a headless relaunch, which is why this module is imported
// from the root layout rather than from the screen that starts tracking.

TaskManager.defineTask(RIDER_LOCATION_TASK, async ({ data, error }: any) => {
  if (error) {
    if (__DEV__) console.warn("[locationTracking] task error:", error.message);
    return;
  }
  const locations: Location.LocationObject[] = data?.locations ?? [];
  if (locations.length === 0) return;

  const orderId = await AsyncStorage.getItem(TRACKED_ORDER_KEY);
  await bufferPings(locations, orderId);
  await trimBuffer();
  await flushLocationPings();
});

/**
 * Record a fix produced by the *foreground* watcher on the same durable path.
 *
 * Two cases need this. The rider who granted "while using the app" but not
 * "always" gets no background task at all, and their positions would otherwise
 * exist only as socket sends. And any rider whose socket happens to be down
 * loses the fix entirely — that `try/catch` around `sendMessage` only logged.
 * Buffering first means the coordinate survives either way.
 */
export async function recordForegroundFix(
  location: Location.LocationObject,
  orderId: string | null
): Promise<void> {
  await bufferPings([location], orderId);
  await flushLocationPings();
}

// ── Permissions ──────────────────────────────────────────────────────────────

export type LocationPermissionResult =
  | "granted"
  | "foreground-only"
  | "denied";

/**
 * Ask for background location.
 *
 * Deliberately *not* called at launch. Both platforms show a much lower grant
 * rate for an "always" prompt that arrives before the user has seen why it is
 * needed, and Android 11+ will not even show the always option in the same
 * prompt as the foreground one. Call this at first pickup, after explaining.
 */
export async function requestTrackingPermissions(): Promise<LocationPermissionResult> {
  const foreground = await Location.requestForegroundPermissionsAsync();
  if (foreground.status !== "granted") return "denied";

  const background = await Location.requestBackgroundPermissionsAsync();
  return background.status === "granted" ? "granted" : "foreground-only";
}

export async function hasBackgroundPermission(): Promise<boolean> {
  try {
    const { status } = await Location.getBackgroundPermissionsAsync();
    return status === "granted";
  } catch {
    return false;
  }
}

// ── Start / stop ─────────────────────────────────────────────────────────────

export async function isTracking(): Promise<boolean> {
  try {
    return await Location.hasStartedLocationUpdatesAsync(RIDER_LOCATION_TASK);
  } catch {
    return false;
  }
}

/**
 * Begin reporting for `orderId`. Idempotent: called again for the same order it
 * does nothing, and for a different order it just re-points the buffer.
 *
 * Returns false when tracking could not start, so the caller can tell the rider
 * rather than silently delivering with no tracking.
 */
export async function startRiderLocationTracking(orderId: string): Promise<boolean> {
  try {
    await AsyncStorage.setItem(TRACKED_ORDER_KEY, orderId);

    if (await isTracking()) return true;

    if (!(await hasBackgroundPermission())) return false;

    await Location.startLocationUpdatesAsync(RIDER_LOCATION_TASK, TRACKING_OPTIONS);
    return true;
  } catch (e) {
    if (__DEV__) console.warn("[locationTracking] start failed:", e);
    return false;
  }
}

/**
 * Stop reporting and flush whatever is left.
 *
 * The flush matters: the last few fixes of a delivery are the ones that show
 * the rider actually reached the door.
 */
export async function stopRiderLocationTracking(): Promise<void> {
  try {
    if (await isTracking()) {
      await Location.stopLocationUpdatesAsync(RIDER_LOCATION_TASK);
    }
  } catch (e) {
    if (__DEV__) console.warn("[locationTracking] stop failed:", e);
  } finally {
    await AsyncStorage.removeItem(TRACKED_ORDER_KEY);
    await flushLocationPings({ force: true });
  }
}

/** Sign-out teardown: no orphaned foreground service, no other rider's trail. */
export async function clearLocationTracking(): Promise<void> {
  try {
    if (await isTracking()) {
      await Location.stopLocationUpdatesAsync(RIDER_LOCATION_TASK);
    }
  } catch {
    /* nothing to stop */
  }
  await AsyncStorage.removeItem(TRACKED_ORDER_KEY);
  const db = await getBuffer();
  if (db) {
    try {
      await db.execAsync("DELETE FROM location_pings;");
    } catch {
      /* best effort */
    }
  }
  setLocationTokenProvider(null);
}
