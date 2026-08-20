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

/**
 * True for a number that can actually receive an M-Pesa prompt.
 *
 * Deliberately strict. This is not a contact field: a number that cannot be
 * pushed to is not a payment method, and accepting one means the customer finds
 * out at checkout rather than here.
 */
export function isValidKenyanMobile(raw?: string | null): boolean {
    const national = normalisePhone(raw);
    return !!national && /^[17]\d{8}$/.test(national);
}

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
