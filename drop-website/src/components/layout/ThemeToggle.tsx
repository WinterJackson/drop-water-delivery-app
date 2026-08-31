"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/lib/use-theme";
import { cn } from "@/lib/utils/cn";

export type ControlTone = "surface" | "chrome";

const TONES: Record<ControlTone, string> = {
  surface: "border-[var(--border)] bg-[var(--surface)] text-[var(--foreground-muted)] hover:text-[var(--foreground)]",
  chrome: "border-[var(--chrome-edge)] text-[var(--chrome-foreground)] hover:bg-[var(--chrome-hover)]",
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
        "relative inline-flex h-8 w-8 items-center justify-center rounded-lg border cursor-pointer",
        "transition-colors disabled:opacity-60",
        TONES[tone],
        className,
      )}
    >
      <Sun
        aria-hidden
        className={cn(
          "absolute h-3.5 w-3.5 transition-all duration-300",
          isDark ? "rotate-0 scale-100 opacity-100" : "-rotate-90 scale-0 opacity-0",
        )}
      />
      <Moon
        aria-hidden
        className={cn(
          "absolute h-3.5 w-3.5 transition-all duration-300",
          isDark ? "rotate-90 scale-0 opacity-0" : "rotate-0 scale-100 opacity-100",
        )}
      />
    </button>
  );
}
