"use client";

import { Loader2, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { searchEverything, type SearchHit } from "@/app/(dashboard)/search-action";
import { useFocusTrap } from "@/lib/hooks/useFocusTrap";

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
export function CommandPalette() {
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
    }
  }, [open]);

  const run = useCallback(async (value: string) => {
    if (value.trim().length < 2) {
      setHits([]);
      return;
    }
    setLoading(true);
    try {
      setHits(await searchEverything(value));
    } finally {
      setLoading(false);
    }
  }, []);

  // Debounced: without this every keystroke is three ILIKE scans against the
  // database, which is a denial of service against your own platform.
  useEffect(() => {
    const timer = setTimeout(() => void run(term), 220);
    return () => clearTimeout(timer);
  }, [term, run]);

  function go(hit: SearchHit) {
    setOpen(false);
    router.push(hit.href);
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        // Square icon button on a phone, where the header has no width to
        // spare; a labelled control with its shortcut from `sm` up.
        aria-label="Search the platform"
        className="inline-flex h-9 w-9 items-center justify-center gap-2 rounded-lg border border-default text-sm text-muted hover:text-[var(--foreground)] sm:w-auto sm:px-3"
      >
        <Search className="h-4 w-4 shrink-0" aria-hidden />
        <span className="hidden sm:inline">Search</span>
        <kbd className="hidden rounded border border-default px-1 text-[10px] sm:inline">⌘K</kbd>
      </button>
    );
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Search the platform"
      className="fixed inset-0 z-[60] flex items-start justify-center bg-black/40 px-4 pt-[12vh]"
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
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActive((i) => Math.min(i + 1, hits.length - 1));
              }
              if (event.key === "ArrowUp") {
                event.preventDefault();
                setActive((i) => Math.max(i - 1, 0));
              }
              if (event.key === "Enter") {
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
            className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted"
          />
          {loading ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted" aria-hidden /> : null}
        </div>

        <p role="status" aria-live="polite" className="sr-only">
          {loading
            ? "Searching"
            : hits.length > 0
              ? `${hits.length} result${hits.length === 1 ? "" : "s"}`
              : term.trim().length >= 2
                ? "No results"
                : ""}
        </p>

        {term.trim().length >= 2 && !loading && hits.length === 0 ? (
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
