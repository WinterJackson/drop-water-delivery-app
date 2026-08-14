from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from dependencies.auth_dependencies import get_active_store, get_owned_store
from models.vendor_model import Vendor
from models.vendor_rider_model import VendorRiderRegistry
from models.deliverer_model import Deliverer
from models.order_model import Order
from sqlalchemy import func, select, and_, or_
from typing import Optional
from utils.paging import stable
from pydantic import BaseModel
import logging
from services.notification_service import create_notification
from services.expo_push_service import send_push_message, dispatch_background
from services.email_service import send_rider_approved

logger = logging.getLogger(__name__)

router = APIRouter()

class RiderActionRequest(BaseModel):
    deliverer_id: str
    action: str # "approve", "reject", "suspend"


def roster_row(reg: VendorRiderRegistry, deliverer: Deliverer, trip_count: int | None) -> dict:
    """One rider on a store's roster, as the vendor app reads it.

    A module-level function rather than a comprehension inside the route, so it
    can be called with two model instances and no database. It needs to be: this
    mapping read `reg.created_at`, which is **not a column on
    `VendorRiderRegistry`** — the table has `requested_at`. Every store with at
    least one rider therefore got an `AttributeError` and a 500, and a store with
    none skipped the loop and got `[]`. The endpoint worked for exactly the
    vendors who had nothing to see, which is why it survived a route-contract
    test that only ever asked whether the path resolves.
    """
    return {
        "registry_id": str(reg.id),
        "deliverer_id": str(deliverer.id),
        "name": deliverer.name,
        "phone_number": deliverer.phone_number,
        "profile_pic": deliverer.profile_pic,
        "status": reg.status,
        "vehicle_type": deliverer.vehicle_type,
        "plate_number": deliverer.plate_number,
        "is_available": deliverer.is_available,
        "applied_at": reg.requested_at.isoformat() if reg.requested_at else None,
        "pending_10L_empties": reg.pending_10L_empties or 0,
        "pending_20L_empties": reg.pending_20L_empties or 0,
        # Both were absent from this payload, and the app's roster card renders
        # each behind an `!= null` guard — so the two badges never drew, and the
        # "Rating" and "Trips" sort chips compared `undefined` and did nothing.
        "rating": deliverer.rating,
        "total_deliveries": trip_count or 0,
    }

@router.get("/my-riders")
async def get_vendor_riders(
    status: Optional[str] = Query(None, description="Registry status: pending, approved, rejected, suspended."),
    available_only: bool = Query(False, description="Only riders currently marked available."),
    search_query: Optional[str] = Query(None, description="Match against the rider's name or phone number."),
    sort: str = Query("recent", description="recent | rating | trips."),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(get_active_store),
):
    """One page of this store's rider roster, newest application first.

    Returned every row with no bound and **no `ORDER BY` at all**, which is two
    problems. Postgres may hand back an unordered result in a different sequence
    on each execution, so the roster reshuffled itself on every pull-to-refresh
    and the rider a vendor was reaching for moved; and a store that has been
    trading for a year has a roster nobody wants to receive in one response —
    on a phone, every thirty seconds, which is this endpoint's refetch interval.

    The status filter and the search are here rather than in the app for the
    usual reason: applied to a page they answer "no pending applications" to a
    vendor who has some.
    """
    # Deliveries this rider has completed **for this store**, which is the figure
    # a vendor is actually sorting by. Correlated on the registry join rather
    # than counted per row in Python, so it costs one aggregate for the page.
    trips = (
        select(
            Order.deliverer_id.label("rider_id"),
            func.count(Order.id).label("trips"),
        )
        .where(Order.vendor_id == vendor.id, Order.order_status == "delivered")
        .group_by(Order.deliverer_id)
        .subquery()
    )

    query = (
        select(VendorRiderRegistry, Deliverer, func.coalesce(trips.c.trips, 0).label("trips"))
        .join(Deliverer, VendorRiderRegistry.rider_id == Deliverer.id)
        .outerjoin(trips, trips.c.rider_id == VendorRiderRegistry.rider_id)
        .where(VendorRiderRegistry.vendor_id == vendor.id)
    )

    if status:
        query = query.where(VendorRiderRegistry.status == status.strip().lower())

    if available_only:
        query = query.where(Deliverer.is_available.is_(True))

    if search_query and search_query.strip():
        term = f"%{search_query.strip()}%"
        query = query.where(
            or_(Deliverer.name.ilike(term), Deliverer.phone_number.ilike(term))
        )

    # Sorting is the server's too. The app had "Rating" and "Trips" chips that
    # sorted its own array on `rider.rating` and `rider.total_deliveries` —
    # neither of which this endpoint has ever returned, so both were `undefined`,
    # every comparison was `NaN`, and the two controls did nothing at all. A
    # control that reaches the user and not the platform is worse than no
    # control, because the person operating it believes it worked. Sorting a
    # page would have been the next version of the same lie.
    orderings = {
        "rating": (Deliverer.rating.desc().nulls_last(),),
        "trips": (func.coalesce(trips.c.trips, 0).desc(),),
    }
    primary = orderings.get(sort, (VendorRiderRegistry.requested_at.desc(),))

    # One row more than the page, then trimmed: `len(rows) == limit` cannot tell
    # a full page from the last one.
    query = (
        query.order_by(*stable(*primary, key=VendorRiderRegistry.id))
        .offset(offset)
        .limit(limit + 1)
    )

    result = await session.execute(query)
    rows = result.all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    riders = [roster_row(reg, deliverer, trip_count) for reg, deliverer, trip_count in rows]
    return {"items": riders, "limit": limit, "offset": offset, "has_more": has_more}

@router.put("/rider-action")
async def manage_rider_status(request: RiderActionRequest, session: AsyncSession = Depends(get_db), vendor: Vendor = Depends(get_owned_store)):
    """Owner only.

    Approving a rider decides who may carry this store's goods and collect its
    cash — the same class of decision as changing the payout account, not a
    shop-floor one. `RiderManagement.tsx` already redirects staff away; that was
    the only thing enforcing it.

    Reading the roster (`GET /my-riders`) stays open to staff: the assign-rider
    sheet in `OrderDetail` needs it to dispatch an order.
    """
    query = select(VendorRiderRegistry).where(
        and_(
            VendorRiderRegistry.vendor_id == vendor.id,
            VendorRiderRegistry.rider_id == request.deliverer_id
        )
    )
    result = await session.execute(query)
    registry = result.scalar_one_or_none()
    
    if not registry:
        raise HTTPException(status_code=404, detail="Rider application not found")
        
    if request.action == "approve":
        registry.status = "approved"
        title = "Vendor Application Approved 🎉"
        body = f"{vendor.business_name} has approved your application! You can now receive orders from them."
    elif request.action == "reject":
        registry.status = "rejected"
        title = "Vendor Application Update"
        body = f"{vendor.business_name} has declined your application."
    elif request.action == "suspend":
        registry.status = "suspended"
        title = "Vendor Access Suspended"
        body = f"{vendor.business_name} has temporarily disabled your rider access."
    else:
        raise HTTPException(status_code=400, detail="Invalid action")
        
    await session.commit()
    
    # Send Notification to Rider
    rider = await session.get(Deliverer, registry.rider_id)
    if rider:
        if request.action == "approve" and rider.email:
            try:
                send_rider_approved(to=rider.email, name=rider.name)
            except Exception as e:
                logger.error(f"Failed to send rider approval email: {e}")
                
        await create_notification(
            session=session,
            user_id=rider.id,
            user_type="rider",
            title=title,
            message=body,
            message_type="vendor_registry_update",
            action_url="/(screens)/DiscoverVendors"
        )
        if rider.push_token:
            dispatch_background(send_push_message(
                to=rider.push_token,
                title=title,
                body=body,
                data={"url": "/(screens)/DiscoverVendors"}
            ))

    return {"message": f"Rider {request.action}d successfully."}

