"use client";

import { Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Button, Field, inputClass } from "@/components/ui/primitives";
import { moderateReview } from "./actions";

const HIDE_REASONS = [
  "Contains someone's phone number or email",
  "Abusive or threatening language",
  "Left on the wrong order",
  "Not about the delivery",
];

/**
 * Hide a review, or put it back.
 *
 * The suggested reasons are the four that account for nearly every real
 * takedown, offered as buttons because a moderator working a queue will
 * otherwise type "spam" forty times and the record becomes worthless. Free text
 * stays available for everything else.
 */
export function ModerateButton({ id, hidden }: { id: string; hidden: boolean }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {hidden ? "Restore" : "Hide"}
      </Button>
    );
  }

  return (
    <form
      className="w-full min-w-[16rem] space-y-2 text-left"
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        startTransition(async () => {
          const result = await moderateReview(id, !hidden, reason);
          if (result.ok) {
            setOpen(false);
            setReason("");
          } else {
            setError(result.error);
          }
        });
      }}
    >
      {hidden ? null : (
        <div className="flex flex-wrap gap-1">
          {HIDE_REASONS.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => setReason(preset)}
              className="rounded-full border border-default px-2 py-1 text-xs text-muted hover:bg-surface-muted"
            >
              {preset}
            </button>
          ))}
        </div>
      )}

      <Field
        label={hidden ? "Why is it going back up?" : "Why is it coming down?"}
        error={error ?? undefined}
        hint={
          hidden
            ? "The target's rating is recalculated to include it again."
            : "The target's rating is recalculated without it."
        }
      >
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={2}
          autoFocus
          className={inputClass}
        />
      </Field>

      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          {hidden ? "Restore it" : "Hide it"}
        </Button>
      </div>
    </form>
  );
}
