"use client";

import { usePathname } from "next/navigation";

import { NavList } from "@/components/shell/NavList";
import { visibleSections } from "@/components/shell/nav-config";
import type { NavCounts } from "@/lib/nav-counts";
import type { AdminMe } from "@/lib/permissions";

/**
 * The desktop sidebar. Hidden below `lg`, where the bottom tab bar and the
 * drawer take over.
 *
 * `sticky` rather than `fixed` so it participates in the flex row and the main
 * column can never end up underneath it — the failure mode of a fixed sidebar
 * is a content area whose first 16rem are unreachable at certain zoom levels.
 */
export function Sidebar({ me, counts }: { me: AdminMe; counts: NavCounts }) {
  const pathname = usePathname();
  const sections = visibleSections(me.permissions);

  return (
    <nav
      aria-label="Main"
      className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-default bg-surface lg:flex"
    >
      <div className="flex h-14 shrink-0 items-center gap-2 border-b border-default px-5">
        {/* The wordmark, not a heading — so it needs the heading face named
            explicitly. The `h1…h6` rule in `globals.css` cannot reach a span,
            and this is the one piece of brand on the console. */}
        <span className="font-heading text-lg font-semibold tracking-tight">Drop</span>
        <span className="text-sm text-muted">Admin</span>
      </div>

      {/* The list scrolls; the identity block below it does not, so an operator
          can always see which account they are acting as. That matters on a
          console where actions are attributed by name in an audit log. */}
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
        <NavList sections={sections} pathname={pathname} counts={counts} />
      </div>

      <div className="shrink-0 border-t border-default p-3">
        <div className="rounded-lg bg-surface-muted px-3 py-2.5">
          <p className="truncate text-sm font-medium">{me.name ?? me.email}</p>
          <p className="truncate text-xs capitalize text-muted">{me.role.replace(/_/g, " ")}</p>
        </div>
      </div>
    </nav>
  );
}
