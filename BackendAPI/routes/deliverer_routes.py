from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from services.deliverer_service import (
    register_deliverer,
    get_deliverer_by_clerk_id,
    update_deliverer_profile,
    update_deliverer_location,
    toggle_availability,
    get_deliverer_orders,
    update_delivery_status,
    get_deliverer_earnings,
    reject_delivery,
    accept_delivery_radar,
    get_trip_radar_orders,
    get_deliverer_reviews,
    cancel_delivery,
)
from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List
from schemas.order_schema import OrderWithDetails
from schemas.order_schema import OrderWithDetails
from schemas.deliverer_schemas import DelivererProfileResponse
from dependencies.auth_dependencies import get_current_rider
from fastapi import UploadFile, File

router = APIRouter()


# --- Pydantic Schemas ---
class RiderRegisterRequest(BaseModel):
    name: str
    email: str
    phone_number: Optional[str] = None
    ID_number: str
    vehicle_type: Optional[str] = "motorbike"
    employment_model: Optional[str] = "gig_economy"
    employer_vendor_id: Optional[UUID] = None
    plate_number: Optional[str] = None
    profile_pic: Optional[str] = None


class RiderProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    phone_number: Optional[str] = None
    profile_pic: Optional[str] = None
    vehicle_type: Optional[str] = None
    plate_number: Optional[str] = None
    driver_license: Optional[str] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    operation_lat: Optional[float] = None
    operation_lng: Optional[float] = None
    preferences: Optional[dict] = None
    payment_methods: Optional[list] = None


class LocationUpdateRequest(BaseModel):
    lat: float
    lng: float


class AvailabilityRequest(BaseModel):
    is_available: bool


class DeliveryStatusRequest(BaseModel):
    status: str
    proof_url: Optional[str] = None
    empties_received: Optional[int] = None

class BottleRejectionRequest(BaseModel):
    reason_text: str
    photo_urls: list[str]


# --- Routes ---

@router.post("/register")
async def rider_register(
    body: RiderRegisterRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    clerk_id = user["sub"]
    deliverer = await register_deliverer(session=db, clerk_id=clerk_id, data=body.model_dump())
    return {"message": "Rider registered", "rider_id": str(deliverer.id)}


@router.get("/profile", response_model=DelivererProfileResponse)
async def rider_profile(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    deliverer = await get_deliverer_by_clerk_id(session=db, clerk_id=clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found. Please register first.")
    
    return deliverer


@router.put("/profile")
async def rider_update_profile(
    body: RiderProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    deliverer = await update_deliverer_profile(session=db, clerk_id=clerk_id, data=body.model_dump(exclude_none=True))
    return {"message": "Profile updated", "rider_id": str(deliverer.id)}


@router.put("/location")
async def rider_update_location(
    body: LocationUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    return await update_deliverer_location(session=db, clerk_id=clerk_id, lat=body.lat, lng=body.lng)


@router.put("/availability")
async def rider_toggle_availability(
    body: AvailabilityRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    result = await toggle_availability(session=db, clerk_id=clerk_id, is_available=body.is_available)

    # When a rider comes online, try to assign any waiting unassigned orders
    if body.is_available:
        try:
            from services.order_service import reassign_unassigned_orders
            reassign_result = await reassign_unassigned_orders(session=db)
            if reassign_result.get("reassigned", 0) > 0:
                result["reassigned_orders"] = reassign_result["reassigned"]
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Reassign on availability toggle failed: {e}")

    return result


@router.get("/orders", response_model=List[OrderWithDetails])
async def rider_get_orders(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None, description="Filter orders by status (e.g. delivered)"),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    orders = await get_deliverer_orders(session=db, clerk_id=clerk_id, skip=skip, limit=limit, status=status)
    return orders


@router.get("/trip-radar", response_model=List[OrderWithDetails])
async def rider_trip_radar(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    orders = await get_trip_radar_orders(session=db, clerk_id=clerk_id)
    return orders


@router.put("/orders/{order_id}/status")
async def rider_update_delivery_status(
    order_id: UUID,
    body: DeliveryStatusRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    return await update_delivery_status(
        session=db,
        clerk_id=clerk_id,
        order_id=order_id,
        new_status=body.status,
        proof_url=body.proof_url,
        empties_received=body.empties_received
    )


@router.get("/earnings")
async def rider_earnings(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    return await get_deliverer_earnings(session=db, clerk_id=clerk_id)


@router.put("/orders/{order_id}/reject")
async def rider_reject_delivery(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """Rider rejects an assigned delivery, triggering automatic reassignment."""
    clerk_id = user["sub"]
    return await reject_delivery(session=db, clerk_id=clerk_id, order_id=order_id)

class CancelOrderRequest(BaseModel):
    reason: str
    details: Optional[str] = None

@router.put("/orders/{order_id}/cancel")
async def rider_cancel_delivery(
    order_id: UUID,
    body: CancelOrderRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """Rider cancels an assigned delivery (handles both pre-pickup unassignment and post-pickup cancellation)."""
    clerk_id = user["sub"]
    return await cancel_delivery(
        session=db, 
        clerk_id=clerk_id, 
        order_id=order_id, 
        reason=body.reason, 
        details=body.details
    )



@router.get("/orders/{order_id}/rider-location")
async def get_rider_location_for_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """Get current rider location for a specific order (polling fallback for WebSocket)."""
    from models.order_model import Order
    order = await db.get(Order, order_id)
    if not order or not order.deliverer_id:
        raise HTTPException(status_code=404, detail="Order not found or no rider assigned")

    from models.deliverer_model import Deliverer
    deliverer = await db.get(Deliverer, order.deliverer_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    return {
        "rider_id": str(deliverer.id),
        "rider_name": deliverer.name,
        "lat": deliverer.current_lat,
        "lng": deliverer.current_lng,
        "is_available": deliverer.is_available,
    }

@router.post("/orders/{order_id}/accept")
async def rider_accept_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """Rider 'swipes to accept' a Trip Radar broadcast."""
    clerk_id = user["sub"]
    return await accept_delivery_radar(session=db, clerk_id=clerk_id, order_id=order_id)

class MismatchRequest(BaseModel):
    actual_floor_level: Optional[int] = None

@router.post("/orders/{order_id}/mismatch")
async def rider_report_address_mismatch(
    order_id: UUID,
    body: MismatchRequest = MismatchRequest(),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """Rider reports a floor level lie. Pauses delivery."""
    clerk_id = user["sub"]
    from services.deliverer_service import report_address_mismatch
    return await report_address_mismatch(session=db, clerk_id=clerk_id, order_id=order_id, actual_floor_level=body.actual_floor_level)

@router.post("/orders/{order_id}/bottle-rejection")
async def rider_report_bottle_rejection(
    order_id: UUID,
    body: BottleRejectionRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """Rider reports a damaged bottle. Pauses delivery for admin review."""
    clerk_id = user["sub"]
    from services.deliverer_service import report_bottle_rejection
    return await report_bottle_rejection(
        session=db, 
        clerk_id=clerk_id, 
        order_id=order_id, 
        reason_text=body.reason_text, 
        photo_urls=body.photo_urls
    )


@router.get("/reviews")
async def rider_reviews(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    clerk_id = user["sub"]
    return await get_deliverer_reviews(session=db, clerk_id=clerk_id, limit=limit, offset=offset)


@router.post("/upload_proof")
async def upload_proof(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """Secure endpoint for riders to upload proof of delivery photos to AWS S3."""
    clerk_id = user["sub"]
    
    # Optional check: ensure it's a valid rider
    deliverer = await get_deliverer_by_clerk_id(session=db, clerk_id=clerk_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    from utils.s3_utils import upload_file_to_s3
    url = await upload_file_to_s3(file, prefix="deliveries/proof")
    
    if not url:
        raise HTTPException(status_code=500, detail="Failed to upload proof photo securely")
        
    return {"url": url, "secure_url": url}


@router.get("/bottle-debt")
async def rider_bottle_debt(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """
    Empties this rider is holding, broken down by vendor.

    There was previously no way for a rider to see this at all: debt accrued
    silently on every quick_swap delivery and only the vendor could see it. A rider
    cannot return bottles they do not know they have.
    """
    from services.bottle_ledger_service import get_rider_outstanding

    deliverer = await get_deliverer_by_clerk_id(session=db, clerk_id=user["sub"])
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    vendors = await get_rider_outstanding(db, deliverer.id)
    return {
        "vendors": vendors,
        "total_bottles": sum(v["total_bottles"] for v in vendors),
    }


@router.get("/bottle-ledger")
async def rider_bottle_ledger(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """This rider's own bottle movement history — accruals and confirmed returns."""
    from services.bottle_ledger_service import get_ledger_history

    deliverer = await get_deliverer_by_clerk_id(session=db, clerk_id=user["sub"])
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    return {
        "entries": await get_ledger_history(db, rider_id=deliverer.id, limit=limit, offset=offset)
    }


@router.get("/wallet-summary")
async def rider_wallet_summary(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_rider),
):
    """
    Balance, float committed to open cash orders, and what is actually withdrawable.

    A rider carrying cash orders holds money that is not theirs to withdraw: it
    settles the vendor's cut and the platform's cut when they deliver. Showing only
    `wallet_balance` made a refused withdrawal look arbitrary.
    """
    from decimal import Decimal
    from services.settlement_service import available_for_payout, committed_cash_float

    deliverer = await get_deliverer_by_clerk_id(session=db, clerk_id=user["sub"])
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    balance = Decimal(str(deliverer.wallet_balance or 0))
    committed = await committed_cash_float(db, deliverer.id)
    available = await available_for_payout(
        db, provider_id=deliverer.id, provider_type="rider", wallet_balance=balance,
    )

    return {
        "wallet_balance": float(balance),
        "committed_cash_float": float(committed),
        "available_for_withdrawal": float(available),
        # Negative means the rider owes the platform — settle before they can
        # accept further cash orders.
        "is_in_arrears": balance < 0,
    }
