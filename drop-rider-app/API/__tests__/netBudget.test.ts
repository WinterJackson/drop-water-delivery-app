/**
 * The timeout is a function of the connection and the request, never a literal.
 *
 * Every app used to abort at a flat 15 seconds, which is a broadband number. On
 * a congested Kenyan cell a request that would have completed at 25 s was
 * aborted, retried twice and reported as a failure — three quarters of a minute
 * of spinner and three uploads of the same body over metered data, manufacturing
 * exactly the hang the timeout existed to prevent.
 *
 * These assert the shape of the policy rather than the exact constants, except
 * where a specific relationship is the point: an upload must always outlast a
 * read, and a slow connection must always get more patience than a fast one.
 */
import NetInfo from "@react-native-community/netinfo";

import { connectionQuality, kindForMethod, timeoutFor } from "../netBudget";

/** Drive the module's NetInfo subscription the way the platform would. */
function setConnection(state: Record<string, unknown>) {
  const listener = (NetInfo.addEventListener as jest.Mock).mock.calls[0]?.[0];
  expect(typeof listener).toBe("function");
  listener(state);
}

describe("kindForMethod", () => {
  it("treats a read as retryable and a write as not", () => {
    // A read can be abandoned and retried cheaply. A write cannot — the server
    // may already have applied it.
    expect(kindForMethod("GET")).toBe("read");
    expect(kindForMethod("HEAD")).toBe("read");
    expect(kindForMethod("POST")).toBe("write");
    expect(kindForMethod("PUT")).toBe("write");
    expect(kindForMethod("PATCH")).toBe("write");
    expect(kindForMethod("DELETE")).toBe("write");
  });

  it("defaults to a read when no method is given", () => {
    expect(kindForMethod(undefined)).toBe("read");
  });
});

describe("timeoutFor", () => {
  it("gives an upload the longest budget of the three", () => {
    // Aborting a proof-of-delivery photo at 90% at a customer's gate is
    // strictly worse than waiting, and it costs the data twice.
    expect(timeoutFor("upload")).toBeGreaterThan(timeoutFor("write"));
    expect(timeoutFor("write")).toBeGreaterThan(timeoutFor("read"));
  });

  it("defaults to the read budget", () => {
    expect(timeoutFor()).toBe(timeoutFor("read"));
  });

  it("never returns a budget short enough to manufacture a hang", () => {
    // The flat 15 s that caused the defect is the floor, not the ceiling.
    expect(timeoutFor("read")).toBeGreaterThanOrEqual(15_000);
  });
});

describe("classification by connection", () => {
  it("gives wifi the fast budget", () => {
    setConnection({ type: "wifi", isConnected: true });
    expect(connectionQuality()).toBe("fast");
  });

  it("treats 4G and 5G as fast", () => {
    setConnection({ type: "cellular", details: { cellularGeneration: "4g" } });
    expect(connectionQuality()).toBe("fast");
    setConnection({ type: "cellular", details: { cellularGeneration: "5g" } });
    expect(connectionQuality()).toBe("fast");
  });

  it("gives 2G three times the patience of wifi on a read", () => {
    setConnection({ type: "wifi", isConnected: true });
    const fast = timeoutFor("read");
    setConnection({ type: "cellular", details: { cellularGeneration: "2g" } });
    const slow = timeoutFor("read");

    expect(connectionQuality()).toBe("slow");
    expect(slow).toBe(fast * 3);
  });

  it("groups an unreported cellular generation with the middle, not the fast, tier", () => {
    // Guessing optimistically costs a real failure; guessing pessimistically
    // costs a few seconds nobody notices.
    setConnection({ type: "cellular", details: {} });
    expect(connectionQuality()).toBe("medium");
  });

  it("treats an unknown connection type as medium rather than fast", () => {
    setConnection({ type: "unknown" });
    expect(connectionQuality()).toBe("medium");
  });

  it("scales every kind together, so the ordering holds on any connection", () => {
    for (const state of [
      { type: "wifi" },
      { type: "cellular", details: { cellularGeneration: "3g" } },
      { type: "cellular", details: { cellularGeneration: "2g" } },
    ]) {
      setConnection(state);
      expect(timeoutFor("upload")).toBeGreaterThan(timeoutFor("write"));
      expect(timeoutFor("write")).toBeGreaterThan(timeoutFor("read"));
    }
  });
});
