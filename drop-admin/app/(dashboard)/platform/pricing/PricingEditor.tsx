"use client";

import { AlertTriangle, Loader2, RotateCcw, Save } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, useTransition } from "react";

import { Badge, Button, Card, CardHeader, Field, inputClass } from "@/components/ui/primitives";
import { cn } from "@/lib/utils/cn";
import { formatMoney, formatMoneyDelta, isZeroMoney } from "@/lib/utils/format";
import { previewChanges, saveChanges, type Preview } from "./actions";

export type Setting = {
  key: string;
  group: string;
  group_label: string;
  label: string;
  help: string;
  /**
   * `int` truncates on the server (`int(value)`), so it is only for quantities
   * that cannot be fractional. `decimal` is its fractional counterpart — the
   * delivery radii use it, because 2.5 km entered against an `int` would have
   * been stored as 2 without a word.
   */
  kind: "rate" | "money" | "int" | "decimal" | "bool" | "windows" | "deposits";
  unit: string;
  value: unknown;
  default: unknown;
  minimum: number | null;
  maximum: number | null;
  is_default: boolean;
};

/** The rows of the preview worth showing, in the order money actually moves. */
const QUOTE_ROWS: { key: string; label: string; emphasis?: boolean }[] = [
  { key: "product_total", label: "Products" },
  { key: "delivery_fee", label: "Delivery" },
  { key: "service_fee", label: "Service fee" },
  { key: "surge_fee", label: "Surge" },
  { key: "delivery_markup", label: "Delivery markup" },
  { key: "payload_surcharge", label: "Payload surcharge" },
  { key: "staircase_surcharge", label: "Staircase surcharge" },
  { key: "bottle_deposit", label: "Bottle deposit" },
  { key: "welcome_discount", label: "Welcome discount" },
  { key: "customer_total", label: "Customer pays", emphasis: true },
  { key: "platform_revenue", label: "Platform keeps", emphasis: true },
  { key: "vendor_receives", label: "Vendor receives", emphasis: true },
  { key: "rider_receives", label: "Rider receives", emphasis: true },
];

function sameValue(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * A setting's value as the owner reads it, not as JSON.
 *
 * Rates are stored as fractions and thought about as percentages, and showing
 * `0.05` beside `0.025` on a screen where a typo moves real money is how the
 * wrong one gets approved.
 */
function show(setting: Setting, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (setting.kind === "bool") return value ? "on" : "off";
  if (setting.kind === "rate") return `${(Number(value) * 100).toFixed(2)}%`;
  if (setting.kind === "money") return formatMoney(String(value));
  if (typeof value === "object") return JSON.stringify(value);
  return `${String(value)}${setting.unit ? ` ${setting.unit}` : ""}`;
}

export function PricingEditor({ settings }: { settings: Setting[] }) {
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [pending, startTransition] = useTransition();

  const [sample, setSample] = useState({
    product_total: 500,
    distance_km: 2,
    quantity: 2,
    vendor_type: "retail_refill",
    delivery_type: "quick_swap",
    first_order: false,
    surge: false,
  });

  const changes = useMemo(() => {
    const out: Record<string, unknown> = {};
    for (const setting of settings) {
      if (setting.key in draft && !sameValue(draft[setting.key], setting.value)) {
        out[setting.key] = draft[setting.key];
      }
    }
    return out;
  }, [draft, settings]);

  const changedCount = Object.keys(changes).length;

  // Debounced: every keystroke would otherwise price a sample order against the
  // database, which is a denial of service against your own platform.
  const runPreview = useCallback(async () => {
    setPreviewing(true);
    try {
      const result = await previewChanges(changes, sample);
      if (result.ok) {
        setPreview(result.data);
        setError(null);
      } else {
        // A refusal here is the bounds check doing its job — show it as it is,
        // not as a failed request.
        setError(result.error);
        setPreview(null);
      }
    } finally {
      setPreviewing(false);
    }
  }, [changes, sample]);

  useEffect(() => {
    const timer = setTimeout(() => void runPreview(), 400);
    return () => clearTimeout(timer);
  }, [runPreview]);

  function set(key: string, value: unknown) {
    setSaved(null);
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function reset(setting: Setting) {
    setSaved(null);
    setDraft((current) => {
      const next = { ...current };
      delete next[setting.key];
      return next;
    });
  }

  function save() {
    setError(null);
    startTransition(async () => {
      const result = await saveChanges(changes, reason);
      if (result.ok) {
        setSaved(result.data.message);
        setDraft({});
        setReason("");
      } else {
        setError(result.error);
      }
    });
  }

  const groups = useMemo(() => {
    const map = new Map<string, { label: string; items: Setting[] }>();
    for (const setting of settings) {
      if (!map.has(setting.group)) {
        map.set(setting.group, { label: setting.group_label, items: [] });
      }
      map.get(setting.group)!.items.push(setting);
    }
    return [...map.entries()];
  }, [settings]);

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0 space-y-6">
        {groups.map(([key, group]) => (
          <Card key={key}>
            <CardHeader title={group.label} />
            <div className="divide-y divide-[var(--border)]">
              {group.items.map((setting) => {
                const current = setting.key in draft ? draft[setting.key] : setting.value;
                const dirty = setting.key in changes;

                return (
                  <div key={setting.key} className="px-5 py-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <label htmlFor={setting.key} className="text-sm font-medium">
                            {setting.label}
                          </label>
                          {dirty ? <Badge tone="warning">changed</Badge> : null}
                          {!setting.is_default && !dirty ? (
                            <Badge tone="accent">customised</Badge>
                          ) : null}
                        </div>
                        {setting.help ? (
                          <p className="mt-1 max-w-prose text-xs text-muted">{setting.help}</p>
                        ) : null}
                      </div>

                      <div className="flex shrink-0 items-center gap-2">
                        <SettingInput setting={setting} value={current} onChange={set} />
                        {dirty ? (
                          <button
                            type="button"
                            onClick={() => reset(setting)}
                            aria-label={`Undo change to ${setting.label}`}
                            className="rounded-lg p-2 text-muted hover:bg-surface-muted"
                          >
                            <RotateCcw className="h-4 w-4" aria-hidden />
                          </button>
                        ) : null}
                      </div>
                    </div>

                    {setting.kind === "rate" && dirty ? (
                      <p className="mt-1.5 text-xs text-muted">
                        {(Number(current) * 100).toFixed(2)}% — was{" "}
                        {(Number(setting.value) * 100).toFixed(2)}%
                      </p>
                    ) : null}

                    {/*
                      What the platform ships, whenever this row differs from it.
                      "Customised" on its own could not distinguish a figure
                      somebody chose from one left behind by an older release —
                      and a stored value silently outranks a new default forever,
                      so the second is invisible until a total comes out wrong.
                    */}
                    {!setting.is_default && !dirty ? (
                      <p className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                        <span>
                          Set to {show(setting, setting.value)}. The platform ships{" "}
                          {show(setting, setting.default)}.
                        </span>
                        <button
                          type="button"
                          onClick={() => set(setting.key, setting.default)}
                          className="rounded text-[var(--accent)] underline underline-offset-2 hover:no-underline"
                        >
                          Use the shipped value
                        </button>
                      </p>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </Card>
        ))}
      </div>

      {/* The preview follows on scroll at desk width; below `xl` it sits after
          the fields, which is the right order on a phone — you change a number,
          then you scroll to what it did. */}
      <div className="space-y-4 xl:sticky xl:top-20 xl:self-start">
        <Card>
          <CardHeader
            title="A typical order"
            description="Priced with your changes, before saving anything."
            action={previewing ? <Loader2 className="h-4 w-4 animate-spin text-muted" aria-hidden /> : null}
          />

          <div className="space-y-3 border-b border-default px-5 py-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Products (KSH)" htmlFor="sample-products">
                <input
                  id="sample-products"
                  type="number"
                  min={0}
                  value={sample.product_total}
                  onChange={(event) =>
                    setSample((s) => ({ ...s, product_total: Number(event.target.value) }))
                  }
                  className={inputClass}
                />
              </Field>
              <Field label="Distance (km)" htmlFor="sample-distance">
                <input
                  id="sample-distance"
                  type="number"
                  min={0}
                  step={0.5}
                  value={sample.distance_km}
                  onChange={(event) =>
                    setSample((s) => ({ ...s, distance_km: Number(event.target.value) }))
                  }
                  className={inputClass}
                />
              </Field>
              <Field label="Bottles" htmlFor="sample-quantity">
                <input
                  id="sample-quantity"
                  type="number"
                  min={1}
                  value={sample.quantity}
                  onChange={(event) =>
                    setSample((s) => ({ ...s, quantity: Number(event.target.value) }))
                  }
                  className={inputClass}
                />
              </Field>
              <Field label="Store type" htmlFor="sample-vendor">
                <select
                  id="sample-vendor"
                  value={sample.vendor_type}
                  onChange={(event) =>
                    setSample((s) => ({ ...s, vendor_type: event.target.value }))
                  }
                  className={inputClass}
                >
                  <option value="retail_refill">Retail refill</option>
                  <option value="wholesale_b2b">Wholesale</option>
                </select>
              </Field>
            </div>

            <div className="flex flex-wrap gap-4 text-sm">
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={sample.first_order}
                  onChange={(event) =>
                    setSample((s) => ({ ...s, first_order: event.target.checked }))
                  }
                />
                First order
              </label>
              <label className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={sample.surge}
                  onChange={(event) => setSample((s) => ({ ...s, surge: event.target.checked }))}
                />
                Peak hour
              </label>
            </div>
          </div>

          {preview ? (
            <dl className="divide-y divide-[var(--border)]">
              {QUOTE_ROWS.filter(
                (row) => preview.before[row.key] !== undefined,
              ).map((row) => {
                const delta = preview.delta[row.key] ?? "0.00";
                const changed = !isZeroMoney(delta);
                const increased = !delta.trim().startsWith("-");
                return (
                  <div
                    key={row.key}
                    className={cn(
                      "flex items-baseline justify-between gap-3 px-5 py-2 text-sm",
                      row.emphasis && "bg-surface-muted font-medium",
                    )}
                  >
                    <dt className={row.emphasis ? "" : "text-muted"}>{row.label}</dt>
                    <dd className="shrink-0 text-right tabular-nums">
                      {formatMoney(preview.after[row.key])}
                      {changed ? (
                        <span
                          className={cn(
                            "ml-2 text-xs",
                            increased ? "text-[var(--success)]" : "text-[var(--danger)]",
                          )}
                        >
                          {formatMoneyDelta(delta)}
                        </span>
                      ) : null}
                    </dd>
                  </div>
                );
              })}
            </dl>
          ) : (
            <p className="px-5 py-8 text-center text-sm text-muted">
              {error ? "Fix the value above to see the effect." : "Pricing…"}
            </p>
          )}
        </Card>

        <Card>
          <CardHeader
            title={changedCount === 0 ? "No changes" : `${changedCount} change${changedCount === 1 ? "" : "s"}`}
          />
          <div className="space-y-3 px-5 py-4">
            {changedCount > 0 ? (
              <div
                role="note"
                className="flex gap-2.5 rounded-lg border border-[var(--warning)] bg-[color-mix(in_oklch,var(--warning)_8%,transparent)] px-3 py-2.5 text-xs"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--warning)]" aria-hidden />
                <p>
                  This applies to the <strong>next order priced</strong> in all three
                  apps. Orders already placed keep the economics they were created
                  with — settlement pays from the order&apos;s own record, not from
                  these values.
                </p>
              </div>
            ) : null}

            <Field
              label="Why are you changing this?"
              htmlFor="config-reason"
              hint="Recorded in the settings history and the audit log."
              error={error ?? undefined}
            >
              <textarea
                id="config-reason"
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={2}
                maxLength={500}
                className={inputClass}
                placeholder="e.g. Raising the retail service fee to cover the new packaging cost."
              />
            </Field>

            {saved ? (
              <p role="status" className="text-sm text-[var(--success)]">
                {saved}
              </p>
            ) : null}

            <Button
              onClick={save}
              disabled={pending || changedCount === 0 || reason.trim().length < 3}
              className="w-full"
            >
              {pending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Save className="h-4 w-4" aria-hidden />
              )}
              Save {changedCount > 0 ? `${changedCount} change${changedCount === 1 ? "" : "s"}` : ""}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  );
}

function SettingInput({
  setting,
  value,
  onChange,
}: {
  setting: Setting;
  value: unknown;
  onChange: (key: string, value: unknown) => void;
}) {
  if (setting.kind === "bool") {
    return (
      <label className="flex items-center gap-2 text-sm">
        <input
          id={setting.key}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(setting.key, event.target.checked)}
          className="h-4 w-4"
        />
        <span className="sr-only">{setting.label}</span>
        {value ? "On" : "Off"}
      </label>
    );
  }

  if (setting.kind === "windows") {
    // Rendered as text because the alternative — a repeating pair of hour
    // pickers — is a lot of UI for a value that changes once a year.
    return (
      <input
        id={setting.key}
        value={(value as number[][]).map((w) => `${w[0]}-${w[1]}`).join(", ")}
        onChange={(event) => {
          const parsed = event.target.value
            .split(",")
            .map((part) => part.trim())
            .filter(Boolean)
            .map((part) => part.split("-").map((n) => Number(n.trim())));
          onChange(setting.key, parsed);
        }}
        aria-describedby={`${setting.key}-hint`}
        placeholder="6-8, 17-19"
        className={cn(inputClass, "w-40")}
      />
    );
  }

  if (setting.kind === "deposits") {
    const entries = Object.entries(value as Record<string, number>);
    return (
      <div className="space-y-1.5">
        {entries.map(([litres, amount]) => (
          <div key={litres} className="flex items-center gap-2">
            <span className="w-10 text-right text-xs text-muted">{litres}L</span>
            <input
              id={`${setting.key}-${litres}`}
              type="number"
              min={0}
              value={amount}
              onChange={(event) =>
                onChange(setting.key, {
                  ...(value as Record<string, number>),
                  [litres]: Number(event.target.value),
                })
              }
              aria-label={`Deposit for a ${litres} litre bottle`}
              className={cn(inputClass, "w-28")}
            />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <input
        id={setting.key}
        type="number"
        inputMode="decimal"
        // A rate is a fraction of 1.0, so it needs four decimal places of
        // resolution; money needs two; a distance in km steps in halves.
        step={
          setting.kind === "rate"
            ? 0.0001
            : setting.kind === "int"
              ? 1
              : setting.kind === "decimal"
                ? 0.1
                : 0.01
        }
        min={setting.minimum ?? undefined}
        max={setting.maximum ?? undefined}
        value={String(value ?? "")}
        onChange={(event) => onChange(setting.key, Number(event.target.value))}
        className={cn(inputClass, "w-32 text-right")}
      />
      {setting.unit ? (
        <span className="w-24 shrink-0 text-xs text-muted">{setting.unit}</span>
      ) : null}
    </div>
  );
}
