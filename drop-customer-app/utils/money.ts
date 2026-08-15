/**
 * Money arrives from the backend as a decimal *string*, never a number.
 *
 * The columns behind these figures are Postgres `NUMERIC` and Python `Decimal`,
 * and `utils/money.py` serialises them as strings for exactly one reason:
 * parsing them into a JS number to add or format them reintroduces the binary
 * floating-point error the backend goes out of its way to avoid. `0.1 + 0.2` is
 * not `0.3` in this runtime either.
 *
 * So: the digits are never converted. `formatMoney` splits the string and
 * groups it; `sumMoney` scales to integer cents and adds with `BigInt`;
 * `compareMoney` compares in cents. This mirrors `lib/utils/format.ts` on the
 * admin console — one convention across four surfaces.
 */

/** Scale a decimal money string to integer cents. Malformed input is `0n`. */
function toCents(value: string | number | null | undefined): bigint {
  if (value === null || value === undefined || value === "") return 0n;

  const trimmed = String(value).trim();
  if (!/^-?\d*(\.\d*)?$/.test(trimmed)) return 0n;

  const negative = trimmed.startsWith("-");
  const [whole = "0", fraction = ""] = trimmed.replace("-", "").split(".");
  // Two decimal places, padded or truncated — the backend quantizes to this.
  const scaled = BigInt(`${whole || "0"}${fraction.padEnd(2, "0").slice(0, 2)}`);
  return negative ? -scaled : scaled;
}

/** Integer cents back to a canonical decimal string. */
function fromCents(cents: bigint): string {
  const negative = cents < 0n;
  const absolute = (negative ? -cents : cents).toString().padStart(3, "0");
  return `${negative ? "-" : ""}${absolute.slice(0, -2)}.${absolute.slice(-2)}`;
}

/**
 * `"1234.5"` → `"KSH 1,234.50"`.
 *
 * Pass `currency: ""` for a bare figure when the label already says KSH.
 */
export function formatMoney(
  value: string | number | null | undefined,
  currency = "KSH",
): string {
  const normalised = fromCents(toCents(value));
  const negative = normalised.startsWith("-");
  const [whole = "0", fraction = "00"] = normalised.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const prefix = currency ? `${currency} ` : "";
  return `${negative ? "-" : ""}${prefix}${grouped}.${fraction}`;
}

/**
 * `"1234.50"` → `"KSH 1,235"`.
 *
 * For headline balances and chips, where two decimal places are noise. Rounds
 * half-up on the cents, so nothing is silently shown as less than it is.
 */
export function formatMoneyShort(
  value: string | number | null | undefined,
  currency = "KSH",
): string {
  const cents = toCents(value);
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  const shillings = (absolute + 50n) / 100n;
  const grouped = shillings.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const prefix = currency ? `${currency} ` : "";
  return `${negative ? "-" : ""}${prefix}${grouped}`;
}

/**
 * `value × count`, where `count` is a whole number of units.
 *
 * A line total: quantity is an integer, so this stays exact in cents. There is
 * deliberately no `multiply` by a fraction and no `divide` — a percentage of
 * money is a decision the server makes, not a figure a screen derives.
 */
export function multiplyMoney(
  value: string | number | null | undefined,
  count: number,
): string {
  if (!Number.isInteger(count)) return fromCents(0n);
  return fromCents(toCents(value) * BigInt(count));
}

/** Add decimal money strings without ever creating a float. */
export function sumMoney(values: (string | number | null | undefined)[]): string {
  return fromCents(values.reduce<bigint>((total, v) => total + toCents(v), 0n));
}

/** `a - b`, as a decimal string. */
export function subtractMoney(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): string {
  return fromCents(toCents(a) - toCents(b));
}

/** `-1 | 0 | 1`, comparing in cents. Never `Number(a) > Number(b)`. */
export function compareMoney(
  a: string | number | null | undefined,
  b: string | number | null | undefined,
): -1 | 0 | 1 {
  const left = toCents(a);
  const right = toCents(b);
  return left < right ? -1 : left > right ? 1 : 0;
}

/** True when the value is zero, however it is written. */
export function isZeroMoney(value: string | number | null | undefined): boolean {
  return toCents(value) === 0n;
}

/** True when the value is below zero — an account in arrears. */
export function isNegativeMoney(value: string | number | null | undefined): boolean {
  return toCents(value) < 0n;
}

/**
 * A ratio between two money values, as a plain number in `0..1`.
 *
 * The **only** sanctioned way money becomes a number: a progress bar's width or
 * a "you are near the cap" threshold, where the output is a pixel count and not
 * a figure anybody reads. Never use this to display, compare or total money.
 */
export function moneyRatio(
  part: string | number | null | undefined,
  whole: string | number | null | undefined,
): number {
  const denominator = toCents(whole);
  if (denominator === 0n) return 0;
  return Number(toCents(part)) / Number(denominator);
}

/**
 * What a product actually costs: `price − discount`, as a decimal string.
 *
 * Six screens wrote this inline as `Math.round((price - discount) * 100) / 100`
 * on two fields the server sends as decimal strings — a float subtraction and
 * then the round-trip through `* 100` that the whole of this module exists to
 * avoid. It also hand-prefixed `KSH ` rather than going through `formatMoney`,
 * so the same figure was grouped on some screens and not on others.
 *
 * Clamped at zero: a discount larger than the price is a data fault, and
 * "KSH -20.00" on a shelf label is the worst possible way to surface it.
 */
export function discountedPrice(
  price: string | number | null | undefined,
  discount: string | number | null | undefined,
): string {
  const net = toCents(price) - toCents(discount);
  return fromCents(net > 0n ? net : 0n);
}

/**
 * The discount as a whole percentage, for the badge on a product card.
 *
 * A percentage is not money — it is a label — so this returns a number, and it
 * rounds *down* so a 49.6% saving is never advertised as 50%.
 */
export function discountPercent(
  price: string | number | null | undefined,
  discount: string | number | null | undefined,
): number {
  const whole = toCents(price);
  if (whole <= 0n) return 0;
  const part = toCents(discount);
  if (part <= 0n) return 0;
  return Number((part * 100n) / whole);
}
