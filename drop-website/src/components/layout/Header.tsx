"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { ThemeToggle } from "./ThemeToggle";
import { Logo } from "@/components/ui/Logo";
import { cn } from "@/lib/utils/cn";

const navItems = [
  { label: "Home", href: "/" },
  { label: "Apps", href: "/apps" },
  { label: "About", href: "/about" },
  { label: "Contact", href: "/contact" },
];

export function Header() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <>
      <div className="brand-chrome sticky top-0 z-40 shrink-0 bg-[var(--background)] pl-[var(--chrome-inset)] pt-[var(--chrome-inset)] pb-[var(--chrome-inset)]">
        <header className="flex h-[var(--header-height)] items-center gap-3 rounded-l-[40px] bg-[var(--chrome)] pl-4 pr-3 text-[var(--chrome-foreground)] sm:pl-6 lg:pl-10 lg:pr-6">
          {/* Logo */}
          <Logo
            href="/"
            height={20}
            label="Drop Home"
            className="shrink-0 rounded-lg bg-[var(--surface)] px-2 py-1.5"
          />

          {/* Desktop Nav */}
          <nav aria-label="Main Navigation" className="hidden md:flex flex-1 items-center justify-end pr-4">
            <ul className="flex items-center gap-1">
              {navItems.map((item) => {
                const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className={cn(
                        "rounded-lg px-3.5 py-2 text-sm font-medium transition-colors",
                        isActive
                          ? "bg-white/15 font-semibold"
                          : "opacity-85 hover:opacity-100 hover:bg-white/10"
                      )}
                    >
                      {item.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>

          {/* Mobile spacer */}
          <div className="flex-1 md:hidden" />

          {/* Right actions */}
          <div className="flex shrink-0 items-center gap-1.5">
            <Link
              href="/become-a-vendor"
              className="hidden lg:flex h-8 items-center justify-center rounded-lg border border-[var(--chrome-edge)] px-3.5 text-xs font-semibold transition-colors hover:bg-[var(--chrome-hover)]"
            >
              Become a Vendor
            </Link>
            <ThemeToggle tone="chrome" />
            {/* Mobile menu button */}
            <button
              type="button"
              onClick={() => setMobileOpen(!mobileOpen)}
              className="inline-flex md:hidden h-8 w-8 items-center justify-center rounded-lg border border-[var(--chrome-edge)] transition-colors hover:bg-[var(--chrome-hover)]"
              aria-label="Toggle navigation menu"
            >
              {mobileOpen ? <X className="h-4 w-4" /> : <Menu className="h-4 w-4" />}
            </button>
          </div>
        </header>
      </div>

      {/* Mobile dropdown */}
      {mobileOpen && (
        <div className="fixed inset-x-0 top-[calc(var(--chrome-inset)+var(--header-height))] z-30 md:hidden animate-fade-in-up">
          <div className="mx-[var(--chrome-inset)] mt-1 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-2 shadow-xl">
            <nav>
              <ul className="flex flex-col">
                {navItems.map((item) => {
                  const isActive = pathname === item.href || (item.href !== "/" && pathname.startsWith(item.href));
                  return (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        onClick={() => setMobileOpen(false)}
                        className={cn(
                          "block rounded-xl px-4 py-3 text-sm font-medium transition-colors",
                          isActive
                            ? "bg-[var(--accent-subtle)] text-[var(--accent)] font-semibold"
                            : "text-[var(--foreground)] hover:bg-[var(--surface-muted)]"
                        )}
                      >
                        {item.label}
                      </Link>
                    </li>
                  );
                })}
                <li className="border-t border-[var(--border)] mt-1 pt-1">
                  <Link
                    href="/become-a-vendor"
                    onClick={() => setMobileOpen(false)}
                    className="block rounded-xl px-4 py-3 text-sm font-semibold text-[var(--accent)] hover:bg-[var(--surface-muted)]"
                  >
                    Become a Vendor
                  </Link>
                </li>
                <li>
                  <Link
                    href="/become-a-rider"
                    onClick={() => setMobileOpen(false)}
                    className="block rounded-xl px-4 py-3 text-sm font-semibold text-[var(--accent)] hover:bg-[var(--surface-muted)]"
                  >
                    Drive with Drop
                  </Link>
                </li>
              </ul>
            </nav>
          </div>
        </div>
      )}
    </>
  );
}
