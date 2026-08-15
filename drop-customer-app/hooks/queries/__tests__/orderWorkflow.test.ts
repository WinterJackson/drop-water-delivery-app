/**
 * The customer's view of the order state machine.
 *
 * Imported from `constants/orderStatus` rather than from the hook that
 * re-exports it: these are domain rules with no dependencies, and asserting
 * them must not require booting Clerk and React Query.
 *
 * Statuses live in one place for a reason: the Orders screen listed them inline
 * and drifted, so it covered neither `preparing` nor `ready` — an order being
 * packed matched no filter and showed no action at all. These tests assert the
 * grouping is exhaustive against what the backend can actually return, which is
 * the property that stops that recurring.
 */
import {
  CANCELLABLE_ORDER_STATUSES,
  ORDER_STATUS_GROUPS,
  isAwaitingPayment,
  matchesOrderFilter,
  statusesFor,
} from "@/constants/orderStatus";

/**
 * Every status `Orders.order_status` can hold, from the backend's own enum.
 *
 * `BackendAPI/tests/test_paging_integrity.py` asserts this list matches
 * `OrderStatusEnum`; it is restated here so a *client* grouping that stops
 * covering one fails this suite too, without a network call.
 */
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

describe("ORDER_STATUS_GROUPS", () => {
  it("covers every status the backend can return", () => {
    const grouped = Object.values(ORDER_STATUS_GROUPS).flat();
    const missing = EVERY_BACKEND_STATUS.filter((s) => !grouped.includes(s as never));
    expect(missing).toEqual([]);
  });

  it("puts each status in exactly one group", () => {
    // Two groups claiming `ready` means one order appears under two filters and
    // the counts stop adding up.
    const grouped = Object.values(ORDER_STATUS_GROUPS).flat();
    expect(new Set(grouped).size).toBe(grouped.length);
  });

  it("groups the two paused states with in-flight work, not with cancelled", () => {
    // `pending_review` and `mismatch_pending` resume; they do not terminate. A
    // customer whose order is under review has not had it cancelled.
    expect(ORDER_STATUS_GROUPS["In Transit"]).toContain("pending_review");
    expect(ORDER_STATUS_GROUPS["In Transit"]).toContain("mismatch_pending");
    expect(ORDER_STATUS_GROUPS.Cancelled).not.toContain("pending_review");
  });

  it("counts a vendor rejection as cancelled from the customer's side", () => {
    // Whoever ended it, the customer's water is not coming.
    expect(ORDER_STATUS_GROUPS.Cancelled).toEqual(
      expect.arrayContaining(["cancelled", "rejected"]),
    );
  });

  it("keeps an order being packed visible under In Transit", () => {
    // The exact regression: `preparing` and `ready` matched no filter.
    expect(matchesOrderFilter("preparing", "In Transit")).toBe(true);
    expect(matchesOrderFilter("ready", "In Transit")).toBe(true);
  });
});

describe("matchesOrderFilter", () => {
  it("matches every status under All", () => {
    for (const status of EVERY_BACKEND_STATUS) {
      expect(matchesOrderFilter(status, "All")).toBe(true);
    }
  });

  it("assigns every status to some filter", () => {
    // A status matching no filter is an order the customer cannot find.
    for (const status of EVERY_BACKEND_STATUS) {
      const filters = (Object.keys(ORDER_STATUS_GROUPS) as (keyof typeof ORDER_STATUS_GROUPS)[])
        .filter((filter) => matchesOrderFilter(status, filter));
      expect(filters).toHaveLength(1);
    }
  });

  it("does not match an unknown status to a specific filter", () => {
    expect(matchesOrderFilter("teleported", "Delivered")).toBe(false);
  });
});

describe("statusesFor", () => {
  it("sends nothing for All, so the server returns everything", () => {
    expect(statusesFor("All")).toBeUndefined();
  });

  it("sends a comma-separated group the backend validates against its enum", () => {
    expect(statusesFor("Cancelled")).toBe("cancelled,rejected");
    expect(statusesFor("Delivered")).toBe("delivered");
  });

  it("sends only names the backend knows", () => {
    // An unknown status renders as "you have no orders", so a typo here reads to
    // the customer as their history having been lost. The server 400s instead,
    // but only if every name we send is one it can check.
    for (const filter of Object.keys(ORDER_STATUS_GROUPS) as (keyof typeof ORDER_STATUS_GROUPS)[]) {
      for (const name of statusesFor(filter)!.split(",")) {
        expect(EVERY_BACKEND_STATUS).toContain(name as never);
      }
    }
  });
});

describe("CANCELLABLE_ORDER_STATUSES", () => {
  it("matches exactly what the backend will accept", () => {
    // `cancel_customer_order` allows these three and 400s on anything else, so
    // offering the button elsewhere only produces a rejection in front of the
    // customer.
    expect([...CANCELLABLE_ORDER_STATUSES].sort()).toEqual(
      ["accepted", "pending", "unassigned"].sort(),
    );
  });

  it("never offers cancellation once the order is on the bike", () => {
    for (const status of ["picked_up", "delivered", "cancelled", "rejected"]) {
      expect(CANCELLABLE_ORDER_STATUSES).not.toContain(status);
    }
  });
});

describe("isAwaitingPayment", () => {
  const order = (over: Record<string, unknown> = {}) =>
    ({
      order_status: "pending",
      payment_method: "mpesa",
      payment_status: "pending",
      ...over,
    }) as any;

  it("is true for an unpaid M-Pesa order", () => {
    expect(isAwaitingPayment(order())).toBe(true);
    expect(isAwaitingPayment(order({ payment_status: "processing" }))).toBe(true);
  });

  it("is false for cash on delivery", () => {
    // There is no STK push to wait for; the money arrives at the door.
    expect(isAwaitingPayment(order({ payment_method: "cash" }))).toBe(false);
  });

  it("is false once the order has ended", () => {
    // A cancelled order with a stuck payment_status must not keep prompting the
    // customer to pay for water that is not coming.
    for (const status of ["cancelled", "rejected", "delivered"]) {
      expect(isAwaitingPayment(order({ order_status: status }))).toBe(false);
    }
  });

  it("is false once payment has settled", () => {
    expect(isAwaitingPayment(order({ payment_status: "paid" }))).toBe(false);
  });

  it("treats a missing payment_status as still owing", () => {
    // Failing open here would hide the pay prompt on an order nobody has paid.
    expect(isAwaitingPayment(order({ payment_status: undefined }))).toBe(true);
  });

  it("is false for no order at all", () => {
    expect(isAwaitingPayment(null)).toBe(false);
    expect(isAwaitingPayment(undefined)).toBe(false);
  });
});
