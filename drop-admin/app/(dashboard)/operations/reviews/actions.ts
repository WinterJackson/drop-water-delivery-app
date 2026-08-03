"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult = { ok: true } | { ok: false; error: string };

/**
 * Take a review down, or put it back.
 *
 * Never a delete. A delete loses that the review existed, releases the unique
 * constraint so the customer can simply leave another, and strands the target's
 * rating counters on a row that is gone. The backend rebuilds the target's
 * rating from the visible reviews in the same transaction.
 */
export async function moderateReview(
  reviewId: string,
  hidden: boolean,
  reason: string,
): Promise<ActionResult> {
  const trimmed = reason.trim();
  if (trimmed.length < 8) {
    return {
      ok: false,
      error: "Give a reason — it is what the next moderator sees, not just the audit log.",
    };
  }

  try {
    await post(`/api/admin/reviews/${reviewId}/moderate`, { hidden, reason: trimmed });
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  revalidatePath("/operations/reviews");
  return { ok: true };
}
