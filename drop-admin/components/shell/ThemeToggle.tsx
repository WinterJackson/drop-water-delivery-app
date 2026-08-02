"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type Theme = "light" | "dark";

/**
 * Follows the OS until the operator says otherwise, then remembers.
 *
 * The stored value is written to `data-theme` on the root element, which the
 * stylesheet gives precedence over the `prefers-color-scheme` block — so an
 * explicit choice wins in both directions rather than only being able to
 * darken a light OS.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem("drop.admin.theme") as Theme | null;
    const system: Theme = window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
    const initial = stored ?? system;
    setTheme(initial);
    document.documentElement.dataset.theme = initial;
  }, []);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem("drop.admin.theme", next);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      // Rendered before hydration resolves the theme, so the label would
      // otherwise claim the wrong direction for a frame.
      aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
      className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-default text-muted hover:text-[var(--foreground)]"
    >
      {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}
