/**
 * Turning `useInfiniteQuery` pages into a list a `FlashList` can render.
 *
 * Every list endpoint on this platform pages with `limit`/`offset`, and offset
 * measures from the top of a result that keeps changing underneath the reader.
 * A new order arrives, a notification lands, a vendor accepts — every row below
 * shifts down one, so the first row of page 2 is the row that was last on
 * page 1 and arrives a second time. React keys it to the cell already on screen,
 * and the customer sees the same order twice while a real one has been pushed
 * out of the window and will not appear until they pull to refresh.
 *
 * That is a property of offset paging rather than a bug in any one query — the
 * server side of it is documented in `BackendAPI/utils/paging.py`. The client's
 * half is to key on the row id when flattening, which costs one pass and makes
 * the drift harmless: at worst a row is missing until the next refresh, never
 * duplicated and never a rendering fault.
 *
 * `keepPaging` is the other half of the same job. `onEndReached` fires
 * repeatedly while a long list settles, and a bare `fetchNextPage()` in it asks
 * for the same page several times over a slow connection — the exact conditions
 * where the extra requests hurt most.
 */

type PageLike<T> = readonly T[] | { readonly data?: readonly T[] | null } | { readonly items?: readonly T[] | null } | null | undefined;

/** The rows in one page, whichever envelope the endpoint uses. */
function rowsOf<T>(page: PageLike<T>): readonly T[] {
  if (!page) return [];
  if (Array.isArray(page)) return page;
  const envelope = page as { data?: readonly T[] | null; items?: readonly T[] | null };
  return envelope.data ?? envelope.items ?? [];
}

/**
 * Every row across every fetched page, in order, each appearing once.
 *
 * `identify` defaults to the row's `id`, which every list on this platform
 * carries. A row without one is kept rather than dropped: a missing id is a
 * schema surprise, and silently hiding rows is a worse answer than showing a
 * duplicate.
 */
export function flattenPages<T>(
  pages: { pages: PageLike<T>[] } | undefined | null,
  identify: (row: T) => string | number | undefined = (row) => (row as { id?: string | number })?.id,
): T[] {
  const seen = new Set<string | number>();
  const rows: T[] = [];

  for (const page of pages?.pages ?? []) {
    for (const row of rowsOf(page)) {
      const key = identify(row);
      if (key === undefined || key === null) {
        rows.push(row);
        continue;
      }
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push(row);
    }
  }

  return rows;
}

/**
 * An `onEndReached` handler that asks for the next page once.
 *
 * Pass the query's own flags straight through:
 *
 *     onEndReached={keepPaging(query)}
 */
export function keepPaging(query: {
  hasNextPage?: boolean;
  isFetchingNextPage?: boolean;
  fetchNextPage: () => unknown;
}): () => void {
  return () => {
    if (!query.hasNextPage || query.isFetchingNextPage) return;
    query.fetchNextPage();
  };
}

/**
 * `getNextPageParam` for an endpoint that answers with a bare array.
 *
 * The only end-of-list signal such an endpoint gives is a short page, so a run
 * that ends on an exactly-full one costs one more request that comes back
 * empty. Counting the rows already held is what makes the next offset correct
 * even then; `allPages.length * size` assumes every page was full and walks
 * past rows the moment one is not.
 */
export function nextOffset<T>(size: number) {
  return (lastPage: readonly T[] | null | undefined, allPages: (readonly T[] | null | undefined)[]) => {
    if (!lastPage || lastPage.length < size) return undefined;
    return allPages.reduce((total, page) => total + (page?.length ?? 0), 0);
  };
}
