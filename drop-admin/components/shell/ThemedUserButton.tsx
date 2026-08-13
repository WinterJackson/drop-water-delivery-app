"use client";

import { UserButton } from "@clerk/nextjs";
import { useMemo } from "react";

import { tokenColour, useTheme } from "@/lib/use-theme";

/**
 * Clerk's account control, wearing the header's own palette.
 *
 * The popover has to be the header. It opens flush against it, and Clerk's
 * default is a white card — so the two read as different applications sharing
 * a corner of the screen, and in dark mode it is a white sheet dropping out of
 * a coloured bar.
 *
 * Two mechanisms, and the difference is the thing that is easy to get wrong:
 *
 * - **`variables` are parsed.** Clerk reads each colour and derives a scale
 *   from it — hover, active, disabled, the translucent separators. A value it
 *   cannot parse yields no scale at all, and `var(--chrome)` is exactly such a
 *   value. This cost a sign-in form with an invisible primary button once
 *   already. So they are resolved to concrete hex in the browser, and the
 *   control is remounted when the theme changes.
 * - **`elements` are written out as CSS.** A class name or a style object
 *   both survive, so `var()` is fine there.
 *
 * Every colour still originates in `globals.css`; none is written here.
 *
 * Nothing in this card is dimmed, for the same measured reason as the rest of
 * the chrome: near-white on the light-mode accent is 4.62:1, which is the
 * ceiling and not a starting point. `colorTextSecondary` is therefore the same
 * value as `colorText` — Clerk's default would have put the signed-in email
 * address, the one piece of information in the card, at roughly 2:1.
 */
export function ThemedUserButton() {
  const { theme } = useTheme();

  const variables = useMemo(
    () => ({
      colorBackground: tokenColour("--chrome", "#0079b8"),
      colorText: tokenColour("--chrome-foreground", "#ffffff"),
      // Deliberately not a quieter shade. See above.
      colorTextSecondary: tokenColour("--chrome-foreground", "#ffffff"),
      // Clerk derives borders, dividers and hover washes from this. Pointing
      // it at the foreground makes every one of them a tint of the colour the
      // text is already using, rather than a grey mixed for a white card.
      colorNeutral: tokenColour("--chrome-foreground", "#ffffff"),
      // Buttons invert, the same way the active navigation row does — a
      // primary button in the accent, on the accent, is a rectangle of
      // nothing.
      colorPrimary: tokenColour("--chrome-foreground", "#ffffff"),
      colorTextOnPrimaryBackground: tokenColour("--chrome", "#0079b8"),
      // A field is the one place that stays light: text entry on a saturated
      // ground is uncomfortable to read and worse to proofread. Same plate as
      // the active navigation row.
      colorInputBackground: tokenColour("--chrome-active", "#ffffff"),
      colorInputText: tokenColour("--foreground", "#1a1a1a"),
      colorDanger: tokenColour("--danger", "#dc2626"),
      colorSuccess: tokenColour("--success", "#16a34a"),
      colorWarning: tokenColour("--warning", "#d97706"),
      borderRadius: "0.75rem",
    }),
    // The token names never change; their values change with the theme.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme],
  );

  // Nothing Clerk-related until the theme is known, and this is not cosmetic —
  // it is what makes the markup hydratable.
  //
  // `tokenColour` reads the resolved value of a custom property off the
  // document. There is no document on the server, so it returns its fallback
  // hex there and the *real* token in the browser — which means `variables`
  // differs between the server render and the first client render, and Clerk
  // mounts a different subtree from the one that was streamed. React reported
  // it against `<div data-clerk-component="UserButton">`.
  //
  // Waiting for `theme` makes both renders identical: the server and the
  // client's first pass both produce this placeholder, and Clerk mounts once,
  // after the effect, with real colours. `ThemedSignIn` holds off for the same
  // reason. Sized and shaped like the avatar so the header does not shift.
  if (theme === null) {
    return (
      <div
        aria-hidden
        className="h-8 w-8 shrink-0 rounded-full ring-2 ring-[var(--chrome-foreground)]"
      />
    );
  }

  return (
    <UserButton
      key={theme}
      appearance={{
        variables,
        elements: {
          // Sized to match the 36px controls beside it rather than Clerk's
          // default, and ringed so a dark avatar still has an edge against the
          // panel. A style object, so `var()` resolves.
          avatarBox: {
            width: "2rem",
            height: "2rem",
            boxShadow: "0 0 0 2px var(--chrome-foreground)",
          },
          // `brand-chrome` re-points `:focus-visible` inside the card. The
          // console's ring is `--ring`, which *is* the accent, so without this
          // every row in the popover loses its keyboard indicator against the
          // accent ground — the same defect the sidebar had.
          //
          // Arbitrary-value utilities with `!` rather than the project's
          // `.bg-chrome` shorthand: these lose a specificity contest with
          // Clerk's own stylesheet otherwise, and Tailwind only emits the
          // important form for utilities it generates itself.
          userButtonPopoverCard:
            "brand-chrome border border-[var(--chrome-edge)]! bg-[var(--chrome)]! text-[var(--chrome-foreground)]!",
          userButtonPopoverMain: "bg-[var(--chrome)]!",
          userButtonPopoverActions: "bg-[var(--chrome)]!",
          userButtonPopoverFooter: "bg-[var(--chrome)]! border-[var(--chrome-rule)]!",
          userButtonPopoverActionButton:
            "text-[var(--chrome-foreground)]! hover:bg-[var(--chrome-hover)]!",
          userButtonPopoverActionButtonText: "text-[var(--chrome-foreground)]!",
          userButtonPopoverActionButtonIcon: "text-[var(--chrome-foreground)]!",
          userPreviewMainIdentifier: "text-[var(--chrome-foreground)]!",
          userPreviewSecondaryIdentifier: "text-[var(--chrome-foreground)]!",
          userButtonPopoverCustomItemButton:
            "text-[var(--chrome-foreground)]! hover:bg-[var(--chrome-hover)]!",
        },
      }}
    />
  );
}
