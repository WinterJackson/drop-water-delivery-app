/**
 * How a rating is rendered, in one place, for the same reason `money.ts` exists.
 *
 * Five screens each answered "what do I show when there is no rating?"
 * differently, and four of them answered it by inventing a number: the
 * directory rendered `Number(rating).toFixed(1)` (`0.0`), the storefront
 * `Number(rating) || "4.8"`, search `rating?.toFixed(1) || "5.0"` and
 * favourites `rating || "4.5"`. The same shop, at the same moment, showed
 * `0.0` in the directory and `4.8` on its own page — and a customer choosing
 * where to buy water read the higher one as earned.
 *
 * A rating is a trust signal. A fabricated one is not a cosmetic defect, and
 * it is worse than showing nothing: `|| "4.8"` also swallows a *real* score of
 * zero, because `0` is falsy, so the worst-rated store on the platform
 * advertised 4.8.
 *
 * The count is what makes the answer knowable at all. `Vendor.rating` defaults
 * to `0` and `Deliverer.rating` defaults to **5.0**, so the average alone
 * cannot distinguish "nobody has rated this" from a real score at either end.
 * `rating_count` now travels with it.
 */

/** Shown in place of a score for something nobody has rated yet. */
export const UNRATED_LABEL = "New";

/**
 * The score to display, or `null` when there is nothing honest to show.
 *
 * `null` covers both "no ratings yet" and "this response did not carry a
 * rating". Callers render {@link UNRATED_LABEL} for the first; the second is
 * indistinguishable to the app, and guessing is the defect this replaces.
 */
export function ratingScore(
  rating: number | string | null | undefined,
  count?: number | null,
): string | null {
  // A count of zero is a *fact*: nobody has rated this. Undefined is not — it
  // means this endpoint does not send the count, and the rating below is then
  // the only thing to go on.
  if (count !== undefined && count !== null && count <= 0) return null;

  if (rating === null || rating === undefined || rating === "") return null;
  const value = Number(rating);
  // `Number(undefined)` is NaN, and `NaN.toFixed(1)` is the string "NaN" —
  // which one screen would have rendered to a customer.
  if (!Number.isFinite(value)) return null;
  return value.toFixed(1);
}

/**
 * The whole label, star included: `"⭐ 4.8"` or `"New"`.
 *
 * Most call sites want exactly this, and going through it keeps the star and
 * the fallback from drifting apart the way the numbers did.
 */
export function ratingLabel(
  rating: number | string | null | undefined,
  count?: number | null,
): string {
  const score = ratingScore(rating, count);
  return score === null ? UNRATED_LABEL : `⭐ ${score}`;
}

/**
 * How many filled stars to draw, clamped to the 0–5 range a five-star row has.
 *
 * `Array.from({ length: Math.round(rating) })` on a null rating crashed the
 * map's vendor card outright, and on a rating above 5 it silently drew a sixth
 * star.
 */
export function filledStars(
  rating: number | string | null | undefined,
  count?: number | null,
): number {
  const score = ratingScore(rating, count);
  if (score === null) return 0;
  return Math.min(5, Math.max(0, Math.round(Number(score))));
}
