"use client";

import { Eye, Loader2, ShieldBan, ShieldCheck, Wallet } from "lucide-react";
import { useState, useTransition } from "react";

import { Button, Card, CardHeader, Field, inputClass } from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { formatMoney } from "@/lib/utils/format";
import { adjustWallet, revealContact, setSuspension, type Contact } from "../actions";

export function AccountActions({
  kind,
  slug,
  id,
  isSuspended,
  canSuspend,
  canViewPii,
  canAdjust,
  walletBalance,
}: {
  kind: string;
  slug: string;
  id: string;
  isSuspended: boolean;
  canSuspend: boolean;
  canViewPii: boolean;
  canAdjust: boolean;
  walletBalance: string;
}) {
  const [contact, setContact] = useState<Contact | null>(null);
  const [askingWhy, setAskingWhy] = useState(false);
  const [revealError, setRevealError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [suspended, setSuspended] = useState(isSuspended);
  const [pending, startTransition] = useTransition();

  const [adjusting, setAdjusting] = useState(false);
  const [amount, setAmount] = useState("");
  const [adjustReason, setAdjustReason] = useState("");
  const [adjustError, setAdjustError] = useState<string | null>(null);
  const [balance, setBalance] = useState(walletBalance);
  const [adjusted, setAdjusted] = useState<string | null>(null);

  function onAdjust() {
    setAdjustError(null);
    startTransition(async () => {
      // `balance` is what is on screen right now. The server refuses if the real
      // one has moved since, so two people fixing the same complaint cannot both
      // apply the credit.
      const result = await adjustWallet(kind, id, amount, adjustReason, balance);
      if (result.ok) {
        setBalance(result.data.balance_after);
        setAdjusted(
          `Balance is now ${result.data.balance_after}. They have been notified.`,
        );
        setAmount("");
        setAdjustReason("");
        setAdjusting(false);
      } else {
        setAdjustError(result.error);
      }
    });
  }

  function onReveal(why: string) {
    setRevealError(null);
    startTransition(async () => {
      const result = await revealContact(kind, id, why);
      if (result.ok) {
        setContact(result.data);
        setAskingWhy(false);
      } else {
        setRevealError(result.error);
      }
    });
  }

  function onSubmit() {
    setError(null);
    startTransition(async () => {
      const result = await setSuspension(kind, id, !suspended, reason);
      if (result.ok) {
        setSuspended(!suspended);
        setOpen(false);
        setReason("");
      } else {
        setError(result.error);
      }
    });
  }

  return (
    <div className="space-y-4">
      {/* The reason is not a formality: it is written to `Admin_Audit_Log`
          before the details are returned, and the endpoint refuses an empty
          one. `window.prompt` could not say that, could not require it, and
          returned `null` without appearing at all in a browser that had
          suppressed dialogs — so the button simply did nothing. */}
      <ConfirmDialog
        open={askingWhy}
        title={`Reveal this ${kind}'s contact details?`}
        body={
          <p>
            Their email, phone number and address are masked for everyone,
            including you. Revealing them is an audited action.
          </p>
        }
        reason={{
          label: "Why do you need them?",
          placeholder: "e.g. Calling about a failed delivery on order #4F2A19C0",
          hint: "Recorded against your account, with the time and this account's id.",
        }}
        confirmLabel="Reveal details"
        pending={pending}
        error={revealError}
        onConfirm={onReveal}
        onCancel={() => {
          setAskingWhy(false);
          setRevealError(null);
        }}
      />

      <Card>
        <CardHeader
          title="Contact details"
          description="Masked for everyone. Revealing them is recorded."
        />
        <div className="px-5 py-4">
          {contact ? (
            <dl className="space-y-1.5 text-sm">
              <Row label="Email" value={contact.email} />
              <Row label="Phone" value={contact.phone_number} />
              <Row label="Address" value={contact.location_address} />
              {contact.ID_number ? <Row label="ID number" value={contact.ID_number} /> : null}
            </dl>
          ) : canViewPii ? (
            <Button variant="secondary" onClick={() => setAskingWhy(true)} disabled={pending}>
              {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
              Reveal contact details
            </Button>
          ) : (
            <p className="text-sm text-muted">
              You don&apos;t have permission to see unmasked contact details.
            </p>
          )}
        </div>
      </Card>

      {canSuspend ? (
        <Card>
          <CardHeader
            title={suspended ? "Reinstate this account" : "Suspend this account"}
            description={
              suspended
                ? "They regain access immediately."
                : kind === "vendor"
                  ? "The store leaves customer search, the directory and its own page immediately."
                  : kind === "rider"
                    ? "They stop receiving delivery offers immediately."
                    : "They lose access to the app immediately."
            }
          />
          <div className="space-y-4 px-5 py-4">
            {open ? (
              <Field
                label={suspended ? "Why are you reinstating them?" : "Why are you suspending them?"}
                htmlFor="suspend-reason"
                hint="Shown to the account holder, and recorded against your account."
                error={error ?? undefined}
              >
                <textarea
                  id="suspend-reason"
                  value={reason}
                  onChange={(event) => setReason(event.target.value)}
                  rows={3}
                  maxLength={500}
                  autoFocus
                  className={inputClass}
                />
              </Field>
            ) : error ? (
              <p role="alert" className="text-sm text-[var(--danger)]">{error}</p>
            ) : null}

            <div className="flex gap-2">
              {open ? (
                <>
                  <Button variant={suspended ? "primary" : "danger"} onClick={onSubmit} disabled={pending}>
                    {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                    Confirm {suspended ? "reinstatement" : "suspension"}
                  </Button>
                  <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
                    Cancel
                  </Button>
                </>
              ) : (
                <Button variant={suspended ? "primary" : "danger"} onClick={() => setOpen(true)}>
                  {suspended ? <ShieldCheck className="h-4 w-4" aria-hidden /> : <ShieldBan className="h-4 w-4" aria-hidden />}
                  {suspended ? "Reinstate" : "Suspend"}
                </Button>
              )}
            </div>
          </div>
        </Card>
      ) : null}

      {canAdjust ? (
        <Card>
          <CardHeader
            title="Wallet"
            description={`Balance ${formatMoney(balance)}`}
          />
          <div className="space-y-3 px-5 py-4">
            {/* Stated plainly, because it is true and because the person doing
                this should be thinking about it. */}
            <p className="text-xs text-muted">
              A manual adjustment creates a balance with no order behind it. It is
              recorded against your account, and {kind === "vendor" ? "the store" : `the ${kind}`}{" "}
              is notified.
            </p>

            {adjusted ? (
              <p role="status" className="text-sm text-[var(--success)]">
                {adjusted}
              </p>
            ) : null}

            {adjusting ? (
              <>
                <Field
                  label="Amount"
                  htmlFor={`adjust-amount-${id}`}
                  hint="Negative debits. e.g. -250 to take KSH 250 back."
                >
                  <input
                    id={`adjust-amount-${id}`}
                    type="number"
                    step="0.01"
                    value={amount}
                    onChange={(event) => setAmount(event.target.value)}
                    autoFocus
                    className={inputClass}
                  />
                </Field>

                <Field
                  label="Why?"
                  htmlFor={`adjust-reason-${id}`}
                  hint="At least a sentence. Somebody reconciling will read this."
                  error={adjustError ?? undefined}
                >
                  <textarea
                    id={`adjust-reason-${id}`}
                    value={adjustReason}
                    onChange={(event) => setAdjustReason(event.target.value)}
                    rows={3}
                    maxLength={500}
                    className={inputClass}
                    placeholder="e.g. Goodwill credit for order 4f2a1c — rider delivered three hours late."
                  />
                </Field>

                <div className="flex flex-wrap gap-2">
                  <Button
                    onClick={onAdjust}
                    disabled={pending || adjustReason.trim().length < 10 || !amount}
                  >
                    {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                    Apply {amount ? formatMoney(amount) : ""}
                  </Button>
                  <Button variant="ghost" onClick={() => setAdjusting(false)} disabled={pending}>
                    Cancel
                  </Button>
                </div>
              </>
            ) : (
              <Button variant="secondary" onClick={() => setAdjusting(true)}>
                <Wallet className="h-4 w-4" aria-hidden />
                Adjust balance
              </Button>
            )}
          </div>
        </Card>
      ) : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div className="flex justify-between gap-4 border-b border-default py-1.5 last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="break-all text-right font-medium">{value ?? "—"}</dd>
    </div>
  );
}
