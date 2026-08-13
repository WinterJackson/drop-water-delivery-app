"use client";

import { SignIn } from "@clerk/nextjs";
import { useMemo } from "react";

import { tokenColour, useTheme } from "@/lib/use-theme";

/**
 * Clerk's sign-in form, wearing the console's palette.
 *
 * Clerk cannot be handed `var(--accent)`. Its appearance variables are not
 * written straight into CSS — it *parses* each colour and derives a scale from
 * it (hover, active, disabled, the translucent focus ring), so a value it
 * cannot read produces no scale at all. The primary button came out invisible:
 * white on white, with its label still there.
 *
 * So the tokens are resolved to concrete hex first, in the browser, and the
 * whole form is remounted when the theme changes. That keeps the single source
 * of truth in `globals.css` — no colour is written here — while giving Clerk
 * the literal it needs.
 *
 * `elements` still carries the structural work: hiding Clerk's own heading in
 * favour of the page's, and hiding the footer that offers to create an account.
 * There is no `/sign-up` route on this origin to send anybody to.
 */
export function ThemedSignIn() {
  const { theme } = useTheme();

  const variables = useMemo(
    () => ({
      colorPrimary: tokenColour("--accent", "#0079b8"),
      colorTextOnPrimaryBackground: tokenColour("--accent-foreground", "#ffffff"),
      colorBackground: tokenColour("--surface", "#ffffff"),
      colorInputBackground: tokenColour("--background", "#fafafa"),
      colorInputText: tokenColour("--foreground", "#1a1a1a"),
      colorText: tokenColour("--foreground", "#1a1a1a"),
      colorTextSecondary: tokenColour("--foreground-muted", "#6b7280"),
      colorNeutral: tokenColour("--foreground", "#1a1a1a"),
      colorDanger: tokenColour("--danger", "#dc2626"),
      colorSuccess: tokenColour("--success", "#16a34a"),
      colorWarning: tokenColour("--warning", "#d97706"),
      borderRadius: "0.5rem",
    }),
    // The token names never change; their values change with the theme.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [theme],
  );

  // Nothing honest to render until the theme is known — the server cannot know
  // it, and a form painted in the wrong palette for a frame is worse than one
  // that arrives a frame late. Reserves its own height so nothing jumps.
  if (theme === null) {
    return <div className="min-h-[26rem] w-full" aria-hidden />;
  }

  return (
    <SignIn
      key={theme}
      appearance={{
        variables,
        elements: {
          // Clerk fixes its root at 400px and outranks `w-full`, so as a grid
          // item narrower than its track it aligned to the start and hung 25px
          // left of the panel's centre line. `justify-self-center` centres the
          // box itself; centring *inside* it cannot, because the box is the
          // thing that is off-axis.
          // `relative` belongs here rather than on the card box, and that is
          // the whole trick. Clerk sets `overflow: hidden` on the card box and
          // wins on specificity, so an absolutely-positioned footer anchored
          // there is clipped away — taking the "Secured by Clerk" attribution
          // with it. Overflow does not clip an absolutely-positioned descendant
          // whose containing block sits outside the clipping box, so anchoring
          // the footer to the root box instead leaves it visible without
          // overriding anything of Clerk's.
          // Clerk fixes its root at 400px and outranks `w-full`, so as a grid
          // item narrower than its track it aligned to the start and hung 25px
          // left of the panel's centre line. `justify-self-center` centres the
          // box itself; centring *inside* it cannot, because the box is the
          // thing that is off-axis.
          rootBox: "justify-self-center",
          // The border, radius and shadow live on the *box*, not the card,
          // because the box is what wraps the card and the "Secured by Clerk"
          // footer together. Put them on the card and the footer hangs below it
          // as a square-cornered strip outside the outline. Clerk's own
          // `overflow: hidden` on this element then clips the footer to the
          // radius, so the corners come out round with nothing overridden.
          cardBox: "rounded-xl border border-default bg-surface shadow-sm",
          card: "rounded-none border-0 shadow-none",
          // The page states who this is and what it is for, above the card, in
          // the console's own heading face. Clerk's "Continue to Drop" is the
          // same sentence twice. All three keys are needed: hiding `header`
          // alone leaves the title rendered.
          header: "hidden",
          headerTitle: "hidden",
          headerSubtitle: "hidden",
          dividerLine: "bg-[var(--border)]",
          dividerText: "text-muted",
          formFieldInput: "rounded-lg border border-default",
          formButtonPrimary: "normal-case",
          socialButtonsBlockButton: "border border-default",
          // In flow, inside the card's outline. It is part of the card, not a
          // strip beneath it, so it is also part of what gets centred.
          footer: "bg-transparent",
          // No self-service registration on the privileged origin.
          footerAction: "hidden",
          footerActionLink: "hidden",
        },
      }}
    />
  );
}
