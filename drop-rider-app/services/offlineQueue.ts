/**
 * Replay of actions the rider took while offline.
 *
 * **The two defects this replaces.** The whole flush used to live inside a
 * `NetInfo.addEventListener` callback, so a replay that failed scheduled no
 * retry — nothing ran again until the next *connectivity transition event*. A
 * completed delivery that failed to sync because a token had just expired, or
 * because the API was restarting, sat in SQLite indefinitely while the device
 * stayed online: the rider was not paid, the customer was not notified, and the
 * order stayed `picked_up`. Nothing surfaced it.
 *
 * And a 400/404/409 during replay *deleted* the action outright behind a toast.
 * For a `delivered` action that is the rider's proof of work being destroyed
 * with a transient message they may not even have been looking at.
 *
 * **What replaces it.** `flushOfflineQueue()` is callable from anywhere and is
 * driven from four places (see `hooks/useNetworkQueue`): the NetInfo listener,
 * app foreground, a timer while the queue is non-empty, and the Pending Sync
 * screen's manual retry. Failures back off, and an action that exhausts its
 * attempts is marked `needs_attention` rather than deleted, so it can be shown
 * to the rider and to support.
 */
import { getDB } from "@/config/database";
import { ApiError, errorMessage } from "@/API/errors";
import { apiFetch } from "@/API/apiFetch";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";

export interface QueuedAction {
  row_id: string;
  id: string;
  type: string;
  payload: string;
  created_at: string;
  attempts: number;
  last_error: string | null;
  needs_attention: number;
}

/**
 * After this many failures the action stops being retried automatically and is
 * surfaced to the rider instead. High enough to ride out a long outage; low
 * enough that a genuinely broken action does not retry forever.
 */
export const MAX_REPLAY_ATTEMPTS = 10;

/** Exponential, capped: 30s, 1m, 2m, 4m, … 30m. */
function backoffMs(attempts: number): number {
  return Math.min(30_000 * 2 ** Math.max(0, attempts - 1), 30 * 60_000);
}

function isDue(action: QueuedAction, now: number): boolean {
  if (action.needs_attention) return false;
  if (action.attempts === 0) return true;
  const last = Date.parse(action.created_at);
  return now - last >= backoffMs(action.attempts) || Number.isNaN(last);
}

/** Actions the rider must be told about rather than have silently dropped. */
const IRREPLACEABLE = new Set(["UPDATE_DELIVERY_STATUS", "REJECT_BOTTLE"]);

function endpointFor(action: QueuedAction): { url: string; method: "PUT" | "POST" } | null {
  switch (action.type) {
    case "UPDATE_DELIVERY_STATUS":
      return { url: RiderApiRoutes.UpdateDeliveryStatus(action.id).path, method: "PUT" };
    case "REJECT_BOTTLE":
      return { url: RiderApiRoutes.ReportBottleRejection(action.id).path, method: "POST" };
    default:
      return null;
  }
}

// One flush at a time. Two overlapping NetInfo events used to be able to replay
// the same action twice — which, for a delivery completion, means two settlement
// attempts.
let flushing = false;

export interface FlushResult {
  sent: number;
  failed: number;
  needsAttention: number;
}

export async function flushOfflineQueue(
  getToken: () => Promise<string | null>,
  onSynced?: (action: QueuedAction) => void
): Promise<FlushResult> {
  const result: FlushResult = { sent: 0, failed: 0, needsAttention: 0 };
  if (flushing) return result;

  const db = await getDB();
  if (!db) return result;

  flushing = true;
  try {
    const actions = (await db.getAllAsync(
      `SELECT * FROM offline_actions ORDER BY created_at ASC`
    )) as QueuedAction[];
    if (!actions || actions.length === 0) return result;

    const token = await getToken();
    if (!token) return result;

    const now = Date.now();
    for (const action of actions) {
      if (action.needs_attention) {
        result.needsAttention += 1;
        continue;
      }
      if (!isDue(action, now)) continue;

      const endpoint = endpointFor(action);
      if (!endpoint) {
        // An action type nobody handles any more. Nothing can replay it.
        await markNeedsAttention(db, action, "This action is no longer supported.");
        result.needsAttention += 1;
        continue;
      }

      try {
        await apiFetch(endpoint.url, {
          method: endpoint.method,
          token,
          body: JSON.parse(action.payload),
        });
        await db.runAsync(`DELETE FROM offline_actions WHERE row_id = ?`, [action.row_id]);
        result.sent += 1;
        onSynced?.(action);
        if (__DEV__) console.log(`[offlineQueue] synced ${action.type} ${action.row_id}`);
      } catch (e) {
        const status = e instanceof ApiError ? e.status : 0;
        const reason = errorMessage(e);

        // A 4xx will say the same thing on every future attempt. For anything
        // disposable, drop it. For a delivery completion or a bottle rejection,
        // flag it — that is the rider's evidence and their pay, and deleting it
        // with a toast is how work disappeared.
        if (status >= 400 && status < 500 && status !== 401 && status !== 429) {
          if (IRREPLACEABLE.has(action.type)) {
            await markNeedsAttention(db, action, reason);
            result.needsAttention += 1;
          } else {
            await db.runAsync(`DELETE FROM offline_actions WHERE row_id = ?`, [action.row_id]);
          }
          continue;
        }

        const attempts = (action.attempts ?? 0) + 1;
        if (attempts >= MAX_REPLAY_ATTEMPTS) {
          await markNeedsAttention(db, action, reason);
          result.needsAttention += 1;
        } else {
          await db.runAsync(
            `UPDATE offline_actions SET attempts = ?, last_error = ?, created_at = ? WHERE row_id = ?`,
            [attempts, reason, new Date().toISOString(), action.row_id]
          );
          result.failed += 1;
        }

        // A transport failure means the rest of the queue will fail the same
        // way; stop rather than burning attempts on all of them at once.
        if (status === 0) break;
      }
    }
  } catch (e) {
    if (__DEV__) console.warn("[offlineQueue] flush failed:", e);
  } finally {
    flushing = false;
  }
  return result;
}

async function markNeedsAttention(db: any, action: QueuedAction, reason: string) {
  await db.runAsync(
    `UPDATE offline_actions SET needs_attention = 1, last_error = ?, attempts = ? WHERE row_id = ?`,
    [reason, (action.attempts ?? 0) + 1, action.row_id]
  );
  if (__DEV__) console.warn(`[offlineQueue] ${action.type} ${action.row_id} needs attention: ${reason}`);
}

/** How many actions are waiting, and how many are stuck. Drives the badge. */
export async function getQueueStatus(): Promise<{ pending: number; needsAttention: number }> {
  const db = await getDB();
  if (!db) return { pending: 0, needsAttention: 0 };
  try {
    const rows = (await db.getAllAsync(
      `SELECT needs_attention, COUNT(*) AS n FROM offline_actions GROUP BY needs_attention`
    )) as { needs_attention: number; n: number }[];
    let pending = 0;
    let needsAttention = 0;
    for (const row of rows) {
      if (row.needs_attention) needsAttention += row.n;
      else pending += row.n;
    }
    return { pending, needsAttention };
  } catch {
    return { pending: 0, needsAttention: 0 };
  }
}

/** Everything the Pending Sync screen shows. */
export async function getQueuedActionsDetailed(): Promise<QueuedAction[]> {
  const db = await getDB();
  if (!db) return [];
  try {
    return (await db.getAllAsync(
      `SELECT * FROM offline_actions ORDER BY created_at ASC`
    )) as QueuedAction[];
  } catch {
    return [];
  }
}

/** Put a stuck action back in the automatic rotation. */
export async function retryQueuedAction(rowId: string): Promise<void> {
  const db = await getDB();
  if (!db) return;
  try {
    await db.runAsync(
      `UPDATE offline_actions SET needs_attention = 0, attempts = 0, last_error = NULL, created_at = ? WHERE row_id = ?`,
      [new Date().toISOString(), rowId]
    );
  } catch (e) {
    if (__DEV__) console.warn("[offlineQueue] retry reset failed:", e);
  }
}

/**
 * Discard an action for good. Only ever from an explicit rider action in the
 * Pending Sync screen — never automatically.
 */
export async function discardQueuedAction(rowId: string): Promise<void> {
  const db = await getDB();
  if (!db) return;
  try {
    await db.runAsync(`DELETE FROM offline_actions WHERE row_id = ?`, [rowId]);
  } catch (e) {
    if (__DEV__) console.warn("[offlineQueue] discard failed:", e);
  }
}
