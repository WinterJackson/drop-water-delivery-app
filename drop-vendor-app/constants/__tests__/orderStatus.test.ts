/**
 * The vendor's view of the order state machine.
 *
 * Statuses live in one place because two divergent colour maps in two screens is
 * how `mismatch_pending` and `pending_review` came to be missing from both — the
 * two states a vendor most needs to find, because they are the ones where an
 * order has stopped and is waiting on somebody.
 */
import {
  ORDER_FILTERS,
  ORDER_STATUS,
  isUnderReview,
  orderStatusStyle,
} from "../orderStatus";

/** Every status the backend can put on an order. */
const EVERY_BACKEND_STATUS = [
  "pending",
  "unassigned",
  "accepted",
  "preparing",
  "ready",
  "picked_up",
  "delivered",
  "cancelled",
  "rejected",
  "pending_review",
  "mismatch_pending",
] as const;

describe("orderStatusStyle", () => {
  it("never returns undefined, so a row always has a pill", () => {
    for (const status of EVERY_BACKEND_STATUS) {
      const style = orderStatusStyle(status);
      expect(style.label).toBeTruthy();
      expect(style.pill).toBeTruthy();
      expect(style.text).toBeTruthy();
    }
  });

  it("degrades readably for a status this build has never met", () => {
    // A new backend status must not render as "Unknown" with no clue what it is;
    // the raw name with underscores stripped is at least actionable.
    const style = orderStatusStyle("awaiting_something_new");
    expect(style.label).toBe("awaiting something new");
    expect(style.pill).toBeTruthy();
  });

  it("falls back for a missing status rather than throwing", () => {
    expect(orderStatusStyle(undefined).label).toBe("Unknown");
    expect(orderStatusStyle(null).label).toBe("Unknown");
    expect(orderStatusStyle("").label).toBe("Unknown");
  });

  it("gives the two review states an explanation the vendor can act on", () => {
    // A stopped order with a coloured pill and no sentence tells the shop
    // nothing about who they are waiting for.
    for (const status of ["pending_review", "mismatch_pending"]) {
      expect(orderStatusStyle(status).explanation).toBeTruthy();
    }
  });

  it("distinguishes every known status by label", () => {
    const labels = EVERY_BACKEND_STATUS.map((s) => orderStatusStyle(s).label);
    expect(new Set(labels).size).toBe(labels.length);
  });
});

describe("isUnderReview", () => {
  it("is true for exactly the two paused states", () => {
    expect(isUnderReview("pending_review")).toBe(true);
    expect(isUnderReview("mismatch_pending")).toBe(true);
  });

  it("is false for everything else, including terminal states", () => {
    for (const status of EVERY_BACKEND_STATUS.filter(
      (s) => s !== "pending_review" && s !== "mismatch_pending",
    )) {
      expect(isUnderReview(status)).toBe(false);
    }
  });

  it("is false for a missing status", () => {
    expect(isUnderReview(undefined)).toBe(false);
    expect(isUnderReview(null)).toBe(false);
  });
});

describe("ORDER_FILTERS", () => {
  it("sends enum values, not labels", () => {
    // `id` goes to the backend as `status_filter` and is compared lowercased
    // against `Order.order_status`. A label there matches nothing and the vendor
    // sees an empty list rather than an error.
    for (const filter of ORDER_FILTERS) {
      if (filter.id === "All") continue;
      expect(EVERY_BACKEND_STATUS).toContain(filter.id as never);
    }
  });

  it("offers the two stopped states, which is why they were added", () => {
    const ids = ORDER_FILTERS.map((f) => f.id);
    expect(ids).toContain("pending_review");
    expect(ids).toContain("mismatch_pending");
  });

  it("keeps All first, so the default view is everything", () => {
    expect(ORDER_FILTERS[0].id).toBe("All");
  });

  it("has a readable label for every filter and no duplicate ids", () => {
    const ids = ORDER_FILTERS.map((f) => f.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const filter of ORDER_FILTERS) {
      expect(filter.label.trim()).toBeTruthy();
    }
  });

  it("names only statuses the style map can render", () => {
    for (const filter of ORDER_FILTERS) {
      if (filter.id === "All") continue;
      expect(ORDER_STATUS[filter.id]).toBeDefined();
    }
  });
});
