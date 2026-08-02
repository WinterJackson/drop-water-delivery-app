import { Users } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";

import { Badge, Card, EmptyState, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatMoney, timeAgo } from "@/lib/utils/format";

/** Plural in the URL, singular in the API — `/people/riders` → `kind=rider`. */
const KINDS = {
  customers: { kind: "customer", title: "Customers", blurb: "Everyone who orders water." },
  riders: { kind: "rider", title: "Riders", blurb: "Everyone who delivers it." },
  vendors: { kind: "vendor", title: "Vendors", blurb: "Every store on the platform." },
} as const;

type Slug = keyof typeof KINDS;

type Person = {
  id: string;
  kind: string;
  name: string | null;
  email: string | null;
  phone_number: string | null;
  is_suspended: boolean;
  suspension_reason: string | null;
  created_at: string | null;
  kyc_status?: string | null;
  plate_number?: string | null;
  vendor_type?: string | null;
  verification_status?: string | null;
  is_online?: boolean;
  rating?: number | null;
  wallet_balance?: string;
  debt_balance?: string;
  bottle_refill_count?: number;
};

export async function generateMetadata({ params }: { params: Promise<{ kind: string }> }) {
  const { kind } = await params;
  return { title: KINDS[kind as Slug]?.title ?? "People" };
}

export default async function PeopleListPage({
  params,
  searchParams,
}: {
  params: Promise<{ kind: string }>;
  searchParams: Promise<{ q?: string; status?: string }>;
}) {
  const { kind: slug } = await params;
  const config = KINDS[slug as Slug];
  if (!config) notFound();

  const { q = "", status = "" } = await searchParams;

  const query = new URLSearchParams();
  if (q.trim()) query.set("search", q.trim());
  if (status) query.set("status", status);

  let data: { items: Person[]; next_cursor: string | null };
  try {
    data = await get(`/api/admin/people/${config.kind}s?${query.toString()}`);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title={`Couldn't load ${config.title.toLowerCase()}`} detail={message} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{config.title}</h1>
        <p className="mt-1 text-sm text-muted">{config.blurb}</p>
      </div>

      {/* A plain GET form: search survives a reload, is linkable, and works
          before any JavaScript has run. */}
      <form method="GET" className="flex flex-wrap gap-2">
        <label htmlFor="q" className="sr-only">Search {config.title.toLowerCase()}</label>
        <input
          id="q"
          name="q"
          defaultValue={q}
          placeholder="Name, email, phone…"
          className="min-w-0 flex-1 rounded-lg border border-default bg-surface px-3 py-2 text-sm"
        />
        <select
          name="status"
          defaultValue={status}
          aria-label="Filter by status"
          className="rounded-lg border border-default bg-surface px-3 py-2 text-sm"
        >
          <option value="">All</option>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
        </select>
        <button type="submit" className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)]">
          Search
        </button>
      </form>

      {data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Users className="h-8 w-8" />}
            title={q ? `No ${config.title.toLowerCase()} match “${q}”` : `No ${config.title.toLowerCase()} yet`}
            description={q ? "Try a phone number or part of an email address." : undefined}
          />
        </Card>
      ) : (
        <>
          {/* Below `md` the table becomes a stack of cards rather than a
              52rem grid you drag sideways two columns at a time. Two sets of
              markup rather than one set forced through `display:block`, which
              is the trick that makes a table stop being a table to a screen
              reader. */}
          <ul className="space-y-3 md:hidden">
            {data.items.map((person) => (
              <li key={person.id}>
                <Card className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <Link
                        href={`/people/${slug}/${person.id}`}
                        className="font-medium hover:underline"
                      >
                        {person.name ?? "—"}
                      </Link>
                      <p className="text-xs text-muted">joined {timeAgo(person.created_at)}</p>
                    </div>
                    {person.is_suspended ? (
                      <Badge tone="danger">Suspended</Badge>
                    ) : (
                      <Badge tone="success">Active</Badge>
                    )}
                  </div>

                  {/* Masked by the server for every role. */}
                  <p className="mt-2 truncate font-mono text-xs text-muted">
                    {person.email ?? "—"} · {person.phone_number ?? "—"}
                  </p>

                  <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs">
                    <div className="flex gap-1.5">
                      <dt className="text-muted">
                        {config.kind === "rider"
                          ? "Verification"
                          : config.kind === "vendor"
                            ? "Type"
                            : "Bottles"}
                      </dt>
                      <dd className="font-medium">
                        {config.kind === "rider"
                          ? (person.kyc_status ?? "—")
                          : config.kind === "vendor"
                            ? (person.vendor_type ?? "—")
                            : (person.bottle_refill_count ?? 0)}
                      </dd>
                    </div>
                    <div className="flex gap-1.5">
                      <dt className="text-muted">Balance</dt>
                      <dd className="font-medium tabular-nums">
                        {formatMoney(person.wallet_balance)}
                      </dd>
                    </div>
                    {person.debt_balance && Number(person.debt_balance) > 0 ? (
                      <div className="flex gap-1.5">
                        <dt className="text-muted">Owes</dt>
                        <dd className="font-medium tabular-nums text-[var(--warning)]">
                          {formatMoney(person.debt_balance)}
                        </dd>
                      </div>
                    ) : null}
                  </dl>
                </Card>
              </li>
            ))}
          </ul>

          <Card className="hidden overflow-hidden md:block">
            <div className="scroll-x">
              <table className="w-full min-w-[44rem] text-sm">
              <caption className="sr-only">{config.title}, newest first</caption>
              <thead>
                <tr className="border-b border-default bg-surface-muted text-left">
                  <th scope="col" className="px-4 py-3 font-medium">Name</th>
                  <th scope="col" className="px-4 py-3 font-medium">Contact</th>
                  <th scope="col" className="px-4 py-3 font-medium">
                    {config.kind === "rider" ? "Verification" : config.kind === "vendor" ? "Type" : "Bottles"}
                  </th>
                  <th scope="col" className="px-4 py-3 font-medium">Balance</th>
                  <th scope="col" className="px-4 py-3 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((person) => (
                  <tr key={person.id} className="border-b border-default last:border-0 hover:bg-surface-muted">
                    <td className="px-4 py-3">
                      <Link href={`/people/${slug}/${person.id}`} className="font-medium hover:underline">
                        {person.name ?? "—"}
                      </Link>
                      <p className="text-xs text-muted">joined {timeAgo(person.created_at)}</p>
                    </td>
                    <td className="px-4 py-3">
                      {/* Masked by the server for every role. */}
                      <p className="font-mono text-xs">{person.email ?? "—"}</p>
                      <p className="font-mono text-xs text-muted">{person.phone_number ?? "—"}</p>
                    </td>
                    <td className="px-4 py-3">
                      {config.kind === "rider" ? (
                        <Badge tone={person.kyc_status === "approved" ? "success" : person.kyc_status === "rejected" ? "danger" : "warning"}>
                          {person.kyc_status ?? "—"}
                        </Badge>
                      ) : config.kind === "vendor" ? (
                        <span className="text-xs">{person.vendor_type ?? "—"}</span>
                      ) : (
                        <span className="tabular-nums">{person.bottle_refill_count ?? 0}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 tabular-nums">
                      {formatMoney(person.wallet_balance)}
                      {person.debt_balance && Number(person.debt_balance) > 0 ? (
                        <p className="text-xs text-[var(--warning)]">owes {formatMoney(person.debt_balance)}</p>
                      ) : null}
                    </td>
                    <td className="px-4 py-3">
                      {person.is_suspended ? (
                        <Badge tone="danger">Suspended</Badge>
                      ) : (
                        <Badge tone="success">Active</Badge>
                      )}
                    </td>
                  </tr>
                ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}
