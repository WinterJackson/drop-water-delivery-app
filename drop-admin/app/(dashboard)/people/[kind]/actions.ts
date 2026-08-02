"use server";

import { revalidatePath } from "next/cache";

import { ApiError, get, post } from "@/lib/api/server";

export type ActionResult<T = undefined> = { ok: true; data: T } | { ok: false; error: string };

function fail(error: unknown): { ok: false; error: string } {
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

/**
 * Suspend or reinstate an account.
 *
 * The reason is mandatory and is shown to the person suspended. A suspension
 * nobody can explain becomes a support ticket and an appeal with nothing to
 * appeal against — so the server refuses a blank one, and this checks first to
 * save a round trip.
 */
export async function setSuspension(
  kind: string,
  id: string,
  suspend: boolean,
  reason: string,
): Promise<ActionResult> {
  const trimmed = reason.trim();
  if (trimmed.length < 3) {
    return { ok: false, error: "Give a reason — the account holder is shown this." };
  }

  try {
    await post(`/api/admin/people/${kind}s/${id}/${suspend ? "suspend" : "reinstate"}`, {
      reason: trimmed,
    });
  } catch (error) {
    return fail(error);
  }

  revalidatePath(`/people/${kind}s`);
  revalidatePath(`/people/${kind}s/${id}`);
  return { ok: true, data: undefined };
}

export type Contact = {
  id: string;
  email: string | null;
  phone_number: string | null;
  location_address: string | null;
  ID_number?: string | null;
};

/** Unmasking contact details is audited, needs `pii.view`, and needs a reason. */
export async function revealContact(
  kind: string,
  id: string,
  reason: string,
): Promise<ActionResult<Contact>> {
  const trimmed = reason.trim();
  if (trimmed.length < 3) {
    return { ok: false, error: "Say why you need these details." };
  }

  try {
    const data = await get<Contact>(
      `/api/admin/people/${kind}s/${id}/contact?reason=${encodeURIComponent(trimmed)}`,
    );
    return { ok: true, data };
  } catch (error) {
    return fail(error);
  }
}

export type Adjustment = {
  ok: true;
  balance_before: string;
  balance_after: string;
  adjustment: string;
};

/**
 * Credit or debit a wallet by hand.
 *
 * The only action on the platform that creates money out of nothing, so the
 * server carries every guard: its own capability held by no preset but super
 * admin, a ten-character minimum reason, a per-adjustment ceiling, an optimistic
 * check against the balance the operator was actually looking at, and a
 * notification to the account holder.
 *
 * `expected` is that optimistic check. Without it, two people acting on the same
 * complaint both apply the credit and the customer is paid twice.
 */
export async function adjustWallet(
  kind: string,
  id: string,
  amount: string,
  reason: string,
  expected: string,
): Promise<ActionResult<Adjustment>> {
  const parsed = Number(amount);
  if (!Number.isFinite(parsed) || parsed === 0) {
    return { ok: false, error: "Enter an amount. Negative debits the balance." };
  }
  if (reason.trim().length < 10) {
    return {
      ok: false,
      error: "Explain this properly — somebody will read it a year from now while reconciling.",
    };
  }

  try {
    const data = await post<Adjustment>(`/api/admin/finance/${kind}s/${id}/adjust`, {
      amount,
      reason: reason.trim(),
      expected_balance: expected,
    });
    revalidatePath(`/people/${kind}s/${id}`);
    revalidatePath("/finance/transactions");
    return { ok: true, data };
  } catch (error) {
    return fail(error);
  }
}
