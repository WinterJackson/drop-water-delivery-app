"use client";

import { AlertTriangle, Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Badge, Button, Card, CardHeader, Field, inputClass } from "@/components/ui/primitives";
import { resolveBottleReturn } from "./actions";

/**
 * Bottle collections the two parties could not agree on.
 *
 * The rider states a count, the customer states a count, and the deposit moves
 * only when they match. When they differ — or when a customer confirms a
 * handover no rider ever confirmed — nothing moves and it waits here.
 *
 * That is deliberate, and it is why this screen has to exist. A system that
 * quietly settles at the lower number teaches riders that understating a count
 * is free, and one that settles at the higher pays for bottles nobody collected.
 * So a person decides, with the two figures in front of them, and their reason
 * is recorded. Without this screen the backend was routing disputes to a human
 * who had nowhere to look at them — the customer told "somebody is checking
 * this" and nobody able to.
 */

export type DisputedReturn = {
  id: string;
  customer_id: string;
  rider_id: string | null;
  status: string;
  bottles_requested: number;
  bottles_stated_by_customer: number | null;
  bottles_stated_by_rider: number | null;
  resolution_note: string | null;
  created_at: string | null;
};

export function DisputedCollections({
  items,
  canResolve,
}: {
  items: DisputedReturn[];
  canResolve: boolean;
}) {
  if (items.length === 0) return null;

  return (
    <Card className="border-[color-mix(in_oklch,var(--warning)_40%,transparent)]">
      <CardHeader
        title={`${items.length} bottle collection${items.length === 1 ? "" : "s"} needs a decision`}
        description="The two counts disagree, or only one side confirmed. No money has moved and the customer still holds their deposit."
      />
      <ul className="divide-y divide-[var(--border)]">
        {items.map((item) => (
          <DisputeRow key={item.id} item={item} canResolve={canResolve} />
        ))}
      </ul>
    </Card>
  );
}

function DisputeRow({ item, canResolve }: { item: DisputedReturn; canResolve: boolean }) {
  const [open, setOpen] = useState(false);
  const [bottles, setBottles] = useState(
    String(item.bottles_stated_by_rider ?? item.bottles_stated_by_customer ?? 0),
  );
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  return (
    <li className="px-5 py-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-[var(--warning)]" aria-hidden />
            <span className="text-sm font-medium">
              Customer said{" "}
              {item.bottles_stated_by_customer ?? "nothing"}, rider said{" "}
              {item.bottles_stated_by_rider ?? "nothing"}
            </span>
            <Badge tone="warning">{item.status}</Badge>
          </div>
          {item.resolution_note ? (
            <p className="mt-1 max-w-prose text-xs text-muted">{item.resolution_note}</p>
          ) : null}
          <p className="mt-1 font-mono text-[11px] text-muted">
            booked {item.bottles_requested} · customer {item.customer_id.slice(0, 8)} ·{" "}
            {item.rider_id ? `rider ${item.rider_id.slice(0, 8)}` : "no rider"}
          </p>
        </div>

        {canResolve && !open && !done ? (
          <Button variant="secondary" onClick={() => setOpen(true)}>
            Decide
          </Button>
        ) : null}
      </div>

      {done ? (
        <p role="status" className="mt-2 text-sm text-[var(--success)]">
          {done}
        </p>
      ) : null}

      {error ? (
        <p role="alert" className="mt-2 text-sm text-[var(--danger)]">
          {error}
        </p>
      ) : null}

      {open ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-[8rem_minmax(0,1fr)]">
          <Field label="Bottles to pay" hint="0 closes it unpaid">
            <input
              type="number"
              min={0}
              className={inputClass}
              value={bottles}
              onChange={(event) => setBottles(event.target.value)}
            />
          </Field>
          <Field label="Why" hint="Recorded against your account and shown on the collection.">
            <input
              className={inputClass}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Spoke to both; rider's count matches the store's intake…"
            />
          </Field>
          <div className="flex flex-wrap gap-2 sm:col-span-2">
            <Button
              onClick={() =>
                startTransition(async () => {
                  setError(null);
                  const result = await resolveBottleReturn({
                    id: item.id,
                    bottles: Number(bottles),
                    reason,
                  });
                  if (result.ok) {
                    setDone(result.message ?? "Decided.");
                    setOpen(false);
                  } else {
                    setError(result.error);
                  }
                })
              }
              disabled={pending || reason.trim().length < 10 || bottles === ""}
            >
              {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {Number(bottles) > 0
                ? `Settle at ${bottles} bottle${Number(bottles) === 1 ? "" : "s"}`
                : "Close unpaid"}
            </Button>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              Cancel
            </Button>
          </div>
        </div>
      ) : null}
    </li>
  );
}
