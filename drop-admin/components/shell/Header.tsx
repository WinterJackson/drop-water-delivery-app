"use client";

import { UserButton } from "@clerk/nextjs";
import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { CommandPalette } from "@/components/shell/CommandPalette";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { matchItem, sectionOf } from "@/components/shell/nav-config";

/**
 * The application bar: where you are on the left, what you can do on the right.
 *
 * On a phone the breadcrumb collapses to the page name alone — there is no
 * sidebar visible to orient against, so the one thing worth the width is which
 * screen this is.
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
    <header className="sticky top-0 z-30 flex h-14 shrink-0 items-center gap-3 border-b border-default bg-surface/85 px-4 backdrop-blur lg:px-6">
      {/* The brand only appears where the sidebar is not showing it. */}
      <Link
        href="/"
        className="shrink-0 font-heading text-base font-semibold tracking-tight lg:hidden"
      >
        Drop
      </Link>

      <nav aria-label="Breadcrumb" className="min-w-0 flex-1">
        <ol className="flex min-w-0 items-center gap-1.5 text-sm">
          {section ? (
            <li className="hidden shrink-0 items-center gap-1.5 text-muted sm:flex">
              <span>{section}</span>
              <ChevronRight className="h-3.5 w-3.5" aria-hidden />
            </li>
          ) : null}

          <li className="min-w-0">
            {isDetail && item ? (
              <Link href={item.href} className="truncate text-muted hover:text-[var(--foreground)]">
                {item.label}
              </Link>
            ) : (
              <span className="truncate font-medium" aria-current="page">
                {item?.label ?? "Drop Admin"}
              </span>
            )}
          </li>

          {isDetail ? (
            <>
              <li aria-hidden className="shrink-0 text-muted">
                <ChevronRight className="h-3.5 w-3.5" />
              </li>
              <li className="shrink-0">
                <span className="font-medium" aria-current="page">
                  Record
                </span>
              </li>
            </>
          ) : null}
        </ol>
      </nav>

      <div className="flex shrink-0 items-center gap-2">
        <CommandPalette />
        <ThemeToggle />
        {/* Clerk's own control: sign out, manage two-factor. Sized to match the
            36px controls beside it rather than Clerk's default. */}
        <UserButton
          appearance={{ elements: { avatarBox: { width: "2rem", height: "2rem" } } }}
        />
      </div>
    </header>
  );
}
