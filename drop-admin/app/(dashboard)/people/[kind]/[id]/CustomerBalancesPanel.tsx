"use client";

import { AlertTriangle, Banknote, Droplets, Loader2 } from "lucide-react";
import { useEffect, useState, useTransition } from "react";

import {
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  inputClass,
} from "@/components/ui/primitives";
import { formatMoney } from "@/lib/utils/format";
import {
  fetchCustomerBalances,
  returnDeposit,
  writeOffDebt,
  type CustomerBalances,
} from "../actions";

/**
 * Debt write-off, deposit return, and balance overview for customers.
 *
 * Only rendered on the customer detail page. The two obligations are independent
 * — a customer can owe the platform (debt) and be owed by it (deposit) at the
 * same time — and each is resolved by a different action with its own capability
 * check on the server.
 */
export function CustomerBalancesPanel({
  id,
  canAdjust,
}: {
  id: string;
  canAdjust: boolean;
}) {
  const [balances, setBalances] = useState<CustomerBalances | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  // ── Debt write-off state ──
  const [debtOpen, setDebtOpen] = useState(false);
  const [debtAmount, setDebtAmount] = useState("");
  const [debtReason, setDebtReason] = useState("");
  const [debtError, setDebtError] = useState<string | null>(null);
  const [debtSuccess, setDebtSuccess] = useState<string | null>(null);

  // ── Deposit return state ──
  const [depositOpen, setDepositOpen] = useState(false);
  const [depositBottles, setDepositBottles] = useState("");
  const [depositReason, setDepositReason] = useState("");
  const [depositError, setDepositError] = useState<string | null>(null);
  const [depositSuccess, setDepositSuccess] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    startTransition(async () => {
      const result = await fetchCustomerBalances(id);
      if (cancelled) return;
      if (result.ok) {
        setBalances(result.data);
      } else {
        setError(result.error);
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  function handleWriteOff() {
    setDebtError(null);
    setDebtSuccess(null);
    startTransition(async () => {
      const result = await writeOffDebt(
        id,
        debtAmount.trim() || null,
        debtReason,
      );
      if (result.ok) {
        setBalances((prev) =>
          prev
            ? {
                ...prev,
                debt_balance: result.data.debt_balance,
                debt_blocks_ordering:
                  Number(result.data.debt_balance) >=
                  Number(prev.debt_ceiling),
              }
            : prev,
        );
        setDebtSuccess(
          `KSH ${result.data.written_off} written off. Balance is now KSH ${result.data.debt_balance}.`,
        );
        setDebtAmount("");
        setDebtReason("");
        setDebtOpen(false);
      } else {
        setDebtError(result.error);
      }
    });
  }

  function handleDepositReturn() {
    setDepositError(null);
    setDepositSuccess(null);
    startTransition(async () => {
      const result = await returnDeposit(id, depositBottles, depositReason);
      if (result.ok) {
        setBalances((prev) =>
          prev
            ? {
                ...prev,
                bottle_deposit_balance: result.data.bottle_deposit_balance,
                bottles_held: result.data.bottles_held,
                wallet_balance: result.data.wallet_balance,
              }
            : prev,
        );
        setDepositSuccess(
          `KSH ${result.data.amount_refunded} refunded to wallet for ${result.data.bottles_returned} bottle(s).`,
        );
        setDepositBottles("");
        setDepositReason("");
        setDepositOpen(false);
      } else {
        setDepositError(result.error);
      }
    });
  }

  if (loading) {
    return (
      <Card>
        <div className="flex items-center justify-center gap-2 px-5 py-10 text-muted">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          <span className="text-sm">Loading balances…</span>
        </div>
      </Card>
    );
  }

  if (error || !balances) {
    return null; // Fail silently — the main detail page still renders.
  }

  const hasDebt = Number(balances.debt_balance) > 0;
  const hasDeposit = Number(balances.bottle_deposit_balance) > 0;

  return (
    <div className="space-y-4">
      {/* ── Debt balance ─────────────────────────────────────────────── */}
      <Card>
        <CardHeader
          title="Outstanding debt"
          description={
            hasDebt
              ? balances.debt_blocks_ordering
                ? "At the ceiling — they cannot order until this is cleared."
                : "Below the ceiling — collected automatically on their next order."
              : "They owe nothing."
          }
        />
        <div className="space-y-3 px-5 py-4">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <p
              className={`text-2xl font-semibold tabular-nums tracking-tight ${
                hasDebt ? "text-[var(--warning)]" : ""
              }`}
            >
              {formatMoney(balances.debt_balance)}
            </p>
            {hasDebt ? (
              <Badge tone={balances.debt_blocks_ordering ? "danger" : "warning"}>
                {balances.debt_blocks_ordering ? (
                  <>
                    <AlertTriangle className="h-3 w-3" aria-hidden /> Blocked
                  </>
                ) : (
                  "Will auto-settle"
                )}
              </Badge>
            ) : (
              <Badge tone="success">Clear</Badge>
            )}
          </div>

          {hasDebt ? (
            <p className="text-xs text-muted">
              Ceiling: {formatMoney(balances.debt_ceiling)}. Balances below it
              are added to the next order automatically.
            </p>
          ) : null}

          {debtSuccess ? (
            <p role="status" className="text-sm text-[var(--success)]">
              {debtSuccess}
            </p>
          ) : null}

          {canAdjust && hasDebt ? (
            debtOpen ? (
              <>
                <Field
                  label="Amount to write off"
                  htmlFor={`debt-amount-${id}`}
                  hint="Leave blank to clear everything."
                >
                  <input
                    id={`debt-amount-${id}`}
                    type="number"
                    step="0.01"
                    min="0"
                    value={debtAmount}
                    onChange={(e) => setDebtAmount(e.target.value)}
                    placeholder={balances.debt_balance}
                    autoFocus
                    className={inputClass}
                  />
                </Field>
                <Field
                  label="Why?"
                  htmlFor={`debt-reason-${id}`}
                  hint="Shown in the audit log and to the customer."
                  error={debtError ?? undefined}
                >
                  <textarea
                    id={`debt-reason-${id}`}
                    value={debtReason}
                    onChange={(e) => setDebtReason(e.target.value)}
                    rows={3}
                    maxLength={500}
                    className={inputClass}
                    placeholder="e.g. Disputed late-cancellation penalty for order 4f2a — vendor had not started."
                  />
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button
                    onClick={handleWriteOff}
                    disabled={pending || debtReason.trim().length < 10}
                  >
                    {pending ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    ) : null}
                    Write off{" "}
                    {debtAmount
                      ? formatMoney(debtAmount)
                      : formatMoney(balances.debt_balance)}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setDebtOpen(false)}
                    disabled={pending}
                  >
                    Cancel
                  </Button>
                </div>
              </>
            ) : (
              <Button variant="secondary" onClick={() => setDebtOpen(true)}>
                <Banknote className="h-4 w-4" aria-hidden />
                Write off debt
              </Button>
            )
          ) : null}
        </div>
      </Card>

      {/* ── Bottle deposit ───────────────────────────────────────────── */}
      <Card>
        <CardHeader
          title="Bottle deposit"
          description={
            hasDeposit
              ? `Holding ${balances.bottles_held} bottle(s). The platform owes this back.`
              : "No deposit held."
          }
        />
        <div className="space-y-3 px-5 py-4">
          <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <p className="text-2xl font-semibold tabular-nums tracking-tight">
              {formatMoney(balances.bottle_deposit_balance)}
            </p>
            {hasDeposit ? (
              <Badge tone="accent">
                {balances.bottles_held} bottle
                {balances.bottles_held !== 1 ? "s" : ""}
              </Badge>
            ) : (
              <Badge tone="neutral">None</Badge>
            )}
          </div>

          {depositSuccess ? (
            <p role="status" className="text-sm text-[var(--success)]">
              {depositSuccess}
            </p>
          ) : null}

          {canAdjust && hasDeposit ? (
            depositOpen ? (
              <>
                <Field
                  label="Bottles returned"
                  htmlFor={`deposit-bottles-${id}`}
                  hint={`They hold ${balances.bottles_held}. Enter how many were handed back.`}
                >
                  <input
                    id={`deposit-bottles-${id}`}
                    type="number"
                    step="1"
                    min="1"
                    max={balances.bottles_held}
                    value={depositBottles}
                    onChange={(e) => setDepositBottles(e.target.value)}
                    autoFocus
                    className={inputClass}
                  />
                </Field>
                <Field
                  label="Why?"
                  htmlFor={`deposit-reason-${id}`}
                  hint="Recorded against your account."
                  error={depositError ?? undefined}
                >
                  <textarea
                    id={`deposit-reason-${id}`}
                    value={depositReason}
                    onChange={(e) => setDepositReason(e.target.value)}
                    rows={3}
                    maxLength={500}
                    className={inputClass}
                    placeholder="e.g. Customer returned 2 × 20L bottles at the Westlands depot."
                  />
                </Field>
                <div className="flex flex-wrap gap-2">
                  <Button
                    onClick={handleDepositReturn}
                    disabled={
                      pending ||
                      depositReason.trim().length < 10 ||
                      !depositBottles
                    }
                  >
                    {pending ? (
                      <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                    ) : null}
                    Return {depositBottles || "—"} bottle
                    {Number(depositBottles) !== 1 ? "s" : ""}
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setDepositOpen(false)}
                    disabled={pending}
                  >
                    Cancel
                  </Button>
                </div>
              </>
            ) : (
              <Button variant="secondary" onClick={() => setDepositOpen(true)}>
                <Droplets className="h-4 w-4" aria-hidden />
                Return deposit
              </Button>
            )
          ) : null}
        </div>
      </Card>
    </div>
  );
}
