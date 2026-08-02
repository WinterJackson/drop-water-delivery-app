"use client";

import { AlertTriangle, Loader2, Send } from "lucide-react";
import { useMemo, useState, useTransition } from "react";

import { Button, Card, CardHeader, Field, inputClass } from "@/components/ui/primitives";
import { formatNumber } from "@/lib/utils/format";
import { sendBroadcast } from "./actions";

export type Audience = { key: string; label: string; recipients: number };

export function Composer({ audiences }: { audiences: Audience[] }) {
  const [audience, setAudience] = useState(audiences[0]?.key ?? "");
  const [channel, setChannel] = useState("in_app");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [transactional, setTransactional] = useState(false);
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const selected = useMemo(
    () => audiences.find((item) => item.key === audience),
    [audiences, audience],
  );

  const recipients = selected?.recipients ?? 0;
  const ready =
    subject.trim().length >= 3 &&
    body.trim().length >= 10 &&
    confirm === audience &&
    recipients > 0;

  function send() {
    setError(null);
    startTransition(async () => {
      const result = await sendBroadcast({
        channel,
        audience,
        subject: subject.trim(),
        body: body.trim(),
        transactional,
        confirm,
      });
      if (result.ok) {
        setSent(result.data.message);
        setSubject("");
        setBody("");
        setConfirm("");
        setTransactional(false);
      } else {
        setError(result.error);
      }
    });
  }

  return (
    <Card>
      <CardHeader
        title="Compose"
        description="This reaches everyone in the segment and cannot be recalled."
      />

      <div className="space-y-4 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Who" htmlFor="audience">
            <select
              id="audience"
              value={audience}
              onChange={(event) => {
                setAudience(event.target.value);
                // The confirmation is tied to the audience, so changing the
                // audience must invalidate it — otherwise a typed confirmation
                // silently authorises a different, larger send.
                setConfirm("");
              }}
              className={inputClass}
            >
              {audiences.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label} ({formatNumber(item.recipients)})
                </option>
              ))}
            </select>
          </Field>

          <Field label="How" htmlFor="channel">
            <select
              id="channel"
              value={channel}
              onChange={(event) => setChannel(event.target.value)}
              className={inputClass}
            >
              <option value="in_app">In-app notification</option>
              <option value="email">Email</option>
              <option value="both">Both</option>
            </select>
          </Field>
        </div>

        <p
          className={
            recipients === 0
              ? "rounded-lg bg-surface-muted px-4 py-3 text-sm text-muted"
              : "rounded-lg bg-surface-muted px-4 py-3 text-sm"
          }
        >
          {recipients === 0 ? (
            "Nobody is in this segment right now."
          ) : (
            <>
              This will reach <strong className="tabular-nums">{formatNumber(recipients)}</strong>{" "}
              {recipients === 1 ? "person" : "people"}. Suspended accounts are always excluded.
            </>
          )}
        </p>

        <Field label="Subject" htmlFor="subject">
          <input
            id="subject"
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            maxLength={200}
            className={inputClass}
            placeholder="e.g. Delivery hours are changing from Monday"
          />
        </Field>

        <Field
          label="Message"
          htmlFor="body"
          hint="A blank line starts a new paragraph. Written as you type it — no formatting."
        >
          <textarea
            id="body"
            value={body}
            onChange={(event) => setBody(event.target.value)}
            rows={7}
            maxLength={5000}
            className={inputClass}
          />
        </Field>

        <label className="flex items-start gap-2.5 rounded-lg border border-default px-4 py-3 text-sm">
          <input
            type="checkbox"
            checked={transactional}
            onChange={(event) => setTransactional(event.target.checked)}
            className="mt-0.5 h-4 w-4"
          />
          <span>
            <span className="font-medium">This is not marketing</span>
            <span className="mt-0.5 block text-xs text-muted">
              {/* Stated as a claim rather than a setting, because that is what it
                  is: ticking it overrides the notification preferences of every
                  recipient, including people who explicitly muted promotions. */}
              Overrides everyone&apos;s notification preferences, including people
              who have muted promotions. Only tick this for something they need to
              know — a service outage, a policy change. It is recorded against your
              account either way.
            </span>
          </span>
        </label>

        {transactional ? (
          <div
            role="note"
            className="flex gap-2.5 rounded-lg border border-[var(--warning)] bg-[color-mix(in_oklch,var(--warning)_8%,transparent)] px-4 py-3 text-sm"
          >
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" aria-hidden />
            <p>
              {formatNumber(recipients)} people will be notified whether or not they
              asked to be.
            </p>
          </div>
        ) : null}

        <Field
          label={`Type "${audience}" to confirm`}
          htmlFor="confirm"
          hint="There is no undo, and no way to stop it once it starts."
          error={error ?? undefined}
        >
          <input
            id="confirm"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            className={inputClass}
            autoComplete="off"
          />
        </Field>

        {sent ? (
          <p role="status" className="text-sm text-[var(--success)]">
            {sent}
          </p>
        ) : null}

        <Button onClick={send} disabled={pending || !ready}>
          {pending ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Send className="h-4 w-4" aria-hidden />
          )}
          Send to {formatNumber(recipients)}
        </Button>
      </div>
    </Card>
  );
}
