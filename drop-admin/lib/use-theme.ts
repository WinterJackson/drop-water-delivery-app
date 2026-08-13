"use client";

import { useEffect, useState } from "react";

/**
 * The console's theme, for the two components that have to know it in
 * JavaScript rather than in CSS.
 *
 * There is no `next-themes` here and there should not be: the stylesheet
 * already resolves three states on its own — an explicit `data-theme` on the
 * root element, and the OS preference when nobody has chosen — and every colour
 * on every screen comes from a custom property that follows those rules for
 * free. A second source of truth would be a second answer to the same question.
 *
 * So this hook does not own the theme. It *writes* `data-theme` when the
 * operator toggles, and otherwise reports what the document already says. Two
 * things can change it underneath a component — another mount of this hook, and
 * the OS moving for somebody who never chose — so it watches for both rather
 * than reading once at mount.
 */

export type Theme = "light" | "dark";

const STORAGE_KEY = "drop.admin.theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

function systemTheme(): Theme {
  return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
}

/** What the page is actually rendering right now. */
function currentTheme(): Theme {
  const stamped = document.documentElement.dataset.theme;
  return stamped === "dark" || stamped === "light" ? stamped : systemTheme();
}

export function useTheme() {
  // `null` until mounted. The server cannot know the theme, so anything that
  // depends on it has to render a stable placeholder for the first paint or
  // React reports a hydration mismatch.
  const [theme, setThemeState] = useState<Theme | null>(null);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORAGE_KEY) as Theme | null;
    const initial = stored ?? systemTheme();
    document.documentElement.dataset.theme = initial;
    setThemeState(initial);

    // The OS flipping for an operator who has never chosen. Once they have,
    // their choice outranks it in both directions.
    const media = window.matchMedia(DARK_QUERY);
    const onSystemChange = () => {
      if (window.localStorage.getItem(STORAGE_KEY)) return;
      const next = systemTheme();
      document.documentElement.dataset.theme = next;
      setThemeState(next);
    };
    media.addEventListener("change", onSystemChange);

    // Any other component calling `setTheme` writes the same attribute. This is
    // what keeps the particle field in step with the toggle without either of
    // them knowing the other exists.
    const observer = new MutationObserver(() => setThemeState(currentTheme()));
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-theme"],
    });

    return () => {
      media.removeEventListener("change", onSystemChange);
      observer.disconnect();
    };
  }, []);

  function setTheme(next: Theme) {
    document.documentElement.dataset.theme = next;
    window.localStorage.setItem(STORAGE_KEY, next);
    setThemeState(next);
  }

  function toggleTheme() {
    setTheme(theme === "dark" ? "light" : "dark");
  }

  return { theme, setTheme, toggleTheme };
}

/**
 * Resolve a semantic colour token to the `#rrggbb` a particle canvas needs.
 *
 * The field paints on a canvas, which is outside CSS: it needs a concrete
 * colour string, and writing one here would mean a hard-coded hex that cannot
 * follow the theme. So it reads `--accent` — but that cannot be handed over as
 * it stands. The palette is authored in `oklch()`, Chrome serialises the
 * computed value as `lab()`, and tsparticles' own colour parser understands
 * neither; it wants hex, `rgb()` or `hsl()`.
 *
 * Reading `fillStyle` back does not help — it returns the same `lab()` string
 * it was given. Painting one pixel and reading it back does: `getImageData`
 * hands back plain sRGB bytes, which is the browser's own colour conversion
 * rather than an approximation of it written here.
 */
export function tokenColour(token: string, fallback: string): string {
  if (typeof document === "undefined") return fallback;

  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(token)
    .trim();
  if (!raw) return fallback;

  const canvas = document.createElement("canvas");
  canvas.width = 1;
  canvas.height = 1;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) return fallback;

  // An unparseable value leaves `fillStyle` untouched, so seeding it with the
  // fallback means a token that has gone missing paints the fallback rather
  // than transparent black.
  context.fillStyle = fallback;
  context.fillStyle = raw;
  context.fillRect(0, 0, 1, 1);

  try {
    const pixel = context.getImageData(0, 0, 1, 1).data;
    const hex = (channel: number | undefined) =>
      (channel ?? 0).toString(16).padStart(2, "0");
    return `#${hex(pixel[0])}${hex(pixel[1])}${hex(pixel[2])}`;
  } catch {
    // Reading pixels back is a tainted-canvas operation in principle. Nothing
    // untrusted is ever drawn here, but a colour is not worth an exception.
    return fallback;
  }
}
