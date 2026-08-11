import { AlarmClock, CheckCircle2, FileWarning, ShieldAlert, Wallet } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatDuration, formatMoney, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { CashExposurePanel, type CashExposure } from "./CashExposure";
import { ResolveButton } from "./ResolveButton";

export const metadata = { title: "Reconciliation" };

/**
 * Payment callbacks that failed.
 *
 * Every row here is a customer who may have paid Safaricom while their order
 * stayed `pending`. The table had no reader at all until now, so the first
 * anybody heard of one of these was a complaint.
 *
 * The screen deliberately offers no "replay" — see
 * `services/admin_reconciliation_service.py`. It identifies the payment and
 * links to the order; the fix goes through the ordinary single-path tools.
 */

export type Failure = {
  id: string;
  source: string;
  error_message: string | null;
  resolved: boolean;
  created_at: string | null;
  age_minutes: number | null;
  checkout_request_id: string | null;
  merchant_request_id: string | null;
  result_code: number | null;
  result_desc: string | null;
  amount: string | null;
  receipt: string | null;
  parse_error: string | null;
  payment: {
    id: string;
    status: string;
    amount: string;
    receipt: string | null;
    failure_reason: string | null;
  } | null;
  order: { id: string; status: string; payment_status: string; total: string } | null;
};

type Summary = {
  open: number;
  resolved: number;
  stale: number;
  unparseable: number;
  amount_at_risk: string;
  oldest_age_minutes: number | null;
  stale_after_hours: number;
};

export default async function ReconciliationPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  const { view = "open" } = await searchParams;
  const resolved = view === "resolved";

  let data: { items: Failure[]; summary: Summary };
  let me: AdminMe;
  try {
    [data, me] = await Promise.all([
      get<{ items: Failure[]; summary: Summary }>(
        `/api/admin/reconciliation/webhooks?resolved=${resolved}`,
      ),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load reconciliation" detail={message} />;
  }

  const { items, summary } = data;
  const canResolve = can(me, PERMISSIONS.financeRead);

  // Cash on the road, and the window after which the sweep takes it back. Both
  // are separate calls and neither is worth an error page: a slow count must
  // not blank a screen whose job is the failed callbacks above.
  let exposure: CashExposure | null = null;
  let releaseAfterMinutes: number | null = null;
  try {
    const [cash, config] = await Promise.all([
      get<CashExposure>("/api/admin/finance/cash-exposure"),
      get<{ settings: { key: string; value: unknown }[] }>("/api/admin/config").catch(
        () => ({ settings: [] }),
      ),
    ]);
    exposure = cash;
    const row = config.settings.find((s) => s.key === "cod_unclaimed_release_minutes");
    releaseAfterMinutes = row ? Number(row.value) : null;
  } catch {
    exposure = null;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reconciliation</h1>
        <p className="mt-1 text-sm text-muted">
          Payment callbacks Safaricom sent that this platform failed to process.
          Each one may be a customer who has paid for an order still sitting
          unpaid.
        </p>
      </div>

      {exposure ? (
        <CashExposurePanel data={exposure} releaseAfterMinutes={releaseAfterMinutes} />
      ) : null}

      <section aria-label="Reconciliation summary">
        <h2 className="sr-only">Summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Money at risk"
            value={formatMoney(summary.amount_at_risk)}
            hint="Summed from the callbacks themselves, not from the ledger — the worst cases never reached it"
            tone={summary.open > 0 ? "danger" : "neutral"}
            icon={<Wallet className="h-4 w-4" />}
          />
          <Stat
            label="Unhandled"
            value={formatNumber(summary.open)}
            hint={
              summary.oldest_age_minutes === null
                ? "Nothing waiting"
                : `Oldest ${formatDuration(summary.oldest_age_minutes)}`
            }
            tone={summary.open > 0 ? "danger" : "neutral"}
            icon={<FileWarning className="h-4 w-4" />}
          />
          <Stat
            label={`Older than ${summary.stale_after_hours}h`}
            value={formatNumber(summary.stale)}
            hint="Past the point where a sweep would have caught it"
            tone={summary.stale > 0 ? "danger" : "neutral"}
            icon={<AlarmClock className="h-4 w-4" />}
          />
          <Stat
            label="Handled"
            value={formatNumber(summary.resolved)}
            hint={
              summary.unparseable > 0
                ? `${summary.unparseable} unhandled payload(s) could not be parsed`
                : "Every payload parsed cleanly"
            }
            tone={summary.unparseable > 0 ? "warning" : "neutral"}
            icon={<CheckCircle2 className="h-4 w-4" />}
          />
        </div>
      </section>

      <nav aria-label="Filter" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {[
            { key: "open", label: "Unhandled" },
            { key: "resolved", label: "Handled" },
          ].map((tab) => (
            <li key={tab.key}>
              <Link
                href={`/finance/reconciliation?view=${tab.key}`}
                aria-current={tab.key === view ? "page" : undefined}
                className={
                  tab.key === view
                    ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                    : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                }
              >
                {tab.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<CheckCircle2 className="h-8 w-8" />}
            title={resolved ? "Nothing handled yet" : "No failed callbacks"}
            description={
              resolved
                ? undefined
                : "Every payment callback Safaricom sent was processed. This is what it should look like."
            }
          />
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((failure) => (
            <li key={failure.id}>
              <FailureCard failure={failure} canResolve={canResolve && !resolved} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FailureCard({ failure, canResolve }: { failure: Failure; canResolve: boolean }) {
  // The order is the point. Everything else on the card exists to help somebody
  // find it, so its state leads.
  const orderState = failure.order
    ? failure.order.payment_status === "paid"
      ? { tone: "success" as const, text: "Order already paid — likely a duplicate callback" }
      : { tone: "danger" as const, text: `Order still ${failure.order.payment_status}` }
    : failure.payment
      ? { tone: "warning" as const, text: "Payment recorded, no order attached" }
      : { tone: "danger" as const, text: "No payment record at all — nothing here knows the customer was charged" };

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={orderState.tone}>{orderState.text}</Badge>
            {failure.parse_error ? (
              <Badge tone="warning">Payload unreadable ({failure.parse_error})</Badge>
            ) : null}
            <span className="text-xs text-muted">
              {formatDuration(failure.age_minutes)} ago · {failure.source}
            </span>
          </div>

          <p className="text-lg font-semibold">
            {failure.amount ? formatMoney(failure.amount) : "Amount unknown"}
          </p>

          <dl className="mt-2 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
            <Detail label="Checkout request" value={failure.checkout_request_id} mono />
            <Detail label="M-Pesa receipt" value={failure.receipt} mono />
            <Detail
              label="Safaricom said"
              value={
                failure.result_desc
                  ? `${failure.result_desc}${failure.result_code === null ? "" : ` (${failure.result_code})`}`
                  : null
              }
            />
            <Detail label="We failed with" value={failure.error_message} />
          </dl>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          {failure.order ? (
            <Link
              href={`/operations/orders?q=${failure.order.id}`}
              className="rounded-lg border border-default px-3 py-1.5 text-sm hover:bg-surface-muted"
            >
              Open order
            </Link>
          ) : null}
          {canResolve ? <ResolveButton id={failure.id} /> : null}
        </div>
      </div>

      {failure.payment ? (
        <p className="mt-3 border-t border-default pt-3 text-xs text-muted">
          Ledger says: payment {failure.payment.status}, {formatMoney(failure.payment.amount)}
          {failure.payment.failure_reason ? ` — ${failure.payment.failure_reason}` : ""}.
        </p>
      ) : (
        <p className="mt-3 flex items-start gap-2 border-t border-default pt-3 text-xs text-[var(--danger)]">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            No <code>payments</code> row exists for this callback. If Safaricom
            took the money, nothing on this platform records it — check the
            M-Pesa portal against the checkout request above before dismissing.
          </span>
        </p>
      )}
    </Card>
  );
}

function Detail({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string | null;
  mono?: boolean;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`truncate ${mono ? "font-mono text-xs" : "text-sm"}`}>
        {value ?? "—"}
      </dd>
    </div>
  );
}
