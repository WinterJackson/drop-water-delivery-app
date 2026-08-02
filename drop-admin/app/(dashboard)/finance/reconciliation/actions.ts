"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult = { ok: true } | { ok: false; error: string };

/**
 * Mark a failed payment callback as handled.
 *
 * The reason is mandatory and is the whole point of the action. "Resolved" with
 * no explanation is indistinguishable from "hidden", and the next person needs
 * to know whether this was settled in the M-Pesa portal, refunded, or dismissed
 * as a duplicate callback for an order that was already paid.
 *
 * It moves no money. The fix goes through the ordinary tools; this records that
 * somebody did it.
 */
export async function resolveWebhook(id: string, reason: string): Promise<ActionResult> {
  const trimmed = reason.trim();
  // Matches the backend's `min_length=8`, so the refusal is written here in
  // words rather than arriving as a validation error nobody can read.
  if (trimmed.length < 8) {
    return {
      ok: false,
      error: "Say what you did about it — eight characters or more. It is recorded.",
    };
  }

  try {
    await post(`/api/admin/reconciliation/webhooks/${id}/resolve`, { reason: trimmed });
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  revalidatePath("/finance/reconciliation");
  revalidatePath("/");
  return { ok: true };
}
