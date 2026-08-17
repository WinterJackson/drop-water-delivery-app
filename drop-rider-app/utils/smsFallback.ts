/**
 * The GSM fallback for completing a delivery without data.
 *
 * A rider at a customer's gate with no signal taps "No Data? SMS to Complete",
 * and the handset sends `DELIVERED <order-prefix>` over GSM to a number an SMS
 * provider owns. That provider forwards it to `POST /api/sms/webhook`, which
 * matches the sender against a rider and completes the order — crediting the
 * vendor, settling the rider's cash float and closing the customer's delivery.
 *
 * The number therefore has to belong to a service that is listening. It was
 * written as:
 *
 *     process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER || "+254700000000"
 *
 * and the variable has never been set in any of the three `.env` files or on
 * EAS. So every rider who used that button texted `+254700000000` — a number
 * this platform does not own and which may well belong to a real person. They
 * watched the message send, believed the delivery was recorded, and it was not:
 * the order stayed open, the vendor was never credited, and their float stayed
 * locked against a delivery they had already made.
 *
 * That is the failure this codebase refuses everywhere else — a control that
 * reaches the user but not the platform, where the person operating it believes
 * it worked. Money, KYC and storage all fail closed here; so does this.
 *
 * `smsGatewayNumber()` returns `null` when unconfigured and the screen renders
 * no button at all, rather than one that exists to send a text into the void.
 * The feature is then honestly absent instead of quietly broken.
 *
 * Turning it on is one variable in the three `.env` files and in the EAS
 * production environment — plus `SMS_WEBHOOK_SECRET` on the backend, which
 * fails closed the same way and must match the provider's webhook header. Both
 * halves are required: a correct number against an unconfigured backend gets a
 * 503 from the webhook, which is equally invisible to the rider.
 */

/** The digits an SMS provider is listening on, or `null` if none is configured. */
export function smsGatewayNumber(): string | null {
  const raw = (process.env.EXPO_PUBLIC_SMS_GATEWAY_NUMBER ?? "").trim();
  if (!raw) return null;

  // A placeholder is not a configuration. `+254700000000` is the literal this
  // module replaced, and an unedited `.env.example` is the obvious way for it
  // to come back — at which point the defect returns wearing a variable's
  // clothes, which is harder to see than the original.
  if (/^\+?2547000000000?$/.test(raw.replace(/[\s-]/g, ""))) return null;

  return raw;
}

/**
 * The `sms:` URL for one order, or `null` when the fallback is unavailable.
 *
 * The body is the exact wire format `sms_routes.process_sms_webhook` parses:
 * `DELIVERED` followed by the first eight characters of the order id, which is
 * what it matches against `Orders.id`. Changing either side alone silently
 * stops deliveries being recorded, so the format lives here rather than being
 * assembled inline at the call site.
 */
export function smsCompletionUrl(orderId: string | undefined | null): string | null {
  const gateway = smsGatewayNumber();
  if (!gateway) return null;

  const prefix = (orderId ?? "").substring(0, 8);
  if (!prefix) return null;

  return `sms:${gateway}?body=DELIVERED ${prefix}`;
}
