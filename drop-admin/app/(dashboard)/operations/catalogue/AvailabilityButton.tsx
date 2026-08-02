"use client";

import { Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Button, Field, inputClass } from "@/components/ui/primitives";
import { setAvailability } from "./actions";

/**
 * Hide a product, or put it back on sale.
 *
 * The confirmation step is not friction for its own sake: this is a vendor's
 * listing coming off the shelf, and the reason is stored against the audit row
 * so the answer to "why is my product gone" exists in writing.
 */
export function AvailabilityButton({ id, listed }: { id: string; listed: boolean }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {listed ? "Hide" : "Restore"}
      </Button>
    );
  }

  return (
    <form
      className="w-full min-w-[14rem] space-y-2 text-left"
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        startTransition(async () => {
          const result = await setAvailability(id, !listed, reason);
          if (result.ok) {
            setOpen(false);
            setReason("");
          } else {
            setError(result.error);
          }
        });
      }}
    >
      <Field
        label={listed ? "Why is this coming off sale?" : "Why is it going back on?"}
        error={error ?? undefined}
      >
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={2}
          autoFocus
          placeholder={listed ? "Priced wrong — vendor contacted…" : "Vendor corrected the price…"}
          className={inputClass}
        />
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          {listed ? "Hide it" : "Restore it"}
        </Button>
      </div>
    </form>
  );
}
