import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import { useActiveStore } from "@/stores/activeStoreStore";

/**
 * Empty the query cache whenever the active store changes.
 *
 * Every vendor query is scoped by the `X-Store-Id` header rather than by its
 * query key — that is what makes the switch a one-line change instead of a
 * rewrite of thirty hooks. The cost is that React Query cannot tell the two
 * stores' answers apart: `["vendorOrders"]` means "the active store's orders",
 * and after a switch the cached entry is the *other* store's.
 *
 * Clearing is the honest response. Adding the store id to thirty query keys
 * would preserve both stores' caches, but every key that was missed would serve
 * store A's data under store B's dashboard — silently, and looking entirely
 * plausible. A switch is a deliberate, rare action; a fresh fetch is the right
 * price for never showing one branch's orders under another's name.
 *
 * Mounted once, in `app/(screens)/_layout.tsx`.
 */
export function useStoreScopedCache() {
  const queryClient = useQueryClient();
  const activeStoreId = useActiveStore((s) => s.activeStoreId);
  const previous = useRef(activeStoreId);

  useEffect(() => {
    if (previous.current === activeStoreId) return;
    previous.current = activeStoreId;
    queryClient.clear();
  }, [activeStoreId, queryClient]);
}

export default useStoreScopedCache;
