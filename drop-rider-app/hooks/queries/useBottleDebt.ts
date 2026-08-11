import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
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
    /**
     * How long the oldest of these has been held, in whole days.
     *
     * The platform judges a rider on age — `STALE_AFTER_DAYS` flags a pair at 14
     * days and a nightly sweep acts on it — and the rider was shown the quantity
     * and never the clock. The first they knew of the threshold was being
     * flagged against it.
     */
    held_days: number | null;
    /** Already past `stale_after_days`. */
    is_stale: boolean;
}

export interface BottleDebtResponse {
    vendors: VendorBottleDebt[];
    total_bottles: number;
    /** The platform's own threshold, so the app never states a number of its own. */
    stale_after_days: number;
    stale_vendors: number;
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


// ── Collecting a customer's bottles ──────────────────────────────────────
//
// A collection is the other half of the deposit the customer paid. Two counts
// release it — the rider's and the customer's — and they must agree; a
// disagreement goes to a human and nothing moves. Confirming also makes this
// rider the holder of those bottles on the ledger above, which is why the
// destination store is required rather than optional.

export type BottleCollectionStatus =
    | 'requested'
    | 'assigned'
    | 'awaiting_counterparty'
    | 'settled'
    | 'disputed'
    | 'expired'
    | 'cancelled';

export interface BottleCollection {
    id: string;
    status: BottleCollectionStatus;
    bottles_requested: number;
    bottles_stated_by_customer: number | null;
    bottles_stated_by_rider: number | null;
    bottles_settled: number | null;
    amount_refunded: string | null;
    rider_id: string | null;
    expires_at: string | null;
    settled_at: string | null;
    resolution_note: string | null;
    created_at: string | null;
}

export function useBottleCollections() {
    const { get } = useApiRequest();
    return useQuery<{ items: BottleCollection[] }, Error>({
        queryKey: ['rider', 'bottle-collections'],
        queryFn: () =>
            get<{ items: BottleCollection[] }>(RiderApiRoutes.BottleCollections.path),
        staleTime: 1000 * 30,
    });
}

export function useClaimBottleCollection() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();

    return useMutation<BottleCollection, Error, { id: string; vendorId?: string }>({
        mutationFn: ({ id, vendorId }) =>
            post<BottleCollection>(
                RiderApiRoutes.ClaimBottleCollection(id).path,
                vendorId ? { bottles: 0, vendor_id: vendorId } : { bottles: 0 },
            ),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['rider', 'bottle-collections'] });
        },
    });
}

export function useConfirmBottleCollection() {
    const { post } = useApiRequest();
    const queryClient = useQueryClient();

    return useMutation<
        { status: string; amount_refunded?: string; detail?: string; waiting_on?: string },
        Error,
        { id: string; bottles: number; vendorId: string }
    >({
        mutationFn: ({ id, bottles, vendorId }) =>
            post(RiderApiRoutes.ConfirmBottleCollection(id).path, {
                bottles,
                vendor_id: vendorId,
            }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['rider', 'bottle-collections'] });
            // Confirming makes this rider the holder of those bottles, so what
            // they owe each store has just changed.
            queryClient.invalidateQueries({ queryKey: ['rider', 'bottle-debt'] });
            queryClient.invalidateQueries({ queryKey: ['rider', 'bottle-ledger'] });
        },
    });
}
