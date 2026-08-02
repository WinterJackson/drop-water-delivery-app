import { useQuery } from '@tanstack/react-query';
import RiderApiRoutes from '../../API/routes/RiderApiRoutes';
import { useApiRequest } from '../../API/useApiClient';

/**
 * Empty bottles this rider is currently holding on a vendor's behalf.
 *
 * Every `quick_swap` delivery makes the rider liable for the empties they
 * collected until the vendor confirms receipt. That debt used to accrue with no
 * way for the rider to see it — only the vendor could. A rider cannot return
 * bottles they do not know they are holding.
 */
export interface VendorBottleDebt {
    vendor_id: string;
    business_name: string;
    pending_10L_empties: number;
    pending_20L_empties: number;
    /** Sizes outside the tracked 10L/20L pair, keyed like "5L". */
    other_capacities: Record<string, number>;
    total_bottles: number;
}

export interface BottleDebtResponse {
    vendors: VendorBottleDebt[];
    total_bottles: number;
}

export interface BottleLedgerEntry {
    id: string;
    rider_id: string;
    vendor_id: string;
    order_id: string | null;
    capacity_litres: number;
    /** Signed: positive increases what the rider owes, negative is a return. */
    quantity: number;
    entry_type: 'delivery_accrual' | 'vendor_receipt' | 'adjustment';
    note: string | null;
    created_at: string | null;
}

export function useBottleDebt() {
    const { get } = useApiRequest();
    return useQuery<BottleDebtResponse, Error>({
        queryKey: ['rider', 'bottle-debt'],
        queryFn: () => get<BottleDebtResponse>(RiderApiRoutes.BottleDebt.path),
        // Changes only when a delivery completes or a vendor confirms a return,
        // both of which invalidate this key explicitly.
        staleTime: 1000 * 60 * 2,
    });
}

export function useBottleLedger(limit = 50) {
    const { get } = useApiRequest();
    return useQuery<{ entries: BottleLedgerEntry[] }, Error>({
        queryKey: ['rider', 'bottle-ledger', limit],
        queryFn: () =>
            get<{ entries: BottleLedgerEntry[] }>(RiderApiRoutes.BottleLedger(limit, 0).path),
        staleTime: 1000 * 60 * 5,
    });
}
