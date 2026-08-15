/**
 * Nothing the rider did offline is deleted silently.
 *
 * A rider works in and out of coverage all day. When a delivery completes on a
 * dead cell, the action goes to SQLite and is replayed later — and what happens
 * to it when the replay *fails* is the single most consequential rule in this
 * app, because a `delivered` action is the rider's proof of work and their pay.
 *
 * The defect this replaced deleted a 400/404/409 outright behind a toast. These
 * tests pin the distinction that fixed it: a disposable action may be dropped, an
 * irreplaceable one is flagged for the rider and for support, and neither is ever
 * quietly discarded.
 */
import { ApiError } from "@/API/errors";

const mockRunAsync = jest.fn().mockResolvedValue(undefined);
const mockGetAllAsync = jest.fn();
const mockApiFetch = jest.fn();

jest.mock("@/config/database", () => ({
  getDB: jest.fn(() => Promise.resolve({ runAsync: mockRunAsync, getAllAsync: mockGetAllAsync })),
}));
jest.mock("@/API/apiFetch", () => ({ apiFetch: (...args: unknown[]) => mockApiFetch(...args) }));

import { MAX_REPLAY_ATTEMPTS, flushOfflineQueue } from "../offlineQueue";

const token = () => Promise.resolve("jwt-token");

/** A queued action, defaulting to a completed delivery — the costly case. */
const action = (over: Record<string, unknown> = {}) => ({
  row_id: "row-1",
  id: "order-1",
  type: "UPDATE_DELIVERY_STATUS",
  payload: JSON.stringify({ status: "delivered" }),
  // Old enough that the backoff has always elapsed.
  created_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
  attempts: 0,
  last_error: null,
  needs_attention: 0,
  ...over,
});

/** The SQL a call issued, for asserting on what happened to the row. */
const statements = () => mockRunAsync.mock.calls.map(([sql]) => String(sql));
const deleted = () => statements().some((s) => s.includes("DELETE FROM offline_actions"));
const flagged = () => statements().some((s) => s.includes("needs_attention = 1"));

beforeEach(() => {
  jest.clearAllMocks();
  mockGetAllAsync.mockResolvedValue([]);
  mockApiFetch.mockResolvedValue({});
});

describe("a successful replay", () => {
  it("sends the action and removes it from the queue", async () => {
    mockGetAllAsync.mockResolvedValue([action()]);

    const result = await flushOfflineQueue(token);

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
    expect(result.sent).toBe(1);
    expect(deleted()).toBe(true);
  });

  it("replays the rider's own payload, not a reconstructed one", async () => {
    mockGetAllAsync.mockResolvedValue([
      action({ payload: JSON.stringify({ status: "delivered", empties_received: 3 }) }),
    ]);

    await flushOfflineQueue(token);

    const [, options] = mockApiFetch.mock.calls[0];
    expect(options.body).toEqual({ status: "delivered", empties_received: 3 });
    expect(options.token).toBe("jwt-token");
  });

  it("tells the caller which action synced, so the UI can update", async () => {
    mockGetAllAsync.mockResolvedValue([action()]);
    const onSynced = jest.fn();

    await flushOfflineQueue(token, onSynced);

    expect(onSynced).toHaveBeenCalledWith(expect.objectContaining({ row_id: "row-1" }));
  });
});

describe("a refusal the server will repeat", () => {
  it("flags a completed delivery instead of deleting it", async () => {
    // The defect: a 409 deleted the rider's proof of work behind a toast they
    // may not have been looking at.
    mockGetAllAsync.mockResolvedValue([action()]);
    mockApiFetch.mockRejectedValue(new ApiError("Order already completed.", 409));

    const result = await flushOfflineQueue(token);

    expect(flagged()).toBe(true);
    expect(deleted()).toBe(false);
    expect(result.needsAttention).toBe(1);
  });

  it("keeps the server's reason, so the rider is told why", async () => {
    mockGetAllAsync.mockResolvedValue([action()]);
    mockApiFetch.mockRejectedValue(new ApiError("This order was reassigned.", 409));

    await flushOfflineQueue(token);

    const flag = mockRunAsync.mock.calls.find(([sql]) => String(sql).includes("needs_attention = 1"));
    expect(flag?.[1]).toEqual(expect.arrayContaining(["This order was reassigned."]));
  });

  it("also protects a bottle rejection, which is evidence", async () => {
    mockGetAllAsync.mockResolvedValue([action({ type: "REJECT_BOTTLE", id: "order-9" })]);
    mockApiFetch.mockRejectedValue(new ApiError("Already resolved.", 400));

    await flushOfflineQueue(token);

    expect(flagged()).toBe(true);
    expect(deleted()).toBe(false);
  });

  it("flags an action type nothing can replay any more", async () => {
    // A retired action type has no endpoint to send to, so it is surfaced rather
    // than retried forever or dropped. Both known types are irreplaceable today,
    // so nothing is currently in the disposable branch.
    mockGetAllAsync.mockResolvedValue([action({ type: "SOMETHING_RETIRED" })]);

    const result = await flushOfflineQueue(token);

    expect(mockApiFetch).not.toHaveBeenCalled();
    expect(flagged()).toBe(true);
    expect(result.needsAttention).toBe(1);
  });
});

describe("a failure worth retrying", () => {
  it("counts an attempt and leaves the action queued", async () => {
    mockGetAllAsync.mockResolvedValue([action()]);
    mockApiFetch.mockRejectedValue(new ApiError("Server error", 500));

    const result = await flushOfflineQueue(token);

    expect(result.failed).toBe(1);
    expect(deleted()).toBe(false);
    expect(flagged()).toBe(false);
    expect(statements().some((s) => s.includes("SET attempts = ?"))).toBe(true);
  });

  it("retries a 401, because a token can be refreshed", async () => {
    // Deleting the rider's delivery because their token expired would be the
    // worst possible reading of "the server refused it".
    mockGetAllAsync.mockResolvedValue([action()]);
    mockApiFetch.mockRejectedValue(new ApiError("Session expired", 401));

    const result = await flushOfflineQueue(token);

    expect(deleted()).toBe(false);
    expect(result.failed).toBe(1);
  });

  it("retries a 429 rather than discarding the work", async () => {
    mockGetAllAsync.mockResolvedValue([action()]);
    mockApiFetch.mockRejectedValue(new ApiError("Slow down", 429));

    const result = await flushOfflineQueue(token);

    expect(deleted()).toBe(false);
    expect(result.failed).toBe(1);
  });

  it("gives up on a genuinely stuck action and surfaces it", async () => {
    mockGetAllAsync.mockResolvedValue([action({ attempts: MAX_REPLAY_ATTEMPTS - 1 })]);
    mockApiFetch.mockRejectedValue(new ApiError("Server error", 500));

    const result = await flushOfflineQueue(token);

    expect(flagged()).toBe(true);
    expect(result.needsAttention).toBe(1);
  });

  it("stops the whole flush on a transport failure", async () => {
    // The rest of the queue will fail the same way; burning an attempt on every
    // action at once would push them all towards needs_attention over one
    // tunnel.
    mockGetAllAsync.mockResolvedValue([
      action({ row_id: "row-1" }),
      action({ row_id: "row-2" }),
      action({ row_id: "row-3" }),
    ]);
    mockApiFetch.mockRejectedValue(new ApiError("offline", 0));

    await flushOfflineQueue(token);

    expect(mockApiFetch).toHaveBeenCalledTimes(1);
  });
});

describe("what the flush skips", () => {
  it("never re-sends an action already awaiting the rider", async () => {
    // Only an explicit tap on Pending Sync may retry one.
    mockGetAllAsync.mockResolvedValue([action({ needs_attention: 1 })]);

    const result = await flushOfflineQueue(token);

    expect(mockApiFetch).not.toHaveBeenCalled();
    expect(result.needsAttention).toBe(1);
  });

  it("waits out the backoff before retrying a recent failure", async () => {
    mockGetAllAsync.mockResolvedValue([
      action({ attempts: 3, created_at: new Date().toISOString() }),
    ]);

    await flushOfflineQueue(token);

    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it("does nothing without a token rather than sending unauthenticated", async () => {
    mockGetAllAsync.mockResolvedValue([action()]);

    const result = await flushOfflineQueue(() => Promise.resolve(null));

    expect(mockApiFetch).not.toHaveBeenCalled();
    expect(result).toEqual({ sent: 0, failed: 0, needsAttention: 0 });
  });

  it("is a no-op on an empty queue", async () => {
    const result = await flushOfflineQueue(token);
    expect(result).toEqual({ sent: 0, failed: 0, needsAttention: 0 });
  });

  it("survives a database that will not open", async () => {
    const { getDB } = require("@/config/database");
    (getDB as jest.Mock).mockResolvedValueOnce(null);

    await expect(flushOfflineQueue(token)).resolves.toEqual({
      sent: 0,
      failed: 0,
      needsAttention: 0,
    });
  });
});
