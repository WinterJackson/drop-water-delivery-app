"use client";

import { Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Button, Field, inputClass } from "@/components/ui/primitives";
import { resolveWebhook } from "./actions";

/**
 * "I have dealt with this" — with a written note saying how.
 *
 * The reason is not optional and not decoration. A failed payment callback can
 * end in three very different places — settled in the M-Pesa portal, refunded,
 * or dismissed because the order was already paid and this was a duplicate —
 * and the next person to open the ledger cannot tell which from a boolean.
 */
export function ResolveButton({ id }: { id: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Mark handled
      </Button>
    );
  }

  return (
    <form
      className="w-full min-w-[16rem] space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        startTransition(async () => {
          const result = await resolveWebhook(id, reason);
          if (result.ok) {
            setOpen(false);
            setReason("");
          } else {
            setError(result.error);
          }
        });
      }}
    >
      <Field label="What did you do about it?" error={error ?? undefined}>
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={3}
          autoFocus
          placeholder="Confirmed paid in the M-Pesa portal and marked the order paid…"
          className={inputClass}
        />
      </Field>

      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          onClick={() => {
            setOpen(false);
            setError(null);
          }}
          disabled={pending}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Record it
        </Button>
      </div>
    </form>
  );
}
