"use client";

import { useClerk } from "@clerk/nextjs";

/**
 * A real sign-out, for the console's dead-end screens.
 *
 * "Sign in with a different account" as a link to `/sign-in` does nothing when
 * a session already exists — Clerk sees one and sends the caller straight back
 * to the page that refused them. Somebody who signed in with their customer
 * account and landed on "you don't have access" was stuck in that loop with no
 * way out but clearing cookies.
 */
export function SignOutButton({ label = "Sign out" }: { label?: string }) {
  const { signOut } = useClerk();

  return (
    <button
      type="button"
      onClick={() => void signOut({ redirectUrl: "/sign-in" })}
      className="text-[var(--accent)] underline underline-offset-4"
    >
      {label}
    </button>
  );
}
