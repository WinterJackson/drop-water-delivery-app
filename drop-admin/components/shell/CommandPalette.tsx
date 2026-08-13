"use client";

import { Loader2, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { searchEverything, type SearchHit } from "@/app/(dashboard)/search-action";
import type { ControlTone } from "@/components/shell/ThemeToggle";
import { useFocusTrap } from "@/lib/hooks/useFocusTrap";
import { cn } from "@/lib/utils/cn";

/** Only the closed trigger takes a tone. The dialog itself is a modal over the
 *  page, on `--surface` like every other overlay in the console. */
const TRIGGER_TONES: Record<ControlTone, string> = {
  surface: "border-default text-muted hover:text-[var(--foreground)]",
  chrome: "border-chrome-edge text-chrome-foreground hover:bg-[var(--chrome-hover)]",
};

/** Below this the server is not asked. Stated on screen rather than left as
 *  silence, which reads as a box that does not work. */
const MIN_TERM = 2;

/**
 * ⌘K — one box that resolves a phone number, email, name, plate or order id to
 * the right page.
 *
 * An operator answering a support call has a phone number, not a UUID, and
 * three separate list screens with three search boxes means guessing which
 * account type the caller is before you can look them up.
 *
 * Results are scoped by capability on the **server**, so this cannot be used to
 * enumerate a table whose detail page the caller is not allowed to open.
 */
export function CommandPalette({ tone = "surface" }: { tone?: ControlTone }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<SearchHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();

  // Traps Tab inside the dialog while it is open and hands focus back to
  // whatever opened it on close. `aria-modal="true"` below is a promise this
  // keeps; without it, Tab walks out into the page behind the overlay.
  useFocusTrap(open, dialogRef, { onEscape: () => setOpen(false) });

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((value) => !value);
      }
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) {
      inputRef.current?.focus();
    } else {
      setTerm("");
      setHits([]);
      setActive(0);
      setLoading(false);
    }
  }, [open]);

  // The page behind a modal must not scroll under it — the same rule the
  // mobile drawer follows, and the palette was missing it: a wheel over the
  // scrim scrolled the console away behind the dialog.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // Which request the answer on screen belongs to. Debouncing thins the
  // requests out; it does not order the *replies*. "07" typed, then "0712"
  // typed, and the first query — the broader one, so the slower one — can land
  // second and replace the narrower results with results for a prefix the box
  // no longer contains. The operator sees a list that does not match what they
  // typed and no way to tell why.
  const latest = useRef(0);

  const run = useCallback(async (value: string) => {
    const ticket = ++latest.current;
    if (value.trim().length < MIN_TERM) {
      setHits([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      const results = await searchEverything(value);
      if (ticket !== latest.current) return; // superseded while in flight
      setHits(results);
      setActive(0);
    } finally {
      if (ticket === latest.current) setLoading(false);
    }
  }, []);

  // Debounced: without this every keystroke is three ILIKE scans against the
  // database, which is a denial of service against your own platform.
  useEffect(() => {
    const timer = setTimeout(() => void run(term), 220);
    return () => clearTimeout(timer);
  }, [term, run]);

  // Keep the highlighted result on screen. The list scrolls at eight or so
  // rows, and without this the highlight walks off the bottom and arrowing
  // down appears to do nothing at all.
  useEffect(() => {
    if (!open) return;
    document
      .getElementById(`${listboxId}-${active}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active, hits, open, listboxId]);

  function go(hit: SearchHit) {
    setOpen(false);
    router.push(hit.href);
  }

  const termLength = term.trim().length;

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        // Square icon button on a phone, where the header has no width to
        // spare; a labelled control with its shortcut from `sm` up.
        aria-label="Search the platform"
        className={cn(
          "inline-flex h-9 w-9 items-center justify-center gap-2 rounded-lg border text-sm transition-colors sm:w-auto sm:px-3",
          TRIGGER_TONES[tone],
        )}
      >
        <Search className="h-4 w-4 shrink-0" aria-hidden />
        <span className="hidden sm:inline">Search</span>
        <kbd
          className={cn(
            "hidden rounded border px-1 text-[10px] sm:inline",
            tone === "chrome" ? "border-chrome-edge" : "border-default",
          )}
        >
          ⌘K
        </kbd>
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Search the platform"
      // Hangs from the header rather than from a fraction of the viewport.
      // `--header-block` is the header's own drop plus its own height, so the
      // panel opens exactly one `--chrome-inset` below the bar it belongs to,
      // at every width, and cannot drift if the bar changes height. `12vh`
      // put it at 61px on a laptop — under the header — and 130px on a tall
      // monitor.
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/40 px-4 pt-[calc(var(--header-block)+var(--chrome-inset))]"
      onClick={(event) => {
        if (event.target === event.currentTarget) setOpen(false);
      }}
    >
      <div
        ref={dialogRef}
        className="w-full max-w-lg overflow-hidden rounded-xl border border-default bg-surface shadow-2xl"
      >
        <div className="flex items-center gap-3 border-b border-default px-4">
          <Search className="h-4 w-4 shrink-0 text-muted" aria-hidden />
          <input
            ref={inputRef}
            value={term}
            onChange={(event) => {
              setTerm(event.target.value);
              setActive(0);
            }}
            onKeyDown={(event) => {
              // Wraps at both ends. A list this short is a ring, and the
              // alternative is an arrow key that silently stops working.
              if (event.key === "ArrowDown" && hits.length) {
                event.preventDefault();
                setActive((i) => (i + 1) % hits.length);
              }
              if (event.key === "ArrowUp" && hits.length) {
                event.preventDefault();
                setActive((i) => (i - 1 + hits.length) % hits.length);
              }
              if (event.key === "Home" && hits.length) {
                event.preventDefault();
                setActive(0);
              }
              if (event.key === "End" && hits.length) {
                event.preventDefault();
                setActive(hits.length - 1);
              }
              if (event.key === "Enter") {
                event.preventDefault();
                const hit = hits[active];
                if (hit) go(hit);
              }
            }}
            placeholder="Phone, email, name, plate or order id…"
            aria-label="Search customers, riders, vendors and orders"
            role="combobox"
            aria-expanded={hits.length > 0}
            aria-controls={listboxId}
            aria-activedescendant={hits[active] ? `${listboxId}-${active}` : undefined}
            aria-autocomplete="list"
            // A search box, told to the browser and the keyboard: no
            // autocomplete history over an operator's shoulder, no red
            // squiggle under a number plate, and a "search" key on a phone
            // rather than a newline that does nothing.
            type="search"
            inputMode="search"
            enterKeyHint="search"
            autoComplete="off"
            autoCorrect="off"
            spellCheck={false}
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted"
          />
          {loading ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted" aria-hidden /> : null}
        </div>

        <p role="status" aria-live="polite" className="sr-only">
          {loading
            ? "Searching"
            : hits.length > 0
              ? `${hits.length} result${hits.length === 1 ? "" : "s"}`
              : termLength >= MIN_TERM
                ? "No results"
                : ""}
        </p>

        {/* Three states, all written. A box that answers nothing until some
            unstated number of characters have been typed reads as broken, and
            the first thing an operator does with a broken search is stop
            using it. */}
        {termLength < MIN_TERM ? (
          <p className="px-4 py-6 text-center text-sm text-muted">
            {termLength === 0
              ? "Search customers, riders, vendors and orders."
              : `Keep typing — ${MIN_TERM} characters or more.`}
          </p>
        ) : null}

        {termLength >= MIN_TERM && !loading && hits.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-muted">
            Nothing found. Only records you have permission to open are searched.
          </p>
        ) : null}

        {hits.length > 0 ? (
          <ul id={listboxId} role="listbox" aria-label="Search results" className="max-h-80 overflow-y-auto py-1">
            {hits.map((hit, index) => (
              <li key={`${hit.kind}-${hit.id}`}>
                <button
                  type="button"
                  id={`${listboxId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => go(hit)}
                  className={
                    index === active
                      ? "flex w-full items-center gap-3 bg-surface-muted px-4 py-2.5 text-left"
                      : "flex w-full items-center gap-3 px-4 py-2.5 text-left"
                  }
                >
                  <span className="w-16 shrink-0 text-xs capitalize text-muted">{hit.kind}</span>
                  <span className="min-w-0 flex-1 truncate text-sm font-medium">{hit.title}</span>
                  <span className="shrink-0 font-mono text-xs text-muted">{hit.subtitle}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
