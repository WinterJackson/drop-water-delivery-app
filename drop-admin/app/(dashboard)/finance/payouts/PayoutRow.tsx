"use client";

import { Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Badge, Button, Card, Field, inputClass } from "@/components/ui/primitives";
import { formatMoney, timeAgo } from "@/lib/utils/format";
import { approvePayout, rejectPayout } from "./actions";

export type Payout = {
  id: string;
  amount: string;
  status: string;
  provider_type: string;
  provider_id: string;
  payment_method: string;
  /** Masked to `••••1234` unless the caller holds `pii.view`. */
  account_details: string | null;
  mpesa_receipt: string | null;
  failure_reason: string | null;
  created_at: string | null;
};

const TONE: Record<string, "neutral" | "success" | "warning" | "danger" | "accent"> = {
  pending: "warning",
  approved: "accent",
  processing: "warning",
  completed: "success",
  failed: "danger",
};

/**
 * The approve/refuse decision, shared by the table row and the mobile card.
 *
 * Only the markup differs between the two — a payout approved on a phone must
 * be the same action, with the same mandatory reason, as one approved at a
 * desk.
 */
function useDecision(payout: Payout) {
  const [open, setOpen] = useState<"approve" | "reject" | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [settled, setSettled] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function submit() {
    if (!open) return;
    setError(null);
    startTransition(async () => {
      const action = open === "approve" ? approvePayout : rejectPayout;
      const result = await action(payout.id, reason);
      if (result.ok) setSettled(open === "approve" ? "approved" : "failed");
      else setError(result.error);
    });
  }

  return { open, setOpen, reason, setReason, error, pending, submit, status: settled ?? payout.status };
}

type Decision = ReturnType<typeof useDecision>;

function DecisionPanel({ payout, state }: { payout: Payout; state: Decision }) {
  const { open, reason, setReason, error, pending, submit, setOpen } = state;
  if (!open) return null;

  return (
    <div className="max-w-xl space-y-3">
      <Field
        label={open === "approve" ? "Why approve this payout?" : "Why refuse it?"}
        htmlFor={`reason-${payout.id}`}
        hint="Recorded against your account, with the amount and destination."
        error={error ?? undefined}
      >
        <input
          id={`reason-${payout.id}`}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={500}
          autoFocus
          className={inputClass}
          placeholder={
            open === "approve"
              ? "e.g. Verified against the vendor's settled orders for the week."
              : "e.g. Destination number doesn't match the registered account."
          }
        />
      </Field>
      <div className="flex gap-2">
        <Button variant={open === "approve" ? "primary" : "danger"} onClick={submit} disabled={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Confirm {open === "approve" ? "approval" : "refusal"}
        </Button>
        <Button variant="ghost" onClick={() => setOpen(null)} disabled={pending}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function Decide({ state, canDecide }: { state: Decision; canDecide: boolean }) {
  if (state.status !== "pending") return <span className="text-xs text-muted">—</span>;
  if (!canDecide) return <span className="text-xs text-muted">No permission</span>;

  return (
    <>
      <Button size="sm" onClick={() => state.setOpen("approve")} disabled={state.pending}>
        Approve
      </Button>
      <Button size="sm" variant="secondary" onClick={() => state.setOpen("reject")} disabled={state.pending}>
        Refuse
      </Button>
    </>
  );
}

/** The `md`-and-up table row. */
export function PayoutRow({ payout, canDecide }: { payout: Payout; canDecide: boolean }) {
  const state = useDecision(payout);

  return (
    <>
      <tr className="border-b border-default last:border-0">
        <td className="px-4 py-3">
          <p className="font-medium tabular-nums">{formatMoney(payout.amount)}</p>
          <p className="text-xs text-muted">{timeAgo(payout.created_at)}</p>
        </td>
        <td className="px-4 py-3">
          <p className="capitalize">{payout.provider_type}</p>
          <p className="font-mono text-xs text-muted">{payout.provider_id.slice(0, 8)}…</p>
        </td>
        <td className="px-4 py-3">
          <p className="capitalize">{payout.payment_method}</p>
          <p className="font-mono text-xs text-muted">{payout.account_details ?? "—"}</p>
        </td>
        <td className="px-4 py-3">
          <Badge tone={TONE[state.status] ?? "neutral"}>{state.status}</Badge>
          {payout.failure_reason ? (
            <p className="mt-1 max-w-[16rem] text-xs text-muted">{payout.failure_reason}</p>
          ) : null}
        </td>
        <td className="px-4 py-3 text-right">
          <div className="flex justify-end gap-2">
            <Decide state={state} canDecide={canDecide} />
          </div>
        </td>
      </tr>

      {state.open ? (
        <tr>
          <td colSpan={5} className="border-b border-default bg-surface-muted px-4 py-4">
            <DecisionPanel payout={payout} state={state} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

/** The same payout below `md`. */
export function PayoutCard({ payout, canDecide }: { payout: Payout; canDecide: boolean }) {
  const state = useDecision(payout);

  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-lg font-semibold tabular-nums">{formatMoney(payout.amount)}</p>
            <p className="text-xs text-muted">requested {timeAgo(payout.created_at)}</p>
          </div>
          <Badge tone={TONE[state.status] ?? "neutral"}>{state.status}</Badge>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
          <div className="min-w-0">
            <dt className="text-xs text-muted">Recipient</dt>
            <dd className="truncate capitalize">{payout.provider_type}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-xs text-muted">Method</dt>
            <dd className="truncate capitalize">{payout.payment_method}</dd>
          </div>
          <div className="col-span-2 min-w-0">
            <dt className="text-xs text-muted">Destination</dt>
            {/* Masked unless the caller holds `pii.view`. */}
            <dd className="truncate font-mono text-xs">{payout.account_details ?? "—"}</dd>
          </div>
        </dl>

        {payout.failure_reason ? (
          <p className="text-xs text-muted">{payout.failure_reason}</p>
        ) : null}

        <DecisionPanel payout={payout} state={state} />
      </div>

      {state.status === "pending" && !state.open ? (
        <div className="flex flex-wrap gap-2 border-t border-default bg-surface-muted px-4 py-3">
          <Decide state={state} canDecide={canDecide} />
        </div>
      ) : null}
    </Card>
  );
}
