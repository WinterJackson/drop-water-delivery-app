import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { retryTransientOnly } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

/**
 * Who may operate this store, and what they may do here.
 *
 * Staff used to be `Vendor.staff_clerk_id` — one nullable, platform-unique
 * column. A store could have one staff member, adding a second silently
 * replaced the first, and one person could work for exactly one store on the
 * whole platform. There was no list, so an owner could not even see who they
 * had given access to.
 */
export interface StaffMember {
  id: string;
  email: string;
  name: string | null;
  permissions: string[];
  /** Invited, but has never signed in — so nothing is bound to them yet. */
  is_pending: boolean;
  is_active: boolean;
  created_at: string | null;
  accepted_at: string | null;
}

export interface StaffPermission {
  key: string;
  label: string;
}

interface StaffResponse {
  staff: StaffMember[];
  /**
   * Shipped with the list rather than hardcoded here, so this screen can never
   * offer a capability the server has dropped — or miss one it has added.
   */
  available_permissions: StaffPermission[];
}

export const STAFF_QUERY_KEY = ["vendor", "staff"];

export function useVendorStaff(enabled = true) {
  const { get } = useApiRequest();

  return useQuery<StaffResponse, Error>({
    queryKey: STAFF_QUERY_KEY,
    queryFn: () => get<StaffResponse>(VendorApiRoutes.GetStaff.path),
    enabled,
    retry: retryTransientOnly(),
  });
}

export function useInviteStaff() {
  const { post } = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (input: { email: string; permissions?: string[] }) =>
      post<{ message: string; updated_existing: boolean; staff: StaffMember }>(
        VendorApiRoutes.InviteStaff.path,
        input
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: STAFF_QUERY_KEY }),
  });
}

export function useUpdateStaffPermissions() {
  const { patch } = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ staffId, permissions }: { staffId: string; permissions: string[] }) =>
      patch<StaffMember>(VendorApiRoutes.UpdateStaffPermissions(staffId).path, { permissions }),
    onMutate: async ({ staffId, permissions }) => {
      // A permission toggle should feel instant; the request is a formality the
      // list refetch confirms.
      await queryClient.cancelQueries({ queryKey: STAFF_QUERY_KEY });
      const previous = queryClient.getQueryData<StaffResponse>(STAFF_QUERY_KEY);
      queryClient.setQueryData<StaffResponse>(STAFF_QUERY_KEY, (old) =>
        old
          ? {
              ...old,
              staff: old.staff.map((s) => (s.id === staffId ? { ...s, permissions } : s)),
            }
          : old
      );
      return { previous };
    },
    onError: (_err, _vars, context: any) => {
      if (context?.previous) queryClient.setQueryData(STAFF_QUERY_KEY, context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: STAFF_QUERY_KEY }),
  });
}

export function useRevokeStaff() {
  const { del } = useApiRequest();
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (staffId: string) => del(VendorApiRoutes.RevokeStaff(staffId).path),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: STAFF_QUERY_KEY }),
  });
}
