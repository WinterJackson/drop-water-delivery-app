"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult<T = undefined> = { ok: true; data: T } | { ok: false; error: string };

function fail(error: unknown): { ok: false; error: string } {
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

/**
 * Cancels the order. Does **not** refund.
 *
 * `refund_service` owns the M-Pesa reversal and its idempotency key. A second
 * path to move money is how a refund gets sent twice — so the response says
 * whether one is still owed and the operator raises it deliberately.
 */
export async function cancelOrder(
  orderId: string,
  reason: string,
): Promise<ActionResult<{ refund_required: boolean }>> {
  if (reason.trim().length < 3) {
    return { ok: false, error: "Give a reason — the customer is shown this." };
  }
  try {
    const data = await post<{ refund_required: boolean }>(
      `/api/admin/orders/${orderId}/cancel`,
      { reason: reason.trim() },
    );
    revalidatePath("/operations/orders");
    return { ok: true, data };
  } catch (error) {
    return fail(error);
  }
}

export async function reassignOrder(
  orderId: string,
  riderId: string,
  reason: string,
): Promise<ActionResult> {
  if (reason.trim().length < 3) return { ok: false, error: "Give a reason." };
  if (!riderId.trim()) return { ok: false, error: "Choose a rider." };
  try {
    await post(
      `/api/admin/orders/${orderId}/reassign?rider_id=${encodeURIComponent(riderId.trim())}`,
      { reason: reason.trim() },
    );
    revalidatePath("/operations/orders");
    return { ok: true, data: undefined };
  } catch (error) {
    return fail(error);
  }
}

export async function resolveDispute(
  ticketId: string,
  // The ledger's vocabulary: `approved` means the rider's rejection stands.
  outcome: "approved" | "denied",
  reason: string,
): Promise<ActionResult> {
  if (reason.trim().length < 3) {
    return { ok: false, error: "Give a reason — the rider is shown this." };
  }
  try {
    await post(`/api/admin/disputes/${ticketId}/resolve`, { outcome, reason: reason.trim() });
    revalidatePath("/operations/disputes");
    return { ok: true, data: undefined };
  } catch (error) {
    return fail(error);
  }
}
