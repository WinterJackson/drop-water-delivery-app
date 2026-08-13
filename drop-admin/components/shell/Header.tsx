"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { CommandPalette } from "@/components/shell/CommandPalette";
import { ThemedUserButton } from "@/components/shell/ThemedUserButton";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { matchItem, sectionOf } from "@/components/shell/nav-config";
import { Logo } from "@/components/ui/Logo";

/**
 * The application bar: where you are on the left, what you can do on the right.
 *
 * On a phone the breadcrumb collapses to the page name alone — there is no
 * sidebar visible to orient against, so the one thing worth the width is which
 * screen this is.
 *
 * Two elements, not one. The outer element is the sticky one and is painted in
 * the **page** background; the bar inside it is the accent. That is what turns
 * the 10px inset into a visible channel between the sidebar and the bar rather
 * than a transparent window — a sticky bar with padding but no ground of its own
 * lets the page scroll through the gap above it.
 *
 * The bar is opaque for the same reason the sidebar has no dimmed text: it used
 * to be `bg-surface/85 backdrop-blur`, and 15% of whatever happens to be
 * scrolling underneath is 15% of an unknown colour behind text that has 4.62:1
 * to spare. Translucency and a measured contrast floor cannot both hold.
 */
export function Header() {
  const pathname = usePathname();
  const item = matchItem(pathname);
  const section = item ? sectionOf(item) : undefined;

  // Anything below a nav entry — `/people/riders/<uuid>` — is a record. The id
  // itself is deliberately not rendered: a breadcrumb showing a UUID tells a
  // human nothing, and this console's pages are full of identifiers that should
  // not end up in a screenshot or a referrer.
  const isDetail = Boolean(item && pathname !== item.href);

  return (
    <div className="brand-chrome sticky top-0 z-30 shrink-0 bg-[var(--background)] pl-[var(--chrome-inset)] pt-[var(--chrome-inset)]">
      {/* The inset is on every side that has something beside it, at every
          width: below `lg` the 10px on the left is the screen edge rather than
          the sidebar, and the bar reads as a card either way.

          The left padding differs by breakpoint because what sits against the
          curve differs. At 56px tall the browser scales a 40px left radius down
          to 28px per corner — two radii on one 56px side cannot both be 40 — so
          the bar ends in a pill.

          From `lg` that first item is *text*, whose glyphs run the full height
          of the line box and would cross the arc, so it clears the curve at
          `pl-10`. Below `lg` it is the logo plate: 34px tall and centred, so it
          only ever meets the arc between y=11 and y=45, where a 28px circle has
          already come in to x≈5.8. 10px therefore clears it with room to spare,
          and the plate's own 12px corners pull further away still. */}
      <header className="flex h-[var(--header-height)] items-center gap-3 rounded-l-[40px] bg-chrome pl-[var(--chrome-inset)] pr-4 text-chrome-foreground lg:pl-10 lg:pr-6">
        {/* The brand only appears where the sidebar is not showing it — and
            below `lg` there is no sidebar, so this is the only mark on screen.
            Same plate as the sidebar's and the sign-in page's, for the same
            reason: both variants of the artwork are blue. */}
        <Logo
          href="/"
          height={22}
          label="Drop Admin, dashboard"
          className="shrink-0 rounded-xl bg-surface px-2.5 py-1.5 lg:hidden"
        />

        {/* One breadcrumb, laid out two ways.
         *
         * A phone has no horizontal room for a trail — the bar is already
         * carrying a wordmark and three controls — so below `sm` the crumbs
         * **stack** rather than compete for the same line. The section becomes
         * a small tracked eyebrow above the page name, and each line truncates
         * independently instead of one long string being cut wherever it
         * happens to land. Two levels are visible at 390px where one barely
         * fitted, and it is the same `<ol>`, so a screen reader hears one
         * breadcrumb at every width rather than two competing copies.
         *
         * The eyebrow reads as secondary through **size and letter-spacing,
         * never opacity**: near-white on the light-mode accent is 4.62:1, the
         * ceiling, so a quieter shade of it fails AA. Same rule, and the same
         * treatment, as the sidebar's section labels.
         *
         * `Record` is the one crumb that stays desktop-only. The id is
         * deliberately never rendered, so it can never say anything more than
         * the word itself — and being `shrink-0` beside a page name that
         * truncates, on a phone it took guaranteed space from the only crumb
         * carrying information. The record's own name is the `<h1>` directly
         * beneath, which is where a name belongs. */}
        <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
          <ol className="flex min-w-0 flex-col items-start leading-tight sm:flex-row sm:items-center sm:gap-1.5 sm:leading-normal">
            {section ? (
              <li className="flex min-w-0 max-w-full items-center gap-1.5 sm:shrink-0">
                <span className="truncate text-[10px] font-semibold uppercase tracking-[0.09em] sm:text-sm sm:font-normal sm:normal-case sm:tracking-normal">
                  {section}
                </span>
                <ChevronRight className="hidden h-3.5 w-3.5 shrink-0 sm:block" aria-hidden />
              </li>
            ) : null}

            <li className="min-w-0 max-w-full">
              {isDetail && item ? (
                <Link href={item.href} className="block truncate text-sm hover:underline">
                  {item.label}
                </Link>
              ) : (
                <span className="block truncate text-sm font-semibold" aria-current="page">
                  {item?.label ?? "Drop Admin"}
                </span>
              )}
            </li>

            {isDetail ? (
              <>
                <li aria-hidden className="hidden shrink-0 sm:block">
                  <ChevronRight className="h-3.5 w-3.5" />
                </li>
                <li className="hidden shrink-0 sm:block">
                  <span className="text-sm font-semibold" aria-current="page">
                    Record
                  </span>
                </li>
              </>
            ) : null}
          </ol>
        </nav>

        <div className="flex shrink-0 items-center gap-2">
          <CommandPalette tone="chrome" />
          <ThemeToggle tone="chrome" />
          {/* Clerk's own control: sign out, manage two-factor. Its popover is
              themed to this bar — see the component. */}
          <ThemedUserButton />
        </div>
      </header>
    </div>
  );
}
