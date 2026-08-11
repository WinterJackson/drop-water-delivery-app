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
    """Fire-and-forget welcome email sent during registration.

    The body comes from `email_templates`, like every other email this platform
    sends. These four functions used to inline their own HTML while a complete,
    better-built set of templates sat unused beside them — two implementations
    of one thing, and the one in use was the one that never escaped the name.
    """
    subjects = {
        "customer": "Welcome to Drop! 💧",
        "vendor": "Welcome to Drop Vendor Portal! 🏪",
        "rider": "Welcome to Drop Rider Network! 🛵",
    }
    builders = {
        "customer": email_templates.welcome_customer,
        "rider": email_templates.welcome_rider,
    }
    if app_type == "vendor":
        # The vendor template names the business as well as the owner; the
        # caller has only the owner's name here, so it stands for both.
        html = email_templates.welcome_vendor(name, name)
    else:
        html = builders.get(app_type, email_templates.welcome_customer)(name)

    _send(to, subjects.get(app_type, "Welcome to Drop!"), html)


def send_vendor_approved(to: str, name: str) -> None:
    """Sent to a vendor after their account is approved during onboarding."""
    _send(
        to,
        "Your Drop Vendor Account is Approved ✅",
        email_templates.vendor_approved(name),
    )


def send_rider_approved(to: str, name: str) -> None:
    """Sent to a rider after a vendor approves them for dedicated employment."""
    _send(
        to,
        "You've Been Approved as a Drop Rider! 🛵",
        email_templates.rider_approved(name),
    )


def send_order_confirmation(to: str, name: str, order_details: dict) -> None:
    """Sent to a customer after successful M-Pesa payment confirmation.

    `total_amount` is rendered exactly as the caller passes it — a decimal
    string off the order. Formatting it here would be a second opinion about a
    figure the customer has already been charged.
    """
    order_id = order_details.get("id", "N/A")
    _send(
        to,
        f"Order #{order_id} Confirmed — Drop 💧",
        email_templates.order_confirmation(
            name,
            {
                "id": order_id,
                "total_amount": order_details.get(
                    "total_amount", order_details.get("total", "0.00")
                ),
            },
        ),
    )


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
