"use client";

import { useState, useTransition } from "react";

import { setTicketPriority } from "../actions";

const OPTIONS = [
  { value: "low", label: "Low" },
  { value: "normal", label: "Normal" },
  { value: "high", label: "High" },
  { value: "urgent", label: "Urgent" },
] as const;

/**
 * Escalation, as a control rather than a decoration.
 *
 * A `<select>` and not four buttons: de-escalating has to be exactly as easy as
 * escalating, or the queue ratchets upward until every ticket is urgent and the
 * field means nothing again.
 */
export function PriorityControl({
  ticketId,
  priority,
  canRespond,
}: {
  ticketId: string;
  priority: string;
  canRespond: boolean;
}) {
  const [value, setValue] = useState(priority);
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  if (!canRespond) return null;

  function change(next: string) {
    const previous = value;
    setValue(next);
    setError(null);
    startTransition(async () => {
      const result = await setTicketPriority(ticketId, next);
      if (!result.ok) {
        // Put the control back where the server still has it, rather than
        // leaving the screen asserting a change that did not happen.
        setValue(previous);
        setError(result.error);
      }
    });
  }

  return (
    <div className="px-5 py-4">
      <label htmlFor="ticket-priority" className="block text-sm text-muted">
        Priority
      </label>
      <select
        id="ticket-priority"
        value={value}
        disabled={pending}
        onChange={(event) => change(event.target.value)}
        className="mt-1.5 w-full rounded-lg border border-default bg-surface px-3 py-2 text-sm disabled:opacity-60"
      >
        {OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      <p className="mt-1.5 text-xs text-muted">
        The queue is oldest-first. Raising this moves the ticket up it, and
        everything else down.
      </p>
      {error ? (
        <p role="alert" className="mt-1.5 text-xs text-[var(--danger)]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
