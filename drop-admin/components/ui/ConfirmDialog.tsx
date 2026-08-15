"use client";

import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, Loader2, ShieldQuestion, Trash2 } from "lucide-react";

import { useFocusTrap } from "@/lib/hooks/useFocusTrap";
import { Button, inputClass } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";

/**
 * The console's own confirmation and reason prompt.
 *
 * Three screens used `window.confirm` and `window.prompt`: removing an
 * administrator, revealing a customer's or rider's contact details, and
 * revealing a rider's identity documents. Chrome's own dialogs are the wrong
 * control for all three, and not only because they ignore the theme:
 *
 * * **They are not styled and cannot be.** A grey system box with the origin
 *   printed above it is the visual language of a browser warning, not of this
 *   console — and it arrives in light chrome over a dark page, which is the
 *   moment an operator stops trusting what they are looking at.
 * * **`prompt` cannot validate.** Two of the three collect a *reason that is
 *   recorded against the operator's account* and sent to an endpoint that
 *   refuses an empty one; the browser will happily return `""`, so the operator
 *   learned they had to type something from a red error afterwards.
 * * **They block the whole tab.** A synchronous dialog freezes React, the idle
 *   timer and every open request behind it. `IdleTimeout` cannot warn — and it
 *   cannot sign anybody out — while one is on screen.
 * * **They are suppressible.** A browser that has been told "prevent this page
 *   from creating additional dialogs" returns `false` and `null` *without
 *   showing anything*. The destructive action then looks to the operator like a
 *   button that does nothing.
 * * **They cannot say what is about to happen.** `confirm` takes a string;
 *   there is nowhere to put the person's name in a heavier weight, the
 *   consequence in muted text, or a danger tone on the button that does the
 *   damage.
 *
 * Controlled rather than imperative (`await confirm(...)`), matching
 * `IdleTimeout` and `MobileNav`: an imperative API needs a provider at the root
 * and a promise that outlives the component, and the one thing a confirmation
 * must never do is resolve into an unmounted tree.
 */
export function ConfirmDialog({
  open,
  title,
  body,
  /** Collects a reason. The confirm button stays disabled until it has one. */
  reason,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "default",
  pending = false,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  reason?: {
    label: string;
    placeholder?: string;
    /** Shown under the field. Say where the reason goes — it is audited. */
    hint?: string;
  };
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: "default" | "danger";
  pending?: boolean;
  error?: string | null;
  /** Called with the trimmed reason, or `""` when the dialog collects none. */
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const [value, setValue] = useState("");
  const titleId = useId();
  const bodyId = useId();
  const fieldId = useId();

  useFocusTrap(open, dialogRef, { onEscape: () => !pending && onCancel() });

  // A reason typed for one subject must never be submitted about the next one.
  useEffect(() => {
    if (!open) setValue("");
  }, [open]);

  // The page behind must not scroll under the overlay — the same lock the
  // command palette and the mobile drawer take, and it matters most here
  // because below `sm` this is a sheet the thumb is already on.
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);

  // With no reason field there is nothing autofocusable, and an `alertdialog`
  // that never receives focus is one a screen reader may not announce at all.
  // Focus lands on **Cancel**, deliberately: the destructive button should not
  // be one Return away from somebody who opened this by accident.
  useEffect(() => {
    if (open && !reason) cancelRef.current?.focus();
  }, [open, reason]);

  if (!open) return null;

  const trimmed = value.trim();
  const blocked = Boolean(reason) && trimmed.length === 0;

  return (
    <div
      className="fixed inset-0 z-[110] flex items-end justify-center bg-black/60 p-0 sm:items-center sm:p-4"
      role="presentation"
      // A click on the backdrop cancels, the same as Escape — but never while a
      // request is in flight, when the outcome is not yet known.
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !pending) onCancel();
      }}
    >
      <div
        ref={dialogRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={bodyId}
        className={cn(
          "w-full max-w-md border border-default bg-surface shadow-xl",
          // Bottom sheet on a phone, centred dialog at a desk: the KYC queue is
          // triaged on a handset, where a centred box puts the buttons under
          // nobody's thumb.
          "rounded-t-2xl p-5 pb-[calc(1.25rem+env(safe-area-inset-bottom,0px))]",
          "sm:rounded-2xl sm:p-6 sm:pb-6",
        )}
      >
        <div className="flex gap-3">
          <span
            className={cn(
              "grid h-9 w-9 shrink-0 place-items-center rounded-full",
              tone === "danger"
                ? "bg-[color-mix(in_oklch,var(--danger)_15%,transparent)] text-[var(--danger)]"
                : "bg-[color-mix(in_oklch,var(--accent)_15%,transparent)] text-[var(--accent)]",
            )}
            aria-hidden
          >
            {tone === "danger" ? (
              <Trash2 className="h-4.5 w-4.5" />
            ) : reason ? (
              <ShieldQuestion className="h-4.5 w-4.5" />
            ) : (
              <AlertTriangle className="h-4.5 w-4.5" />
            )}
          </span>

          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-base font-semibold leading-tight">
              {title}
            </h2>
            <div id={bodyId} className="mt-1.5 space-y-1.5 text-sm text-muted">
              {body}
            </div>
          </div>
        </div>

        {reason ? (
          <div className="mt-4 space-y-1.5">
            <label htmlFor={fieldId} className="block text-sm font-medium">
              {reason.label}
            </label>
            <textarea
              id={fieldId}
              rows={3}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder={reason.placeholder}
              className={cn(inputClass, "resize-y")}
              disabled={pending}
              autoFocus
            />
            {reason.hint ? <p className="text-xs text-muted">{reason.hint}</p> : null}
          </div>
        ) : null}

        {error ? (
          <p role="alert" className="mt-3 text-sm text-[var(--danger)]">
            {error}
          </p>
        ) : null}

        <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={pending}>
            {cancelLabel}
          </Button>
          <Button
            variant={tone === "danger" ? "danger" : "primary"}
            onClick={() => onConfirm(trimmed)}
            disabled={pending || blocked}
          >
            {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
