/**
 * Money arrives from the backend as a decimal *string*, never a number.
 *
 * `Order.platform_total` and friends are Postgres NUMERIC and Python `Decimal`.
 * Parsing them into a JS number to format them would reintroduce exactly the
 * float error the backend goes out of its way to avoid — so the integer and
 * fractional parts are formatted separately and the digits are never converted.
 */
export function formatMoney(value: string | null | undefined, currency = "KES"): string {
  if (value === null || value === undefined || value === "") return `${currency} 0.00`;

  const negative = value.trim().startsWith("-");
  const [whole = "0", fraction = "00"] = value.replace("-", "").split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}${currency} ${grouped}.${fraction.padEnd(2, "0").slice(0, 2)}`;
}

export function formatNumber(value: number | null | undefined): string {
  return (value ?? 0).toLocaleString("en-KE");
}

/** True when a decimal money string is zero, however it is written. */
export function isZeroMoney(value: string | null | undefined): boolean {
  return sumMoney([value]) === "0.00";
}

/**
 * A signed difference — `+41.00`, `-12.50`.
 *
 * The obvious version is `Number(delta).toFixed(2)`, and it is a float round
 * trip on money shown to a human, on the one screen whose entire job is to make
 * a pricing change safe to approve. The sign is read off the string; the digits
 * are never converted.
 */
export function formatMoneyDelta(value: string | null | undefined, currency = ""): string {
  const normalised = sumMoney([value]);
  const negative = normalised.startsWith("-");
  const magnitude = formatMoney(negative ? normalised.slice(1) : normalised, currency).trim();
  return `${negative ? "-" : "+"}${magnitude}`;
}

/**
 * Add decimal money strings without ever creating a float.
 *
 * `values.reduce((a, b) => a + Number(b), 0).toFixed(2)` is the obvious version
 * and it is wrong for exactly the reason the backend sends strings in the first
 * place — it reintroduces binary floating point into a figure that is then
 * shown to a human as a total.
 *
 * Everything is scaled to integer cents, summed with `BigInt`, and scaled back.
 */
export function sumMoney(values: (string | null | undefined)[]): string {
  let cents = 0n;

  for (const value of values) {
    if (!value) continue;
    const trimmed = value.trim();
    const negative = trimmed.startsWith("-");
    const [whole = "0", fraction = ""] = trimmed.replace("-", "").split(".");
    // Two decimal places, padded or truncated — the backend quantizes to this.
    const scaled = BigInt(`${whole || "0"}${fraction.padEnd(2, "0").slice(0, 2)}`);
    cents += negative ? -scaled : scaled;
  }

  const negative = cents < 0n;
  const absolute = (negative ? -cents : cents).toString().padStart(3, "0");
  return `${negative ? "-" : ""}${absolute.slice(0, -2)}.${absolute.slice(-2)}`;
}

/** "3 days ago" — a queue is read by age, not by timestamp. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";

  const seconds = Math.floor((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";

  const units: [number, Intl.RelativeTimeFormatUnit][] = [
    [60, "minute"], [3600, "hour"], [86400, "day"], [604800, "week"],
    [2629800, "month"], [31557600, "year"],
  ];

  let previous = 1;
  const formatter = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
  for (const [threshold, unit] of units) {
    if (seconds < threshold) return formatter.format(-Math.floor(seconds / previous), unit);
    previous = threshold;
  }
  return formatter.format(-Math.floor(seconds / 31557600), "year");
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString("en-KE", {
    year: "numeric", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}
