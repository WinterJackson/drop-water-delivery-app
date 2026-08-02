import { AlertTriangle, Clock, Package, Scale, Users } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatMoney, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { AdjustButton } from "./AdjustButton";
import { ReseatButton } from "./ReseatButton";

export const metadata = { title: "Bottle float" };

/**
 * The empty-bottle float.
 *
 * A 20L bottle carries a refundable deposit the platform has already collected
 * from the customer, so bottles a rider never returns are money the platform
 * owes and cannot recover. `bottle_ledger_entries` recorded every movement and
 * nobody could see the total.
 *
 * Every figure here nets per rider/vendor/capacity before it is totalled: a
 * credit against one store must never cancel a debt to another and report less
 * float than exists.
 */

type Capacity = {
  capacity: number;
  bottles: number;
  deposit: string;
  value: string;
  priced: boolean;
};

type Summary = {
  bottles_out: number;
  by_capacity: Capacity[];
  value_at_risk: string;
  unpriced_capacities: number[];
  riders_holding: number;
  vendors_awaiting: number;
  pairs: number;
  stale_pairs: number;
  stale_bottles: number;
  stale_after_days: number;
  oldest_debt_days: number | null;
  movements_24h: number;
  entries_total: number;
  drift_count: number;
};

type Holder = {
  rider_id: string;
  rider_name: string | null;
  rider_suspended: boolean;
  vendor_id: string;
  vendor_name: string | null;
  bottles: number;
  by_capacity: Record<string, number>;
  age_days: number | null;
  stale: boolean;
  value: string;
};

type Drift = {
  rider_id: string;
  rider_name: string | null;
  vendor_id: string;
  vendor_name: string | null;
  capacity: number;
  ledger: number;
  counter: number;
  difference: number;
};

type Movement = {
  id: string;
  rider_name: string | null;
  vendor_name: string | null;
  order_id: string | null;
  capacity: number;
  quantity: number;
  entry_type: string;
  note: string | null;
  created_at: string | null;
};

type Payload = {
  summary: Summary;
  holders: Holder[];
  drift: Drift[];
  movements: Movement[];
};

const VIEWS = [
  { key: "all", label: "Everyone holding" },
  { key: "stale", label: "Gone quiet" },
  { key: "drift", label: "Counter drift" },
  { key: "movements", label: "Movements" },
] as const;

const MOVEMENT_LABEL: Record<string, string> = {
  delivery_accrual: "Collected on delivery",
  vendor_receipt: "Returned to store",
  adjustment: "Corrected by hand",
};

export default async function BottlesPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  const { view = "all" } = await searchParams;
  const active = VIEWS.find((v) => v.key === view)?.key ?? "all";

  let data: Payload;
  let me: AdminMe;
  try {
    [data, me] = await Promise.all([
      get<Payload>(`/api/admin/bottles?view=${active}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the bottle float" detail={message} />;
  }

  const { summary, holders, drift, movements } = data;
  const mayAdjust = can(me, PERMISSIONS.financeAdjust);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Bottle float</h1>
        <p className="mt-1 text-sm text-muted">
          Empties riders are holding on stores&apos; behalf, valued at the same
          refundable deposit the customer was charged. A balance that stops
          moving is the one that costs money, so age sits beside every figure.
        </p>
      </div>

      <section aria-label="Float summary">
        <h2 className="sr-only">Float summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Bottles out"
            value={formatNumber(summary.bottles_out)}
            hint={
              summary.by_capacity.length > 0
                ? summary.by_capacity
                    .map((row) => `${formatNumber(row.bottles)} × ${row.capacity}L`)
                    .join(" · ")
                : "Nothing outstanding"
            }
            icon={<Package className="h-4 w-4" />}
          />
          <Stat
            label="Deposit value"
            value={formatMoney(summary.value_at_risk)}
            hint={
              summary.unpriced_capacities.length > 0
                ? `${summary.unpriced_capacities.join("L, ")}L has no configured deposit and is not counted`
                : "Priced from the platform's own deposit settings"
            }
            tone={summary.unpriced_capacities.length > 0 ? "warning" : "neutral"}
            icon={<Scale className="h-4 w-4" />}
          />
          <Stat
            label={`Quiet over ${summary.stale_after_days} days`}
            value={formatNumber(summary.stale_pairs)}
            hint={
              summary.oldest_debt_days === null
                ? "No outstanding balances"
                : `${formatNumber(summary.stale_bottles)} bottles · oldest ${summary.oldest_debt_days}d`
            }
            tone={summary.stale_pairs > 0 ? "warning" : "neutral"}
            icon={<Clock className="h-4 w-4" />}
          />
          <Stat
            label="Riders holding"
            value={formatNumber(summary.riders_holding)}
            hint={`Across ${formatNumber(summary.vendors_awaiting)} stores · ${formatNumber(summary.movements_24h)} movements today`}
            icon={<Users className="h-4 w-4" />}
          />
        </div>
      </section>

      {drift.length > 0 ? (
        <Card className="border-[color-mix(in_oklch,var(--danger)_40%,transparent)] p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="flex items-center gap-2 text-sm font-semibold">
                <AlertTriangle className="h-4 w-4 text-[var(--danger)]" aria-hidden />
                {formatNumber(drift.length)} counter
                {drift.length === 1 ? "" : "s"} disagree with the ledger
              </h2>
              <p className="mt-1 text-sm text-muted">
                The apps read the counter; the ledger is the record of what
                actually happened. While these disagree, a rider and a store are
                being shown different numbers — and every total above is drawn
                from the ledger, so it is the apps that are wrong.
              </p>
            </div>
            {mayAdjust ? <ReseatButton count={drift.length} /> : null}
          </div>

          <ul className="mt-3 space-y-2">
            {drift.slice(0, 10).map((row) => (
              <li
                key={`${row.rider_id}-${row.vendor_id}-${row.capacity}`}
                className="flex flex-wrap items-baseline justify-between gap-2 border-b border-default pb-2 text-sm last:border-0 last:pb-0"
              >
                <span className="min-w-0">
                  <span className="font-medium">{row.rider_name ?? "Unnamed rider"}</span>
                  <span className="text-muted"> at {row.vendor_name ?? "unknown store"}</span>
                </span>
                <span className="shrink-0 text-muted">
                  {row.capacity}L — ledger says{" "}
                  <span className="font-medium text-[var(--foreground)]">{row.ledger}</span>, apps
                  show <span className="font-medium text-[var(--foreground)]">{row.counter}</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <nav aria-label="Filter the float" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {VIEWS.map((v) => (
            <li key={v.key}>
              <Link
                href={`/operations/bottles?view=${v.key}`}
                aria-current={v.key === active ? "page" : undefined}
                className={
                  v.key === active
                    ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                    : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                }
              >
                {v.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {active === "movements" ? (
        <MovementsView movements={movements} />
      ) : active === "drift" ? (
        <DriftView drift={drift} />
      ) : (
        <HoldersView holders={holders} summary={summary} mayAdjust={mayAdjust} stale={active === "stale"} />
      )}

      {summary.entries_total === 0 ? (
        <p className="text-xs text-muted">
          No bottle movement has been recorded yet — quick-swap deliveries have
          not started. These figures are computed from the same signed-sum the
          rider and vendor apps already use, but they have not been observed
          against real volume, so treat the {summary.stale_after_days}-day quiet
          threshold as a first estimate rather than a tuned one.
        </p>
      ) : null}
    </div>
  );
}

function HoldersView({
  holders,
  summary,
  mayAdjust,
  stale,
}: {
  holders: Holder[];
  summary: Summary;
  mayAdjust: boolean;
  stale: boolean;
}) {
  if (holders.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<Package className="h-8 w-8" />}
          title={stale ? "Nothing has gone quiet" : "No bottles outstanding"}
          description={
            stale
              ? `Every outstanding balance has moved within ${summary.stale_after_days} days. This is what it should look like.`
              : "Every empty collected has been returned to the store it belongs to."
          }
        />
      </Card>
    );
  }

  return (
    <>
      <ul className="space-y-3 md:hidden">
        {holders.map((holder) => (
          <li key={`${holder.rider_id}-${holder.vendor_id}`}>
            <Card className="p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <Link
                    href={`/people/riders/${holder.rider_id}`}
                    className="font-medium hover:underline"
                  >
                    {holder.rider_name ?? "Unnamed rider"}
                  </Link>
                  <p className="text-xs text-muted">
                    holding for {holder.vendor_name ?? "unknown store"}
                  </p>
                  <p className="mt-1 text-sm">
                    {formatNumber(holder.bottles)} bottles · {formatMoney(holder.value)}
                  </p>
                  <p className="mt-1">
                    <AgeBadge holder={holder} days={summary.stale_after_days} />
                  </p>
                </div>
                {mayAdjust ? <AdjustButton holder={holder} /> : null}
              </div>
            </Card>
          </li>
        ))}
      </ul>

      <Card className="hidden overflow-hidden md:block">
        <div className="scroll-x">
          <table className="w-full min-w-[48rem] text-sm">
            <caption className="sr-only">Riders holding empties</caption>
            <thead>
              <tr className="border-b border-default bg-surface-muted text-left">
                <th scope="col" className="px-4 py-3 font-medium">Rider</th>
                <th scope="col" className="px-4 py-3 font-medium">Holding for</th>
                <th scope="col" className="px-4 py-3 font-medium">Bottles</th>
                <th scope="col" className="px-4 py-3 font-medium">Deposit value</th>
                <th scope="col" className="px-4 py-3 font-medium">Oldest</th>
                <th scope="col" className="px-4 py-3 text-right font-medium">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {holders.map((holder) => (
                <tr
                  key={`${holder.rider_id}-${holder.vendor_id}`}
                  className="border-b border-default last:border-0"
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/people/riders/${holder.rider_id}`}
                      className="font-medium hover:underline"
                    >
                      {holder.rider_name ?? "Unnamed"}
                    </Link>
                    {holder.rider_suspended ? (
                      <span className="block text-xs text-muted">suspended</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">{holder.vendor_name ?? "—"}</td>
                  <td className="px-4 py-3">
                    {formatNumber(holder.bottles)}
                    <span className="block text-xs text-muted">
                      {Object.entries(holder.by_capacity)
                        .map(([capacity, count]) => `${count} × ${capacity}L`)
                        .join(" · ")}
                    </span>
                  </td>
                  <td className="px-4 py-3">{formatMoney(holder.value)}</td>
                  <td className="px-4 py-3">
                    <AgeBadge holder={holder} days={summary.stale_after_days} />
                  </td>
                  <td className="px-4 py-3 text-right">
                    {mayAdjust ? <AdjustButton holder={holder} /> : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="text-xs text-muted">
        Value is the refundable deposit for each size, read from the platform&apos;s
        own pricing settings — the same figure the customer paid. Sorted by value
        rather than count, because twelve 10L bottles are a smaller problem than
        eight 20L ones.
      </p>
    </>
  );
}

function DriftView({ drift }: { drift: Drift[] }) {
  if (drift.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<Scale className="h-8 w-8" />}
          title="Ledger and counters agree"
          description="Every registry counter matches the sum of its ledger entries, which is the invariant the ledger exists to keep."
        />
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="scroll-x">
        <table className="w-full min-w-[42rem] text-sm">
          <caption className="sr-only">Counters that disagree with the ledger</caption>
          <thead>
            <tr className="border-b border-default bg-surface-muted text-left">
              <th scope="col" className="px-4 py-3 font-medium">Rider</th>
              <th scope="col" className="px-4 py-3 font-medium">Store</th>
              <th scope="col" className="px-4 py-3 font-medium">Size</th>
              <th scope="col" className="px-4 py-3 font-medium">Ledger</th>
              <th scope="col" className="px-4 py-3 font-medium">Apps show</th>
              <th scope="col" className="px-4 py-3 font-medium">Difference</th>
            </tr>
          </thead>
          <tbody>
            {drift.map((row) => (
              <tr
                key={`${row.rider_id}-${row.vendor_id}-${row.capacity}`}
                className="border-b border-default last:border-0"
              >
                <td className="px-4 py-3">{row.rider_name ?? "—"}</td>
                <td className="px-4 py-3">{row.vendor_name ?? "—"}</td>
                <td className="px-4 py-3">{row.capacity}L</td>
                <td className="px-4 py-3">{row.ledger}</td>
                <td className="px-4 py-3">{row.counter}</td>
                <td className="px-4 py-3">
                  <Badge tone="danger">
                    {row.difference > 0 ? "+" : ""}
                    {row.difference}
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function MovementsView({ movements }: { movements: Movement[] }) {
  if (movements.length === 0) {
    return (
      <Card>
        <EmptyState
          icon={<Package className="h-8 w-8" />}
          title="No movements recorded"
          description="Every collection, return and correction appears here once quick-swap deliveries start."
        />
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="scroll-x">
        <table className="w-full min-w-[44rem] text-sm">
          <caption className="sr-only">Bottle ledger movements</caption>
          <thead>
            <tr className="border-b border-default bg-surface-muted text-left">
              <th scope="col" className="px-4 py-3 font-medium">When</th>
              <th scope="col" className="px-4 py-3 font-medium">What</th>
              <th scope="col" className="px-4 py-3 font-medium">Rider</th>
              <th scope="col" className="px-4 py-3 font-medium">Store</th>
              <th scope="col" className="px-4 py-3 font-medium">Change</th>
            </tr>
          </thead>
          <tbody>
            {movements.map((entry) => (
              <tr key={entry.id} className="border-b border-default last:border-0">
                <td className="px-4 py-3 whitespace-nowrap">
                  {entry.created_at ? entry.created_at.slice(0, 16).replace("T", " ") : "—"}
                </td>
                <td className="px-4 py-3">
                  {MOVEMENT_LABEL[entry.entry_type] ?? entry.entry_type}
                  {entry.note ? (
                    <span className="block text-xs text-muted">{entry.note}</span>
                  ) : null}
                </td>
                <td className="px-4 py-3">{entry.rider_name ?? "—"}</td>
                <td className="px-4 py-3">{entry.vendor_name ?? "—"}</td>
                <td className="px-4 py-3">
                  <Badge tone={entry.quantity > 0 ? "warning" : "success"}>
                    {entry.quantity > 0 ? "+" : ""}
                    {entry.quantity} × {entry.capacity}L
                  </Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** Age with its threshold, never a bare number. */
function AgeBadge({ holder, days }: { holder: Holder; days: number }) {
  if (holder.age_days === null) return <span className="text-muted">—</span>;
  return (
    <Badge tone={holder.stale ? "danger" : holder.age_days >= days / 2 ? "warning" : "neutral"}>
      {holder.age_days}d
    </Badge>
  );
}
