"use server";

import { revalidatePath } from "next/cache";

import { ApiError, post } from "@/lib/api/server";

export type ActionResult<T> = { ok: true; data: T } | { ok: false; error: string };

/**
 * Send a campaign.
 *
 * `confirm` must equal the audience key. It is a small friction and it is
 * deliberate: this is the one control in the console that cannot be undone, and
 * a dialog with an OK button is something people click without reading.
 */
export async function sendBroadcast(payload: {
  channel: string;
  audience: string;
  subject: string;
  body: string;
  transactional: boolean;
  confirm: string;
}): Promise<ActionResult<{ id: string; status: string; recipients: number; message: string }>> {
  try {
    const data = await post<{
      id: string;
      status: string;
      recipients: number;
      message: string;
    }>("/api/admin/broadcast/send", payload);
    revalidatePath("/platform/broadcast");
    return { ok: true, data };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Something went wrong. Please try again." };
  }
}
