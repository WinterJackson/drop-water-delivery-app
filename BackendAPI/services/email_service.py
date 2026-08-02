"""
Drop Email Service — Resend-backed transactional emails.

Sends welcome and approval emails. Gracefully degrades to logging
if the Resend API key is missing or invalid (e.g. local dev / MVP).
"""
import os
import logging

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "Drop <onboarding@resend.dev>")

_resend_available = False
try:
    import resend
    if RESEND_API_KEY and "PLACEHOLDER" not in RESEND_API_KEY:
        resend.api_key = RESEND_API_KEY
        _resend_available = True
    else:
        logger.warning("RESEND_API_KEY is missing or placeholder — emails will be logged only.")
except ImportError:
    logger.warning("resend package not installed — emails will be logged only. Run: pip install resend")


from tenacity import retry, stop_after_attempt, wait_exponential

from services import email_templates

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=False
)
def _send(to: str, subject: str, html: str) -> None:
    """Internal helper: send via Resend or fall back to logging."""
    if _resend_available:
        try:
            resend.Emails.send({
                "from": EMAIL_FROM,
                "to": [to],
                "subject": subject,
                "html": html,
            })
            logger.info(f"Email sent to {to}: {subject}")
        except Exception as e:
            logger.error(f"Resend email failed for {to}: {e}", exc_info=True)
            raise e  # trigger tenacity retry
    else:
        logger.info(f"[EMAIL STUB] To: {to} | Subject: {subject}")


def send_welcome_email(to: str, name: str, app_type: str = "customer") -> None:
    """
    Fire-and-forget welcome email sent during user/vendor/rider registration.
    """
    role_labels = {
        "customer": "Welcome to Drop! 💧",
        "vendor": "Welcome to Drop Vendor Portal! 🏪",
        "rider": "Welcome to Drop Rider Network! 🛵",
    }
    subject = role_labels.get(app_type, "Welcome to Drop!")

    html = f"""
    <div style="font-family: 'Segoe UI', Helvetica, Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px; background: #f9fafb; border-radius: 12px;">
        <h1 style="color: #1e3a5f; margin-bottom: 8px;">Karibu, {name}! 🎉</h1>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            Your <strong>{app_type}</strong> account on <strong>Drop</strong> is all set.
            You can now enjoy fast, reliable water delivery across Kenya.
        </p>
        <p style="color: #6b7280; font-size: 14px; margin-top: 24px;">
            If you have any questions, just reply to this email — we're here to help.
        </p>
        <p style="color: #9ca3af; font-size: 12px; margin-top: 32px;">© Drop Water Delivery</p>
    </div>
    """
    _send(to, subject, html)


def send_vendor_approved(to: str, name: str) -> None:
    """
    Sent to a vendor after their account is auto-approved during onboarding.
    """
    subject = "Your Drop Vendor Account is Approved ✅"
    html = f"""
    <div style="font-family: 'Segoe UI', Helvetica, Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px; background: #f0fdf4; border-radius: 12px;">
        <h1 style="color: #166534;">You're Approved, {name}! 🎉</h1>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            Great news — your vendor store is now <strong>live</strong> on Drop.
            Customers in your area can start ordering from you immediately.
        </p>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            Open the <strong>Drop Vendor App</strong> to manage your products, track orders, and grow your business.
        </p>
        <p style="color: #9ca3af; font-size: 12px; margin-top: 32px;">© Drop Water Delivery</p>
    </div>
    """
    _send(to, subject, html)


def send_rider_approved(to: str, name: str) -> None:
    """
    Sent to a rider after a vendor approves them for dedicated employment.
    """
    subject = "You've Been Approved as a Drop Rider! 🛵"
    html = f"""
    <div style="font-family: 'Segoe UI', Helvetica, Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px; background: #eff6ff; border-radius: 12px;">
        <h1 style="color: #1e40af;">Congrats, {name}! 🎉</h1>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            You have been <strong>approved</strong> as an active rider on the Drop platform.
            You can now go online and start accepting delivery requests.
        </p>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            Open the <strong>Drop Rider App</strong>, toggle your availability to <strong>Online</strong>,
            and your first trip will appear on the Trip Radar shortly.
        </p>
        <p style="color: #9ca3af; font-size: 12px; margin-top: 32px;">© Drop Water Delivery</p>
    </div>
    """
    _send(to, subject, html)


def send_order_confirmation(to: str, name: str, order_details: dict) -> None:
    """
    Sent to a customer after successful M-Pesa payment confirmation.
    """
    order_id = order_details.get("id", "N/A")
    total = order_details.get("total", "0.00")
    date = order_details.get("date", "Today")

    subject = f"Order #{order_id} Confirmed — Drop 💧"
    html = f"""
    <div style="font-family: 'Segoe UI', Helvetica, Arial, sans-serif; max-width: 520px; margin: 0 auto; padding: 32px; background: #f0fdf4; border-radius: 12px;">
        <h1 style="color: #166534;">Order Confirmed! ✅</h1>
        <p style="color: #374151; font-size: 16px; line-height: 1.6;">
            Hi <strong>{name}</strong>, your order has been paid and is being prepared.
        </p>
        <table style="width: 100%; margin: 20px 0; border-collapse: collapse;">
            <tr style="border-bottom: 1px solid #d1d5db;">
                <td style="padding: 8px 0; color: #6b7280;">Order ID</td>
                <td style="padding: 8px 0; text-align: right; font-weight: bold; color: #111827;">#{order_id}</td>
            </tr>
            <tr style="border-bottom: 1px solid #d1d5db;">
                <td style="padding: 8px 0; color: #6b7280;">Date</td>
                <td style="padding: 8px 0; text-align: right; color: #111827;">{date}</td>
            </tr>
            <tr>
                <td style="padding: 8px 0; color: #6b7280;">Total Paid</td>
                <td style="padding: 8px 0; text-align: right; font-weight: bold; font-size: 18px; color: #166534;">KSH {total}</td>
            </tr>
        </table>
        <p style="color: #374151; font-size: 14px; line-height: 1.6;">
            You'll receive a notification once a rider picks up your order. Track it live in the Drop app.
        </p>
        <p style="color: #9ca3af; font-size: 12px; margin-top: 32px;">© Drop Water Delivery</p>
    </div>
    """
    _send(to, subject, html)


def send_broadcast_email(to: str, name: str, subject: str, body: str) -> None:
    """One message from an admin campaign.

    Fire-and-forget by design, like every other email here: `_send` retries the
    transport failures worth retrying and swallows the rest. The campaign's
    authoritative record is the `Notification` row that was already written, so
    an email that does not arrive loses the interruption, never the history.
    """
    html = email_templates.broadcast(name=name, subject=subject, body=body)
    _send(to, subject, html)


def send_support_reply_email(to: str, name: str, subject: str, body: str, ticket_id: str) -> None:
    """An administrator's reply to a support ticket.

    Best-effort in exactly the same way. The reply is already in the requester's
    in-app notifications before this is attempted, so a bounced address delays
    the conversation rather than losing it.
    """
    html = email_templates.support_reply(
        name=name, subject=subject, body=body, ticket_id=ticket_id
    )
    _send(to, f"Re: {subject}", html)
