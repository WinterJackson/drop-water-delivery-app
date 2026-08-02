import { create } from "zustand";
import * as SecureStore from "expo-secure-store";

/**
 * Shared rider state that is not server state.
 *
 * `isOnline`, `riderId` and `riderProfile` are mirrored here from the
 * `['rider', 'profile']` query so that non-React consumers and screens far from
 * the fetch can read them without re-querying. React Query remains the source of
 * truth; `(screens)/index.tsx` writes them on every profile change.
 *
 * This store used to carry its own `initAvailability` and `toggleAvailability`,
 * each with a hand-rolled `fetch` — a second, drifting implementation of the
 * go-online flow that nothing called. The live one is `toggleOnline` in
 * `(screens)/index.tsx`, which additionally checks that GPS is physically
 * enabled and reports why the toggle failed. Two implementations of "am I
 * online" is exactly the state to avoid, so the dead pair is gone.
 */
interface RiderState {
  isOnline: boolean;
  riderId: string | null;
  riderProfile: any | null;
  /** Vendors whose radar broadcasts this rider has silenced. Device-local. */
  mutedVendors: string[];
  toggleVendorMute: (vendorId: string) => Promise<void>;
  hydrateMutedVendors: () => Promise<void>;
}

export const useRiderStore = create<RiderState>((set, get) => ({
  isOnline: false,
  riderId: null,
  riderProfile: null,
  mutedVendors: [],

  hydrateMutedVendors: async () => {
    try {
      const cached = await SecureStore.getItemAsync("muted_vendors");
      if (cached) set({ mutedVendors: JSON.parse(cached) });
    } catch (e) {
      if (__DEV__) console.warn("[useRiderStore] muted vendors hydrate failed:", e);
    }
  },

  toggleVendorMute: async (vendorId: string) => {
    const { mutedVendors } = get();
    const isMuted = mutedVendors.includes(vendorId);
    const newMuted = isMuted
      ? mutedVendors.filter((id) => id !== vendorId)
      : [...mutedVendors, vendorId];
    set({ mutedVendors: newMuted });
    await SecureStore.setItemAsync("muted_vendors", JSON.stringify(newMuted));
  },
}));
