"use client";

import { MoreHorizontal, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { NavList } from "@/components/shell/NavList";
import { isActive, tabBarItems, visibleSections } from "@/components/shell/nav-config";
import { useFocusTrap } from "@/lib/hooks/useFocusTrap";
import type { NavCounts } from "@/lib/nav-counts";
import type { AdminMe } from "@/lib/permissions";
import { cn } from "@/lib/utils/cn";

/**
 * Navigation below `lg`: a fixed bottom tab bar, plus a drawer behind "More".
 *
 * A phone is a first-class way to use this console, not a degraded one — the
 * person approving a rider at 7am is doing it between other things, standing
 * up. So the primary destinations sit under the thumb rather than behind a
 * hamburger two taps away, and the drawer exists only for the long tail.
 *
 * Icons only, by design: five labelled tabs on a 360px screen truncate to
 * "Ver…", "Dis…", "Pay…", which is worse than an icon. Each tab still carries a
 * real accessible name, so a screen reader announces the word the label would
 * have shown.
 *
 * Both surfaces here are `--chrome`, the same accent as the desktop sidebar,
 * because that is what these *are* — this is the sidebar on a phone, not a
 * separate piece of furniture. It is also forced: the drawer renders `NavList`,
 * whose every colour is an on-accent one, so putting it on `--surface` would
 * mean a second variant of every rule in that component.
 *
 * The bar is opaque rather than `bg-surface/95 backdrop-blur`. Text on this
 * ground has 4.62:1 in light mode and no more, and 5% of an unknown colour
 * scrolling underneath is not a risk that budget can absorb.
 */
export function MobileNav({ me, counts }: { me: AdminMe; counts: NavCounts }) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const drawerRef = useRef<HTMLDivElement>(null);

  useFocusTrap(open, drawerRef, { onEscape: () => setOpen(false) });

  // A tap that navigates must also dismiss the drawer, or the new page renders
  // underneath an open overlay.
  useEffect(() => setOpen(false), [pathname]);

  // The page behind a modal drawer must not scroll under it.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  const tabs = tabBarItems(me.permissions);
  const sections = visibleSections(me.permissions);

  // Everything reachable from the drawer but not on the bar. If a queue in
  // there is waiting on someone, "More" says so — otherwise the tab bar quietly
  // hides the fact that work is piling up two taps away.
  const hiddenBadgeTotal = sections
    .flatMap((section) => section.items)
    .filter((item) => !tabs.some((tab) => tab.href === item.href))
    .reduce((total, item) => total + (item.badge ? (counts[item.badge] ?? 0) : 0), 0);

  const moreActive = !tabs.some((tab) => isActive(pathname, tab.href));

  return (
    <>
      {open ? (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-black/50"
          />

          {/* A bottom sheet rather than a side drawer: it opens next to the
              thumb that summoned it, and `max-h` keeps it short of the status
              bar so the page behind stays visibly present. */}
          <div
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-label="All pages"
            className="brand-chrome absolute bottom-0 left-[var(--chrome-inset)] right-[var(--chrome-inset)] flex max-h-[85dvh] flex-col rounded-t-[40px] bg-chrome pb-safe text-chrome-foreground shadow-2xl"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-chrome px-5 py-3">
              <div className="min-w-0">
                <p className="truncate font-semibold">{me.name ?? me.email}</p>
                <p className="truncate text-xs capitalize">{me.role.replace(/_/g, " ")}</p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close navigation"
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-chrome-edge transition-colors hover:bg-[var(--chrome-hover)]"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
              <NavList
                sections={sections}
                pathname={pathname}
                counts={counts}
                onNavigate={() => setOpen(false)}
              />
            </div>
          </div>
        </div>
      ) : null}

      {/* Same two-element split as the header, mirrored. The outer element is
          the fixed one and carries the page's own ground, so the 10px the bar
          is lifted by is a solid strip rather than a window the page scrolls
          through underneath it.

          `pb-safe` stays on the *bar*, not on the drop. The home indicator has
          to be cleared by the bar's own padding — moving it outward would lift
          the bar 34px off the bottom of an iPhone instead of 10. */}
      <nav
        aria-label="Primary"
        className="brand-chrome fixed inset-x-0 bottom-0 z-40 bg-[var(--background)] pb-[var(--chrome-inset)] pl-[var(--chrome-inset)] lg:hidden"
      >
        <ul
          className="grid rounded-l-[40px] bg-chrome pb-safe text-chrome-foreground"
          // One column per tab plus "More". Set inline because the count varies
          // with the caller's permissions, and Tailwind cannot emit a class for
          // a number it does not know at build time.
          style={{ gridTemplateColumns: `repeat(${tabs.length + 1}, minmax(0, 1fr))` }}
        >
          {tabs.map((item) => {
            const active = isActive(pathname, item.href);
            const Icon = item.icon;
            const count = item.badge ? counts[item.badge] : undefined;

            return (
              <li key={item.href}>
                <Link
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  // Icons carry no text, so the name has to come from here.
                  aria-label={item.label}
                  className={cn(
                    // 56px tall: comfortably past the 44px minimum target, and
                    // the whole cell is the target rather than just the glyph.
                    "relative flex h-14 flex-col items-center justify-center",
                  )}
                >
                  {/* The current tab is a filled plate, not a tinted glyph.
                      That is the same inversion the sidebar's active row uses,
                      and it is a *shape* — so the current tab survives a
                      colour-vision difference without needing the separate dot
                      marker this replaces. */}
                  <span
                    className={cn(
                      "relative flex h-9 w-9 items-center justify-center rounded-full transition-colors",
                      active
                        ? "bg-[var(--chrome-active)] text-[var(--chrome-active-foreground)]"
                        : "text-chrome-foreground",
                    )}
                  >
                    <Icon className="h-5 w-5" aria-hidden />
                    {count !== undefined && count > 0 ? (
                      <span
                        aria-hidden
                        // Ringed in the bar's own colour so the chip separates
                        // from *either* ground — the accent bar behind an
                        // inactive tab, or the light plate behind an active
                        // one. Amber on this panel measured 1.38:1.
                        className="absolute -right-1.5 -top-0.5 min-w-4 rounded-full bg-[var(--chrome-foreground)] px-1 text-center text-[10px] font-bold leading-4 text-[var(--chrome)] ring-2 ring-[var(--chrome)]"
                      >
                        {count > 9 ? "9+" : count}
                      </span>
                    ) : null}
                  </span>

                  {/* The short label is announced but not drawn — the request
                      was icons only, and this is what keeps that from meaning
                      "unlabelled" to anyone using a screen reader. */}
                  <span className="sr-only">
                    {item.short}
                    {count !== undefined && count > 0 ? `, ${count} waiting` : ""}
                  </span>
                </Link>
              </li>
            );
          })}

          <li>
            <button
              type="button"
              onClick={() => setOpen(true)}
              aria-expanded={open}
              aria-haspopup="dialog"
              aria-label="More pages"
              className="relative flex h-14 w-full flex-col items-center justify-center"
            >
              <span
                className={cn(
                  "relative flex h-9 w-9 items-center justify-center rounded-full transition-colors",
                  moreActive
                    ? "bg-[var(--chrome-active)] text-[var(--chrome-active-foreground)]"
                    : "text-chrome-foreground",
                )}
              >
                <MoreHorizontal className="h-5 w-5" aria-hidden />
                {hiddenBadgeTotal > 0 ? (
                  <span
                    aria-hidden
                    className="absolute -right-1.5 -top-0.5 min-w-4 rounded-full bg-[var(--chrome-foreground)] px-1 text-center text-[10px] font-bold leading-4 text-[var(--chrome)] ring-2 ring-[var(--chrome)]"
                  >
                    {hiddenBadgeTotal > 9 ? "9+" : hiddenBadgeTotal}
                  </span>
                ) : null}
              </span>
              <span className="sr-only">
                More{hiddenBadgeTotal > 0 ? `, ${hiddenBadgeTotal} waiting` : ""}
              </span>
            </button>
          </li>
        </ul>
      </nav>
    </>
  );
}
