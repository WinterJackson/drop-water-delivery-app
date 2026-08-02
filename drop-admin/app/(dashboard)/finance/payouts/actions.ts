"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult = { ok: true } | { ok: false; error: string };

/**
 * Approving or refusing a payout.
 *
 * Both require a written reason. That is not bureaucracy: a payout decision is
 * the most contested thing in the console — someone is either being paid or
 * not — and "why did you refuse my withdrawal" needs an answer that is not
 * somebody's recollection. The backend stores it on the audit row alongside
 * who decided and when.
 */
async function decide(
  payoutId: string,
  decision: "approve" | "reject",
  reason: string,
): Promise<ActionResult> {
  const trimmed = reason.trim();
  if (trimmed.length < 3) {
    return { ok: false, error: "Give a reason — it's recorded against the decision." };
  }

  try {
    await post(`/api/admin/payouts/${payoutId}/${decision}`, { reason: trimmed });
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }

  revalidatePath("/finance/payouts");
  revalidatePath("/");
  return { ok: true };
}

// Every export of a "use server" module must be an async *function* — a
// `const` arrow is not a valid Server Action reference and the module compiles
// to no exports at all.
export async function approvePayout(id: string, reason: string): Promise<ActionResult> {
  return decide(id, "approve", reason);
}

export async function rejectPayout(id: string, reason: string): Promise<ActionResult> {
  return decide(id, "reject", reason);
}
