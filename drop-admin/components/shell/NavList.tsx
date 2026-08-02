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
          <p className="px-2 pb-1.5 text-xs font-medium uppercase tracking-wide text-muted">
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
                        ? "bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] font-medium text-[var(--accent)]"
                        : "text-muted hover:bg-surface-muted hover:text-[var(--foreground)]",
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
                          active
                            ? "bg-[var(--accent)] text-[var(--accent-foreground)]"
                            : "bg-[color-mix(in_oklch,var(--warning)_20%,transparent)] text-[var(--warning)]",
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
