/**
 * One phone number, one set of rules.
 *
 * Three screens each carried their own copy of
 * `/^(\+254|0)[17]\d{8}$|^\+?[1-9]\d{1,14}$/`, whose second alternative accepts
 * any 2-to-15 digit string — so "12" passed as a valid M-Pesa number on the
 * screen that chooses which line gets billed. `Cart.tsx` then declared its own
 * `normalisePhone` inline, which is the same second-declaration defect one layer
 * down: the number a customer saves and the number the STK push is sent to have
 * to be the same number.
 *
 * Kenyan mobiles are `07XXXXXXXX` / `01XXXXXXXX` nationally, `+2547…` /
 * `+2541…` internationally. Nothing else can receive an M-Pesa prompt, so
 * nothing else is a valid answer here.
 */

/** National significant number — nine digits, no country code, no leading zero. */
export function normalisePhone(raw?: string | null): string | null {
    if (!raw) return null;
    let cleaned = raw.replace(/[^0-9]/g, "");
    if (cleaned.startsWith("254")) cleaned = cleaned.substring(3);
    if (cleaned.startsWith("0")) cleaned = cleaned.substring(1);
    return cleaned;
}

/** A well-formed Kenyan mobile number, on any network. */
export function isValidKenyanMobile(raw?: string | null): boolean {
    const national = normalisePhone(raw);
    return !!national && /^[17]\d{8}$/.test(national);
}

/**
 * National prefixes allocated to Safaricom, as inclusive ranges over the first
 * three digits of the nine-digit national number.
 *
 * Airtel (730-739, 750-756, 762, 780-789, 100-106) and Telkom (770-779) are
 * deliberately absent. Mirrors `BackendAPI/utils/phone.py`, which is the rule;
 * this copy exists so the person typing is told before they submit.
 */
const SAFARICOM_PREFIX_RANGES: ReadonlyArray<readonly [number, number]> = [
    [110, 115],
    [700, 729],
    [740, 743],
    [745, 746],
    [748, 748],
    [757, 759],
    [768, 769],
    [790, 799],
];

/**
 * True only for a Safaricom line.
 *
 * M-Pesa is Safaricom's. An STK push to an Airtel or Telkom number never
 * arrives, so saving one is not a payment method — it is a failure deferred to
 * the moment the customer is trying to pay.
 */
export function isSafaricomNumber(raw?: string | null): boolean {
    const national = normalisePhone(raw);
    if (!national || !/^[17]\d{8}$/.test(national)) return false;
    const prefix = Number(national.slice(0, 3));
    return SAFARICOM_PREFIX_RANGES.some(([low, high]) => prefix >= low && prefix <= high);
}

/**
 * How many M-Pesa numbers a customer may keep.
 *
 * Enforced here for the person typing and in `routes/auth_routes.py` as the
 * actual rule — `payment_methods` is a JSONB column that used to be written
 * straight from the request body.
 */
export const MAX_PAYMENT_METHODS = 2;

/** The canonical stored form, matching the backend's `sanitize_phone_number`. */
export function toE164(raw?: string | null): string | null {
    const national = normalisePhone(raw);
    return national ? `+254${national}` : null;
}

/** `+254 712 345 678` — grouped so a customer can check it digit by digit. */
export function formatPhone(raw?: string | null): string {
    const national = normalisePhone(raw);
    if (!national || national.length !== 9) return raw ?? "";
    return `+254 ${national.slice(0, 3)} ${national.slice(3, 6)} ${national.slice(6)}`;
}
