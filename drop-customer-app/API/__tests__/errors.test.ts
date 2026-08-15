/**
 * Every failure reaches the user as the backend's own sentence.
 *
 * The rule these enforce: never show a raw status code, and never branch on the
 * *wording* of a message — branch on `ApiError.type` or `.status`. The defect
 * that motivated the module was a customer blocked by an outstanding deposit
 * (402), a locked cart (409) and an out-of-range address (400) all seeing the
 * same "Network error" toast, because every hook threw away FastAPI's `detail`.
 */
import {
  ApiError,
  errorMessage,
  extractDetailMessage,
  retryTransientOnly,
  toApiError,
} from "../errors";

describe("extractDetailMessage", () => {
  it("reads a plain HTTPException detail", () => {
    expect(extractDetailMessage("Store is closed right now.")).toBe(
      "Store is closed right now.",
    );
  });

  it("joins the field errors in a 422", () => {
    const detail = [
      { loc: ["body", "phone"], msg: "not a valid phone number", type: "value_error" },
      { loc: ["body", "qty"], msg: "must be at least 1", type: "value_error" },
    ];
    expect(extractDetailMessage(detail)).toBe(
      "not a valid phone number. must be at least 1",
    );
  });

  it("reads a nested object, as the cart's vendor conflict returns", () => {
    expect(
      extractDetailMessage({ type: "vendor_conflict", message: "Your cart has items from another store." }),
    ).toBe("Your cart has items from another store.");
  });

  it("returns null rather than a string for a body it cannot read", () => {
    // Null is what lets `toApiError` fall through to a status-appropriate
    // sentence instead of rendering "[object Object]".
    expect(extractDetailMessage({ unexpected: 1 })).toBeNull();
    expect(extractDetailMessage(null)).toBeNull();
    expect(extractDetailMessage([])).toBeNull();
  });
});

describe("toApiError", () => {
  it("prefers the backend's message over any fallback", () => {
    const error = toApiError(402, { detail: "Return 2 bottles to place a new order." });
    expect(error.message).toBe("Return 2 bottles to place a new order.");
    expect(error.status).toBe(402);
  });

  it("gives a status-appropriate sentence when the body says nothing", () => {
    expect(toApiError(403, {}).message).toBe("You don't have permission to do that.");
    expect(toApiError(0, null).message).toBe(
      "We couldn't reach the server. Check your connection and try again.",
    );
  });

  it("never leaves the user with a bare status code", () => {
    const error = toApiError(418, {});
    expect(error.message).toBe("Something went wrong. Please try again.");
    expect(error.message).not.toMatch(/418/);
  });

  it("carries the machine-readable discriminator so callers need not read prose", () => {
    // Branching on wording is what broke when a message was reworded; `type` is
    // the contract.
    const error = toApiError(409, {
      detail: { type: "vendor_conflict", message: "Cart belongs to another store." },
    });
    expect(error.type).toBe("vendor_conflict");
  });

  it("leaves type undefined when the backend did not send one", () => {
    expect(toApiError(400, { detail: "Bad address." }).type).toBeUndefined();
  });
});

describe("ApiError", () => {
  it("identifies a transport failure by status 0", () => {
    expect(new ApiError("offline", 0).isNetworkError).toBe(true);
    expect(new ApiError("nope", 500).isNetworkError).toBe(false);
  });

  it("treats 401 and 403 as auth failures", () => {
    expect(new ApiError("expired", 401).isAuthError).toBe(true);
    expect(new ApiError("forbidden", 403).isAuthError).toBe(true);
    expect(new ApiError("conflict", 409).isAuthError).toBe(false);
  });

  it("has no `.response` — reading one is the documented mistake", () => {
    // `err.response.data.type` is always undefined here, which is how the
    // vendor-conflict prompt silently stopped appearing.
    expect((new ApiError("x", 409) as any).response).toBeUndefined();
  });

  it("is a real Error, so `instanceof` and `.message` behave", () => {
    const error = new ApiError("Store is closed.", 409);
    expect(error).toBeInstanceOf(Error);
    expect(String(error)).toContain("Store is closed.");
  });
});

describe("retryTransientOnly", () => {
  const retry = retryTransientOnly(2);

  it("never retries a refusal", () => {
    // A 4xx is a decision, not a dropped packet. Retrying a 401 fires the
    // sign-out handler once per attempt.
    for (const status of [400, 401, 402, 403, 404, 409, 422, 429]) {
      expect(retry(0, new ApiError("no", status))).toBe(false);
    }
  });

  it("retries a transport failure up to the budget", () => {
    const offline = new ApiError("offline", 0);
    expect(retry(0, offline)).toBe(true);
    expect(retry(1, offline)).toBe(true);
    expect(retry(2, offline)).toBe(false);
  });

  it("retries a 5xx", () => {
    expect(retry(0, new ApiError("boom", 500))).toBe(true);
    expect(retry(0, new ApiError("gateway", 502))).toBe(true);
  });

  it("treats an unknown throw as transient", () => {
    // A thrown string or a TypeError from the transport has no status; it is
    // more likely a dropped connection than a considered refusal.
    expect(retry(0, new Error("boom"))).toBe(true);
  });

  it("honours a caller-supplied budget", () => {
    const once = retryTransientOnly(1);
    expect(once(0, new ApiError("offline", 0))).toBe(true);
    expect(once(1, new ApiError("offline", 0))).toBe(false);
  });
});

describe("errorMessage", () => {
  it("returns the backend's sentence for an ApiError", () => {
    expect(errorMessage(new ApiError("Store is closed right now.", 409))).toBe(
      "Store is closed right now.",
    );
  });

  it("falls back rather than rendering an empty toast", () => {
    expect(errorMessage(new Error(""), "Could not load orders.")).toBe(
      "Could not load orders.",
    );
    expect(errorMessage(undefined, "Could not load orders.")).toBe(
      "Could not load orders.",
    );
  });

  it("never renders [object Object]", () => {
    expect(errorMessage({ some: "shape" })).not.toContain("[object Object]");
  });

  it("reads a bare thrown object that happens to carry a message", () => {
    expect(errorMessage({ message: "Payment declined by M-Pesa." })).toBe(
      "Payment declined by M-Pesa.",
    );
  });
});
