/**
 * Which of the vendor's stores the app is currently operating.
 *
 * A `Vendor` row is a *store*, not an account: one Clerk identity may own
 * several, and `GET /api/vendor/stores` returns them all. The switcher sheet has
 * existed since the first version of the dashboard, but selecting a store only
 * moved a highlight — `handleSelectStore` held the id in a `useState` beside the
 * comment `// Future: refetch dashboard with new store context`, and every
 * request kept hitting whichever row the database returned first.
 *
 * The id lives here rather than in a screen because it has to reach the API
 * layer, which sends it as `X-Store-Id` on every request. It is persisted so a
 * vendor who switched to their second branch is still there after a cold start —
 * otherwise the app silently reverts to the first store between launches, which
 * is worse than not switching at all.
 *
 * The id is *not* an authorisation token. The backend validates it against the
 * caller's own stores and answers 404 for one they do not own, so a tampered
 * value selects nothing; it can never reach another vendor's data.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import { create } from "zustand";

const STORAGE_KEY = "drop.vendor.activeStoreId";

interface ActiveStoreState {
  activeStoreId: string | null;
  /** False until the persisted value has been read back. */
  hydrated: boolean;
}

interface ActiveStoreActions {
  hydrate: () => Promise<void>;
  setActiveStore: (storeId: string | null) => void;
  /**
   * Drop a selection that no longer exists — a store was deleted, or this
   * device is now signed in as a different vendor. Without this the app would
   * send a stale id forever and every request would 404.
   */
  reconcile: (availableStoreIds: string[]) => void;
  clear: () => void;
}

export const useActiveStore = create<ActiveStoreState & ActiveStoreActions>((set, get) => ({
  activeStoreId: null,
  hydrated: false,

  hydrate: async () => {
    try {
      const stored = await AsyncStorage.getItem(STORAGE_KEY);
      set({ activeStoreId: stored || null, hydrated: true });
    } catch {
      // A failed read is not worth blocking on: with no id the backend falls
      // back to the vendor's first store, which is the pre-switcher behaviour.
      set({ hydrated: true });
    }
  },

  setActiveStore: (storeId) => {
    set({ activeStoreId: storeId });
    // Fire-and-forget: the in-memory value is what this session uses, and
    // failing to persist it should not fail the switch.
    if (storeId) AsyncStorage.setItem(STORAGE_KEY, storeId).catch(() => {});
    else AsyncStorage.removeItem(STORAGE_KEY).catch(() => {});
  },

  reconcile: (availableStoreIds) => {
    const current = get().activeStoreId;
    if (!current) return;
    if (!availableStoreIds.includes(current)) get().setActiveStore(null);
  },

  clear: () => {
    set({ activeStoreId: null, hydrated: true });
    AsyncStorage.removeItem(STORAGE_KEY).catch(() => {});
  },
}));

/** Read the id from outside React — the API layer and the socket both need it. */
export const getActiveStoreId = () => useActiveStore.getState().activeStoreId;
