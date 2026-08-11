"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult = { ok: true } | { ok: false; error: string };

function fail(error: unknown): { ok: false; error: string } {
  if (error instanceof ApiError) return { ok: false, error: error.message };
  return { ok: false, error: "Something went wrong. Please try again." };
}

/**
 * Reply to a ticket.
 *
 * `internal` is the important flag: an internal note goes into the thread for
 * administrators and is sent nowhere. Support staff need somewhere to write
 * "rider says nobody was home, checking the GPS trail" without it becoming a
 * message to the customer.
 */
export async function replyToTicket(
  ticketId: string,
  body: string,
  options: { internal: boolean; status?: string },
): Promise<ActionResult> {
  if (body.trim().length < 1) {
    return { ok: false, error: "Write something first." };
  }

  try {
    await post(`/api/admin/support/tickets/${ticketId}/reply`, {
      body: body.trim(),
      internal: options.internal,
      status: options.status ?? null,
    });
  } catch (error) {
    return fail(error);
  }

  revalidatePath("/support");
  revalidatePath(`/support/${ticketId}`);
  return { ok: true };
}

export async function setTicketStatus(
  ticketId: string,
  status: string,
  resolution?: string,
): Promise<ActionResult> {
  try {
    await post(`/api/admin/support/tickets/${ticketId}/status`, {
      status,
      resolution: resolution?.trim() || null,
    });
  } catch (error) {
    return fail(error);
  }

  revalidatePath("/support");
  revalidatePath(`/support/${ticketId}`);
  return { ok: true };
}

/**
 * Escalate or de-escalate.
 *
 * The column existed, the queue filtered on it and the badge was coloured from
 * it, but nothing on the platform could ever write it — so every ticket was
 * `normal` and the filter could only return everything or nothing.
 */
export async function setTicketPriority(
  ticketId: string,
  priority: string,
): Promise<ActionResult> {
  try {
    await post(`/api/admin/support/tickets/${ticketId}/priority`, { priority });
  } catch (error) {
    return fail(error);
  }

  revalidatePath("/support");
  revalidatePath(`/support/${ticketId}`);
  return { ok: true };
}

export async function takeTicket(ticketId: string): Promise<ActionResult> {
  try {
    await post(`/api/admin/support/tickets/${ticketId}/assign`);
  } catch (error) {
    return fail(error);
  }

  revalidatePath("/support");
  revalidatePath(`/support/${ticketId}`);
  return { ok: true };
}
