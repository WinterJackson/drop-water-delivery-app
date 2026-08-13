import { Boxes, PackageX, Store, TriangleAlert } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { Pagination, sizeHrefFactory } from "@/components/table/Pagination";
import { TableToolbar } from "@/components/table/TableToolbar";
import { pageLinks, readPageState, type SearchParams } from "@/lib/table/query";
import { ApiError, get } from "@/lib/api/server";
import { formatMoney, formatNumber } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { AvailabilityButton } from "./AvailabilityButton";

export const metadata = { title: "Catalogue" };

/**
 * What the platform is actually selling.
 *
 * `Product` was read in exactly one place before this — the top-sellers query —
 * so the platform could report what sold and not what was on the shelf. There
 * was no way to find a mispriced item or take one down.
 */

export type CatalogueItem = {
  id: string;
  name: string;
  vendor: string | null;
  vendor_id: string | null;
  price: string;
  capacity: number;
  unit: string;
  stock: number;
  low_stock_threshold: number;
  is_available: boolean;
  category: string | null;
  created_at: string | null;
};

type Outlier = {
  id: string;
  name: string;
  vendor: string | null;
  price: string;
  band_median: string;
  band: string;
  ratio: number;
  direction: "high" | "low";
};

type Summary = {
  total: number;
  listed: number;
  hidden: number;
  out_of_stock_listed: number;
  low_stock: number;
  vendors_selling: number;
  outliers: number;
};

const VIEWS = [
  { key: "all", label: "Everything" },
  { key: "out_of_stock", label: "Out of stock" },
  { key: "low_stock", label: "Running low" },
  { key: "hidden", label: "Hidden" },
] as const;

export default async function CataloguePage({
  searchParams,
}: {
  searchParams: Promise<SearchParams>;
}) {
  const params = await searchParams;
  const state = readPageState(params);
  const view = typeof params.view === "string" ? params.view : "all";
  const q = state.q;
  const active = VIEWS.find((v) => v.key === view)?.key ?? "all";

  const query = new URLSearchParams({ view: active, limit: String(state.per) });
  if (q) query.set("search", q);
  if (state.cursor) query.set("cursor", state.cursor);

  type CataloguePage = {
    items: CatalogueItem[];
    next_cursor: string | null;
    summary: Summary;
    outliers: Outlier[];
  };
  let data: CataloguePage;
  let me: AdminMe;
  try {
    [data, me] = await Promise.all([
      get<CataloguePage>(`/api/admin/catalogue?${query.toString()}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load the catalogue" detail={message} />;
  }

  const links = pageLinks({
    pathname: "/operations/catalogue",
    filters: { view: active, q },
    state,
    nextCursor: data.next_cursor,
    count: data.items.length,
  });
  const pager = (
    <Pagination
      links={links}
      noun="products"
      perPage={state.per}
      sizeHref={sizeHrefFactory("/operations/catalogue", { view: active, q })}
    />
  );

  const { items, summary, outliers } = data;
  const canChange = can(me, PERMISSIONS.vendorsApprove);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Catalogue</h1>
        <p className="mt-1 text-sm text-muted">
          Every product across every store. Prices are checked against the median
          for the same category and size, so a misplaced decimal shows up here
          rather than on a customer&apos;s bill.
        </p>
      </div>

      <section aria-label="Catalogue summary">
        <h2 className="sr-only">Catalogue summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="On sale"
            value={formatNumber(summary.listed)}
            hint={`Across ${formatNumber(summary.vendors_selling)} stores · ${formatNumber(summary.hidden)} hidden`}
            icon={<Boxes className="h-4 w-4" />}
          />
          <Stat
            label="Listed but out of stock"
            value={formatNumber(summary.out_of_stock_listed)}
            hint="A customer can add these, pay, and not be able to be served"
            tone={summary.out_of_stock_listed > 0 ? "danger" : "neutral"}
            icon={<PackageX className="h-4 w-4" />}
          />
          <Stat
            label="Running low"
            value={formatNumber(summary.low_stock)}
            hint="At or below the vendor's own threshold"
            tone={summary.low_stock > 0 ? "warning" : "neutral"}
            icon={<Store className="h-4 w-4" />}
          />
          <Stat
            label="Price outliers"
            value={formatNumber(summary.outliers)}
            hint="2.5× away from the median for the same category and size"
            tone={summary.outliers > 0 ? "warning" : "neutral"}
            icon={<TriangleAlert className="h-4 w-4" />}
          />
        </div>
      </section>

      {outliers.length > 0 ? (
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Prices worth a second look</h2>
          <p className="mt-1 text-sm text-muted">
            Compared within category and size — a dispenser is never measured
            against a refill. Worst first.
          </p>
          <ul className="mt-3 space-y-2">
            {outliers.slice(0, 8).map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-baseline justify-between gap-2 border-b border-default pb-2 text-sm last:border-0 last:pb-0"
              >
                <span className="min-w-0">
                  <span className="font-medium">{item.name}</span>
                  <span className="text-muted"> · {item.vendor ?? "unknown store"}</span>
                </span>
                <span className="shrink-0">
                  <Badge tone={item.direction === "high" ? "danger" : "warning"}>
                    {item.ratio}× {item.direction}
                  </Badge>{" "}
                  <span className="font-medium">{formatMoney(item.price)}</span>
                  <span className="text-muted">
                    {" "}
                    vs {formatMoney(item.band_median)} typical
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <nav aria-label="Filter catalogue" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {VIEWS.map((v) => (
            <li key={v.key}>
              <Link
                href={`/operations/catalogue?view=${v.key}`}
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

      <TableToolbar placeholder="Search by product name or store" keep={{ view: active }}>

      {items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Boxes className="h-8 w-8" />}
            title="Nothing here"
            description={
              active === "out_of_stock"
                ? "Every listed product has stock. This is what it should look like."
                : undefined
            }
          />
        </Card>
      ) : (
        <>
          <ul className="space-y-3 md:hidden">
            {items.map((item) => (
              <li key={item.id}>
                <ProductCard item={item} canChange={canChange} />
              </li>
            ))}
          </ul>

          <Card className="hidden overflow-hidden md:block">
            <div className="scroll-x">
              <table className="w-full min-w-[48rem] text-sm">
                <caption className="sr-only">Catalogue — {active}</caption>
                <thead>
                  <tr className="border-b border-default bg-surface-muted text-left">
                    <th scope="col" className="px-4 py-3 font-medium">Product</th>
                    <th scope="col" className="px-4 py-3 font-medium">Store</th>
                    <th scope="col" className="px-4 py-3 font-medium">Price</th>
                    <th scope="col" className="px-4 py-3 font-medium">Stock</th>
                    <th scope="col" className="px-4 py-3 text-right font-medium">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={item.id} className="border-b border-default last:border-0">
                      <td className="px-4 py-3">
                        <span className="font-medium">{item.name}</span>
                        <span className="block text-xs text-muted">
                          {item.capacity > 0 ? `${item.capacity}L · ` : ""}
                          {item.category ?? "uncategorised"}
                        </span>
                      </td>
                      <td className="px-4 py-3">{item.vendor ?? "—"}</td>
                      <td className="px-4 py-3">{formatMoney(item.price)}</td>
                      <td className="px-4 py-3">
                        <StockCell item={item} />
                      </td>
                      <td className="px-4 py-3 text-right">
                        {canChange ? (
                          <AvailabilityButton id={item.id} listed={item.is_available} />
                        ) : (
                          <Badge tone={item.is_available ? "success" : "neutral"}>
                            {item.is_available ? "On sale" : "Hidden"}
                          </Badge>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {pager}
          </Card>

          <Card className="md:hidden">{pager}</Card>
        </>
      )}
      </TableToolbar>
    </div>
  );
}

function StockCell({ item }: { item: CatalogueItem }) {
  if (!item.is_available) return <span className="text-muted">—</span>;
  if (item.stock <= 0) return <Badge tone="danger">Out of stock</Badge>;
  if (item.stock <= item.low_stock_threshold) {
    return (
      <Badge tone="warning">
        {formatNumber(item.stock)} left
      </Badge>
    );
  }
  return <span>{formatNumber(item.stock)}</span>;
}

function ProductCard({ item, canChange }: { item: CatalogueItem; canChange: boolean }) {
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium">{item.name}</p>
          <p className="text-xs text-muted">
            {item.vendor ?? "—"}
            {item.capacity > 0 ? ` · ${item.capacity}L` : ""}
          </p>
          <p className="mt-1 text-sm">
            {formatMoney(item.price)} · <StockCell item={item} />
          </p>
        </div>
        {canChange ? (
          <AvailabilityButton id={item.id} listed={item.is_available} />
        ) : (
          <Badge tone={item.is_available ? "success" : "neutral"}>
            {item.is_available ? "On sale" : "Hidden"}
          </Badge>
        )}
      </div>
    </Card>
  );
}
