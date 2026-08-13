import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";

import { DEFAULT_PAGE_SIZE, PAGE_SIZES, buildQuery, type PageLinks } from "@/lib/table/query";
import { formatNumber } from "@/lib/utils/format";
import { cn } from "@/lib/utils/cn";

/**
 * The footer under every list: what you are looking at, and how to move.
 *
 * A **Server Component built from plain links**, deliberately. Paging is a
 * navigation, so it should be a navigation: middle-click opens page 2 in a tab,
 * the browser prefetches it, and it works before any JavaScript has run. A
 * button calling `router.push` gains nothing here and loses all three.
 *
 * There are no numbered pages, because keyset pagination cannot produce them —
 * it answers "the page after this one" and nothing else. Numbered pages would
 * mean OFFSET, which re-scans on every page and slides the window whenever a
 * row is inserted underneath it, so page 2 skips a row that page 1 already
 * showed. On the order board that is somebody's stuck delivery disappearing
 * between two clicks. See `utils/keyset.py`.
 */
export function Pagination({
  links,
  /** Population size, where the backend can produce one honestly. */
  total,
  /** Plural noun for the row count — "orders", "riders". */
  noun,
  /** Page-size links. Omitted where the caller has a fixed page size. */
  sizeHref,
  perPage,
  className,
}: {
  links: PageLinks;
  total?: number | null;
  noun: string;
  sizeHref?: (per: number) => string;
  perPage?: number;
  className?: string;
}) {
  const { previous, next, from, to } = links;

  // Nothing to say about a single page of a short list, and nowhere to go from
  // it. Rendering an inert Previous/Next pair under four rows is furniture that
  // reads as a broken control.
  if (!previous && !next && from <= 1) {
    if (to === 0) return null;
    if (!sizeHref) return null;
  }

  return (
    <nav
      aria-label={`${noun} pagination`}
      className={cn(
        "flex flex-col gap-3 border-t border-default px-4 py-3",
        "sm:flex-row sm:items-center sm:justify-between",
        className,
      )}
    >
      {/* An `aria-live` region: paging is a navigation, so a screen reader
          lands on the new page with no announcement of what changed. This is
          the sentence that says it. */}
      <p className="text-xs text-muted" aria-live="polite">
        {to === 0 ? (
          <>No {noun} to show</>
        ) : (
          <>
            Showing{" "}
            <span className="font-medium tabular-nums text-[var(--foreground)]">
              {formatNumber(from)}–{formatNumber(to)}
            </span>
            {typeof total === "number" ? (
              <>
                {" "}
                of{" "}
                <span className="font-medium tabular-nums text-[var(--foreground)]">
                  {formatNumber(total)}
                </span>
              </>
            ) : null}{" "}
            {noun}
          </>
        )}
      </p>

      <div className="flex items-center justify-between gap-2 sm:justify-end">
        {sizeHref && perPage ? (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted" id="rows-per-page">
              Rows
            </span>
            {/* Links rather than a `<select>`: a select needs an onChange
                handler, which would make this whole footer a Client Component
                for a control with three values in it. */}
            <ul className="flex items-center gap-0.5" aria-labelledby="rows-per-page">
              {PAGE_SIZES.map((size) => {
                const current = size === (perPage ?? DEFAULT_PAGE_SIZE);
                return (
                  <li key={size}>
                    <Link
                      href={sizeHref(size)}
                      aria-current={current ? "true" : undefined}
                      aria-label={`${size} rows per page`}
                      className={cn(
                        "inline-flex min-h-8 min-w-8 items-center justify-center rounded-md px-1.5 text-xs tabular-nums transition-colors",
                        current
                          ? "bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] font-medium text-[var(--accent)]"
                          : "text-muted hover:bg-surface-muted hover:text-[var(--foreground)]",
                      )}
                    >
                      {size}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : (
          <span />
        )}

        <div className="flex items-center gap-2">
          <Step href={previous} direction="previous" noun={noun} />
          <Step href={next} direction="next" noun={noun} />
        </div>
      </div>
    </nav>
  );
}

/**
 * One end of the pager.
 *
 * The unavailable end renders as a `<span>`, never a disabled `<a>`: an anchor
 * with no `href` is not focusable and announces as plain text anyway, so the
 * markup may as well say what it is. 44px tall — this is the control most
 * likely to be tapped on a phone, being at the bottom of a long list.
 */
function Step({
  href,
  direction,
  noun,
}: {
  href: string | null;
  direction: "previous" | "next";
  noun: string;
}) {
  const label = direction === "previous" ? "Previous" : "Next";
  const Icon = direction === "previous" ? ChevronLeft : ChevronRight;

  const shared =
    "inline-flex min-h-11 items-center gap-1 rounded-lg border px-3 text-sm transition-colors";

  if (!href) {
    return (
      <span
        aria-hidden
        className={cn(shared, "cursor-default border-default text-muted opacity-45")}
      >
        {direction === "previous" ? <Icon className="h-4 w-4" /> : null}
        {label}
        {direction === "next" ? <Icon className="h-4 w-4" /> : null}
      </span>
    );
  }

  return (
    <Link
      href={href}
      rel={direction === "next" ? "next" : "prev"}
      aria-label={`${label} page of ${noun}`}
      className={cn(shared, "border-default hover:bg-surface-muted")}
    >
      {direction === "previous" ? <Icon className="h-4 w-4" aria-hidden /> : null}
      {label}
      {direction === "next" ? <Icon className="h-4 w-4" aria-hidden /> : null}
    </Link>
  );
}

/** Build a page-size href generator that resets to page 1. See `resetHref`. */
export function sizeHrefFactory(
  pathname: string,
  filters: Record<string, string | undefined>,
) {
  return (per: number) =>
    pathname + buildQuery({ ...filters, per: per === DEFAULT_PAGE_SIZE ? undefined : per });
}
