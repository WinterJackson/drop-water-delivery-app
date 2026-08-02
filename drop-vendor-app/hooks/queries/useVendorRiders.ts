import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { retryTransientOnly } from "@/API/errors";
import { useApiRequest } from "@/API/useApiClient";
import { useAuth } from "@clerk/clerk-expo";
import { useQuery } from "@tanstack/react-query";

export interface VendorRider {
  registry_id: string;
  deliverer_id: string;
  name?: string;
  phone_number?: string;
  profile_pic?: string;
  vehicle_type?: string;
  plate_number?: string;
  status: string;
  is_available?: boolean;
  applied_at?: string;
  pending_10L_empties: number;
  pending_20L_empties: number;
  /** Present on some rows; the roster endpoint does not return them today. */
  rating?: number;
  total_deliveries?: number;
}

export function useVendorRiders() {
  const { isLoaded, isSignedIn } = useAuth();
  const { get } = useApiRequest();

  return useQuery<VendorRider[], Error>({
    queryKey: ['vendor', 'riders'],
    queryFn: async () => {
      const data = await get<VendorRider[]>(VendorApiRoutes.GetMyRiders.path);
      return Array.isArray(data) ? data : [];
    },
    enabled: isLoaded && isSignedIn,
    refetchInterval: 30000,
    retry: retryTransientOnly(),
  });
}
