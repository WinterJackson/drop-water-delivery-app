"use client";

import { Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Button, Field, inputClass } from "@/components/ui/primitives";
import { settleRefund } from "./actions";

/**
 * Record a refund made by hand in the M-Pesa portal.
 *
 * The wording is deliberate: this button does not send money. Labelling it
 * "Retry" would be the single most dangerous control in the console, because a
 * reversal that succeeded and lost its callback is indistinguishable from one
 * that failed, and a second reversal comes out of the platform's own float.
 */
export function SettleButton({ orderId, amount }: { orderId: string; amount: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Mark settled
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
          const result = await settleRefund(orderId, reason);
          if (result.ok) {
            setOpen(false);
            setReason("");
          } else {
            setError(result.error);
          }
        });
      }}
    >
      <p className="text-xs text-muted">
        This records that {amount} was returned to the customer some other way.
        It sends nothing.
      </p>
      <Field
        label="How was it settled?"
        error={error ?? undefined}
        hint="Include the M-Pesa reference if there is one."
      >
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={2}
          autoFocus
          placeholder="Reversed manually in the portal, ref QK4H8T2LMN…"
          className={inputClass}
        />
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
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
