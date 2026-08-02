"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult = { ok: true } | { ok: false; error: string };

/**
 * Record a verification decision on a store.
 *
 * Rejection deliberately does **not** suspend the store — the backend is
 * explicit about that, and this wording is what the vendor is shown. "We
 * haven't confirmed your paperwork" and "you may not trade" are different
 * statements, and conflating them takes a working business offline over a
 * missing document.
 */
export async function reviewVendor(
  vendorId: string,
  decision: "verified" | "rejected",
  reason: string,
): Promise<ActionResult> {
  const trimmed = reason.trim();
  if (trimmed.length < 3) {
    return { ok: false, error: "Give a reason — the vendor is shown this." };
  }

  try {
    await post(`/api/admin/people/vendors/${vendorId}/verification`, {
      decision,
      reason: trimmed,
    });
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  revalidatePath("/operations/vendors");
  revalidatePath("/people/vendors");
  revalidatePath(`/people/vendors/${vendorId}`);
  return { ok: true };
}
