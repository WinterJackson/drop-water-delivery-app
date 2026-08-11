"use client";

import { Plus, Trash2 } from "lucide-react";
import { useState, useTransition } from "react";

import { Badge, Card, CardHeader, EmptyState } from "@/components/ui/primitives";
import { formatMoney } from "@/lib/utils/format";
import { deleteSpend, recordSpend } from "./actions";

/**
 * The half of acquisition cost this database will never contain.
 *
 * Posters at the stage, a branded boda, Meta ads, a referral paid in cash, the
 * salary of whoever walked the estate signing people up. Real money, spent on
 * acquisition, invisible to every query on this platform.
 *
 * Without it the console reports a CAC built only from the welcome discount —
 * precise, confident, and typically wrong by an order of magnitude in the
 * direction that makes acquisition look cheap. Somebody then spends against it.
 *
 * A Client Component that calls a Server Action, which calls the API module:
 * the browser never holds a token. Every figure it renders comes back from the
 * server rather than being kept locally, so a refused write leaves the table
 * showing what is actually stored.
 */

export type SpendEntry = {
  id: string;
  period_month: string;
  channel: string;
  amount: string;
  note: string | null;
};

function monthLabel(iso: string) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** `2026-08` for a month input, defaulting to the current one. */
function currentMonthValue() {
  const now = new Date();
  return `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, "0")}`;
}

export function SpendEditor({
  entries,
  canEdit,
}: {
  entries: SpendEntry[];
  /** `settings.manage`. Reading is `analytics.read` — a CAC with the spend hidden is not a CAC. */
  canEdit: boolean;
}) {
  const [month, setMonth] = useState(currentMonthValue());
  const [channel, setChannel] = useState("");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const existing = entries.find(
    (e) => e.period_month.startsWith(month) && e.channel.toLowerCase() === channel.trim().toLowerCase(),
  );

  const submit = () => {
    setError(null);
    startTransition(async () => {
      const result = await recordSpend({
        // The server takes any day in the month and normalises to the first;
        // sending the first explicitly keeps the two ends agreeing about which
        // month this is regardless of the viewer's timezone.
        period_month: `${month}-01`,
        channel: channel.trim(),
        amount: amount.trim(),
        note: note.trim() || undefined,
      });
      if (!result.ok) {
        setError(result.error);
        return;
      }
      setChannel("");
      setAmount("");
      setNote("");
    });
  };

  const remove = (id: string) => {
    setError(null);
    startTransition(async () => {
      const result = await deleteSpend(id);
      if (!result.ok) setError(result.error);
    });
  };

  const total = entries.reduce((sum, e) => sum + Number(e.amount), 0);

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title="Off-platform acquisition spend"
        description="What was spent getting customers that no query here can find. Entered per month and per channel; correcting a figure replaces it rather than adding to it."
      />

      {canEdit ? (
        <div className="border-b border-default px-5 pb-5">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-[10rem_1fr_9rem_auto]">
            <label className="block">
              <span className="text-xs text-muted">Month</span>
              <input
                type="month"
                value={month}
                max={currentMonthValue()}
                onChange={(e) => setMonth(e.target.value)}
                className="mt-1 w-full rounded-lg border border-default bg-surface px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-xs text-muted">Channel</span>
              <input
                value={channel}
                onChange={(e) => setChannel(e.target.value)}
                placeholder="Estate walk-ups, Meta ads, referrals…"
                maxLength={60}
                className="mt-1 w-full rounded-lg border border-default bg-surface px-3 py-2 text-sm"
              />
            </label>
            <label className="block">
              <span className="text-xs text-muted">Amount (KSH)</span>
              <input
                inputMode="decimal"
                value={amount}
                onChange={(e) => setAmount(e.target.value.replace(/[^0-9.]/g, ""))}
                placeholder="0"
                className="mt-1 w-full rounded-lg border border-default bg-surface px-3 py-2 text-sm tabular-nums"
              />
            </label>
            <div className="flex items-end">
              <button
                type="button"
                onClick={submit}
                disabled={pending || !channel.trim() || !amount.trim()}
                className="inline-flex h-[38px] items-center gap-1.5 rounded-lg bg-[var(--accent)] px-4 text-sm font-medium text-white disabled:opacity-40"
              >
                <Plus className="h-4 w-4" aria-hidden />
                {existing ? "Update" : "Record"}
              </button>
            </div>
          </div>

          <label className="mt-3 block">
            <span className="text-xs text-muted">
              What it bought — a figure with no note is unauditable a quarter later
            </span>
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
              placeholder="Two agents, one weekend"
              className="mt-1 w-full rounded-lg border border-default bg-surface px-3 py-2 text-sm"
            />
          </label>

          {existing ? (
            <p className="mt-2 text-xs text-muted">
              {monthLabel(existing.period_month)} already has {formatMoney(existing.amount)} against{" "}
              <strong>{existing.channel}</strong>. Recording will replace it.
            </p>
          ) : null}

          {error ? (
            <p role="alert" className="mt-2 text-sm text-[var(--danger)]">
              {error}
            </p>
          ) : null}
        </div>
      ) : null}

      {entries.length === 0 ? (
        <EmptyState
          title="Nothing recorded"
          description="Until spend is entered here, every CAC on this page counts only the welcome discount — which is real, but is not what acquiring a customer costs."
        />
      ) : (
        <div className="scroll-x">
          <table className="w-full min-w-[36rem] text-sm">
            <caption className="sr-only">Recorded acquisition spend, newest month first</caption>
            <thead>
              <tr className="border-b border-default bg-surface-muted text-left text-xs">
                <th scope="col" className="px-4 py-2.5 font-medium">Month</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Channel</th>
                <th scope="col" className="px-4 py-2.5 text-right font-medium">Amount</th>
                <th scope="col" className="px-4 py-2.5 font-medium">Note</th>
                {canEdit ? <th scope="col" className="px-4 py-2.5" /> : null}
              </tr>
            </thead>
            <tbody>
              {entries.map((entry) => (
                <tr key={entry.id} className="border-b border-default last:border-0">
                  <th scope="row" className="whitespace-nowrap px-4 py-2.5 text-left font-normal">
                    {monthLabel(entry.period_month)}
                  </th>
                  <td className="px-4 py-2.5">
                    <Badge tone="neutral">{entry.channel}</Badge>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums">
                    {formatMoney(entry.amount)}
                  </td>
                  <td className="px-4 py-2.5 text-muted">{entry.note ?? "—"}</td>
                  {canEdit ? (
                    <td className="px-4 py-2.5 text-right">
                      <button
                        type="button"
                        onClick={() => remove(entry.id)}
                        disabled={pending}
                        aria-label={`Remove ${entry.channel} for ${monthLabel(entry.period_month)}`}
                        className="rounded-lg p-1.5 text-muted hover:bg-surface-muted hover:text-[var(--danger)] disabled:opacity-40"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden />
                      </button>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-default">
                <th scope="row" colSpan={2} className="px-4 py-2.5 text-left font-medium">
                  Total in window
                </th>
                <td className="px-4 py-2.5 text-right font-semibold tabular-nums">
                  {formatMoney(String(total))}
                </td>
                <td colSpan={canEdit ? 2 : 1} />
              </tr>
            </tfoot>
          </table>
        </div>
      )}
    </Card>
  );
}
