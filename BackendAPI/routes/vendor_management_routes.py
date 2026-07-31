from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from dependencies.auth_dependencies import get_current_vendor
from services.vendor_management_service import (
    register_vendor,
    get_vendor_by_clerk_id,
    get_all_vendors_by_clerk_id,
    update_vendor_profile,
    create_product,
    update_product,
    delete_product,
    get_vendor_orders,
    get_vendor_products,
    update_order_status,
    get_vendor_dashboard,
    cancel_order,
    assign_order_rider
)
from pydantic import BaseModel
from uuid import UUID
from typing import Optional, List, Literal
from utils.serializers import safe_serialize
from schemas.order_schema import PaginatedOrders

router = APIRouter()


# --- Pydantic Schemas ---
class VendorRegisterRequest(BaseModel):
    owners_name: str
    business_name: str
    email: str
    phone_number: Optional[str] = None
    profile_pic: Optional[str] = None
    vendor_type: Literal["retail_refill", "wholesale_b2b"] = "retail_refill"


class VendorProfileUpdateRequest(BaseModel):
    business_name: Optional[str] = None
    owners_name: Optional[str] = None
    phone_number: Optional[str] = None
    profile_pic: Optional[str] = None
    business_license: Optional[str] = None
    location_address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    delivery_radius: Optional[float] = None
    shift_start: Optional[str] = None
    shift_end: Optional[str] = None
    preferred_payment_method: Optional[List[str]] = None
    vendor_type: Optional[Literal["retail_refill", "wholesale_b2b"]] = None
    is_online: Optional[bool] = None
    deposit_fee: Optional[float] = None


from pydantic import BaseModel, Field

class ProductCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    image_url: str
    price: float = Field(gt=0)
    discount: Optional[float] = 0
    capacity: float = Field(gt=0)
    weight_kg: float = Field(gt=0, le=1000, default=20.0)
    minimum_order_qty: int = Field(ge=1, default=1)
    unit: str
    stock: int = Field(ge=0)
    is_available: Optional[bool] = True


class ProductUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    price: Optional[float] = Field(default=None, gt=0)
    discount: Optional[float] = None
    capacity: Optional[float] = Field(default=None, gt=0)
    weight_kg: Optional[float] = Field(default=None, gt=0, le=1000)
    minimum_order_qty: Optional[int] = Field(default=None, ge=1)
    unit: Optional[str] = None
    stock: Optional[int] = Field(default=None, ge=0)
    is_available: Optional[bool] = None


class OrderStatusRequest(BaseModel):
    status: str

class AssignRiderRequest(BaseModel):
    deliverer_id: str

class ReceiveBottlesRequest(BaseModel):
    rider_id: str
    received_10L: int = Field(0, ge=0)
    received_20L: int = Field(0, ge=0)
    note: Optional[str] = Field(None, max_length=500)

# --- Routes ---

@router.post("/register")
async def vendor_register(
    body: VendorRegisterRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    clerk_id = user["sub"]
    vendor = await register_vendor(session=db, clerk_id=clerk_id, data=body.model_dump())
    return {"message": "Vendor registered", "vendor_id": str(vendor.id)}

@router.get("/stores")
async def vendor_stores(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    stores = await get_all_vendors_by_clerk_id(session=db, clerk_id=clerk_id)
    return [safe_serialize(s) for s in stores]

@router.put("/staff")
async def vendor_assign_staff(
    email: str,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    # Only the owner can assign staff to their store
    vendor = await get_vendor_by_clerk_id(session=db, clerk_id=clerk_id)
    if not vendor or vendor.clerk_id != clerk_id:
        raise HTTPException(status_code=403, detail="Only the store owner can assign staff.")
    
    import os
    from clerk_backend_api import Clerk
    clerk_secret = os.getenv("CLERK_SECRET_KEY")
    if not clerk_secret:
        raise HTTPException(status_code=500, detail="Server misconfiguration: Clerk secret missing.")
        
    try:
        clerk = Clerk(bearer_auth=clerk_secret)
        # Assuming clerk.users.list accepts email_address as a parameter.
        # The clerk_backend_api v2.2.0 uses 'list' for getting users
        users_response = clerk.users.list(email_address=[email])
        
        # clerk_backend_api .list returns a UserList or list of Users depending on the specific API version.
        # Let's inspect the length. If it has .data, we use that.
        users = getattr(users_response, "data", users_response)
        
        if not users or len(users) == 0:
            raise HTTPException(status_code=404, detail="Staff member not found. Please ask them to download the app and sign up first.")
            
        staff_clerk_id = users[0].id
        
        vendor.staff_clerk_id = staff_clerk_id
        await db.commit()
        return {"message": "Staff assigned successfully."}
    except Exception as e:
        logger.error(f"Failed to assign staff via Clerk: {e}")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=400, detail="Failed to find the specified user.")



@router.get("/profile")
async def vendor_profile(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    vendor = await get_vendor_by_clerk_id(session=db, clerk_id=clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found. Please register first.")
    
    vendor_data = safe_serialize(vendor)
    vendor_data["role"] = "owner" if vendor.clerk_id == clerk_id else "staff"
    return vendor_data


@router.put("/profile")
async def vendor_update_profile(
    body: VendorProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    vendor = await get_vendor_by_clerk_id(session=db, clerk_id=clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
        
    if vendor.clerk_id != clerk_id:
        restricted_fields = ["preferred_payment_method", "business_name", "owners_name", "business_license", "location_address", "deposit_fee", "shift_start", "shift_end", "lat", "lng", "delivery_radius"]
        for field in restricted_fields:
            if getattr(body, field, None) is not None:
                raise HTTPException(status_code=403, detail="Staff members cannot update restricted store settings.")
                
    from datetime import datetime
    data = body.model_dump(exclude_none=True)
    if "shift_start" in data and isinstance(data["shift_start"], str):
        try:
            data["shift_start"] = datetime.strptime(data["shift_start"], "%H:%M").time()
        except ValueError:
            pass # Or handle error
    if "shift_end" in data and isinstance(data["shift_end"], str):
        try:
            data["shift_end"] = datetime.strptime(data["shift_end"], "%H:%M").time()
        except ValueError:
            pass # Or handle error

    updated_vendor = await update_vendor_profile(session=db, clerk_id=clerk_id, data=data)
    return {"message": "Profile updated", "vendor_id": str(vendor.id)}


@router.post("/products")
async def vendor_create_product(
    body: ProductCreateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    product = await create_product(session=db, clerk_id=clerk_id, data=body.model_dump())
    return {"message": "Product created", "product_id": str(product.id)}


@router.get("/products/{product_id}")
async def vendor_get_single_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    """Fetch a single product by ID for the edit product flow."""
    clerk_id = user["sub"]
    vendor = await get_vendor_by_clerk_id(session=db, clerk_id=clerk_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    from models.product_model import Product
    product = await db.get(Product, product_id)
    if not product or product.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Product not found or does not belong to this vendor")

    return safe_serialize(product)


@router.put("/products/{product_id}")
async def vendor_update_product(
    product_id: UUID,
    body: ProductUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    product = await update_product(session=db, clerk_id=clerk_id, product_id=product_id, data=body.model_dump(exclude_none=True))
    return {"message": "Product updated", "product_id": str(product.id)}


@router.delete("/products/{product_id}")
async def vendor_delete_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    await delete_product(session=db, clerk_id=clerk_id, product_id=product_id)
    return {"message": "Product deleted"}


@router.post("/receive-bottles")
async def vendor_receive_bottles(
    body: ReceiveBottlesRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    from services.vendor_management_service import receive_bottles_from_rider
    clerk_id = user["sub"]
    result = await receive_bottles_from_rider(
        session=db,
        clerk_id=clerk_id,
        rider_id=body.rider_id,
        received_10L=body.received_10L,
        received_20L=body.received_20L,
        note=body.note,
    )
    return result


@router.get("/bottle-debtors")
async def vendor_bottle_debtors(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    """
    Riders currently holding this vendor's empties.

    Sourced from the bottle ledger, not the rider registry, so riders who took a
    radar order without ever registering with the vendor are included. They were
    invisible before, which is exactly how bottles went missing.
    """
    from services.vendor_management_service import get_vendor_bottle_debtors

    return await get_vendor_bottle_debtors(session=db, clerk_id=user["sub"])


@router.get("/bottle-ledger")
async def vendor_bottle_ledger(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    """Audit trail of every bottle movement for this vendor."""
    from services.bottle_ledger_service import get_ledger_history
    from services.vendor_management_service import get_vendor_by_clerk_id

    vendor = await get_vendor_by_clerk_id(db, user["sub"])
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    return {
        "entries": await get_ledger_history(db, vendor_id=vendor.id, limit=limit, offset=offset)
    }


@router.get("/products")
async def vendor_get_products(
    search_query: Optional[str] = Query(None, description="Search query for product name"),
    stock_filter: str = Query("All", description="Filter by stock: All, Low Stock, Out of Stock"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    
    from core.redis_client import cache_get, cache_set
    cache_key = f"vendor_products:{clerk_id}:{search_query}:{stock_filter}:{limit}:{offset}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    products = await get_vendor_products(
        session=db, 
        clerk_id=clerk_id, 
        search_query=search_query, 
        stock_filter=stock_filter, 
        limit=limit, 
        offset=offset
    )
    
    result = {"pages": [products]}
    await cache_set(cache_key, result, ttl_seconds=60) # Cache for 60 seconds
    return result


@router.get("/orders", response_model=PaginatedOrders)
async def vendor_get_orders(
    search_query: Optional[str] = Query(None, description="Search query for order ID"),
    status_filter: str = Query("All", description="Filter by status: All, pending, accepted, preparing, ready, cancelled"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    orders = await get_vendor_orders(
        session=db, 
        clerk_id=clerk_id, 
        search_query=search_query, 
        status_filter=status_filter, 
        skip=skip, 
        limit=limit
    )
    return {"pages": [orders]}


@router.put("/orders/{order_id}/status")
async def vendor_update_order_status(
    order_id: UUID,
    body: OrderStatusRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    result = await update_order_status(session=db, clerk_id=clerk_id, order_id=order_id, new_status=body.status)
    return result


@router.get("/dashboard")
async def vendor_dashboard(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    clerk_id = user["sub"]
    return await get_vendor_dashboard(session=db, clerk_id=clerk_id)


@router.put("/orders/{order_id}/cancel")
async def vendor_cancel_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    """Cancel an order before preparation"""
    clerk_id = user["sub"]
    result = await cancel_order(session=db, clerk_id=clerk_id, order_id=order_id)
    return result

@router.put("/orders/{order_id}/assign-rider")
async def vendor_assign_rider(
    order_id: UUID,
    body: AssignRiderRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_vendor),
):
    """Assign an order to a specific rider"""
    clerk_id = user["sub"]
    result = await assign_order_rider(session=db, clerk_id=clerk_id, order_id=order_id, rider_id=body.deliverer_id)
    return result
