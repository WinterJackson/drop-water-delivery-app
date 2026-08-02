"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult = { ok: true; message?: string } | { ok: false; error: string };

/**
 * Write off, or write on, a rider's bottle debt.
 *
 * Goes through the ledger, never the counter. Editing the registry counter
 * directly — which is what people did before this existed — breaks the
 * invariant the ledger maintains and leaves no reason and no author.
 */
export async function adjustBottles(input: {
  riderId: string;
  vendorId: string;
  capacity: number;
  quantity: number;
  reason: string;
}): Promise<ActionResult> {
  const reason = input.reason.trim();
  if (reason.length < 8) {
    return { ok: false, error: "Give a reason — it is stored on the ledger entry itself." };
  }
  if (!Number.isInteger(input.quantity) || input.quantity === 0) {
    return { ok: false, error: "Enter a whole number of bottles, positive or negative." };
  }

  try {
    await post("/api/admin/bottles/adjust", {
      rider_id: input.riderId,
      vendor_id: input.vendorId,
      capacity: input.capacity,
      quantity: input.quantity,
      reason,
    });
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  revalidatePath("/operations/bottles");
  return { ok: true };
}

/**
 * Rewrite drifted registry counters from the ledger.
 *
 * One direction only. The ledger is append-only and attributed; the counter is
 * a denormalisation of it, so the ledger wins by construction.
 */
export async function reseatCounters(reason: string): Promise<ActionResult> {
  const trimmed = reason.trim();
  if (trimmed.length < 8) {
    return { ok: false, error: "Say what caused the drift — the next person needs it." };
  }

  let repaired = 0;
  try {
    const result = await post<{ repaired: number }>("/api/admin/bottles/reseat", {
      reason: trimmed,
    });
    repaired = result.repaired;
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  revalidatePath("/operations/bottles");
  return {
    ok: true,
    message: repaired === 0 ? "Nothing to repair." : `${repaired} counter(s) rewritten.`,
  };
}
