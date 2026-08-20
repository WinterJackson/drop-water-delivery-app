import { normalisePhone, isValidKenyanMobile, toE164, formatPhone } from "../phone";

describe("normalisePhone", () => {
    it("reduces every way of writing one number to the same nine digits", () => {
        for (const written of [
            "0712345678",
            "+254712345678",
            "254712345678",
            "254 712 345 678",
            "+254-712-345-678",
            "0712 345 678",
        ]) {
            expect(normalisePhone(written)).toBe("712345678");
        }
    });

    it("returns null for nothing rather than an empty string", () => {
        expect(normalisePhone(null)).toBeNull();
        expect(normalisePhone(undefined)).toBeNull();
        expect(normalisePhone("")).toBeNull();
    });
});

describe("isValidKenyanMobile", () => {
    it("accepts Safaricom and Airtel lines in any format", () => {
        for (const ok of ["0712345678", "+254712345678", "0112345678", "254701234567"]) {
            expect(isValidKenyanMobile(ok)).toBe(true);
        }
    });

    it("rejects what the old regex let through", () => {
        // `^\+?[1-9]\d{1,14}$` was the second alternative of the regex three
        // screens shared, and it accepts any 2-to-15 digit string. "12" saved
        // cleanly as an M-Pesa number on the screen that decides what gets
        // billed, and the failure only surfaced at checkout.
        for (const bad of ["12", "1", "123456", "99999999999999"]) {
            expect(isValidKenyanMobile(bad)).toBe(false);
        }
    });

    it("rejects a landline or short code, which cannot take an M-Pesa prompt", () => {
        expect(isValidKenyanMobile("0202345678")).toBe(false); // Nairobi landline
        expect(isValidKenyanMobile("0812345678")).toBe(false); // not a mobile prefix
    });

    it("rejects the right length with the wrong prefix, and vice versa", () => {
        expect(isValidKenyanMobile("071234567")).toBe(false); // one digit short
        expect(isValidKenyanMobile("07123456789")).toBe(false); // one digit long
    });

    it("is false for nothing", () => {
        expect(isValidKenyanMobile(null)).toBe(false);
        expect(isValidKenyanMobile("")).toBe(false);
    });
});

describe("toE164", () => {
    it("stores one canonical form whatever was typed", () => {
        expect(toE164("0712345678")).toBe("+254712345678");
        expect(toE164("254712345678")).toBe("+254712345678");
        expect(toE164("+254 712 345 678")).toBe("+254712345678");
    });

    it("round-trips through normalisePhone, so a stored number matches a typed one", () => {
        expect(normalisePhone(toE164("0712345678"))).toBe(normalisePhone("+254712345678"));
    });
});

describe("formatPhone", () => {
    it("groups the digits so a customer can check them", () => {
        expect(formatPhone("0712345678")).toBe("+254 712 345 678");
        expect(formatPhone("+254712345678")).toBe("+254 712 345 678");
    });

    it("shows an unexpected value back rather than mangling it", () => {
        expect(formatPhone("12")).toBe("12");
        expect(formatPhone(null)).toBe("");
    });
});
