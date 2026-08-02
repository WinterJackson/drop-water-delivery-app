"""The catalogue, from the platform's side.

Read gated on `vendors.read` — a product belongs to a store, and anyone allowed
to look at stores may look at what they sell. Taking a product **down** is gated
on `vendors.approve`, because hiding a vendor's listing is an intervention in
their business and belongs with the people who can approve or suspend one.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.admin_dependencies import AdminAccess, require_admin
from dependencies.dependencies import get_db
from models.admin_model import PERM_VENDORS_APPROVE, PERM_VENDORS_READ
from services import admin_catalogue_service, admin_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/catalogue", summary="Every product on the platform")
@limiter.limit("60/minute")
async def catalogue(
    request: Request,
    view: str = Query("all", pattern="^(all|out_of_stock|low_stock|hidden)$"),
    search: str | None = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=300),
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_VENDORS_READ)),
):
    return {
        "items": await admin_catalogue_service.list_products(
            db, search=search, view=view, limit=limit
        ),
        "summary": await admin_catalogue_service.summary(db),
        "outliers": await admin_catalogue_service.price_outliers(db),
    }


class Availability(BaseModel):
    listed: bool
    reason: str = Field(min_length=8, max_length=500)


@router.post("/catalogue/{product_id}/availability", summary="Hide or restore a product")
async def set_availability(
    product_id: UUID,
    body: Availability,
    db: AsyncSession = Depends(get_db),
    access: AdminAccess = Depends(require_admin(PERM_VENDORS_APPROVE)),
):
    """Hide, never delete.

    Order history references products. Deleting one turns every past order that
    contained it into a receipt with a hole in it, and those receipts are the
    platform's own record of what it charged for.

    A reason is required because this is somebody's livelihood being taken off
    the shelf, and "why is my product gone" deserves an answer that is not
    somebody's recollection.
    """
    product = await admin_catalogue_service.set_availability(db, product_id, body.listed)
    if product is None:
        raise HTTPException(status_code=404, detail="No such product.")

    admin_service.record_audit(
        db,
        access=access,
        action="catalogue.availability",
        target_type="product",
        target_id=str(product_id),
        before={"is_available": not body.listed},
        after={"is_available": body.listed, "reason": body.reason.strip()},
    )
    await db.commit()

    return {"id": str(product_id), "is_available": body.listed}
