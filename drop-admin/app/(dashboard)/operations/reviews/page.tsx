import { EyeOff, MessageSquare, Phone, Star, ThumbsDown } from "lucide-react";
import Link from "next/link";

import { Badge, Card, EmptyState, ErrorState, Stat } from "@/components/ui/primitives";
import { ApiError, get } from "@/lib/api/server";
import { formatNumber, timeAgo } from "@/lib/utils/format";
import { PERMISSIONS, can, type AdminMe } from "@/lib/permissions";
import { ModerateButton } from "./ModerateButton";

export const metadata = { title: "Reviews" };

/**
 * Review moderation.
 *
 * `reviews` had no moderation state and no admin reader. A review naming a
 * rider's home address could only be removed with a DELETE, which loses that it
 * existed and strands the target's rating counters.
 *
 * Nothing here is user-reported — no app has a report button — so the default
 * view is a heuristic and says so on the page. A heuristic presented as a queue
 * of confirmed problems is how moderators learn to clear a screen without
 * reading it.
 */

type Review = {
  id: string;
  order_id: string;
  target_type: string;
  target_id: string;
  target_name: string | null;
  rating: number;
  comment: string | null;
  flags: string[];
  hidden: boolean;
  hidden_at: string | null;
  hidden_reason: string | null;
  created_at: string | null;
};

type Summary = {
  total: number;
  visible: number;
  hidden: number;
  low_rated: number;
  with_contact_details: number;
  average_rating: number | null;
  last_7_days: number;
  low_rating_threshold: number;
};

type Worst = {
  target_type: string;
  target_id: string;
  target_name: string | null;
  average: number;
  reviews: number;
};

const VIEWS = [
  { key: "flagged", label: "Worth reading" },
  { key: "low", label: "Low rated" },
  { key: "all", label: "Everything" },
  { key: "hidden", label: "Taken down" },
] as const;

const FLAG_LABEL: Record<string, string> = {
  contact_details: "Contact details",
  low_rating_with_comment: "Low rating with a comment",
};

export default async function ReviewsPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string; q?: string }>;
}) {
  const { view = "flagged", q = "" } = await searchParams;
  const active = VIEWS.find((v) => v.key === view)?.key ?? "flagged";

  const query = new URLSearchParams({ view: active });
  if (q.trim()) query.set("search", q.trim());

  let data: { items: Review[]; summary: Summary; worst_rated: Worst[] };
  let me: AdminMe;
  try {
    [data, me] = await Promise.all([
      get<{ items: Review[]; summary: Summary; worst_rated: Worst[] }>(
        `/api/admin/reviews?${query.toString()}`,
      ),
      get<AdminMe>("/api/admin/me"),
    ]);
  } catch (error) {
    const message = error instanceof ApiError ? error.message : "Something went wrong.";
    return <ErrorState title="Couldn't load reviews" detail={message} />;
  }

  const { items, summary, worst_rated: worst } = data;
  const mayModerate = can(me, PERMISSIONS.disputesResolve);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Reviews</h1>
        <p className="mt-1 text-sm text-muted">
          What customers said about stores and riders. Hiding a review is never a
          delete — it stays in the table and leaves the target&apos;s average in
          the same transaction.
        </p>
      </div>

      <section aria-label="Review summary">
        <h2 className="sr-only">Review summary</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Stat
            label="Visible reviews"
            value={formatNumber(summary.visible)}
            hint={`${formatNumber(summary.last_7_days)} in the last 7 days · ${formatNumber(summary.hidden)} taken down`}
            icon={<MessageSquare className="h-4 w-4" />}
          />
          <Stat
            label="Average rating"
            value={summary.average_rating === null ? "—" : summary.average_rating.toFixed(2)}
            hint={
              summary.average_rating === null
                ? "Nobody has been rated yet"
                : "Across every visible review, both stores and riders"
            }
            icon={<Star className="h-4 w-4" />}
          />
          <Stat
            label={`${summary.low_rating_threshold} stars or below`}
            value={formatNumber(summary.low_rated)}
            hint="Where a service problem shows up first"
            tone={summary.low_rated > 0 ? "warning" : "neutral"}
            icon={<ThumbsDown className="h-4 w-4" />}
          />
          <Stat
            label="Contact details in a comment"
            value={formatNumber(summary.with_contact_details)}
            hint="Reviews are public — a phone number in one is a safety problem"
            tone={summary.with_contact_details > 0 ? "danger" : "neutral"}
            icon={<Phone className="h-4 w-4" />}
          />
        </div>
      </section>

      {worst.length > 0 ? (
        <Card className="p-5">
          <h2 className="text-sm font-semibold">Lowest rated right now</h2>
          <p className="mt-1 text-sm text-muted">
            Only targets with at least three visible reviews. A store with one
            one-star review is not the platform&apos;s worst store, and putting
            them at the top of this list is how somebody gets suspended for a bad
            day.
          </p>
          <ul className="mt-3 space-y-2">
            {worst.map((row) => (
              <li
                key={`${row.target_type}-${row.target_id}`}
                className="flex flex-wrap items-baseline justify-between gap-2 border-b border-default pb-2 text-sm last:border-0 last:pb-0"
              >
                <Link
                  href={`/people/${row.target_type === "vendor" ? "vendors" : "riders"}/${row.target_id}`}
                  className="min-w-0 font-medium hover:underline"
                >
                  {row.target_name ?? "Unnamed"}
                  <span className="font-normal text-muted">
                    {" "}
                    · {row.target_type === "vendor" ? "store" : "rider"}
                  </span>
                </Link>
                <span className="shrink-0">
                  <Badge tone={row.average <= 2 ? "danger" : row.average <= 3.5 ? "warning" : "neutral"}>
                    {row.average.toFixed(2)}
                  </Badge>{" "}
                  <span className="text-muted">from {formatNumber(row.reviews)} reviews</span>
                </span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      <nav aria-label="Filter reviews" className="scroll-x -mx-1 px-1">
        <ul className="flex gap-1">
          {VIEWS.map((v) => (
            <li key={v.key}>
              <Link
                href={`/operations/reviews?view=${v.key}`}
                aria-current={v.key === active ? "page" : undefined}
                className={
                  v.key === active
                    ? "inline-flex whitespace-nowrap rounded-lg bg-[color-mix(in_oklch,var(--accent)_14%,transparent)] px-3 py-1.5 text-sm font-medium text-[var(--accent)]"
                    : "inline-flex whitespace-nowrap rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-muted"
                }
              >
                {v.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {active === "flagged" ? (
        <p className="text-xs text-muted">
          Nothing on this platform lets a customer, rider or vendor report a
          review — there is no report button in any of the three apps. This list
          is a heuristic: comments that look like they contain a phone number or
          an email address, and low ratings that came with something written.
          Treat it as a reading list, not a list of confirmed problems.
        </p>
      ) : null}

      <form method="GET" className="flex gap-2">
        <input type="hidden" name="view" value={active} />
        <label htmlFor="q" className="sr-only">Search review comments</label>
        <input
          id="q"
          name="q"
          defaultValue={q}
          placeholder="Search what people wrote…"
          className="min-w-0 flex-1 rounded-lg border border-default bg-surface px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="rounded-lg bg-[var(--accent)] px-4 py-2 text-sm font-medium text-[var(--accent-foreground)]"
        >
          Search
        </button>
      </form>

      {items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<MessageSquare className="h-8 w-8" />}
            title={summary.total === 0 ? "Nobody has left a review yet" : "Nothing here"}
            description={
              summary.total === 0
                ? "Reviews appear once customers start rating deliveries."
                : active === "flagged"
                  ? "No comment matched either pattern. This is what it should look like."
                  : active === "hidden"
                    ? "No review has been taken down."
                    : undefined
            }
          />
        </Card>
      ) : (
        <ul className="space-y-3">
          {items.map((review) => (
            <li key={review.id}>
              <ReviewCard review={review} mayModerate={mayModerate} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ReviewCard({ review, mayModerate }: { review: Review; mayModerate: boolean }) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Stars rating={review.rating} />
            <Link
              href={`/people/${review.target_type === "vendor" ? "vendors" : "riders"}/${review.target_id}`}
              className="text-sm font-medium hover:underline"
            >
              {review.target_name ?? "Unnamed"}
            </Link>
            <span className="text-xs text-muted">
              {review.target_type === "vendor" ? "store" : "rider"} · {timeAgo(review.created_at)}
            </span>
          </div>

          {review.comment ? (
            <p className="text-sm">{review.comment}</p>
          ) : (
            <p className="text-sm text-muted">No comment — a rating only.</p>
          )}

          <div className="flex flex-wrap items-center gap-1">
            {review.flags.map((flag) => (
              <Badge key={flag} tone={flag === "contact_details" ? "danger" : "warning"}>
                {FLAG_LABEL[flag] ?? flag}
              </Badge>
            ))}
            <Link
              href={`/operations/orders?q=${review.order_id}`}
              className="text-xs text-muted hover:underline"
            >
              the order
            </Link>
          </div>

          {review.hidden ? (
            <p className="flex items-center gap-1.5 text-xs text-muted">
              <EyeOff className="h-3.5 w-3.5" aria-hidden />
              Taken down {timeAgo(review.hidden_at)}
              {review.hidden_reason ? ` — ${review.hidden_reason}` : ""}
            </p>
          ) : null}
        </div>

        {mayModerate ? <ModerateButton id={review.id} hidden={review.hidden} /> : null}
      </div>
    </Card>
  );
}

/** Stars, plus the number as text — colour and shape are never the only carrier. */
function Stars({ rating }: { rating: number }) {
  const filled = Math.round(rating);
  return (
    <span className="flex items-center gap-1">
      <span aria-hidden className="flex">
        {[1, 2, 3, 4, 5].map((star) => (
          <Star
            key={star}
            className={
              star <= filled
                ? "h-3.5 w-3.5 fill-[var(--warning)] text-[var(--warning)]"
                : "h-3.5 w-3.5 text-muted"
            }
          />
        ))}
      </span>
      <span className="text-sm font-medium">{rating.toFixed(1)}</span>
      <span className="sr-only">out of 5</span>
    </span>
  );
}
