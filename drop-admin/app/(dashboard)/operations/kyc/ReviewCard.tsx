"use client";

import { Check, Eye, FileWarning, Loader2, X } from "lucide-react";
import { useState, useTransition } from "react";

import {
  Badge,
  Button,
  Card,
  Field,
  inputClass,
} from "@/components/ui/primitives";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { timeAgo } from "@/lib/utils/format";
import { revealDocuments, reviewRider, type RiderDocuments } from "./actions";

export type QueueRider = {
  id: string;
  full_name: string | null;
  phone_number: string | null;
  vehicle_type: string | null;
  plate_number: string | null;
  kyc_status: string | null;
  has_license: boolean;
  rejection_reason: string | null;
  submitted_at: string | null;
  waiting_hours: number | null;
};

/** Past this, a rider has been waiting long enough that it is a supply problem. */
const SLA_HOURS = 24;

export function ReviewCard({ rider, canReview, canViewPii }: {
  rider: QueueRider;
  canReview: boolean;
  canViewPii: boolean;
}) {
  const [documents, setDocuments] = useState<RiderDocuments | null>(null);
  const [askingWhy, setAskingWhy] = useState(false);
  const [revealError, setRevealError] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [rejecting, setRejecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<"approved" | "rejected" | null>(null);
  const [pending, startTransition] = useTransition();

  const overdue = (rider.waiting_hours ?? 0) >= SLA_HOURS;

  function onReveal(why: string) {
    setRevealError(null);
    startTransition(async () => {
      const result = await revealDocuments(rider.id, why);
      if (result.ok) {
        setDocuments(result.data);
        setAskingWhy(false);
      } else {
        setRevealError(result.error);
      }
    });
  }

  function onDecide(status: "approved" | "rejected") {
    setError(null);
    startTransition(async () => {
      const result = await reviewRider(rider.id, status, reason);
      if (result.ok) setDone(status);
      else setError(result.error);
    });
  }

  if (done) {
    return (
      <Card className="p-5">
        <div className="flex items-center gap-3">
          {done === "approved" ? (
            <Check className="h-5 w-5 text-[var(--success)]" aria-hidden />
          ) : (
            <X className="h-5 w-5 text-[var(--danger)]" aria-hidden />
          )}
          <p className="text-sm">
            <span className="font-medium">{rider.full_name ?? "Rider"}</span>{" "}
            {done === "approved"
              ? "is verified and can start accepting deliveries."
              : "was rejected. They've been told why and can resubmit."}
          </p>
        </div>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      {/* Audited *before* the presigned URLs are minted, and the endpoint
          refuses an empty reason — neither of which `window.prompt` could say
          or enforce. It also returns `null` without appearing at all in a
          browser that has suppressed dialogs, which read here as a "View
          identity documents" button that did nothing. */}
      <ConfirmDialog
        open={askingWhy}
        title="View this rider's identity documents?"
        body={
          <p>
            This mints 5-minute links to {rider.full_name ?? "this rider"}&apos;s
            national ID and driving licence. Opening them is an audited action.
          </p>
        }
        reason={{
          label: "Why do you need to see them?",
          placeholder: "e.g. Verifying the name on the licence against the application",
          hint: "Recorded against your account, with the time and this rider's id.",
        }}
        confirmLabel="View documents"
        pending={pending}
        error={revealError}
        onConfirm={onReveal}
        onCancel={() => {
          setAskingWhy(false);
          setRevealError(null);
        }}
      />

      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-default px-5 py-4">
        <div className="min-w-0">
          <h3 className="truncate font-medium">{rider.full_name ?? "Unnamed rider"}</h3>
          <p className="mt-0.5 text-sm text-muted">
            {rider.vehicle_type ?? "—"}
            {rider.plate_number ? ` · ${rider.plate_number}` : ""}
            {" · "}
            {/* Masked by the server. The full number needs pii.view. */}
            {rider.phone_number ?? "no phone"}
          </p>
        </div>
        <Badge tone={overdue ? "danger" : "warning"}>
          waiting {timeAgo(rider.submitted_at)}
        </Badge>
      </div>

      {rider.rejection_reason ? (
        <div className="flex gap-2 border-b border-default bg-surface-muted px-5 py-3 text-sm">
          <FileWarning className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" aria-hidden />
          <p className="text-muted">
            <span className="font-medium text-[var(--foreground)]">Previously rejected:</span>{" "}
            {rider.rejection_reason}
          </p>
        </div>
      ) : null}

      <div className="space-y-4 px-5 py-4">
        {documents ? (
          <div>
            <div className="grid gap-3 sm:grid-cols-3">
              <Document label="ID front" url={documents.id_card_front} />
              <Document label="ID back" url={documents.id_card_back} />
              <Document label="Driving licence" url={documents.driver_license} />
            </div>
            <dl className="mt-4 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
              <Detail label="Full name" value={documents.full_name} />
              <Detail label="Phone" value={documents.phone_number} />
              <Detail label="ID number" value={documents.ID_number} />
            </dl>
            <p className="mt-3 text-xs text-muted">
              These links expire in {Math.round(documents.expires_in / 60)} minutes.
              Opening them was recorded against your account.
            </p>
          </div>
        ) : canViewPii ? (
          <Button variant="secondary" onClick={() => setAskingWhy(true)} disabled={pending}>
            {pending ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Eye className="h-4 w-4" aria-hidden />
            )}
            View identity documents
          </Button>
        ) : (
          <p className="text-sm text-muted">
            You don&apos;t have permission to view identity documents, so you
            can&apos;t complete this review.
          </p>
        )}

        {canReview && rejecting ? (
          <Field
            label="What was wrong?"
            htmlFor={`reason-${rider.id}`}
            hint="The rider sees this on their verification screen, so be specific enough to act on."
          >
            <textarea
              id={`reason-${rider.id}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={500}
              autoFocus
              className={inputClass}
              placeholder="e.g. The back of the ID card is blurred — please retake it in better light."
            />
          </Field>
        ) : null}

        {error ? (
          <p role="alert" className="text-sm text-[var(--danger)]">{error}</p>
        ) : null}
      </div>

      {canReview ? (
        <div className="flex flex-wrap gap-2 border-t border-default bg-surface-muted px-5 py-3">
          {rejecting ? (
            <>
              <Button variant="danger" onClick={() => onDecide("rejected")} disabled={pending}>
                {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                Confirm rejection
              </Button>
              <Button variant="ghost" onClick={() => setRejecting(false)} disabled={pending}>
                Cancel
              </Button>
            </>
          ) : (
            <>
              <Button
                onClick={() => onDecide("approved")}
                // Approving without looking is the mistake this queue makes
                // easiest, so the control is not available until the documents
                // have actually been opened.
                disabled={pending || !documents}
                title={documents ? undefined : "View the documents first"}
              >
                {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Check className="h-4 w-4" aria-hidden />}
                Approve
              </Button>
              <Button variant="secondary" onClick={() => setRejecting(true)} disabled={pending}>
                <X className="h-4 w-4" aria-hidden />
                Reject
              </Button>
            </>
          )}
        </div>
      ) : null}
    </Card>
  );
}

function Document({ label, url }: { label: string; url: string | null }) {
  if (!url) {
    return (
      <div className="flex h-32 items-center justify-center rounded-lg border border-dashed border-default text-xs text-muted">
        No {label.toLowerCase()}
      </div>
    );
  }
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="group block overflow-hidden rounded-lg border border-default"
    >
      {/* A plain <img>, not next/image: optimising it would pull the document
          through Next's server cache, which turns a 5-minute presigned link
          into a stored copy of somebody's national ID. */}
      <img
        src={url}
        alt={label}
        className="h-32 w-full bg-surface-muted object-cover transition-opacity group-hover:opacity-90"
      />
      <span className="block border-t border-default px-2 py-1.5 text-xs text-muted">
        {label}
      </span>
    </a>
  );
}

function Detail({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="flex justify-between gap-4 border-b border-default py-1 last:border-0">
      <dt className="text-muted">{label}</dt>
      <dd className="truncate font-medium">{value ?? "—"}</dd>
    </div>
  );
}
