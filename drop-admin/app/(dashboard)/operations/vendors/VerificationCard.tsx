"use client";

import { Check, ExternalLink, Loader2, X } from "lucide-react";
import Link from "next/link";
import { useState, useTransition } from "react";

import { Badge, Button, Card, Field, inputClass } from "@/components/ui/primitives";
import { formatMoney, timeAgo } from "@/lib/utils/format";
import { reviewVendor } from "./actions";

export type QueueVendor = {
  id: string;
  name: string | null;
  email: string | null;
  phone_number: string | null;
  vendor_type: string | null;
  verification_status: string | null;
  is_online: boolean;
  is_suspended: boolean;
  rating: number | null;
  wallet_balance?: string;
  created_at: string | null;
};

export function VerificationCard({
  vendor,
  canApprove,
}: {
  vendor: QueueVendor;
  canApprove: boolean;
}) {
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<"verified" | "rejected" | null>(null);
  const [pending, startTransition] = useTransition();

  function decide(decision: "verified" | "rejected") {
    setError(null);
    startTransition(async () => {
      const result = await reviewVendor(vendor.id, decision, reason);
      if (result.ok) setDone(decision);
      else setError(result.error);
    });
  }

  if (done) {
    return (
      <Card className="p-5">
        <div className="flex items-start gap-3">
          {done === "verified" ? (
            <Check className="mt-0.5 h-5 w-5 shrink-0 text-[var(--success)]" aria-hidden />
          ) : (
            <X className="mt-0.5 h-5 w-5 shrink-0 text-[var(--danger)]" aria-hidden />
          )}
          <p className="text-sm">
            <span className="font-medium">{vendor.name ?? "This store"}</span>{" "}
            {done === "verified"
              ? "is verified. They've been notified."
              : "was not verified. They've been told why and can resubmit — the store is still trading."}
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-default px-5 py-4">
        <div className="min-w-0">
          <h3 className="truncate font-medium">{vendor.name ?? "Unnamed store"}</h3>
          <p className="mt-0.5 text-sm text-muted">
            {vendor.vendor_type ?? "—"}
            {" · joined "}
            {timeAgo(vendor.created_at)}
            {/* Masked by the server for every role; the full value is a separate
                audited request on the vendor's own page. */}
            {vendor.phone_number ? ` · ${vendor.phone_number}` : ""}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {vendor.is_suspended ? <Badge tone="danger">Suspended</Badge> : null}
          {vendor.is_online ? <Badge tone="success">Open</Badge> : <Badge>Closed</Badge>}
          <Badge tone={vendor.verification_status === "rejected" ? "danger" : "warning"}>
            {vendor.verification_status ?? "pending"}
          </Badge>
        </div>
      </div>

      <div className="space-y-4 px-5 py-4">
        <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
          <Detail label="Rating" value={vendor.rating ? `${vendor.rating.toFixed(1)} ★` : "No reviews yet"} />
          <Detail label="Wallet balance" value={formatMoney(vendor.wallet_balance)} />
        </dl>

        <p className="text-sm text-muted">
          {/* The decision needs the store's catalogue, licence and trading
              history, none of which belong crammed into a queue card. */}
          Open the store to check its catalogue, documents and order history
          before deciding.
        </p>

        <Link
          href={`/people/vendors/${vendor.id}`}
          className="inline-flex items-center gap-1.5 text-sm text-[var(--accent)] underline underline-offset-4"
        >
          Open store record
          <ExternalLink className="h-3.5 w-3.5" aria-hidden />
        </Link>

        {canApprove && rejecting ? (
          <Field
            label="What's missing?"
            htmlFor={`reason-${vendor.id}`}
            hint="The vendor sees this. Be specific enough that they can fix it and resubmit."
          >
            <textarea
              id={`reason-${vendor.id}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={500}
              autoFocus
              className={inputClass}
              placeholder="e.g. The business permit has expired — please upload a current one."
            />
          </Field>
        ) : null}

        {canApprove && !rejecting ? (
          <Field
            label="Why are you verifying this store?"
            htmlFor={`note-${vendor.id}`}
            hint="Recorded in the audit log against your account, and sent to the vendor."
          >
            <input
              id={`note-${vendor.id}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={500}
              className={inputClass}
              placeholder="e.g. Permit and water quality certificate both current."
            />
          </Field>
        ) : null}

        {error ? (
          <p role="alert" className="text-sm text-[var(--danger)]">
            {error}
          </p>
        ) : null}
      </div>

      {canApprove ? (
        <div className="flex flex-wrap gap-2 border-t border-default bg-surface-muted px-5 py-3">
          {rejecting ? (
            <>
              <Button variant="danger" onClick={() => decide("rejected")} disabled={pending}>
                {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                Confirm rejection
              </Button>
              <Button variant="ghost" onClick={() => setRejecting(false)} disabled={pending}>
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button onClick={() => decide("verified")} disabled={pending || reason.trim().length < 3}>
                {pending ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Check className="h-4 w-4" aria-hidden />
                )}
                Verify
              </Button>
              <Button variant="secondary" onClick={() => setRejecting(true)} disabled={pending}>
                <X className="h-4 w-4" aria-hidden />
                Reject
              </Button>
            </>
          )}
        </div>
      ) : (
        <p className="border-t border-default bg-surface-muted px-5 py-3 text-sm text-muted">
          You can see this queue but not decide on it — that needs the
          &ldquo;Approve vendors&rdquo; permission.
        </p>
      )}
    </Card>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-default py-1 last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="truncate font-medium">{value}</dd>
    </div>
  );
}
