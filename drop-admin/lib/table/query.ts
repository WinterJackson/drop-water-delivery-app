/**
 * The URL is the table's state. Search term, filters, page size, page.
 *
 * Not component state, for four reasons that all showed up in this console:
 * a filtered view can be pasted into a support thread, the back button steps
 * back through pages rather than leaving the screen, a reload keeps the row you
 * were looking at, and — since these pages are Server Components — the server
 * can do the filtering rather than the browser filtering the fifty rows it
 * happens to hold. That last one is the difference between a search box and a
 * search box that lies: filtering client-side searches the current page, and
 * quietly answers "no results" for a customer who is on page 3.
 *
 * This module is pure and has no `server-only` marker on purpose — the page
 * reads params with it on the server, and the toolbar writes them with it on
 * the client. One spelling of the query string, used from both sides.
 */

/** Rows per page. Bounded because every backend list endpoint caps its `limit`. */
export const PAGE_SIZES = [25, 50, 100] as const;

export const DEFAULT_PAGE_SIZE = 25;

/**
 * Separator for the cursor trail.
 *
 * Cursors are base64url — `A–Z a–z 0–9 - _` — so `~` cannot occur inside one
 * and needs no escaping in a query string. A comma would be percent-encoded by
 * some clients and not others, and the trail would round-trip differently
 * depending on who built the link.
 */
const TRAIL_SEPARATOR = "~";

/** How deep the trail may get before the URL becomes the problem. */
const MAX_TRAIL = 40;

/**
 * Stands in for page 1 in the trail, which has no cursor of its own.
 *
 * The trail records the position of every page *before* this one, and page 1's
 * position is "the top" — the absence of a cursor. An absence cannot be carried
 * in a query string: an empty value is indistinguishable from an absent one and
 * gets dropped, so stepping forward from page 1 left an empty trail, page 2
 * counted itself as page 1, and its Previous link was never rendered. A single
 * character is unambiguous because a real cursor is base64 of a JSON array and
 * is never shorter than ten characters.
 */
const FIRST_PAGE = "1";

export type SearchParams = Record<string, string | string[] | undefined>;

export type PageState = {
  /** The free-text search term, trimmed. Empty string when not searching. */
  q: string;
  /** The opaque cursor for the page being shown. Absent on the first page. */
  cursor?: string;
  /** Cursors of the pages before this one, oldest first. */
  trail: string[];
  /** Rows per page. */
  per: number;
  /** 1-based page number, derived from the trail rather than stored. */
  page: number;
};

function one(value: string | string[] | undefined): string {
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

/** Read the pagination and search state a list page shares. */
export function readPageState(searchParams: SearchParams): PageState {
  const raw = Number(one(searchParams.per));
  const per = (PAGE_SIZES as readonly number[]).includes(raw) ? raw : DEFAULT_PAGE_SIZE;

  const trail = one(searchParams.back)
    .split(TRAIL_SEPARATOR)
    .filter(Boolean)
    .slice(-MAX_TRAIL);

  const cursor = one(searchParams.cursor) || undefined;

  return {
    q: one(searchParams.q).trim(),
    cursor,
    trail,
    per,
    // The trail holds every page before this one, so its depth *is* the page
    // number. Storing a page number alongside the cursor would give two facts
    // that can disagree, and the one that gets edited by hand in the URL is
    // always the wrong one.
    page: trail.length + 1,
  };
}

/**
 * Build a query string, dropping anything empty or at its default.
 *
 * Empty parameters are dropped rather than serialised as `q=`: a URL somebody
 * copies out of the address bar should contain the state they can see, and
 * `?q=&status=&cursor=` reads as a filtered view when nothing is filtered.
 */
export function buildQuery(entries: Record<string, string | number | undefined | null>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(entries)) {
    if (value === undefined || value === null) continue;
    const text = String(value);
    if (!text) continue;
    params.set(key, text);
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export type PageLinks = {
  /** Href for the previous page, or null on the first. */
  previous: string | null;
  /** Href for the next page, or null when the backend reported no more. */
  next: string | null;
  /** Href back to page 1 with the same filters. Null when already there. */
  first: string | null;
  /** 1-based index of the first row shown. */
  from: number;
  /** 1-based index of the last row shown. */
  to: number;
};

/**
 * Previous / next as plain hrefs, from a cursor trail carried in the URL.
 *
 * Keyset pagination gives you "the page after this one" and nothing else — it
 * cannot count backwards, and it cannot jump to page 7, which is why there are
 * no numbered pages here. Rather than pretend otherwise, the trail of cursors
 * already visited travels in the URL, so Previous is a real link with a real
 * href: it works in a new tab, it survives a reload, and it is not the browser
 * back button wearing a costume. Back would also undo a filter change rather
 * than stepping a page, which is precisely when somebody loses their place.
 */
export function pageLinks({
  pathname,
  filters,
  state,
  nextCursor,
  count,
}: {
  pathname: string;
  /** Everything that is not pagination: the search term and the page's filters. */
  filters: Record<string, string | undefined>;
  state: PageState;
  /** `next_cursor` from the API. Null or undefined means this is the last page. */
  nextCursor: string | null | undefined;
  /** How many rows this page actually rendered. */
  count: number;
}): PageLinks {
  const per = state.per === DEFAULT_PAGE_SIZE ? undefined : state.per;
  const base = { ...filters, per };

  // Forward: this page's position joins the trail, so the page after it can
  // step back here. Page 1's position is the sentinel, not an omission.
  const forwardTrail = [...state.trail, state.cursor ?? FIRST_PAGE];

  // Back: the last position on the trail becomes the current one. The sentinel
  // means the page before this one is page 1, which carries no cursor at all.
  const previousTrail = state.trail.slice(0, -1);
  const previousRaw = state.trail[state.trail.length - 1];
  const previousCursor = previousRaw === FIRST_PAGE ? undefined : previousRaw;

  const from = (state.page - 1) * state.per + 1;

  return {
    previous:
      state.page > 1
        ? pathname +
          buildQuery({
            ...base,
            cursor: previousCursor,
            back: previousTrail.join(TRAIL_SEPARATOR),
          })
        : null,
    next: nextCursor
      ? pathname +
        buildQuery({
          ...base,
          cursor: nextCursor,
          back: forwardTrail.slice(-MAX_TRAIL).join(TRAIL_SEPARATOR),
        })
      : null,
    first: state.page > 1 ? pathname + buildQuery(base) : null,
    from: count === 0 ? 0 : from,
    to: count === 0 ? 0 : from + count - 1,
  };
}

/**
 * The href for a change that invalidates the current position.
 *
 * A new search term, a different filter, or a new page size all change *which*
 * rows exist, so the cursor pointing into the old sequence is meaningless —
 * worse than meaningless, since a keyset cursor is a value comparison and would
 * silently land somewhere plausible in the middle of the new results. Every one
 * of these returns to page 1, which is also what somebody expects when they
 * type in a search box.
 */
export function resetHref(
  pathname: string,
  filters: Record<string, string | number | undefined>,
  per?: number,
): string {
  return (
    pathname +
    buildQuery({ ...filters, per: per === DEFAULT_PAGE_SIZE ? undefined : per })
  );
}
