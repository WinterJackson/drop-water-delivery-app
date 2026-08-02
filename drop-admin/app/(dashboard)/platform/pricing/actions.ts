"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post, put } from "@/lib/api/server";

export type ActionResult<T = undefined> =
  | { ok: true; data: T }
  | { ok: false; error: string };

function fail(error: unknown): { ok: false; error: string } {
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

export type Quote = Record<string, string>;

export type Preview = {
  before: Quote;
  after: Quote;
  delta: Record<string, string>;
};

/**
 * Price a representative order under proposed values, without saving them.
 *
 * The whole point of this screen. A commission rate is an abstraction; "the
 * vendor receives KSH 41 less on a typical order" is not, and a decimal-place
 * slip is obvious in the second form and invisible in the first.
 */
export async function previewChanges(
  changes: Record<string, unknown>,
  sample: {
    product_total: number;
    distance_km: number;
    quantity: number;
    vendor_type: string;
    delivery_type: string;
    first_order: boolean;
    surge: boolean;
  },
): Promise<ActionResult<Preview>> {
  try {
    const data = await post<Preview>("/api/admin/config/preview", { changes, ...sample });
    return { ok: true, data };
  } catch (error) {
    return fail(error);
  }
}

/**
 * Save. The backend validates bounds and the cross-field invariants, audits the
 * before/after, and publishes a cache invalidation so every worker picks the
 * new values up — the apps see them on the next quote with no release.
 */
export async function saveChanges(
  changes: Record<string, unknown>,
  reason: string,
): Promise<ActionResult<{ message: string }>> {
  if (reason.trim().length < 3) {
    return { ok: false, error: "Say why — this is recorded against your account." };
  }
  if (Object.keys(changes).length === 0) {
    return { ok: false, error: "Nothing has changed." };
  }

  try {
    const data = await put<{ message: string }>("/api/admin/config", {
      changes,
      reason: reason.trim(),
    });
    revalidatePath("/platform/pricing");
    revalidatePath("/analytics");
    return { ok: true, data };
  } catch (error) {
    return fail(error);
  }
}
