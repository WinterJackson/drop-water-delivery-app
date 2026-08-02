"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult = { ok: true } | { ok: false; error: string };

/**
 * Take a product off the shelf, or put it back.
 *
 * Never a delete — order history references products, and removing one turns
 * every past order that contained it into a receipt with a hole in it.
 *
 * The reason is mandatory because this is somebody's livelihood coming off the
 * shelf, and "why is my product gone" deserves an answer that is not a
 * recollection.
 */
export async function setAvailability(
  productId: string,
  listed: boolean,
  reason: string,
): Promise<ActionResult> {
  const trimmed = reason.trim();
  if (trimmed.length < 8) {
    return { ok: false, error: "Give a reason — it is recorded against the change." };
  }

  try {
    await post(`/api/admin/catalogue/${productId}/availability`, {
      listed,
      reason: trimmed,
    });
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  revalidatePath("/operations/catalogue");
  return { ok: true };
}
