import VendorApiRoutes from "@/API/routes/VendorApiRoutes";
import { useAuth } from "@clerk/clerk-expo";
import { useQuery } from "@tanstack/react-query";

/**
 * Riders currently holding this vendor's empty bottles.
 *
 * Reads the bottle ledger rather than the rider registry. The registry only knows
 * about riders who applied and were approved; radar dispatch routinely assigns
 * orders to nearby gig riders who never registered. Those riders still walk away
 * with bottles, and reconciliation that filters on registry status will never show
 * them.
 */
export interface BottleDebtor {
  rider_id: string;
  name?: string;
  phone_number?: string;
  pending_10L_empties: number;
  pending_20L_empties: number;
  /** Sizes outside the tracked 10L/20L pair, keyed like "5L". */
  other_capacities: Record<string, number>;
  total_bottles: number;
}

export function useBottleDebtors() {
  const { getToken, isLoaded, isSignedIn } = useAuth();

  return useQuery<BottleDebtor[], Error>({
    queryKey: ["vendor", "bottle-debtors"],
    queryFn: async () => {
      const token = await getToken();
      if (!token) throw new Error("No token found");

      const route = VendorApiRoutes.BottleDebtors;
      const res = await fetch(route.path, {
        method: route.method,
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      });
      if (!res.ok) throw new Error(`Bottle debtors fetch failed: ${res.status}`);
      const data = await res.json();
      return Array.isArray(data?.riders) ? data.riders : [];
    },
    enabled: isLoaded && isSignedIn,
    staleTime: 1000 * 30,
  });
}
