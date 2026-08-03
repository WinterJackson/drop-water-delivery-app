"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult = { ok: true } | { ok: false; error: string };

/**
 * Record that a refund was settled outside the platform.
 *
 * Deliberately not a retry. A reversal that in fact succeeded but lost its
 * callback looks identical to one that failed, and retrying that pays the
 * customer twice out of the platform's own money.
 */
export async function settleRefund(orderId: string, reason: string): Promise<ActionResult> {
  const trimmed = reason.trim();
  if (trimmed.length < 8) {
    return {
      ok: false,
      error: "Say how it was settled — the row disappears from this screen once you do.",
    };
  }

  try {
    await post(`/api/admin/settlement/refunds/${orderId}/settle`, { reason: trimmed });
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  revalidatePath("/finance/settlement");
  return { ok: true };
}
