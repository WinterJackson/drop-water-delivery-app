"use server";

import { revalidatePath } from "next/cache";

import { ApiError, del, put } from "@/lib/api/server";

export type ActionResult<T = undefined> =
  | { ok: true; data: T }
  | { ok: false; error: string };

function fail(error: unknown): { ok: false; error: string } {
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

/**
 * Record (or correct) one month's off-platform acquisition spend.
 *
 * An upsert on the server, keyed on month and channel. The ordinary case is
 * "the invoice came in and it was 12,000 not 10,000", and a second row for that
 * would double the month's spend — a CAC that doubles overnight looks exactly
 * like a bad month, which is the worst kind of wrong number because it prompts
 * a decision.
 */
export async function recordSpend(input: {
  period_month: string;
  channel: string;
  amount: string;
  note?: string;
}): Promise<ActionResult<{ id: string }>> {
  try {
    const data = await put<{ id: string }>("/api/admin/growth/spend", input);
    revalidatePath("/analytics/growth");
    return { ok: true, data };
  } catch (error) {
    return fail(error);
  }
}

export async function deleteSpend(id: string): Promise<ActionResult> {
  try {
    await del(`/api/admin/growth/spend/${id}`);
    revalidatePath("/analytics/growth");
    return { ok: true, data: undefined };
  } catch (error) {
    return fail(error);
  }
}
