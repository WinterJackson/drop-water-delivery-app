"""The business model, editable.

Everything here is gated on `settings.manage`, which no role holds except
`super_admin` — an operations manager can suspend a rider, and cannot change
what the platform charges.

Three things make this defensible rather than merely possible:

* **Bounds.** `platform_config_service` refuses a value outside its range with a
  sentence explaining why. This is a screen where typing `5` where `0.05` was
  meant would set a 500% commission.
* **A preview.** `/config/preview` prices a representative order under the
  proposed values *before* they are saved, so the effect is visible as money
  rather than as a rate.
* **A reason, and a history.** Every change writes a `Platform_Setting_History`
  row and an audit entry carrying the full before/after.
"""
import logging
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.admin_dependencies import AdminAccess, require_admin
from dependencies.dependencies import get_db
from models.admin_model import PERM_ANALYTICS_READ, PERM_SETTINGS_MANAGE
from models.platform_setting_model import PlatformSettingHistory
from services import admin_service
from services import platform_config_service as config

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/config", summary="Every configurable business value")
async def get_config(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SETTINGS_MANAGE)),
):
    """The registry, with current values, bounds and whether each is still the
    shipped default.

    `is_default` matters more than it looks: an owner opening this screen for the
    first time needs to tell "we chose 5%" apart from "nobody has ever touched
    this", and the two are otherwise identical on screen.
    """
    await config.ensure_fresh(db)
    return {
        "settings": config.describe(),
        "groups": [
            {"key": key, "label": label}
            for key, label in config.GROUP_LABELS.items()
        ],
        "version": config.current_version(),
    }


class ConfigUpdate(BaseModel):
    changes: dict[str, object] = Field(..., min_length=1)
    reason: str = Field(..., min_length=3, max_length=500)


@router.put("/config", summary="Change business values")
# Deliberately tight. Nobody legitimately edits the platform's commission
# structure thirty times a minute, and this is the endpoint where a scripted
# mistake is most expensive.
@limiter.limit("20/minute")
async def update_config(
    request: Request,
    body: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SETTINGS_MANAGE)),
):
    """Validate, persist, audit, then invalidate — in that order.

    The invalidation is last and deliberately after the commit. Publishing the
    new version first would tell other workers to reload during a transaction
    that can still roll back, and they would read the *old* values while
    believing they had the new ones.
    """
    try:
        diff = await config.apply_changes(
            db,
            changes=body.changes,
            admin_email=access.email,
            reason=body.reason,
        )
    except ValueError as exc:
        # A refusal the operator can act on, not a validation dump.
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not diff:
        return {"changed": {}, "message": "Nothing changed — those are the current values."}

    admin_service.record_audit(
        db,
        access=access,
        action="platform.config.update",
        target_type="platform_config",
        target_id=None,
        before={key: change["before"] for key, change in diff.items()},
        after={key: change["after"] for key, change in diff.items()},
        reason=body.reason,
    )

    await db.commit()
    await config.invalidate()

    logger.info(
        "Platform config changed by %s: %s",
        access.email,
        ", ".join(f"{k} {v['before']!r}->{v['after']!r}" for k, v in diff.items()),
    )

    return {
        "changed": diff,
        "message": (
            f"{len(diff)} value{'s' if len(diff) != 1 else ''} updated. "
            "This applies to the next order priced in every app — nothing needs "
            "to be released."
        ),
    }


@router.get("/config/history", summary="What changed, when, and why")
async def config_history(
    key: str | None = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SETTINGS_MANAGE)),
):
    query = (
        select(PlatformSettingHistory)
        .order_by(desc(PlatformSettingHistory.created_at))
        .limit(limit)
    )
    if key:
        query = query.where(PlatformSettingHistory.key == key)

    rows = (await db.execute(query)).scalars().all()
    labels = {spec.key: spec.label for spec in config.SPECS}

    return {
        "items": [
            {
                "id": str(row.id),
                "key": row.key,
                "label": labels.get(row.key, row.key),
                "before": row.before,
                "after": row.after,
                "reason": row.reason,
                "changed_by": row.changed_by_email,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


class PreviewRequest(BaseModel):
    """A representative basket, priced under proposed values.

    Defaults describe the platform's most common order: two 20-litre bottles,
    delivered two kilometres, to a ground-floor address.
    """

    changes: dict[str, object] = Field(default_factory=dict)
    product_total: float = Field(500.0, ge=0, le=1_000_000)
    distance_km: float = Field(2.0, ge=0, le=200)
    quantity: int = Field(2, ge=1, le=200)
    bottle_capacity: int = Field(20, ge=1, le=1000)
    vendor_type: str = Field("retail_refill")
    delivery_type: str = Field("quick_swap")
    floor_level: int = Field(0, ge=0, le=100)
    first_order: bool = False
    surge: bool = False


@router.post("/config/preview", summary="Price a sample order under proposed values")
@limiter.limit("60/minute")
async def preview_config(
    request: Request,
    body: PreviewRequest,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_SETTINGS_MANAGE)),
):
    """What the change actually does to an order, side by side with today.

    A commission rate is an abstraction; "the vendor receives KSH 41 less on a
    typical order" is not. Presenting only the rate is how a decimal-place slip
    gets approved — the preview is where a 500% commission stops looking like a
    number and starts looking like a vendor paying the platform.

    Computed **without persisting anything**: the proposed values are applied to
    an in-memory copy of the configuration and the arithmetic is the same
    `calculate_revenue_splits` the real quote uses, so the preview cannot drift
    from what customers would be charged.
    """
    await config.ensure_fresh(db)

    try:
        proposed = config.validate_all(body.changes) if body.changes else {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    current = config.effective()
    after = {**current, **proposed}

    def _price(values: dict) -> dict:
        with config.temporarily(values):
            return config.price_sample(
                product_total=body.product_total,
                distance_km=body.distance_km,
                quantity=body.quantity,
                bottle_capacity=body.bottle_capacity,
                vendor_type=body.vendor_type,
                delivery_type=body.delivery_type,
                floor_level=body.floor_level,
                first_order=body.first_order,
                surge=body.surge,
            )

    before_quote = _price(current)
    after_quote = _price(after)

    # Money stays a decimal string end to end, differences included. Not every
    # string in the quote is money, though: `vehicle_class` is a description,
    # and subtracting it raises `InvalidOperation` — which is a 500 on the one
    # screen whose entire purpose is to make a change safe to approve.
    delta: dict[str, str] = {}
    for key, before_value in before_quote.items():
        if not isinstance(before_value, str):
            continue
        try:
            difference = Decimal(after_quote[key]) - Decimal(before_value)
        except InvalidOperation:
            continue
        delta[key] = str(difference.quantize(Decimal("0.01")))

    return {"before": before_quote, "after": after_quote, "delta": delta}


@router.get("/config/effective", summary="The values the apps are pricing with")
async def effective_config(
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_ANALYTICS_READ)),
):
    """A read-only view for anyone who can see analytics.

    Reading a revenue chart without knowing the take rate that produced it is
    guesswork, and that does not require permission to *change* the rate.
    """
    await config.ensure_fresh(db)
    return {"values": config.effective(), "version": config.current_version()}
