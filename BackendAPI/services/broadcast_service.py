"""Messaging a whole segment of the platform at once.

This is the most dangerous feature in the admin console. Every other action
affects one account; this one reaches everybody, and it cannot be recalled. The
design reflects that:

**Preferences are honoured, always.** A campaign is `transactional=False` by
default, which routes it through `notification_service.push_allowed` exactly as
a promotion from any other part of the system would. Someone who muted
promotions stays muted. Marking a campaign transactional bypasses that and is
therefore a claim the sender is making — the console says so in those words, and
the audit row records which was chosen.

**The in-app row is always written; the push and the email are best-effort.**
Same rule as the rest of the platform: the `Notification` row is the history and
survives, the interruption is subject to preference and to a device having a
token.

**It runs in ARQ, in batches, and records progress.** Sending 10,000 emails
inside a request would time out at around 30 and leave nobody able to say how
far it got. `sent_count` and `failed_count` on the campaign row are updated as
it goes, so a run that dies leaves evidence.

**There is no "everyone" audience.** The segments are deliberately concrete —
customers, riders, vendors, each optionally narrowed — because "everyone"
invites sending a rider-shift notice to customers.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable, Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.deliverer_model import Deliverer, KYCStatus
from models.platform_setting_model import BroadcastCampaign
from models.user_model import User
from models.vendor_model import Vendor
from services import email_service
from services.notification_service import create_notification, push_allowed
from services.expo_push_service import send_push_message

logger = logging.getLogger(__name__)

#: Rows fetched and sent per batch. Small enough that a failure loses little,
#: large enough that a big campaign does not take all day.
BATCH_SIZE = 200

#: A campaign's in-app message type. Chosen so `push_allowed` maps it to the
#: recipient's "promotions" preference — the correct default for a broadcast.
PROMOTIONAL_TYPE = "promotion"

#: Used only when a campaign is explicitly marked transactional, which routes it
#: past the preference check.
TRANSACTIONAL_TYPE = "account_status"


AUDIENCES: dict[str, str] = {
    "customers": "Everyone who has a customer account",
    "customers_active": "Customers who have placed a paid order",
    "customers_dormant": "Customers who have never ordered",
    "riders": "Every registered rider",
    "riders_approved": "Riders who have passed KYC",
    "riders_pending_kyc": "Riders still waiting for verification",
    "vendors": "Every store",
    "vendors_verified": "Verified stores only",
    "vendors_unverified": "Stores that have not been verified",
}

USER_TYPE_OF = {
    "customers": "customer",
    "customers_active": "customer",
    "customers_dormant": "customer",
    "riders": "rider",
    "riders_approved": "rider",
    "riders_pending_kyc": "rider",
    "vendors": "vendor",
    "vendors_verified": "vendor",
    "vendors_unverified": "vendor",
}


AUDIENCE_MODEL = {"customers": User, "riders": Deliverer, "vendors": Vendor}


def _audience_model(audience: str):
    for prefix, model in AUDIENCE_MODEL.items():
        if audience.startswith(prefix):
            return model
    raise ValueError(f"Unknown audience: {audience}")


def _audience_query(audience: str):
    """The select for one segment.

    Suspended accounts are excluded from every segment. Someone who has been
    suspended should not receive a marketing message from the platform that
    suspended them, and the one time you *do* want to reach them is a
    one-to-one message, not a broadcast.
    """
    if audience.startswith("customers"):
        query = select(User).where(User.suspended_at.is_(None))
        if audience == "customers_active":
            query = query.where(User.last_order_date.isnot(None))
        elif audience == "customers_dormant":
            query = query.where(User.last_order_date.is_(None))
        return query

    if audience.startswith("riders"):
        query = select(Deliverer).where(Deliverer.suspended_at.is_(None))
        if audience == "riders_approved":
            query = query.where(Deliverer.kyc_status == KYCStatus.approved)
        elif audience == "riders_pending_kyc":
            query = query.where(Deliverer.kyc_status == KYCStatus.pending)
        return query

    if audience.startswith("vendors"):
        query = select(Vendor).where(Vendor.suspended_at.is_(None), Vendor.is_active.is_(True))
        if audience == "vendors_verified":
            query = query.where(Vendor.verification_status == "verified")
        elif audience == "vendors_unverified":
            query = query.where(Vendor.verification_status != "verified")
        return query

    raise ValueError(f"Unknown audience: {audience}")


async def estimate_recipients(session: AsyncSession, audience: str) -> int:
    """How many people this would actually reach.

    Shown before sending, and it is the single most useful guardrail on the
    screen: "this will message 4,812 people" stops a mistake that "send" does
    not.
    """
    query = _audience_query(audience)
    subquery = query.subquery()
    return int(
        (await session.execute(select(func.count()).select_from(subquery))).scalar() or 0
    )


async def create_campaign(
    session: AsyncSession,
    *,
    channel: str,
    audience: str,
    subject: str,
    body: str,
    transactional: bool,
    created_by_email: str,
) -> BroadcastCampaign:
    """Record the campaign before sending a single message.

    Written first on purpose: a send that crashes halfway must still leave a row
    saying what was attempted and how far it got. Creating the record afterwards
    would mean the failures that matter most are the ones with no evidence.
    """
    if audience not in AUDIENCES:
        raise ValueError(f"Unknown audience: {audience}")
    if channel not in ("in_app", "email", "both"):
        raise ValueError("Channel must be in_app, email or both.")

    campaign = BroadcastCampaign(
        channel=channel,
        audience=audience,
        subject=subject.strip()[:200],
        body=body.strip(),
        transactional=transactional,
        created_by_email=created_by_email,
        recipient_count=await estimate_recipients(session, audience),
        status="queued",
    )
    session.add(campaign)
    return campaign


def _email_of(account) -> Optional[str]:
    value = getattr(account, "email", None)
    return value if value and "@" in value else None


def _name_of(account) -> str:
    for attribute in ("full_name", "business_name", "name"):
        value = getattr(account, attribute, None)
        if value:
            return value
    return "there"


async def run_campaign(session: AsyncSession, campaign_id: UUID) -> dict:
    """Send it. Called from the ARQ worker, never from a request.

    Commits per batch rather than once at the end: a campaign that fails on
    batch 40 of 50 keeps the 39 batches of notification rows it already wrote,
    and the counters on the row say exactly that.
    """
    campaign = await session.get(BroadcastCampaign, campaign_id)
    if campaign is None:
        return {"error": "campaign not found"}
    if campaign.status not in ("queued", "sending"):
        return {"skipped": f"campaign already {campaign.status}"}

    campaign.status = "sending"
    await session.commit()

    user_type = USER_TYPE_OF[campaign.audience]
    message_type = TRANSACTIONAL_TYPE if campaign.transactional else PROMOTIONAL_TYPE

    model = _audience_model(campaign.audience)
    sent = 0
    failed = 0
    #: Keyset, not OFFSET. The loop commits between batches, and an OFFSET with
    #: no total ordering is free to return rows in a different order on the next
    #: query — which on a campaign means somebody is messaged twice and somebody
    #: else never hears from us at all. Ordering by the primary key and walking
    #: past it makes each account appear exactly once.
    after_id = None

    try:
        while True:
            query = _audience_query(campaign.audience).order_by(model.id).limit(BATCH_SIZE)
            if after_id is not None:
                query = query.where(model.id > after_id)

            batch = (await session.execute(query)).scalars().all()
            if not batch:
                break
            after_id = batch[-1].id

            pushes: list[tuple[str, str, str]] = []

            for account in batch:
                try:
                    # Always written. The in-app history is what survives a muted
                    # push or a bounced email.
                    await create_notification(
                        session=session,
                        user_id=account.id,
                        user_type=user_type,
                        title=campaign.subject,
                        message=campaign.body,
                        message_type=message_type,
                        delivered_via=campaign.channel,
                    )

                    if campaign.channel in ("in_app", "both"):
                        token = getattr(account, "push_token", None)
                        if token and push_allowed(account, message_type):
                            pushes.append((token, campaign.subject, campaign.body))

                    if campaign.channel in ("email", "both"):
                        address = _email_of(account)
                        if address:
                            email_service.send_broadcast_email(
                                to=address,
                                name=_name_of(account),
                                subject=campaign.subject,
                                body=campaign.body,
                            )

                    sent += 1
                except Exception:
                    logger.exception(
                        "Broadcast %s failed for %s", campaign.id, getattr(account, "id", "?")
                    )
                    failed += 1

            campaign.sent_count = sent
            campaign.failed_count = failed
            await session.commit()

            # After the commit, so a rollback cannot leave people notified about
            # something that did not happen — the same rule the rest of the
            # platform follows.
            for token, title, message in pushes:
                try:
                    await send_push_message(token, title, message, {"type": "broadcast"})
                except Exception:
                    logger.warning("Broadcast push failed", exc_info=True)

            # Yield between batches: this is a worker, but it shares an event
            # loop with every other job on it.
            await asyncio.sleep(0)

        campaign.status = "sent"
        campaign.completed_at = datetime.now(timezone.utc)
        await session.commit()

    except Exception as exc:
        logger.exception("Broadcast %s failed", campaign.id)
        campaign.status = "failed"
        campaign.error = str(exc)[:2000]
        campaign.completed_at = datetime.now(timezone.utc)
        await session.commit()
        return {"campaign": str(campaign.id), "status": "failed", "sent": sent, "failed": failed}

    return {"campaign": str(campaign.id), "status": "sent", "sent": sent, "failed": failed}


async def list_campaigns(session: AsyncSession, limit: int = 50) -> dict:
    rows = (
        await session.execute(
            select(BroadcastCampaign)
            .order_by(BroadcastCampaign.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(row.id),
                "channel": row.channel,
                "audience": row.audience,
                "audience_label": AUDIENCES.get(row.audience, row.audience),
                "subject": row.subject,
                "body": row.body,
                "status": row.status,
                "transactional": bool(row.transactional),
                "recipient_count": row.recipient_count,
                "sent_count": row.sent_count,
                "failed_count": row.failed_count,
                "error": row.error,
                "created_by": row.created_by_email,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
            }
            for row in rows
        ]
    }
