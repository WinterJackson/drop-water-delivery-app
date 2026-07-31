import AsyncStorage from '@react-native-async-storage/async-storage';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';

/**
 * The on-disk snapshot of the React Query cache.
 *
 * Lives in its own module so `useSessionCleanup` can erase it on sign-out
 * without importing the root layout. `queryClient.clear()` only empties the
 * in-memory cache; the persister writes on a throttle, so an app killed shortly
 * after sign-out still had the previous account's orders and saved addresses on
 * disk and restored them into the next session.
 */
export const QUERY_CACHE_KEY = 'DROP_CUSTOMER_QUERY_CACHE';

export const asyncStoragePersister = createAsyncStoragePersister({
  storage: AsyncStorage,
  key: QUERY_CACHE_KEY,
});
