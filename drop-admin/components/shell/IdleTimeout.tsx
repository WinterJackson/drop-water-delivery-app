"use client";

import { useClerk } from "@clerk/nextjs";
import { ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { useFocusTrap } from "@/lib/hooks/useFocusTrap";

/**
 * Signs an idle administrator out.
 *
 * Clerk sessions last days. That is right for the water app on somebody's own
 * phone and wrong for this console, which reads national ID photographs and
 * releases payouts and is used on shared desks. An unattended tab is the most
 * ordinary way a privileged session gets used by the wrong person, and it needs
 * no attacker at all.
 *
 * The warning is not decoration: signing somebody out mid-sentence while they
 * are typing a suspension reason loses their work. They get a minute and a
 * button.
 *
 * Deliberately client-side and deliberately **not** the only control: the
 * backend re-resolves the administrator on every single request, so a revoked
 * or suspended account stops working immediately regardless of what this
 * component believes. This shortens the window on an *unattended* screen; it is
 * not what stops a stolen token.
 */

/** Idle time before the warning. Long enough to read a KYC queue in peace. */
const IDLE_MS = 15 * 60 * 1000;

/** How long the warning stands before the session ends. */
const GRACE_MS = 60 * 1000;

/**
 * Activity worth counting. Deliberately excludes `mousemove` and `scroll`: a
 * trackpad nudged by a sleeve, or a page that scrolls itself, would keep a
 * session alive for ever and quietly defeat the whole control.
 */
const ACTIVITY = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

export function IdleTimeout() {
  const { signOut } = useClerk();
  const [warning, setWarning] = useState(false);
  const [remaining, setRemaining] = useState(Math.round(GRACE_MS / 1000));
  const dialogRef = useRef<HTMLDivElement>(null);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const endSession = useCallback(() => {
    // `redirectUrl` rather than letting Clerk default: landing back on a
    // dashboard URL would bounce through the middleware and read as a glitch.
    void signOut({ redirectUrl: "/sign-in" });
  }, [signOut]);

  const resetIdle = useCallback(() => {
    if (idleTimer.current) clearTimeout(idleTimer.current);
    idleTimer.current = setTimeout(() => setWarning(true), IDLE_MS);
  }, []);

  // Idle tracking. Suspended while the warning is up, or a stray keypress
  // aimed at the dialog would silently cancel the countdown without the
  // operator having chosen to stay.
  useEffect(() => {
    if (warning) return;

    resetIdle();
    const handler = () => resetIdle();
    ACTIVITY.forEach((event) => window.addEventListener(event, handler, { passive: true }));

    return () => {
      ACTIVITY.forEach((event) => window.removeEventListener(event, handler));
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, [warning, resetIdle]);

  // The countdown, and the sign-out at the end of it.
  useEffect(() => {
    if (!warning) return;

    setRemaining(Math.round(GRACE_MS / 1000));
    const deadline = Date.now() + GRACE_MS;

    // Driven off wall-clock time, not by decrementing a counter: a backgrounded
    // tab is throttled to roughly one timer per second at best and stops
    // entirely when the machine sleeps, so a decrementing counter would resume
    // at 47 an hour later and keep the session open.
    const tick = setInterval(() => {
      const left = Math.ceil((deadline - Date.now()) / 1000);
      if (left <= 0) {
        clearInterval(tick);
        endSession();
        return;
      }
      setRemaining(left);
    }, 1000);

    return () => clearInterval(tick);
  }, [warning, endSession]);

  useFocusTrap(warning, dialogRef);

  if (!warning) return null;

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4"
      role="presentation"
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="idle-title"
        aria-describedby="idle-body"
        className="w-full max-w-sm rounded-2xl border border-default bg-surface p-6 text-center shadow-xl"
      >
        <ShieldAlert className="mx-auto mb-3 h-8 w-8 text-[var(--warning)]" aria-hidden />
        <h2 id="idle-title" className="text-lg font-semibold">
          Still there?
        </h2>
        <p id="idle-body" className="mt-2 text-sm text-muted">
          You&apos;ll be signed out in{" "}
          <strong className="tabular-nums">{remaining}s</strong> because this console
          has been idle. It can read identity documents and move money, so it
          doesn&apos;t stay open on an unattended screen.
        </p>

        <div className="mt-5 flex gap-2">
          <button
            type="button"
            onClick={() => setWarning(false)}
            className="flex-1 rounded-lg bg-[var(--accent)] px-4 py-2.5 text-sm font-medium text-white"
            autoFocus
          >
            Stay signed in
          </button>
          <button
            type="button"
            onClick={endSession}
            className="rounded-lg border border-default px-4 py-2.5 text-sm font-medium"
          >
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}
