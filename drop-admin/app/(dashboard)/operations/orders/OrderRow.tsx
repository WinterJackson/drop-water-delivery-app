"use client";

import { Loader2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Badge, Button, Card, Field, inputClass } from "@/components/ui/primitives";
import { formatMoney } from "@/lib/utils/format";
import { cancelOrder, reassignOrder } from "./actions";

export type BoardOrder = {
  id: string;
  status: string;
  payment_status: string;
  payment_method: string | null;
  total: string;
  vendor: { id: string | null; name: string | null };
  rider: { id: string | null; name: string | null };
  customer: { id: string | null; name: string | null };
  created_at: string | null;
  waiting_minutes: number | null;
};

const STATUS_TONE: Record<string, "neutral" | "success" | "warning" | "danger" | "accent"> = {
  pending: "warning",
  accepted: "accent",
  ready: "accent",
  picked_up: "accent",
  delivered: "success",
  cancelled: "danger",
  mismatch_pending: "danger",
  pending_review: "danger",
};

/** Past this, an undelivered order is a customer waiting, not an order in flight. */
const OVERDUE_MINUTES = 90;

/**
 * Cancelling and reassigning, shared by the table row and the mobile card.
 *
 * The two render completely different markup — a `<tr>` cannot hold a card
 * layout and a `<div>` cannot live in a `<tbody>` — but they must behave
 * identically, so the behaviour lives here and only the presentation is
 * written twice.
 */
function useIntervention(order: BoardOrder) {
  const [panel, setPanel] = useState<"cancel" | "reassign" | null>(null);
  const [reason, setReason] = useState("");
  const [riderId, setRiderId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [status, setStatus] = useState(order.status);
  const [pending, startTransition] = useTransition();

  function submit() {
    setError(null);
    startTransition(async () => {
      if (panel === "cancel") {
        const result = await cancelOrder(order.id, reason);
        if (!result.ok) return setError(result.error);
        setStatus("cancelled");
        setPanel(null);
        if (result.data.refund_required) {
          // The one thing the operator must not miss: the money is still out.
          setNotice(
            "Cancelled. This order was already paid — raise the refund separately; cancelling does not return the money.",
          );
        }
      } else if (panel === "reassign") {
        const result = await reassignOrder(order.id, riderId, reason);
        if (!result.ok) return setError(result.error);
        setPanel(null);
        setNotice("Reassigned. The new rider has been notified.");
      }
    });
  }

  const actionable = status !== "cancelled" && status !== "delivered";

  return {
    panel, setPanel, reason, setReason, riderId, setRiderId,
    error, notice, status, pending, submit, actionable,
  };
}

type Intervention = ReturnType<typeof useIntervention>;

function InterventionPanel({ order, state }: { order: BoardOrder; state: Intervention }) {
  const { panel, reason, setReason, riderId, setRiderId, error, pending, submit, setPanel } = state;
  if (!panel) return null;

  return (
    <div className="max-w-xl space-y-3">
      {panel === "reassign" ? (
        <Field
          label="New rider id"
          htmlFor={`rider-${order.id}`}
          hint="They must be verified and not suspended."
        >
          <input
            id={`rider-${order.id}`}
            value={riderId}
            onChange={(event) => setRiderId(event.target.value)}
            className={inputClass}
            placeholder="Paste the rider's id"
          />
        </Field>
      ) : null}

      <Field
        label={panel === "cancel" ? "Why are you cancelling?" : "Why are you reassigning?"}
        htmlFor={`reason-${order.id}`}
        hint="The customer or rider is shown this, and it is recorded against your account."
        error={error ?? undefined}
      >
        <input
          id={`reason-${order.id}`}
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={500}
          autoFocus={panel === "cancel"}
          className={inputClass}
        />
      </Field>

      <div className="flex gap-2">
        <Button variant={panel === "cancel" ? "danger" : "primary"} onClick={submit} disabled={pending}>
          {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
          Confirm
        </Button>
        <Button variant="ghost" onClick={() => setPanel(null)} disabled={pending}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

function Actions({ state, canIntervene }: { state: Intervention; canIntervene: boolean }) {
  if (!canIntervene || !state.actionable) return null;
  return (
    <>
      <Button size="sm" variant="secondary" onClick={() => state.setPanel("reassign")} disabled={state.pending}>
        Reassign
      </Button>
      <Button
        size="sm"
        variant="ghost"
        onClick={() => state.setPanel("cancel")}
        disabled={state.pending}
        className="text-[var(--danger)]"
      >
        Cancel
      </Button>
    </>
  );
}

/** The `md`-and-up table row. */
export function OrderRow({ order, canIntervene }: { order: BoardOrder; canIntervene: boolean }) {
  const state = useIntervention(order);
  const overdue = (order.waiting_minutes ?? 0) > OVERDUE_MINUTES;

  return (
    <>
      <tr className="border-b border-default last:border-0">
        <td className="px-4 py-3">
          <p className="font-mono text-xs">{order.id.slice(0, 8)}</p>
          <p className={overdue ? "text-xs text-[var(--danger)]" : "text-xs text-muted"}>
            {order.waiting_minutes !== null ? `${order.waiting_minutes} min` : "—"}
          </p>
        </td>
        <td className="px-4 py-3">
          <p className="truncate">{order.vendor.name ?? "—"}</p>
          <p className="truncate text-xs text-muted">{order.customer.name ?? "customer"}</p>
        </td>
        <td className="px-4 py-3">
          {order.rider.name ?? <span className="text-muted">unassigned</span>}
        </td>
        <td className="px-4 py-3">
          <Badge tone={STATUS_TONE[state.status] ?? "neutral"}>{state.status}</Badge>
        </td>
        <td className="px-4 py-3">
          <p className="tabular-nums">{formatMoney(order.total)}</p>
          <p className="text-xs text-muted">
            {order.payment_method ?? "—"} · {order.payment_status}
          </p>
        </td>
        <td className="px-4 py-3 text-right">
          <div className="flex justify-end gap-2">
            <Actions state={state} canIntervene={canIntervene} />
          </div>
        </td>
      </tr>

      {state.notice ? (
        <tr>
          <td
            colSpan={6}
            className="border-b border-default bg-[color-mix(in_oklch,var(--warning)_10%,transparent)] px-4 py-3 text-sm"
          >
            {state.notice}
          </td>
        </tr>
      ) : null}

      {state.panel ? (
        <tr>
          <td colSpan={6} className="border-b border-default bg-surface-muted px-4 py-4">
            <InterventionPanel order={order} state={state} />
          </td>
        </tr>
      ) : null}
    </>
  );
}

/** The same order below `md`, where six columns do not fit under a thumb. */
export function OrderCard({ order, canIntervene }: { order: BoardOrder; canIntervene: boolean }) {
  const state = useIntervention(order);
  const overdue = (order.waiting_minutes ?? 0) > OVERDUE_MINUTES;

  return (
    <Card className="overflow-hidden">
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="font-mono text-xs">{order.id.slice(0, 8)}</p>
            <p className={overdue ? "text-xs text-[var(--danger)]" : "text-xs text-muted"}>
              waiting {order.waiting_minutes !== null ? `${order.waiting_minutes} min` : "—"}
            </p>
          </div>
          <Badge tone={STATUS_TONE[state.status] ?? "neutral"}>{state.status}</Badge>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
          <div className="min-w-0">
            <dt className="text-xs text-muted">Vendor</dt>
            <dd className="truncate">{order.vendor.name ?? "—"}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-xs text-muted">Customer</dt>
            <dd className="truncate">{order.customer.name ?? "—"}</dd>
          </div>
          <div className="min-w-0">
            <dt className="text-xs text-muted">Rider</dt>
            <dd className="truncate">
              {order.rider.name ?? <span className="text-muted">unassigned</span>}
            </dd>
          </div>
          <div className="min-w-0">
            <dt className="text-xs text-muted">Value</dt>
            <dd className="truncate tabular-nums">
              {formatMoney(order.total)}
              <span className="ml-1 text-xs text-muted">{order.payment_status}</span>
            </dd>
          </div>
        </dl>

        <InterventionPanel order={order} state={state} />
      </div>

      {state.notice ? (
        <p className="border-t border-default bg-[color-mix(in_oklch,var(--warning)_10%,transparent)] px-4 py-3 text-sm">
          {state.notice}
        </p>
      ) : null}

      {canIntervene && state.actionable && !state.panel ? (
        <div className="flex flex-wrap gap-2 border-t border-default bg-surface-muted px-4 py-3">
          <Actions state={state} canIntervene={canIntervene} />
        </div>
      ) : null}
    </Card>
  );
}
