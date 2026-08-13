"use client";

import { Moon, Sun } from "lucide-react";

import { useTheme } from "@/lib/use-theme";
import { cn } from "@/lib/utils/cn";

/**
 * Follows the OS until the operator says otherwise, then remembers.
 *
 * The stored value is written to `data-theme` on the root element, which the
 * stylesheet gives precedence over the `prefers-color-scheme` block — so an
 * explicit choice wins in both directions rather than only being able to darken
 * a light OS. `useTheme` owns that, and is shared: the particle field on the
 * sign-in screen watches the same attribute, so both stay in step without
 * either knowing about the other.
 *
 * Both icons are always mounted and cross-fade by rotating and scaling, rather
 * than one being swapped for the other. A swap has nothing to animate, and on a
 * toggle this small the movement is what tells the operator the click landed.
 */
/**
 * Which ground the control is sitting on.
 *
 * A prop rather than a `className` override, because the two tones differ in
 * `text-muted` vs `text-chrome-foreground` — both project utilities, which
 * `twMerge` has no conflict rule for, so a caller's override would be appended
 * rather than substituted and the winner would come down to source order.
 */
export type ControlTone = "surface" | "chrome";

const TONES: Record<ControlTone, string> = {
  surface: "border-default bg-surface text-muted hover:text-[var(--foreground)]",
  // Transparent over the accent, so the only colour here is the panel's own.
  // Hover moves the *ground*, never the text — dimming the glyph is what would
  // cost the contrast this panel does not have to give.
  chrome: "border-chrome-edge text-chrome-foreground hover:bg-[var(--chrome-hover)]",
};

export function ThemeToggle({
  className,
  tone = "surface",
}: {
  className?: string;
  tone?: ControlTone;
}) {
  const { theme, toggleTheme } = useTheme();
  const isDark = theme === "dark";

  return (
    <button
      type="button"
      onClick={toggleTheme}
      // Until the effect has run, the theme is genuinely unknown — the server
      // cannot know it. Disabling for that first frame stops a click resolving
      // in the wrong direction, and the label stays honest rather than
      // asserting a direction it cannot know yet.
      disabled={theme === null}
      aria-label={
        theme === null
          ? "Switch theme"
          : isDark
            ? "Switch to light theme"
            : "Switch to dark theme"
      }
      title={theme === null ? undefined : isDark ? "Switch to light" : "Switch to dark"}
      className={cn(
        "relative inline-flex h-9 w-9 items-center justify-center rounded-lg border",
        "transition-colors disabled:opacity-60",
        TONES[tone],
        className,
      )}
    >
      <Sun
        aria-hidden
        className={cn(
          "absolute h-4 w-4 transition-all duration-300",
          isDark ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-0 opacity-0",
        )}
      />
      <Moon
        aria-hidden
        className={cn(
          "absolute h-4 w-4 transition-all duration-300",
          isDark ? "rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100",
        )}
      />
    </button>
  );
}
