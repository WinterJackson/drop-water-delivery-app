"use client";

import { usePathname } from "next/navigation";

import { NavList } from "@/components/shell/NavList";
import { visibleSections } from "@/components/shell/nav-config";
import { Logo } from "@/components/ui/Logo";
import type { NavCounts } from "@/lib/nav-counts";
import type { AdminMe } from "@/lib/permissions";

/**
 * The desktop sidebar. Hidden below `lg`, where the bottom tab bar and the
 * drawer take over.
 *
 * `sticky` rather than `fixed` so it participates in the flex row and the main
 * column can never end up underneath it — the failure mode of a fixed sidebar
 * is a content area whose first 16rem are unreachable at certain zoom levels.
 *
 * Painted in `--chrome`, the same accent the sign-in page's branding panel
 * uses, so the console the operator signs into looks like the page they signed
 * in from. Everything that follows from that — why nothing here is dimmed, why
 * hover darkens, why the active row inverts — is written up against measured
 * contrast ratios in `globals.css`. The short version: on this ground there is
 * no contrast budget to spend on opacity, so hierarchy is weight, size and the
 * solid active plate.
 *
 * `brand-chrome` is not decoration: it re-points `:focus-visible` at a colour
 * that is visible against the accent. Without it the ring is the accent, on the
 * accent.
 */
export function Sidebar({ me, counts }: { me: AdminMe; counts: NavCounts }) {
  const pathname = usePathname();
  const sections = visibleSections(me.permissions);

  return (
    <nav
      aria-label="Main"
      className="brand-chrome sticky top-0 hidden h-dvh w-64 shrink-0 py-[10px] lg:block"
    >
      {/* Two elements, and the split is the whole point of the 10px.

          Padding *inside* a filled panel is invisible — the background paints
          the padding box, so a 10px inset on the accent element itself just
          moves the content down and leaves the blue running edge to edge. The
          inset has to sit on an element that is **not** the accent. So the
          `nav` carries the padding and no ground of its own, the page shows
          through it, and this is the panel. Exactly the arrangement the header
          bar uses, which is why the two line up: both accent surfaces start at
          y=10 and the wordmark below sits on the breadcrumb's line.

          `h-full` resolves against the nav's content box — `100dvh` less the
          20px of padding — so the panel ends 10px clear of the bottom too, and
          both right-hand corners get to show their radius. */}
      <div className="flex h-full flex-col rounded-r-[40px] bg-chrome text-chrome-foreground">
        {/* The same wordmark, on the same light plate, as the top-left of the
            sign-in page — and for the same reason: both variants of the artwork
            are blue, so neither reads against an accent panel without one.

            The 10px is *padding*, not centring in a fixed row. The row used to
            be `h-14 items-center`, which left the plate 4px off the panel's top
            edge — near enough to read as touching it, and a figure that moves
            whenever the plate's height changes. This states the gap instead. */}
        <div className="flex shrink-0 items-center px-5 pt-[var(--chrome-inset)]">
          <Logo
            href="/"
            height={28}
            label="Drop Admin, dashboard"
            className="rounded-xl bg-surface p-[var(--chrome-inset)] shadow-sm"
          />
        </div>

        {/* The list scrolls; the identity block below it does not, so an
            operator can always see which account they are acting as. That
            matters on a console where actions are attributed by name in an
            audit log. */}
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-4">
          <NavList sections={sections} pathname={pathname} counts={counts} />
        </div>

        {/* A rule rather than the plate this used to be. A tinted block here
            would sit at the same value as the hover ground and read as a row
            that is permanently hovered. */}
        <div className="shrink-0 border-t border-chrome px-5 pb-4 pt-3">
          <p className="truncate text-sm font-semibold">{me.name ?? me.email}</p>
          <p className="truncate text-xs capitalize">{me.role.replace(/_/g, " ")}</p>
        </div>
      </div>
    </nav>
  );
}
