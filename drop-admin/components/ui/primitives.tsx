import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps, ReactNode } from "react";

import { cn } from "@/lib/utils/cn";

/**
 * The small set of primitives every screen is built from.
 *
 * Kept in one file, and deliberately small. A component library nobody has read
 * gets bypassed the first time it does not quite fit, and then the console has
 * two button styles.
 */

// ── Button ────────────────────────────────────────────────────────────────

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors " +
    "disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 " +
    // 44px minimum touch target on the smallest size, because operations staff
    // triage the KYC queue on a phone as often as at a desk.
    "min-h-[2.25rem] whitespace-nowrap",
  {
    variants: {
      variant: {
        primary: "bg-[var(--accent)] text-[var(--accent-foreground)] hover:opacity-90",
        secondary: "bg-surface-muted text-[var(--foreground)] border border-default hover:bg-[var(--border)]",
        ghost: "text-muted hover:bg-surface-muted hover:text-[var(--foreground)]",
        danger: "bg-[var(--danger)] text-white hover:opacity-90",
      },
      size: {
        sm: "h-9 px-3 text-sm",
        md: "h-10 px-4 text-sm",
        lg: "h-11 px-5 text-base",
        icon: "h-10 w-10 p-0",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: ComponentProps<"button"> & VariantProps<typeof button>) {
  return <button className={cn(button({ variant, size }), className)} {...props} />;
}

// ── Surfaces ──────────────────────────────────────────────────────────────

export function Card({ className, ...props }: ComponentProps<"div">) {
  return (
    <div
      className={cn("bg-surface border border-default rounded-xl shadow-sm", className)}
      {...props}
    />
  );
}

export function CardHeader({
  title,
  description,
  action,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-default px-5 py-4">
      <div className="min-w-0">
        <h2 className="text-base font-semibold leading-tight">{title}</h2>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {action}
    </div>
  );
}

// ── Badge ─────────────────────────────────────────────────────────────────

const badge = cva(
  "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      tone: {
        neutral: "bg-surface-muted text-muted border border-default",
        success: "bg-[color-mix(in_oklch,var(--success)_15%,transparent)] text-[var(--success)]",
        warning: "bg-[color-mix(in_oklch,var(--warning)_18%,transparent)] text-[var(--warning)]",
        danger: "bg-[color-mix(in_oklch,var(--danger)_15%,transparent)] text-[var(--danger)]",
        accent: "bg-[color-mix(in_oklch,var(--accent)_15%,transparent)] text-[var(--accent)]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export function Badge({
  className,
  tone,
  ...props
}: ComponentProps<"span"> & VariantProps<typeof badge>) {
  return <span className={cn(badge({ tone }), className)} {...props} />;
}

// ── Empty and error states ────────────────────────────────────────────────

/**
 * An empty queue is good news and should look like it.
 *
 * The platform currently has no orders and no riders, so *every* screen renders
 * empty on day one. A console whose empty state is a blank rectangle reads as
 * broken, and the first impression of the product is that it does not work.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon ? <div className="mb-3 text-muted" aria-hidden>{icon}</div> : null}
      <p className="font-medium">{title}</p>
      {description ? (
        <p className="mt-1 max-w-sm text-sm text-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ title, detail }: { title: string; detail?: string }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-[var(--danger)] bg-[color-mix(in_oklch,var(--danger)_8%,transparent)] px-5 py-4"
    >
      <p className="font-medium text-[var(--danger)]">{title}</p>
      {detail ? <p className="mt-1 text-sm text-muted">{detail}</p> : null}
    </div>
  );
}

// ── Stat ──────────────────────────────────────────────────────────────────

export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
  /** Percentage change against the previous period, as a signed number. */
  delta,
  /** True when a *fall* is the good outcome — cancellations, disputes. */
  deltaInverted = false,
  /** A `<Sparkline>`; the card lays it out, the caller supplies the series. */
  trend,
  icon,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "neutral" | "warning" | "danger";
  delta?: number | null;
  deltaInverted?: boolean;
  trend?: ReactNode;
  icon?: ReactNode;
}) {
  const good = delta === null || delta === undefined ? null : deltaInverted ? delta <= 0 : delta >= 0;

  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <p className="min-w-0 text-sm text-muted">{label}</p>
        {icon ? <span className="shrink-0 text-muted" aria-hidden>{icon}</span> : null}
      </div>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <p
          className={cn(
            "text-2xl font-semibold tabular-nums tracking-tight",
            tone === "warning" && "text-[var(--warning)]",
            tone === "danger" && "text-[var(--danger)]",
          )}
        >
          {value}
        </p>

        {/* An arrow as well as a colour: "up" must survive a colour-vision
            difference and a greyscale print of the board. */}
        {delta !== null && delta !== undefined ? (
          <span
            className={cn(
              "text-xs font-medium tabular-nums",
              good ? "text-[var(--success)]" : "text-[var(--danger)]",
            )}
          >
            {delta >= 0 ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}%
            <span className="sr-only">
              {delta >= 0 ? " higher" : " lower"} than the previous period
            </span>
          </span>
        ) : null}
      </div>

      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
      {trend ? <div className="mt-3">{trend}</div> : null}
    </Card>
  );
}

// ── Field ─────────────────────────────────────────────────────────────────

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-sm text-[var(--danger)]" role="alert">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted">{hint}</p>
      ) : null}
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-default bg-surface px-3 py-2 text-sm " +
  "placeholder:text-muted focus-visible:outline-2 focus-visible:outline-offset-0";
