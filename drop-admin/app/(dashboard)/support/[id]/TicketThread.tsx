"use client";

import { EyeOff, Loader2, Send } from "lucide-react";
import { useState, useTransition } from "react";

import { Badge, Button, Card, CardHeader, Field, inputClass } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";
import { formatDateTime } from "@/lib/utils/format";
import { replyToTicket, setTicketStatus, takeTicket } from "../actions";

export type Message = {
  author: string;
  author_email?: string;
  body: string;
  at: string;
  internal?: boolean;
};

export function TicketThread({
  ticketId,
  subject,
  body,
  messages,
  status,
  assignedTo,
  canRespond,
  createdAt,
}: {
  ticketId: string;
  subject: string;
  body: string;
  messages: Message[];
  status: string;
  assignedTo: string | null;
  canRespond: boolean;
  createdAt: string | null;
}) {
  const [draft, setDraft] = useState("");
  const [internal, setInternal] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function send(newStatus?: string) {
    setError(null);
    startTransition(async () => {
      const result = await replyToTicket(ticketId, draft, { internal, status: newStatus });
      if (result.ok) {
        setDraft("");
        setInternal(false);
      } else {
        setError(result.error);
      }
    });
  }

  function changeStatus(next: string) {
    setError(null);
    startTransition(async () => {
      const result = await setTicketStatus(ticketId, next);
      if (!result.ok) setError(result.error);
    });
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Conversation"
          description={
            assignedTo ? `Assigned to ${assignedTo}` : "Nobody has taken this yet"
          }
          action={
            !assignedTo && canRespond ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() =>
                  startTransition(async () => {
                    const result = await takeTicket(ticketId);
                    if (!result.ok) setError(result.error);
                  })
                }
                disabled={pending}
              >
                Take this
              </Button>
            ) : null
          }
        />

        <ol className="divide-y divide-[var(--border)]">
          <li className="px-5 py-4">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm font-medium">{subject}</p>
              <p className="text-xs text-muted">{formatDateTime(createdAt)}</p>
            </div>
            <p className="mt-2 whitespace-pre-wrap text-sm">{body}</p>
          </li>

          {messages.map((message, index) => (
            <li
              key={`${message.at}-${index}`}
              className={cn(
                "px-5 py-4",
                message.internal && "bg-[color-mix(in_oklch,var(--warning)_7%,transparent)]",
              )}
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-sm font-medium">
                  {message.author === "admin"
                    ? (message.author_email ?? "Drop")
                    : "Them"}
                  {message.internal ? (
                    <Badge tone="warning" className="ml-2">
                      <EyeOff className="h-3 w-3" aria-hidden />
                      internal
                    </Badge>
                  ) : null}
                </p>
                <p className="text-xs text-muted">{formatDateTime(message.at)}</p>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-sm">{message.body}</p>
            </li>
          ))}
        </ol>
      </Card>

      {canRespond ? (
        <Card>
          <div className="space-y-3 p-5">
            <Field
              label={internal ? "Internal note" : "Reply"}
              htmlFor="reply-body"
              hint={
                internal
                  ? "Visible only here. Nothing is sent to them."
                  : "Sent to their app, and emailed if we have an address."
              }
              error={error ?? undefined}
            >
              <textarea
                id="reply-body"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                rows={4}
                maxLength={5000}
                className={inputClass}
                placeholder={
                  internal
                    ? "e.g. Rider says nobody answered the gate. Checking the GPS trail."
                    : "Write the reply they'll see…"
                }
              />
            </Field>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={internal}
                onChange={(event) => setInternal(event.target.checked)}
                className="h-4 w-4"
              />
              {/* The distinction that matters most on this screen. Getting it
                  wrong sends a colleague-facing note to a customer. */}
              Internal note — don&apos;t send this to them
            </label>

            <div className="flex flex-wrap gap-2">
              <Button onClick={() => send()} disabled={pending || draft.trim().length === 0}>
                {pending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Send className="h-4 w-4" aria-hidden />
                )}
                {internal ? "Add note" : "Send reply"}
              </Button>

              {!internal ? (
                <Button
                  variant="secondary"
                  onClick={() => send("resolved")}
                  disabled={pending || draft.trim().length === 0}
                >
                  Send and resolve
                </Button>
              ) : null}

              {status !== "closed" ? (
                <Button
                  variant="ghost"
                  onClick={() => changeStatus(status === "resolved" ? "closed" : "resolved")}
                  disabled={pending}
                >
                  Mark {status === "resolved" ? "closed" : "resolved"}
                </Button>
              ) : (
                <Button variant="ghost" onClick={() => changeStatus("open")} disabled={pending}>
                  Reopen
                </Button>
              )}
            </div>
          </div>
        </Card>
      ) : (
        <p className="rounded-lg bg-surface-muted px-4 py-3 text-sm text-muted">
          You can read this queue but not reply — that needs the &ldquo;Reply to
          and resolve support tickets&rdquo; permission.
        </p>
      )}
    </div>
  );
}
