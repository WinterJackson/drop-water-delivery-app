import { Ban, Clock, Coins, Pause, Store } from "lucide-react";

import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { formatDateTime, formatMoney } from "@/lib/utils/format";

/**
 * What this store has decided for itself.
 *
 * "Why is this shop getting no orders" was previously answerable only as
 * `is_online: false` — one of five reasons, and the least likely. A store that
 * had paused, priced itself out with a minimum nobody in the area meets, or
 * switched cash off looked identical on this console to one that was simply
 * quiet, so the support answer was always "we'll look into it".
 *
 * Read-only on purpose. These are the vendor's decisions, and an operator
 * reaching in to un-pause a shop that paused itself is how a customer ends up
 * ordering water from a counter with nobody behind it. What the console *does*
 * control is the bounds — the `storefront` settings group — and suspension,
 * which is an administrator's decision and already has its own control on this
 * page.
 */

export type Storefront = {
  accepting: boolean;
  /** open | paused | offline | closed_hours | suspended */
  state: string;
  reason: string | null;
  reopens_at: string | null;
  accepts_cash: boolean;
  cash_reason: string | null;
  min_order_value: string;
};

const STATE_LABEL: Record<string, string> = {
  open: "Taking orders",
  paused: "Paused",
  offline: "Switched offline",
  closed_hours: "Outside opening hours",
  suspended: "Suspended",
};

export function StorefrontPanel({ storefront }: { storefront: Storefront }) {
  const minimum = Number(storefront.min_order_value);
  const paused = storefront.state === "paused";

  return (
    <Card>
      <CardHeader
        title="Storefront"
        description="Set by the vendor. The platform sets the bounds these sit within, not the values."
      />

      <dl className="divide-y divide-[var(--border)]">
        <div className="flex items-start justify-between gap-4 px-5 py-3">
          <dt className="flex items-center gap-2 text-sm text-muted">
            {paused ? (
              <Pause className="h-4 w-4" aria-hidden />
            ) : (
              <Store className="h-4 w-4" aria-hidden />
            )}
            Right now
          </dt>
          <dd className="text-right">
            <Badge tone={storefront.accepting ? "success" : paused ? "warning" : "neutral"}>
              {STATE_LABEL[storefront.state] ?? storefront.state}
            </Badge>
            {storefront.reason ? (
              <p className="mt-1 text-xs text-muted">{storefront.reason}</p>
            ) : null}
          </dd>
        </div>

        {storefront.reopens_at ? (
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="flex items-center gap-2 text-sm text-muted">
              <Clock className="h-4 w-4" aria-hidden />
              Reopens
            </dt>
            <dd className="text-sm tabular-nums">{formatDateTime(storefront.reopens_at)}</dd>
          </div>
        ) : null}

        <div className="flex items-center justify-between gap-4 px-5 py-3">
          <dt className="flex items-center gap-2 text-sm text-muted">
            <Coins className="h-4 w-4" aria-hidden />
            Cash orders
          </dt>
          <dd className="text-sm">
            {storefront.accepts_cash ? (
              <span>Accepted</span>
            ) : (
              <Badge tone="warning">
                <Ban className="h-3 w-3" aria-hidden />
                Declined by the store
              </Badge>
            )}
          </dd>
        </div>

        <div className="flex items-center justify-between gap-4 px-5 py-3">
          <dt className="text-sm text-muted">Minimum order</dt>
          <dd className="text-sm tabular-nums">
            {minimum > 0 ? formatMoney(storefront.min_order_value) : "None"}
          </dd>
        </div>
      </dl>
    </Card>
  );
}
