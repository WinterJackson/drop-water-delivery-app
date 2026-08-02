"use server";

import { revalidatePath } from "next/cache";

import { ApiError, get, put } from "@/lib/api/server";

/**
 * Server Actions for the review queue.
 *
 * They exist so the client component never needs an API token: the browser
 * posts to this app, and this app calls FastAPI with a server-minted bearer.
 * That is the same reason the whole console is a BFF — see `lib/api/server.ts`.
 *
 * Each returns a result object rather than throwing. A rejected review with a
 * reason the backend didn't like is an ordinary outcome the reviewer has to
 * see and fix, not an error boundary.
 */

export type ActionResult<T = undefined> =
  | { ok: true; data: T }
  | { ok: false; error: string };

function toResult(error: unknown): { ok: false; error: string } {
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

export async function reviewRider(
  riderId: string,
  status: "approved" | "rejected",
  rejectionReason: string,
): Promise<ActionResult> {
  const reason = rejectionReason.trim();

  // Checked here as well as on the server, so a reviewer gets the message
  // without a round trip — the server check is the one that counts.
  if (status === "rejected" && reason.length < 3) {
    return {
      ok: false,
      error: "Tell the rider what was wrong, so they can fix it and resubmit.",
    };
  }

  try {
    await put(`/api/admin/riders/${riderId}/kyc`, {
      status,
      rejection_reason: status === "rejected" ? reason : null,
    });
  } catch (error) {
    return toResult(error);
  }

  revalidatePath("/operations/kyc");
  revalidatePath("/");
  return { ok: true, data: undefined };
}

export type RiderDocuments = {
  id: string;
  full_name: string | null;
  phone_number: string | null;
  ID_number: string | null;
  id_card_front: string | null;
  id_card_back: string | null;
  driver_license: string | null;
  expires_in: number;
};

/**
 * Fetching someone's identity documents is an audited action, not a page load.
 *
 * The backend requires `pii.view`, requires the stated reason, writes an audit
 * row *before* returning anything, and presigns for five minutes rather than
 * the platform default of fifteen. Nothing is prefetched: the queue listing
 * deliberately carries no URLs at all.
 */
export async function revealDocuments(
  riderId: string,
  reason: string,
): Promise<ActionResult<RiderDocuments>> {
  const trimmed = reason.trim();
  if (trimmed.length < 3) {
    return { ok: false, error: "Say why you need to see these documents." };
  }

  try {
    const data = await get<RiderDocuments>(
      `/api/admin/riders/${riderId}/documents?reason=${encodeURIComponent(trimmed)}`,
    );
    return { ok: true, data };
  } catch (error) {
    return toResult(error);
  }
}
