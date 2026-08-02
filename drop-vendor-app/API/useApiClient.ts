/**
 * Centralised HTTP client for the vendor app.
 *
 * Handles the five things every backend call needs and that the raw `fetch`
 * calls scattered through thirty hooks and screens were each doing differently
 * (or not at all):
 *   1. injects the Clerk JWT,
 *   2. names the active store in `X-Store-Id`, so the switcher on the dashboard
 *      actually switches — previously every request hit whichever `Vendor` row
 *      the database returned first,
 *   3. signs the user out on a 401 in one place, rather than copy-pasted at
 *      thirty call sites with three different spellings,
 *   4. converts every failure into an `ApiError` whose message is the backend's
 *      own `detail`, so callers can show it verbatim,
 *   5. applies a timeout. `fetch` has none, so a hung request hung forever and
 *      the screen sat on its skeleton with nothing to retry.
 *
 * Built on `fetch` rather than axios (which the other two apps use) purely to
 * avoid adding a dependency for behaviour `API/apiFetch.ts` already implements;
 * the surface — `get/post/put/patch/del` returning parsed data, throwing
 * `ApiError` — is identical, so hooks read the same across all three apps.
 */
import { useAuth } from "@clerk/clerk-expo";
import { useCallback, useMemo } from "react";

import { useActiveStore } from "@/stores/activeStoreStore";
import { apiFetch, type ApiFetchOptions } from "./apiFetch";
import { ApiError } from "./errors";

export interface RequestConfig extends Omit<ApiFetchOptions, "token" | "method" | "body"> {
  /**
   * Skip the `X-Store-Id` header. Only `GET /api/vendor/stores` wants this: it
   * lists every store the account can reach, and scoping it to one would make
   * the switcher unable to show the others.
   */
  allStores?: boolean;
}

type Method = NonNullable<ApiFetchOptions["method"]>;

export const useApiRequest = () => {
  const { getToken, signOut } = useAuth();
  const activeStoreId = useActiveStore((s) => s.activeStoreId);

  const request = useCallback(
    async <T = unknown>(
      method: Method,
      url: string,
      body?: unknown,
      config: RequestConfig = {}
    ): Promise<T> => {
      const { allStores, ...rest } = config;

      let token: string | null = null;
      try {
        token = await getToken();
      } catch (error) {
        if (__DEV__) console.error("Token retrieval failed", error);
      }

      try {
        return await apiFetch<T>(url, {
          ...rest,
          method,
          token,
          body,
          storeId: allStores ? null : activeStoreId,
        });
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          // The session is gone. Wipe it here so one handler covers every
          // caller — `useSessionCleanup` clears the query cache off the back of
          // Clerk's own session change.
          if (__DEV__) console.warn("401 Unauthorized captured - signing out client");
          try {
            await signOut();
          } catch (signOutError) {
            if (__DEV__) console.error("Sign-out after 401 failed", signOutError);
          }
        }

        if (__DEV__ && error instanceof ApiError) {
          console.error(`API ${method} ${url} → ${error.status}: ${error.message}`);
        }
        throw error;
      }
    },
    [getToken, signOut, activeStoreId]
  );

  const get = useCallback(
    <T = unknown>(url: string, config?: RequestConfig) => request<T>("GET", url, undefined, config),
    [request]
  );

  const post = useCallback(
    <T = unknown>(url: string, data?: unknown, config?: RequestConfig) =>
      request<T>("POST", url, data, config),
    [request]
  );

  const put = useCallback(
    <T = unknown>(url: string, data?: unknown, config?: RequestConfig) =>
      request<T>("PUT", url, data, config),
    [request]
  );

  const patch = useCallback(
    <T = unknown>(url: string, data?: unknown, config?: RequestConfig) =>
      request<T>("PATCH", url, data, config),
    [request]
  );

  const del = useCallback(
    <T = unknown>(url: string, config?: RequestConfig) => request<T>("DELETE", url, undefined, config),
    [request]
  );

  return useMemo(
    () => ({ request, get, post, put, patch, del }),
    [request, get, post, put, patch, del]
  );
};

export default useApiRequest;
