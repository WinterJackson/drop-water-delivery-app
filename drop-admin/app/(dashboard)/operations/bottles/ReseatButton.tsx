"use client";

import { Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Button, Field, inputClass } from "@/components/ui/primitives";
import { reseatCounters } from "./actions";

/**
 * Rewrite drifted registry counters from the ledger.
 *
 * A reason is required even though the repair itself is mechanical, because
 * drift means something wrote a counter without a ledger row. Whoever presses
 * this knows more about what happened than the next person ever will, and this
 * is the only place that knowledge gets written down.
 */
export function ReseatButton({ count }: { count: number }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (done) {
    return <p className="text-sm text-muted">{done}</p>;
  }

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Repair {count === 1 ? "it" : `all ${count}`}
      </Button>
    );
  }

  return (
    <form
      className="w-full max-w-sm space-y-2"
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        startTransition(async () => {
          const result = await reseatCounters(reason);
          if (result.ok) {
            setOpen(false);
            setDone(result.message ?? "Repaired.");
          } else {
            setError(result.error);
          }
        });
      }}
    >
      <Field
        label="What caused this?"
        error={error ?? undefined}
        hint="The counters are rewritten from the ledger, never the other way round."
      >
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={2}
          autoFocus
          placeholder="Counters edited by hand during the September incident…"
          className={inputClass}
        />
      </Field>
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" disabled={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Rewrite from the ledger
        </Button>
      </div>
    </form>
  );
}
