"use client";

import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Keeps keyboard focus inside an open overlay, and hands it back on close.
 *
 * `aria-modal="true"` is a *promise* that focus cannot leave the dialog. Without
 * a trap it is simply untrue: Tab walks straight out into the page behind the
 * overlay, which is still fully interactive to the keyboard while being visually
 * dimmed and looking inert. A sighted mouse user never notices; a keyboard user
 * ends up operating a page they cannot see.
 *
 * Restoring focus matters just as much. Without it, closing the overlay drops
 * the caret at the top of the document and the operator has to tab all the way
 * back to where they were.
 *
 * Shared by the command palette and the mobile navigation drawer, because two
 * copies of this is how one of them loses its trap in a refactor and nobody
 * notices for a year.
 */
export function useFocusTrap(
  open: boolean,
  containerRef: RefObject<HTMLElement | null>,
  { onEscape }: { onEscape?: () => void } = {},
) {
  const openerRef = useRef<HTMLElement | null>(null);
  // Kept in a ref so the effect below does not re-subscribe on every render of
  // a parent that passes a fresh closure.
  const escapeRef = useRef(onEscape);
  escapeRef.current = onEscape;

  useEffect(() => {
    if (!open) return;

    openerRef.current = document.activeElement as HTMLElement | null;

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        escapeRef.current?.();
        return;
      }
      if (event.key !== "Tab") return;

      const root = containerRef.current;
      if (!root) return;

      const focusable = Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        // `offsetParent` is null for anything `display:none`, which is how a
        // collapsed section's controls would otherwise become invisible stops.
        (element) => element.offsetParent !== null || element === document.activeElement,
      );
      if (focusable.length === 0) return;

      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      const active = document.activeElement;

      // Focus outside the container at all — the browser handed it somewhere we
      // do not control — is pulled back to the start rather than left loose.
      if (!root.contains(active)) {
        event.preventDefault();
        first.focus();
        return;
      }

      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      const opener = openerRef.current;
      openerRef.current = null;
      // The opener may have unmounted while the overlay was up; focusing a
      // detached node silently does nothing, which is the right outcome.
      opener?.focus?.();
    };
  }, [open, containerRef]);
}
