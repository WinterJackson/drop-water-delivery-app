/**
 * The rider's verification status — one query, one cache entry.
 *
 * This endpoint was fetched by hand in three places (`(screens)/_layout.tsx`,
 * `Profile.tsx`, `VerificationWall.tsx`), each with its own error handling, and
 * `VerificationWall` kept the answer in `useState` instead of the query cache.
 * That divergence was a live bug: when an admin approved a rider, the wall's own
 * fetch saw `approved` and called `router.replace("/(screens)")`, while the
 * layout's cache still said `pending` and redirected straight back — a redirect
 * loop that only broke when the 60s `staleTime` happened to expire.
 *
 * One key, one shape. Screens that change the status call
 * `invalidateKycStatus()` so the gate re-reads it.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";

import { ApiError } from "@/API/errors";
import RiderApiRoutes from "@/API/routes/RiderApiRoutes";
import { useApiRequest } from "@/API/useApiClient";

export type KycStatusValue = "unsubmitted" | "pending" | "approved" | "rejected";

export interface RiderKycStatus {
  is_verified: boolean;
  kyc_status: KycStatusValue;
  employer_vendor_id: string | null;
  vehicle_type: string | null;
  plate_number: string | null;
  /**
   * Why the last review was rejected, written by the admin who rejected it.
   *
   * Without this the rider sees a form prefilled with their previous answers
   * and no indication of what was wrong, so the usual response to a rejection
   * was resubmitting the same document. The reason used to exist only inside a
   * push notification, which is best-effort and easily dismissed.
   *
   * Cleared by the backend on resubmission, so it never describes documents
   * that have already been replaced.
   */
  rejection_reason: string | null;
  reviewed_at: string | null;
}

/** Thrown when the caller has no `Deliverer` row at all — they never onboarded. */
export const NOT_A_RIDER = "403_FORBIDDEN";

export const RIDER_KYC_QUERY_KEY = ["rider", "kyc_status"] as const;

export function useKycStatus(enabled = true) {
  const { get } = useApiRequest();

  return useQuery<RiderKycStatus>({
    queryKey: RIDER_KYC_QUERY_KEY,
    queryFn: async () => {
      try {
        return await get<RiderKycStatus>(RiderApiRoutes.KycStatus.path);
      } catch (e) {
        // A caller with no `Deliverer` row is not an error to retry — they never
        // onboarded, and the gate routes them there.
        if (e instanceof ApiError && e.status === 403) throw new Error(NOT_A_RIDER);
        throw e;
      }
    },
    enabled,
    staleTime: 60_000,
    retry: (failureCount, error) => {
      if ((error as Error).message === NOT_A_RIDER) return false;
      // 4xx is a refusal; the shared `retryTransientOnly` default cannot see
      // through the NOT_A_RIDER remap above, so this stays explicit.
      if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
      return failureCount < 3;
    },
  });
}

/** Call after anything that can change the status (a KYC upload, an approval push). */
export function useInvalidateKycStatus() {
  const queryClient = useQueryClient();
  return useCallback(
    () => queryClient.invalidateQueries({ queryKey: RIDER_KYC_QUERY_KEY }),
    [queryClient]
  );
}
