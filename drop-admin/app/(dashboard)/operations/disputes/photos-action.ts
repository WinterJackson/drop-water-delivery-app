"use server";

import { ApiError, get } from "@/lib/api/server";

export type PhotoResult = { ok: true; data: string[] } | { ok: false; error: string };

/**
 * Presigned URLs for a dispute's evidence photos, fetched on demand.
 *
 * The list endpoint returns a photo *count* and no URLs. Minting them per row
 * would create live links to every dispute photo on every page load, the same
 * reasoning as the KYC queue — and these are 5-minute URLs, so a preloaded one
 * is usually dead by the time anyone clicks it anyway.
 */
export async function loadDisputePhotos(ticketId: string): Promise<PhotoResult> {
  try {
    const data = await get<{ photos: string[] }>(`/api/admin/disputes/${ticketId}`);
    return { ok: true, data: data.photos ?? [] };
  } catch (error) {
    if (error instanceof ApiError) return { ok: false, error: error.message };
    return { ok: false, error: "Couldn't load the photos." };
  }
}
