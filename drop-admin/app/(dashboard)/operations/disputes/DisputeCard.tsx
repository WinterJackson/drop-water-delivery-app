"use client";

import { Check, Images, Loader2, X } from "lucide-react";
import { useState, useTransition } from "react";

import { Badge, Button, Card, Field, inputClass } from "@/components/ui/primitives";
import { timeAgo } from "@/lib/utils/format";
import { resolveDispute } from "../orders/actions";
import { loadDisputePhotos } from "./photos-action";

export type Dispute = {
  id: string;
  order_id: string;
  rider: { id: string; name: string | null };
  status: string;
  reason_text: string;
  photo_count: number;
  created_at: string | null;
};

export function DisputeCard({ dispute, canResolve }: { dispute: Dispute; canResolve: boolean }) {
  const [photos, setPhotos] = useState<string[] | null>(null);
  const [panel, setPanel] = useState<"approved" | "denied" | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [decided, setDecided] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  function onLoadPhotos() {
    setError(null);
    startTransition(async () => {
      const result = await loadDisputePhotos(dispute.id);
      if (result.ok) setPhotos(result.data);
      else setError(result.error);
    });
  }

  function submit() {
    if (!panel) return;
    setError(null);
    startTransition(async () => {
      const result = await resolveDispute(dispute.id, panel, reason);
      if (result.ok) setDecided(panel);
      else setError(result.error);
    });
  }

  if (decided) {
    return (
      <Card className="p-5">
        <p className="text-sm">
          Dispute {decided === "approved" ? "upheld" : "not upheld"}. The rider has been told why.
        </p>
      </Card>
    );
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-default px-5 py-4">
        <div className="min-w-0">
          <h3 className="truncate font-medium">{dispute.rider.name ?? "Rider"}</h3>
          <p className="mt-0.5 font-mono text-xs text-muted">
            order {dispute.order_id.slice(0, 8)}
          </p>
        </div>
        <Badge tone="warning">raised {timeAgo(dispute.created_at)}</Badge>
      </div>

      <div className="space-y-4 px-5 py-4">
        <p className="text-sm">{dispute.reason_text}</p>

        {photos ? (
          photos.length === 0 ? (
            <p className="text-sm text-muted">No photos were attached.</p>
          ) : (
            <div className="grid grid-cols-3 gap-2">
              {photos.map((url, index) => (
                <a key={url} href={url} target="_blank" rel="noopener noreferrer" className="overflow-hidden rounded-lg border border-default">
                  {/* Plain <img>: routing evidence photos through Next's image
                      optimiser would cache them server-side, outliving the
                      5-minute presigned URL. */}
                  <img src={url} alt={`Dispute evidence ${index + 1}`} className="h-24 w-full bg-surface-muted object-cover" />
                </a>
              ))}
            </div>
          )
        ) : dispute.photo_count > 0 ? (
          <Button variant="secondary" size="sm" onClick={onLoadPhotos} disabled={pending}>
            {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Images className="h-4 w-4" aria-hidden />}
            View {dispute.photo_count} photo{dispute.photo_count === 1 ? "" : "s"}
          </Button>
        ) : (
          <p className="text-sm text-muted">No photos were attached.</p>
        )}

        {panel ? (
          <Field
            label={panel === "approved" ? "Why are you upholding this?" : "Why are you rejecting the report?"}
            htmlFor={`dispute-${dispute.id}`}
            hint="The rider is shown this."
            error={error ?? undefined}
          >
            <textarea
              id={`dispute-${dispute.id}`}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={500}
              autoFocus
              className={inputClass}
            />
          </Field>
        ) : error ? (
          <p role="alert" className="text-sm text-[var(--danger)]">{error}</p>
        ) : null}
      </div>

      {canResolve ? (
        <div className="flex flex-wrap gap-2 border-t border-default bg-surface-muted px-5 py-3">
          {panel ? (
            <>
              <Button variant={panel === "approved" ? "primary" : "danger"} onClick={submit} disabled={pending}>
                {pending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                Confirm
              </Button>
              <Button variant="ghost" onClick={() => setPanel(null)} disabled={pending}>Cancel</Button>
            </>
          ) : (
            <>
              <Button
                onClick={() => setPanel("approved")}
                // Deciding without looking at the evidence is the mistake this
                // queue makes easiest.
                disabled={pending || (dispute.photo_count > 0 && photos === null)}
                title={dispute.photo_count > 0 && photos === null ? "View the photos first" : undefined}
              >
                <Check className="h-4 w-4" aria-hidden />
                Uphold the rider
              </Button>
              <Button
                variant="secondary"
                onClick={() => setPanel("denied")}
                disabled={pending || (dispute.photo_count > 0 && photos === null)}
              >
                <X className="h-4 w-4" aria-hidden />
                Reject the report
              </Button>
            </>
          )}
        </div>
      ) : null}
    </Card>
  );
}
