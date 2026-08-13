"use client";

import Link from "next/link";

import { cn } from "@/lib/utils/cn";
import { isActive, type NavSection } from "@/components/shell/nav-config";
import type { NavCounts } from "@/lib/nav-counts";

/**
 * The grouped list of destinations, shared by the desktop sidebar and the
 * mobile drawer.
 *
 * Written once so the two cannot drift — a page that is reachable at a desk and
 * not on a phone is a page whose queue silently stops being worked.
 *
 * Both its hosts are the `--chrome` accent, so every colour here is an on-accent
 * one and **nothing is dimmed**. Near-white on that ground measures 4.62:1 in
 * light mode, which is the ceiling rather than a starting point — a muted
 * variant of it fails AA outright. So an inactive row is the same colour as an
 * active one, and the difference is carried by weight and by the solid plate.
 */
export function NavList({
  sections,
  pathname,
  counts,
  onNavigate,
}: {
  sections: NavSection[];
  pathname: string;
  counts: NavCounts;
  /** Lets the drawer close itself on selection. */
  onNavigate?: () => void;
}) {
  return (
    <ul className="space-y-6">
      {sections.map((section) => (
        <li key={section.title}>
          {/* Full strength, like everything else here. A section label is
              information, so it needs the same 4.5:1 a row does — and on this
              ground there is no lighter shade that still clears it. It reads as
              a label instead by being smaller and more widely tracked. */}
          <p className="px-2 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.09em]">
            {section.title}
          </p>
          <ul className="space-y-0.5">
            {section.items.map((item) => {
              const active = isActive(pathname, item.href);
              const Icon = item.icon;
              const count = item.badge ? counts[item.badge] : undefined;

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors",
                      active
                        ? // Inverts to the content area's own material: 4.74:1
                          // light and 6.26:1 dark, for the plate against the
                          // panel and for the label against the plate.
                          "bg-[var(--chrome-active)] font-semibold text-[var(--chrome-active-foreground)] shadow-sm"
                        : // Hover darkens under light mode's near-white text
                          // and lightens under dark mode's near-black, so the
                          // row gets *more* legible on hover, never less. The
                          // translucent-white wash this replaces measured
                          // 3.83:1 in light and failed.
                          "font-medium hover:bg-[var(--chrome-hover)]",
                    )}
                  >
                    <Icon className="h-4 w-4 shrink-0" aria-hidden />
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>

                    {/* A count is only rendered when the backend sent one, and
                        it only sends the queues this administrator may open. An
                        absent key is a refusal, not a zero — and zero is worth
                        showing, because "nothing waiting" is the answer people
                        come to this nav for. */}
                    {count !== undefined && count > 0 ? (
                      <span
                        className={cn(
                          "shrink-0 rounded-full px-1.5 py-0.5 text-[11px] font-semibold tabular-nums",
                          // Whichever ground the row is on, the chip takes the
                          // other one — 4.62:1 light, 6.87:1 dark, both ways
                          // round. The amber it replaces was a 1.87:1 patch
                          // against this panel: legible text inside a boundary
                          // nobody could see.
                          active
                            ? "bg-[var(--chrome)] text-[var(--chrome-foreground)]"
                            : "bg-[var(--chrome-foreground)] text-[var(--chrome)]",
                        )}
                      >
                        {count > 99 ? "99+" : count}
                        <span className="sr-only"> waiting</span>
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ul>
  );
}
