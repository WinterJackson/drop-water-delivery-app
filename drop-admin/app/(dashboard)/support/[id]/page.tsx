import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { Badge, Card, CardHeader, ErrorState } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { formatDateTime } from "@/lib/utils/format";
import { PriorityControl } from "./PriorityControl";
import { TicketThread, type Message } from "./TicketThread";

export const metadata = { title: "Ticket" };

type Ticket = {
  id: string;
  subject: string;
  body: string;
  category: string;
  priority: string;
  status: string;
  requester: {
    type: string;
    id: string;
    name: string | null;
    email_masked: string | null;
    exists: boolean;
  };
  related_order_id: string | null;
  assigned_to: string | null;
  messages: Message[];
  resolution: string | null;
  created_at: string | null;
  resolved_at: string | null;
};

const PLURAL: Record<string, string> = {
  customer: "customers",
  rider: "riders",
  vendor: "vendors",
};

export default async function TicketPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;

  let ticket: Ticket;
  let me: AdminMe;
  try {
    [ticket, me] = await Promise.all([
      get<Ticket>(`/api/admin/support/tickets/${id}`),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load this ticket" detail={message} />;
  }

  const canOpenAccount = can(
    me,
    ticket.requester.type === "customer"
      ? PERMISSIONS.customersRead
      : ticket.requester.type === "rider"
        ? PERMISSIONS.ridersRead
        : PERMISSIONS.vendorsRead,
  );

  // Gated for the same reason the name above it is. Both stock presets that
  // reach this screen happen to carry `orders.read`, but **roles are presets,
  // not authority** — permissions are edited per administrator, and a link that
  // walks someone into a refusal is the failure the courtesy layer exists to
  // avoid. The id itself is not hidden; only the link to a page they cannot open.
  const canOpenOrder = can(me, PERMISSIONS.ordersRead);

  return (
    <div className="space-y-6">
      <Link
        href="/support"
        className="-my-2 inline-flex min-h-11 items-center gap-1.5 py-2 text-sm text-muted hover:text-[var(--foreground)]"
      >
        <ArrowLeft className="h-4 w-4" aria-hidden />
        Back to the queue
      </Link>

      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{ticket.subject}</h1>
          <p className="mt-1 text-sm text-muted">
            {ticket.category} · raised {formatDateTime(ticket.created_at)}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Badge tone={ticket.priority === "urgent" ? "danger" : ticket.priority === "high" ? "warning" : "neutral"}>
            {ticket.priority}
          </Badge>
          <Badge tone={ticket.status === "resolved" ? "success" : "neutral"}>{ticket.status}</Badge>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
        <TicketThread
          ticketId={ticket.id}
          subject={ticket.subject}
          body={ticket.body}
          messages={ticket.messages}
          status={ticket.status}
          assignedTo={ticket.assigned_to}
          canRespond={can(me, PERMISSIONS.supportRespond)}
          createdAt={ticket.created_at}
        />

        <div className="space-y-4 lg:sticky lg:top-20 lg:self-start">
          <Card>
            <CardHeader title="Who raised this" />
            <dl className="divide-y divide-[var(--border)] text-sm">
              <Row label="Type" value={<span className="capitalize">{ticket.requester.type}</span>} />
              <Row
                label="Name"
                value={
                  ticket.requester.exists && canOpenAccount ? (
                    <Link
                      href={`/people/${PLURAL[ticket.requester.type]}/${ticket.requester.id}`}
                      className="text-[var(--accent)] underline underline-offset-4"
                    >
                      {ticket.requester.name ?? "—"}
                    </Link>
                  ) : (
                    (ticket.requester.name ?? "—")
                  )
                }
              />
              {/* Masked, like every other address in this console. Replying does
                  not require reading it, so this screen does not offer it. */}
              <Row label="Email" value={<span className="font-mono text-xs">{ticket.requester.email_masked ?? "—"}</span>} />
              {!ticket.requester.exists ? (
                <Row
                  label="Account"
                  value={<span className="text-[var(--warning)]">deleted</span>}
                />
              ) : null}
            </dl>
            <div className="border-t border-default">
              <PriorityControl
                ticketId={ticket.id}
                priority={ticket.priority}
                canRespond={can(me, PERMISSIONS.supportRespond)}
              />
            </div>
          </Card>

          {ticket.related_order_id ? (
            <Card>
              <CardHeader title="Related order" />
              <div className="px-5 py-4 text-sm">
                {/* Carries the id. This linked to the bare queue, so an agent
                    answering "where is my order" landed on an unfiltered board
                    with the one thing they needed sitting on the screen behind
                    them. `view=all` because the default board is "stuck" and a
                    delivered order is not on it. */}
                {canOpenOrder ? (
                  <Link
                    href={`/operations/orders?view=all&q=${ticket.related_order_id}`}
                    className="font-mono text-[var(--accent)] underline underline-offset-4"
                  >
                    {ticket.related_order_id.slice(0, 8)}
                  </Link>
                ) : (
                  <span className="font-mono">{ticket.related_order_id.slice(0, 8)}</span>
                )}
              </div>
            </Card>
          ) : null}

          {ticket.resolution ? (
            <Card>
              <CardHeader title="Resolution" />
              <p className="px-5 py-4 text-sm">{ticket.resolution}</p>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 px-5 py-2.5">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium">{value}</dd>
    </div>
  );
}
