/**
 * The GSM delivery fallback fails closed.
 *
 * `EXPO_PUBLIC_SMS_GATEWAY_NUMBER` has never been set — not in any of the three
 * `.env` files, not on EAS — and the call site read
 * `process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER || "+254700000000"`. So a rider
 * with no signal texted a number this platform does not own, watched it send,
 * and believed the delivery was recorded. It was not: the order stayed open,
 * the vendor was never credited, and the rider's cash float stayed committed
 * against a delivery they had already made.
 *
 * Nothing would have caught it. The button worked, the SMS app opened, the
 * message left the handset. Only the far end was missing.
 */
import { smsCompletionUrl, smsGatewayNumber } from "../smsFallback";

const ORDER = "a1b2c3d4-0000-4000-8000-000000000001";

function withGateway<T>(value: string | undefined, fn: () => T): T {
  const previous = process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER;
  if (value === undefined) delete process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER;
  else process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER = value;
  try {
    return fn();
  } finally {
    if (previous === undefined) delete process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER;
    else process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER = previous;
  }
}

describe("smsGatewayNumber", () => {
  it("is null when nothing is configured", () => {
    expect(withGateway(undefined, smsGatewayNumber)).toBeNull();
  });

  it("is null for an empty or whitespace value", () => {
    expect(withGateway("", smsGatewayNumber)).toBeNull();
    expect(withGateway("   ", smsGatewayNumber)).toBeNull();
  });

  it("rejects the placeholder that caused this", () => {
    // The exact literal, and the shapes an unedited `.env.example` produces.
    // A placeholder is not a configuration: it would restore the original
    // defect while looking configured, which is harder to spot than the
    // hardcoded version was.
    for (const placeholder of [
      "+254700000000",
      "254700000000",
      "+254 700 000 000",
      "+254-700-000-000",
    ]) {
      expect(withGateway(placeholder, smsGatewayNumber)).toBeNull();
    }
  });

  it("returns a real configured number", () => {
    expect(withGateway("+254711223344", smsGatewayNumber)).toBe("+254711223344");
  });

  it("trims surrounding whitespace from a pasted value", () => {
    expect(withGateway("  20880  ", smsGatewayNumber)).toBe("20880");
  });

  it("accepts a shortcode, not just a long number", () => {
    // Africa's Talking issues shortcodes; the rider texts that, not an MSISDN.
    expect(withGateway("20880", smsGatewayNumber)).toBe("20880");
  });
});

describe("smsCompletionUrl", () => {
  it("is null when no gateway is configured, so no button renders", () => {
    expect(withGateway(undefined, () => smsCompletionUrl(ORDER))).toBeNull();
  });

  it("builds the exact body the webhook parses", () => {
    // `sms_routes.process_sms_webhook` upper-cases the body, requires it to
    // start with DELIVERED, splits on whitespace and matches part[1] against
    // the order id prefix. Both sides of that contract are asserted here
    // because a change to either alone is silent.
    const url = withGateway("20880", () => smsCompletionUrl(ORDER));

    expect(url).toBe("sms:20880?body=DELIVERED a1b2c3d4");
    expect(url!.split("body=")[1].split(" ")[0]).toBe("DELIVERED");
    expect(url!.split("body=")[1].split(" ")[1]).toHaveLength(8);
  });

  it("is null for a missing order id rather than texting a bare command", () => {
    // `DELIVERED` with no id reaches the webhook as "invalid format" — a
    // message that costs the rider an SMS and completes nothing.
    expect(withGateway("20880", () => smsCompletionUrl(undefined))).toBeNull();
    expect(withGateway("20880", () => smsCompletionUrl(""))).toBeNull();
  });
});
