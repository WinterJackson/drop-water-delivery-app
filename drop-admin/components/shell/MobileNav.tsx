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
            className="absolute inset-x-0 bottom-0 flex max-h-[85dvh] flex-col rounded-t-2xl border-t border-default bg-surface pb-safe shadow-2xl"
          >
            <div className="flex shrink-0 items-center justify-between border-b border-default px-4 py-3">
              <div className="min-w-0">
                <p className="truncate font-semibold">{me.name ?? me.email}</p>
                <p className="truncate text-xs capitalize text-muted">
                  {me.role.replace(/_/g, " ")}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close navigation"
                className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-default"
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

      <nav
        aria-label="Primary"
        className="fixed inset-x-0 bottom-0 z-40 border-t border-default bg-surface/95 pb-safe backdrop-blur lg:hidden"
      >
        <ul
          className="grid"
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
                    "relative flex h-14 flex-col items-center justify-center gap-1",
                    active ? "text-[var(--accent)]" : "text-muted",
                  )}
                >
                  <span className="relative">
                    <Icon className="h-5 w-5" aria-hidden />
                    {count !== undefined && count > 0 ? (
                      <span
                        aria-hidden
                        className="absolute -right-2 -top-1 min-w-4 rounded-full bg-[var(--warning)] px-1 text-center text-[10px] font-bold leading-4 text-[var(--accent-foreground)]"
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

                  {/* The active marker is a shape, not just a colour, so the
                      current tab survives a colour-vision difference. */}
                  <span
                    aria-hidden
                    className={cn(
                      "h-1 w-1 rounded-full",
                      active ? "bg-[var(--accent)]" : "bg-transparent",
                    )}
                  />
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
              className={cn(
                "relative flex h-14 w-full flex-col items-center justify-center gap-1",
                moreActive ? "text-[var(--accent)]" : "text-muted",
              )}
            >
              <span className="relative">
                <MoreHorizontal className="h-5 w-5" aria-hidden />
                {hiddenBadgeTotal > 0 ? (
                  <span
                    aria-hidden
                    className="absolute -right-2 -top-1 min-w-4 rounded-full bg-[var(--warning)] px-1 text-center text-[10px] font-bold leading-4 text-[var(--accent-foreground)]"
                  >
                    {hiddenBadgeTotal > 9 ? "9+" : hiddenBadgeTotal}
                  </span>
                ) : null}
              </span>
              <span className="sr-only">
                More{hiddenBadgeTotal > 0 ? `, ${hiddenBadgeTotal} waiting` : ""}
              </span>
              <span
                aria-hidden
                className={cn(
                  "h-1 w-1 rounded-full",
                  moreActive ? "bg-[var(--accent)]" : "bg-transparent",
                )}
              />
            </button>
          </li>
        </ul>
      </nav>
    </>
  );
}
