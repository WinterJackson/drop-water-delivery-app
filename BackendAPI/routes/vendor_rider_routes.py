from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from dependencies.auth_dependencies import get_active_store, get_owned_store
from models.vendor_model import Vendor
from models.vendor_rider_model import VendorRiderRegistry
from models.deliverer_model import Deliverer
from sqlalchemy import select, and_
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

@router.get("/my-riders")
async def get_vendor_riders(session: AsyncSession = Depends(get_db), vendor: Vendor = Depends(get_active_store)):
    query = select(VendorRiderRegistry, Deliverer).join(
        Deliverer, VendorRiderRegistry.rider_id == Deliverer.id
    ).where(VendorRiderRegistry.vendor_id == vendor.id)
    
    result = await session.execute(query)
    rows = result.all()
    
    riders = []
    for reg, deliverer in rows:
        riders.append({
            "registry_id": str(reg.id),
            "deliverer_id": str(deliverer.id),
            "name": deliverer.name,
            "phone_number": deliverer.phone_number,
            "profile_pic": deliverer.profile_pic,
            "status": reg.status,
            "vehicle_type": deliverer.vehicle_type,
            "plate_number": deliverer.plate_number,
            "is_available": deliverer.is_available,
            "applied_at": reg.created_at,
            "pending_10L_empties": reg.pending_10L_empties or 0,
            "pending_20L_empties": reg.pending_20L_empties or 0,
        })
        
    return riders

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

