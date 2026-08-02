"use client";

import { Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Button, Field, inputClass } from "@/components/ui/primitives";
import { adjustBottles } from "./actions";

type Holder = {
  rider_id: string;
  rider_name: string | null;
  vendor_id: string;
  vendor_name: string | null;
  by_capacity: Record<string, number>;
};

/**
 * Correct a bottle balance by hand.
 *
 * The form only offers sizes this pair actually has outstanding, and defaults
 * to writing the whole lot off, because "the rider left holding these" is the
 * case that brings anyone to this screen. Everything else is typed deliberately.
 */
export function AdjustButton({ holder }: { holder: Holder }) {
  const capacities = Object.keys(holder.by_capacity)
    .map(Number)
    .sort((a, b) => b - a);

  const [open, setOpen] = useState(false);
  const [capacity, setCapacity] = useState(capacities[0] ?? 20);
  const [quantity, setQuantity] = useState(String(-(holder.by_capacity[String(capacities[0])] ?? 0)));
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        Correct
      </Button>
    );
  }

  const held = holder.by_capacity[String(capacity)] ?? 0;

  return (
    <form
      className="w-full min-w-[16rem] space-y-2 text-left"
      onSubmit={(event) => {
        event.preventDefault();
        setError(null);
        startTransition(async () => {
          const result = await adjustBottles({
            riderId: holder.rider_id,
            vendorId: holder.vendor_id,
            capacity,
            quantity: Number(quantity),
            reason,
          });
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
        {holder.rider_name ?? "This rider"} holds {held} × {capacity}L for{" "}
        {holder.vendor_name ?? "this store"}.
      </p>

      <Field label="Size">
        <select
          value={capacity}
          onChange={(event) => {
            const next = Number(event.target.value);
            setCapacity(next);
            setQuantity(String(-(holder.by_capacity[String(next)] ?? 0)));
          }}
          className={inputClass}
        >
          {capacities.map((c) => (
            <option key={c} value={c}>
              {c}L — {holder.by_capacity[String(c)]} outstanding
            </option>
          ))}
        </select>
      </Field>

      <Field
        label="Change"
        hint="Negative forgives what they owe. Positive records bottles the ledger missed."
      >
        <input
          type="number"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          step={1}
          className={inputClass}
        />
      </Field>

      <Field label="Why?" error={error ?? undefined}>
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          rows={2}
          placeholder="Rider left the platform; store agreed to write these off…"
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
