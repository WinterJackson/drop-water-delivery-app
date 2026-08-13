"use client";

import { Loader2, Search, X } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { buildQuery } from "@/lib/table/query";
import { cn } from "@/lib/utils/cn";

/**
 * Search and filters for a list page. One component, every table.
 *
 * **The search runs on the server.** It has to: a page holds 25 rows and the
 * table behind it holds every order on the platform, so filtering what is
 * already in the browser would search the current page and answer "no results"
 * for anything on page 2 — confidently, and with no way for the person to tell.
 * Typing therefore updates the URL, and the Server Component re-queries.
 *
 * What makes that *feel* immediate rather than like the submit button it
 * replaces:
 *
 * - **Debounced**, so a five-letter word is one request rather than five.
 * - **`replace`, not `push`**, so the browser back button leaves the screen
 *   instead of replaying every keystroke as a history entry.
 * - **`scroll: false`**, because re-searching is not arriving somewhere new and
 *   jumping to the top loses the row somebody was reading.
 * - **`useTransition`**, so the old rows stay on screen, dimmed, while the new
 *   ones are fetched. A spinner where the table was is a screen that flashes
 *   empty on every keystroke, which reads as "no results" over and over.
 * - The input is **uncontrolled by the URL**: it keeps its own state and its
 *   own focus, so a slow round trip can never eat a character or move the
 *   caret. The URL is synced *from* it, not the other way round.
 *
 * It degrades to the plain GET form it replaces. Everything lives inside a
 * `<form method="GET">` with a real submit button, so with no JavaScript the
 * Enter key still searches and the selects still filter — which is also what
 * makes this safe to render on the server for the first paint.
 */

export type ToolbarFilter = {
  /** Query-string parameter this control writes. */
  name: string;
  /** Accessible name. Rendered visually only as the select's own text. */
  label: string;
  value: string;
  options: readonly { value: string; label: string }[];
};

/** How long to wait after the last keystroke. */
const DEBOUNCE_MS = 250;

export function TableToolbar({
  placeholder,
  /** Parameters to preserve that this toolbar does not itself own. */
  keep = {},
  filters = [],
  /** Rendered at the end of the row — an export button, a "new" action. */
  action,
  className,
  children,
}: {
  placeholder: string;
  keep?: Record<string, string | undefined>;
  filters?: readonly ToolbarFilter[];
  action?: React.ReactNode;
  className?: string;
  /** The results. Rendered here so they dim while a search is in flight. */
  children?: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();

  const urlQuery = searchParams.get("q") ?? "";
  const [term, setTerm] = useState(urlQuery);

  // What this component last wrote to the URL. Used to tell "the URL changed
  // because I typed" from "the URL changed because they pressed Back" — only
  // the second should overwrite what is in the box under the caret.
  const written = useRef(urlQuery);

  useEffect(() => {
    if (urlQuery !== written.current) {
      written.current = urlQuery;
      setTerm(urlQuery);
    }
  }, [urlQuery]);

  /**
   * Navigate with the new state, always back to page 1.
   *
   * `cursor` and `back` are dropped rather than carried: they are positions in
   * the *old* result sequence. A keyset cursor is a value comparison, so a
   * stale one does not error — it lands somewhere plausible in the middle of
   * the new results, which is the worst of the three possible behaviours.
   */
  const commit = (next: Record<string, string | undefined>) => {
    const query = buildQuery({
      ...keep,
      ...Object.fromEntries(filters.map((filter) => [filter.name, filter.value])),
      ...next,
    });
    startTransition(() => router.replace(pathname + query, { scroll: false }));
  };

  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const onType = (value: string) => {
    setTerm(value);
    written.current = value.trim();
    clearTimeout(timer.current);
    timer.current = setTimeout(() => commit({ q: value.trim() }), DEBOUNCE_MS);
  };

  // A pending navigation whose timer has already fired must not be re-fired by
  // an unmount, and a component that unmounts mid-debounce must not navigate at
  // all — the person has left the screen.
  useEffect(() => () => clearTimeout(timer.current), []);

  const clear = () => {
    clearTimeout(timer.current);
    setTerm("");
    written.current = "";
    commit({ q: undefined });
  };

  const form = (
    <form
      method="GET"
      action={pathname}
      onSubmit={(event) => {
        // With JavaScript, the debounce has already navigated or is about to;
        // let Enter flush it immediately rather than reloading the document.
        event.preventDefault();
        clearTimeout(timer.current);
        commit({ q: term.trim() });
      }}
      className={cn("flex flex-wrap items-center gap-2", !children && className)}
    >
      {/* No-JS: the values this toolbar would otherwise carry forward. */}
      {Object.entries(keep).map(([name, value]) =>
        value ? <input key={name} type="hidden" name={name} value={value} /> : null,
      )}

      <div className="relative min-w-0 flex-1 basis-56">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          aria-hidden
        />
        <label htmlFor="table-search" className="sr-only">
          {placeholder}
        </label>
        <input
          id="table-search"
          name="q"
          type="search"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          spellCheck={false}
          value={term}
          onChange={(event) => onType(event.target.value)}
          placeholder={placeholder}
          className={cn(
            "min-h-11 w-full rounded-lg border border-default bg-surface pl-9 pr-9 text-sm",
            "placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-0",
          )}
        />

        {/* The spinner replaces the clear button rather than sitting beside it:
            two controls in one 36px slot is a mis-tap on a phone, and while a
            search is in flight "clear" is the thing least likely to be wanted. */}
        {pending ? (
          <Loader2
            className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted motion-reduce:animate-none"
            aria-hidden
          />
        ) : term ? (
          <button
            type="button"
            onClick={clear}
            aria-label="Clear search"
            className="absolute right-1 top-1/2 inline-flex h-9 w-9 -translate-y-1/2 items-center justify-center rounded-md text-muted transition-colors hover:bg-surface-muted hover:text-[var(--foreground)]"
          >
            <X className="h-4 w-4" aria-hidden />
          </button>
        ) : null}
      </div>

      {filters.map((filter) => (
        <div key={filter.name}>
          <label htmlFor={`filter-${filter.name}`} className="sr-only">
            {filter.label}
          </label>
          <select
            id={`filter-${filter.name}`}
            name={filter.name}
            value={filter.value}
            onChange={(event) => commit({ [filter.name]: event.target.value || undefined })}
            className="min-h-11 rounded-lg border border-default bg-surface px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-0"
          >
            {filter.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      ))}

      {/* Reachable only without JavaScript, where it is the whole mechanism. */}
      <noscript>
        <button
          type="submit"
          className="min-h-11 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-[var(--accent-foreground)]"
        >
          Search
        </button>
      </noscript>

      {action ? <div className="shrink-0">{action}</div> : null}

      {/* Announced, never drawn: the visible signal is the dimmed table. */}
      <output className="sr-only" aria-live="polite">
        {pending ? "Updating results" : ""}
      </output>
    </form>
  );

  // The results are rendered *inside* this component so they can be dimmed
  // from the same `useTransition` state that drives the spinner. They are
  // Server Components passed through as `children` — this file is a Client
  // Component, but children are rendered on the server and arrive as an
  // already-serialised tree, so wrapping them here costs the browser nothing
  // and does not drag the table's imports into the client bundle.
  if (!children) return form;

  return (
    <div className={cn("space-y-4", className)}>
      {form}
      <div
        aria-busy={pending || undefined}
        className={cn(
          "space-y-4 transition-opacity duration-150 motion-reduce:transition-none",
          // Dimmed, never replaced. Swapping the rows for a spinner makes the
          // screen flash empty on every keystroke, which reads as "no results"
          // again and again while somebody is still typing the word.
          pending && "opacity-60",
        )}
      >
        {children}
      </div>
    </div>
  );
}
