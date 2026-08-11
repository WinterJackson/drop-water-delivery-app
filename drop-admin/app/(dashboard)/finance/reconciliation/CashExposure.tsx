import { Bike, Clock, Wallet } from "lucide-react";

import { Badge, Card, CardHeader } from "@/components/ui/primitives";
import { formatMoney, formatNumber } from "@/lib/utils/format";

/**
 * Cash currently in riders' hands.
 *
 * The one figure nobody on this platform could produce. Each rider sees their
 * own committed float on their own screen; the platform's total — how much of
 * its money is on a motorbike right now — existed only as a query somebody
 * would have had to write. So the limits that cap it were being set against a
 * number no one had ever looked at.
 *
 * **Age sits beside every amount**, because the release sweep acts on it. A
 * carrier past the release window is about to have their float returned and
 * their order re-offered, and operations should see that before the rider
 * rings to ask why their balance is locked.
 */

export type CashExposure = {
  total_at_risk: string;
  orders_open: number;
  riders_carrying: number;
  carriers: {
    rider_id: string;
    rider_name: string | null;
    orders: number;
    value: string;
    held_minutes: number | null;
  }[];
};

export function CashExposurePanel({
  data,
  releaseAfterMinutes,
}: {
  data: CashExposure;
  /** From `cod_unclaimed_release_minutes`. Never a literal here. */
  releaseAfterMinutes: number | null;
}) {
  if (data.riders_carrying === 0) {
    return (
      <Card>
        <CardHeader
          title="Cash with riders"
          description="Nothing outstanding — no rider is carrying an undelivered cash order."
        />
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Cash with riders"
        description="Undelivered cash orders, by who is carrying them. This money is outside the ledger until the delivery settles."
      />

      <div className="grid gap-4 border-b border-default px-5 pb-4 sm:grid-cols-3">
        <div>
          <p className="text-xs text-muted">On the road now</p>
          <p className="mt-0.5 flex items-center gap-2 text-xl font-semibold tabular-nums">
            <Wallet className="h-4 w-4 text-muted" aria-hidden />
            {formatMoney(data.total_at_risk)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Open cash orders</p>
          <p className="mt-0.5 text-xl font-semibold tabular-nums">
            {formatNumber(data.orders_open)}
          </p>
        </div>
        <div>
          <p className="text-xs text-muted">Riders carrying</p>
          <p className="mt-0.5 flex items-center gap-2 text-xl font-semibold tabular-nums">
            <Bike className="h-4 w-4 text-muted" aria-hidden />
            {formatNumber(data.riders_carrying)}
          </p>
        </div>
      </div>

      <div className="scroll-x">
        <table className="w-full min-w-[32rem] text-sm">
          <caption className="sr-only">
            Riders carrying undelivered cash orders, largest first
          </caption>
          <thead>
            <tr className="border-b border-default text-left text-xs text-muted">
              <th scope="col" className="px-5 py-2 font-medium">Rider</th>
              <th scope="col" className="px-5 py-2 text-right font-medium">Orders</th>
              <th scope="col" className="px-5 py-2 text-right font-medium">Cash held</th>
              <th scope="col" className="px-5 py-2 text-right font-medium">Oldest</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)]">
            {data.carriers.map((carrier) => {
              const overdue =
                releaseAfterMinutes !== null &&
                carrier.held_minutes !== null &&
                carrier.held_minutes >= releaseAfterMinutes;

              return (
                <tr key={carrier.rider_id}>
                  <th scope="row" className="px-5 py-2.5 text-left font-normal">
                    {carrier.rider_name ?? (
                      <span className="font-mono text-xs text-muted">
                        {carrier.rider_id.slice(0, 8)}
                      </span>
                    )}
                  </th>
                  <td className="px-5 py-2.5 text-right tabular-nums">
                    {formatNumber(carrier.orders)}
                  </td>
                  <td className="px-5 py-2.5 text-right tabular-nums">
                    {formatMoney(carrier.value)}
                  </td>
                  <td className="px-5 py-2.5 text-right">
                    {carrier.held_minutes === null ? (
                      <span className="text-muted">—</span>
                    ) : overdue ? (
                      <Badge tone="warning">
                        <Clock className="h-3 w-3" aria-hidden />
                        {carrier.held_minutes}m · releasing
                      </Badge>
                    ) : (
                      <span className="tabular-nums">{carrier.held_minutes}m</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {releaseAfterMinutes !== null ? (
        <p className="border-t border-default px-5 py-3 text-xs text-muted">
          A cash order undelivered for {releaseAfterMinutes} minutes has its float
          released and goes back to the pool. The customer keeps their order; the
          rider stops being liable for it.
        </p>
      ) : null}
    </Card>
  );
}
