from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from dependencies.auth_dependencies import (
    StoreAccess,
    get_active_store,
    get_store_access,
    get_current_vendor,
    get_owned_store,
    require_permission,
)
from models.vendor_model import Vendor
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


def _signed(data: dict, *fields: str) -> dict:
    """Presign the S3 keys in a `safe_serialize` dict.

    `safe_serialize` copies columns verbatim, so image fields came back as raw S3
    keys — the vendor's own product list and store avatar rendered as broken
    images the moment uploads moved off the public Cloudinary preset. The
    Pydantic response schemas do this with `field_validator`; these three
    endpoints return plain dicts and have to do it explicitly.
    """
    from utils.s3_utils import generate_presigned_url

    for field in fields:
        value = data.get(field)
        if value and not str(value).startswith("http") and not str(value).startswith("/api/uploads/"):
            data[field] = generate_presigned_url(value)
    return data


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
    #: Warn at or below this level. 0 disables the warning for this product —
    #: a dispenser ordered in on request has no meaningful "low".
    low_stock_threshold: int = Field(ge=0, le=10_000, default=5)
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
    low_stock_threshold: Optional[int] = Field(default=None, ge=0, le=10_000)
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
    return [_signed(safe_serialize(s), "profile_pic") for s in stores]

# ── Staff ────────────────────────────────────────────────────────────────────
# `Vendor.staff_clerk_id` held one id, was UNIQUE platform-wide, and adding a
# second person silently replaced the first — behind a screen called "Manage
# Staff". Access was also all-or-nothing: handing someone the till handed them
# the catalogue, the bottle ledger and the wallet balance. Both are now
# `Vendor_Staff` rows with an explicit capability set.


class StaffInviteRequest(BaseModel):
    email: str
    #: Omitted means the default set — orders, products and bottles, but not
    #: finances. Seeing the store's balance should be a deliberate grant.
    permissions: Optional[List[str]] = None


class StaffPermissionsRequest(BaseModel):
    permissions: List[str]


@router.get("/staff")
async def vendor_list_staff(
    db: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(get_owned_store),
):
    """Owner only. Everyone who can currently act on this store.

    There was no way to see this at all: the one grant lived in a column, the
    screen had no list, and an owner had no way to discover who they had given
    access to — or that adding a second person had removed the first.
    """
    from services.vendor_staff_service import list_staff
    from models.vendor_staff_model import ALL_PERMISSIONS, PERMISSION_LABELS

    return {
        "staff": await list_staff(db, vendor.id),
        # Shipped with the list so the management screen never hardcodes a
        # capability set that has drifted from the server's.
        "available_permissions": [
            {"key": key, "label": PERMISSION_LABELS[key]} for key in ALL_PERMISSIONS
        ],
    }


@router.post("/staff")
async def vendor_invite_staff(
    body: StaffInviteRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(get_owned_store),
):
    """Owner only. Grant someone access to this store.

    The response is deliberately the same whether or not the email belongs to a
    Drop account. It used to answer 404 "Staff member not found. Please ask them
    to download the app and sign up first." for an unknown address and 200 for a
    known one, which let any vendor test whether an arbitrary email — a
    competitor, a customer, anyone — has an account here. An invitation is
    recorded either way and binds on that person's first sign-in.
    """
    from services.vendor_staff_service import invite_staff

    return await invite_staff(
        db,
        vendor_id=vendor.id,
        owner_clerk_id=user["sub"],
        email=body.email,
        permissions=body.permissions,
    )


@router.patch("/staff/{staff_id}")
async def vendor_update_staff_permissions(
    staff_id: UUID,
    body: StaffPermissionsRequest,
    db: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(get_owned_store),
):
    """Owner only. Change what one staff member may do."""
    from services.vendor_staff_service import update_permissions

    return await update_permissions(
        db, vendor_id=vendor.id, staff_id=staff_id, permissions=body.permissions
    )


@router.delete("/staff/{staff_id}")
async def vendor_revoke_staff(
    staff_id: UUID,
    db: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(get_owned_store),
):
    """Owner only. Remove access, keeping the record that they had it.

    A soft delete: who could act on a store and when is part of the audit trail
    behind every order and bottle movement they touched.
    """
    from services.vendor_staff_service import revoke_staff

    return await revoke_staff(db, vendor_id=vendor.id, staff_id=staff_id)


@router.get("/profile")
async def vendor_profile(
    db: AsyncSession = Depends(get_db),
    access: StoreAccess = Depends(get_store_access),
):
    """The active store, plus what this caller may do in it.

    `role` used to be computed here for display only — `"owner" if
    vendor.clerk_id == clerk_id else "staff"` — while the server enforced
    nothing. It is now derived from the same resolution the gates use, and it
    carries the caller's actual capability set so the app can hide what would be
    refused instead of guessing from a role name.
    """
    from models.vendor_staff_model import ALL_PERMISSIONS

    vendor_data = _signed(safe_serialize(access.vendor), "profile_pic")
    vendor_data["role"] = access.role
    # Owners have every capability implicitly; spelling them out means the app
    # has one thing to check rather than "is owner, or has permission".
    vendor_data["permissions"] = (
        list(ALL_PERMISSIONS) if access.is_owner else sorted(access.permissions)
    )
    return vendor_data


@router.put("/profile")
async def vendor_update_profile(
    body: VendorProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(get_owned_store),
):
    """Owner only.

    This writes the business name, the store's coordinates and delivery radius,
    the deposit fee, the accepted payment methods and the online flag — i.e.
    what the business *is* and where it trades. Staff were blocked from it by a
    `router.replace()` in six React screens and by nothing at all on the server.
    """
    clerk_id = user["sub"]
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

    await update_vendor_profile(session=db, clerk_id=clerk_id, data=data, vendor_id=vendor.id)
    return {"message": "Profile updated", "vendor_id": str(vendor.id)}


@router.post("/products")
async def vendor_create_product(
    body: ProductCreateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(require_permission("manage_products")),
):
    clerk_id = user["sub"]
    product = await create_product(session=db, clerk_id=clerk_id, data=body.model_dump(), vendor_id=vendor.id)
    return {"message": "Product created", "product_id": str(product.id)}


@router.get("/products/{product_id}")
async def vendor_get_single_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(get_active_store),
):
    """Fetch a single product by ID for the edit product flow."""
    from models.product_model import Product
    product = await db.get(Product, product_id)
    if not product or product.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Product not found or does not belong to this vendor")

    return _signed(safe_serialize(product), "image_url")


@router.put("/products/{product_id}")
async def vendor_update_product(
    product_id: UUID,
    body: ProductUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(require_permission("manage_products")),
):
    clerk_id = user["sub"]
    product = await update_product(session=db, clerk_id=clerk_id, product_id=product_id, data=body.model_dump(exclude_none=True), vendor_id=vendor.id)
    return {"message": "Product updated", "product_id": str(product.id)}


@router.delete("/products/{product_id}")
async def vendor_delete_product(
    product_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(require_permission("manage_products")),
):
    clerk_id = user["sub"]
    await delete_product(session=db, clerk_id=clerk_id, product_id=product_id, vendor_id=vendor.id)
    return {"message": "Product deleted"}


@router.post("/receive-bottles")
async def vendor_receive_bottles(
    body: ReceiveBottlesRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(require_permission("manage_bottles")),
):
    from services.vendor_management_service import receive_bottles_from_rider
    clerk_id = user["sub"]
    result = await receive_bottles_from_rider(
        session=db,
        clerk_id=clerk_id,
        vendor_id=vendor.id,
        rider_id=body.rider_id,
        received_10L=body.received_10L,
        received_20L=body.received_20L,
        note=body.note,
    )
    return result


@router.get("/bottle-debtors")
async def vendor_bottle_debtors(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(get_active_store),
):
    """
    Riders currently holding this vendor's empties.

    Sourced from the bottle ledger, not the rider registry, so riders who took a
    radar order without ever registering with the vendor are included. They were
    invisible before, which is exactly how bottles went missing.
    """
    from services.vendor_management_service import get_vendor_bottle_debtors

    return await get_vendor_bottle_debtors(session=db, clerk_id=user["sub"], vendor_id=vendor.id)


@router.get("/bottle-ledger")
async def vendor_bottle_ledger(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(get_active_store),
):
    """Audit trail of every bottle movement for this vendor."""
    from services.bottle_ledger_service import get_ledger_history

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
    user=Depends(get_current_user),
    vendor: Vendor = Depends(get_active_store),
):
    clerk_id = user["sub"]

    from core.redis_client import cache_get, cache_set

    # Keyed on the *store*, not the account. Keying on clerk_id served store A's
    # catalogue to store B for 60 seconds after a switch — and to a staff member
    # who can reach only one of them.
    cache_key = f"vendor_products:{vendor.id}:{search_query}:{stock_filter}:{limit}:{offset}"
    cached = await cache_get(cache_key)
    if cached:
        return cached

    products = await get_vendor_products(
        session=db,
        clerk_id=clerk_id,
        search_query=search_query,
        stock_filter=stock_filter,
        limit=limit,
        offset=offset,
        vendor_id=vendor.id,
    )

    result = {
        "items": [_signed(safe_serialize(p), "image_url") for p in products],
        "limit": limit,
        "offset": offset,
        # The page is short => there is nothing after it. Cheaper and racier-safe
        # than a COUNT(*) on every keystroke of the search box.
        "has_more": len(products) == limit,
    }
    await cache_set(cache_key, result, ttl_seconds=60) # Cache for 60 seconds
    return result


@router.get("/orders", response_model=PaginatedOrders)
async def vendor_get_orders(
    search_query: Optional[str] = Query(None, description="Search query for order ID"),
    status_filter: str = Query("All", description="Filter by status: All, pending, accepted, preparing, ready, cancelled"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(get_active_store),
):
    """One page of this store's orders.

    The envelope used to be `{"pages": [orders]}` — the server pretending to be a
    React Query `InfiniteData`. Every consumer then unwrapped `data.pages[0]`,
    which meant the *second* page silently replaced the first in one caller and
    the app had no way at all to know whether more existed; it guessed from
    `page.length < limit` after the unwrap.
    """
    clerk_id = user["sub"]
    orders = await get_vendor_orders(
        session=db,
        clerk_id=clerk_id,
        search_query=search_query,
        status_filter=status_filter,
        skip=skip,
        limit=limit,
        vendor_id=vendor.id,
    )
    return {
        "items": orders,
        "limit": limit,
        "offset": skip,
        "has_more": len(orders) == limit,
    }


@router.get("/orders/{order_id}")
async def vendor_get_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(get_active_store),
):
    """One order belonging to this store, with its items, customer and rider.

    There was no such endpoint. `OrderDetail/[id].tsx` found its order by
    scanning the list `GET /orders` had already returned — so an order past the
    first page did not exist as far as the detail screen was concerned, and
    opening it from a search result rendered "Order not found" over a live order
    the vendor was being asked to prepare.
    """
    from sqlalchemy.orm import joinedload

    from models.order_model import Order, OrderItem

    result = await db.execute(
        select(Order)
        .where(Order.id == order_id, Order.vendor_id == vendor.id)
        .options(
            joinedload(Order.order_item).joinedload(OrderItem.product),
            joinedload(Order.user),
            joinedload(Order.deliverer),
        )
    )
    order = result.unique().scalars().first()
    if not order:
        # 404 rather than 403 for another store's order: whether that id exists
        # is not something this caller gets to learn.
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@router.get("/orders/{order_id}/review")
async def vendor_order_review(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(get_active_store),
):
    """Why an order is parked in `pending_review` or `mismatch_pending`.

    Both states are reachable in ordinary operation — a rider flags a damaged
    empty (`POST /api/rider/orders/{id}/bottle-rejection`) or reports the
    customer understated their floor (`.../mismatch`) — and the order stops
    there until it is resolved.

    The vendor app had no representation of either: neither string appeared in
    its status colour maps or its filters, so the order showed a blank pill and
    no explanation while the vendor's stock was committed and their money
    pending. This is the missing half — the rider's stated reason and their
    photographs, so the vendor can see what is actually being reviewed.

    Read-only. Resolving a bottle rejection is an admin decision (and the ARQ
    sweep `jobs/auto_resolve_bottle_rejections.py` times it out); the vendor
    seeing it is not the same as the vendor adjudicating it.
    """
    from models.bottle_rejection_model import BottleRejectionTicket
    from models.order_model import Order

    order = await db.get(Order, order_id)
    if not order or order.vendor_id != vendor.id:
        raise HTTPException(status_code=404, detail="Order not found")

    result = await db.execute(
        select(BottleRejectionTicket)
        .where(BottleRejectionTicket.order_id == order_id)
        .order_by(BottleRejectionTicket.created_at.desc())
        .limit(1)
    )
    ticket = result.scalars().first()

    payload = {
        "order_status": order.order_status,
        "actual_floor_level": getattr(order, "actual_floor_level", None),
        "bottle_rejection": None,
    }

    if ticket:
        from utils.s3_utils import generate_presigned_url

        payload["bottle_rejection"] = {
            "id": str(ticket.id),
            "status": getattr(ticket.status, "value", str(ticket.status)),
            "reason_text": ticket.reason_text,
            # Stored as S3 keys; signed here for 15 minutes like every other
            # image on the platform.
            "photo_urls": [
                url if str(url).startswith("http") else generate_presigned_url(url)
                for url in (ticket.photo_urls or [])
            ],
            "created_at": ticket.created_at.isoformat() if ticket.created_at else None,
        }

    return payload


@router.put("/orders/{order_id}/status")
async def vendor_update_order_status(
    order_id: UUID,
    body: OrderStatusRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(require_permission("manage_orders")),
):
    clerk_id = user["sub"]
    result = await update_order_status(session=db, clerk_id=clerk_id, order_id=order_id, new_status=body.status, vendor_id=vendor.id)
    return result


@router.get("/wallet-summary")
async def vendor_wallet_summary(
    db: AsyncSession = Depends(get_db),
    vendor: Vendor = Depends(require_permission("view_finances")),
):
    """Balance, float committed to open cash orders, and what is withdrawable.

    On a wholesale cash order the vendor's own in-house rider collects the cash
    and the platform's cut is debited from the *vendor's* wallet at delivery —
    so it is committed from the moment the order is accepted, and is not the
    vendor's to withdraw in the meantime.

    `settlement_service` has computed this for vendors all along
    (`committed_cash_float_for_vendor`), and `request_payout` refuses on it. What
    was missing was any way for the vendor to *see* it: the app showed the raw
    `wallet_balance`, so a refusal read as the platform withholding money it had
    just displayed. The rider app has had this endpoint; the vendor app had no
    equivalent.

    Staff may read this — they need to know whether the store can accept a cash
    order. Only the owner can act on it (`POST /api/payouts/request`).
    """
    from decimal import Decimal

    from services.settlement_service import available_for_payout, committed_cash_float_for_vendor

    balance = Decimal(str(vendor.wallet_balance or 0))
    committed = await committed_cash_float_for_vendor(db, vendor.id)
    available = await available_for_payout(
        db, provider_id=vendor.id, provider_type="vendor", wallet_balance=balance,
    )

    return {
        "wallet_balance": float(balance),
        "committed_cash_float": float(committed),
        "available_for_withdrawal": float(available),
        # Negative means the store owes the platform — settle before it can
        # accept further cash orders.
        "is_in_arrears": balance < 0,
    }


#: What a browser will render inline. Anything else — SVG in particular, which
#: can carry script — must not be served back from our own origin.
_ALLOWED_IMAGE_KINDS = {"jpeg", "png", "webp", "gif"}


@router.post("/upload-image")
async def vendor_upload_image(
    file: UploadFile = File(...),
    vendor: Vendor = Depends(require_permission("manage_products")),
):
    """Store a product photo or store avatar, and return its S3 key.

    Replaces an **unsigned** Cloudinary upload preset that shipped in the app
    bundle. `upload_preset: "drop_uploads"` with no signature means anyone who
    unzips the APK can upload arbitrary files to the account, at the account
    owner's expense, from any machine — and nothing in the request identified the
    vendor, so nothing could be attributed or revoked short of deleting the
    preset for everybody.

    Returns the S3 **key**, not a URL, matching every other upload on the
    platform: the response schemas presign it for 15 minutes on the way out
    (`BaseProduct.image_url`, `BaseVendor.profile_pic`). `secure_url` is kept in
    the response body because that is the field name the apps already read.
    """
    import imghdr

    header = await file.read(512)
    await file.seek(0)
    kind = imghdr.what(None, h=header)
    # imghdr predates WebP; expo-image-manipulator emits it, so accept the RIFF
    # container explicitly rather than rejecting the app's own output.
    is_webp = header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    if not (kind in _ALLOWED_IMAGE_KINDS or is_webp):
        raise HTTPException(status_code=400, detail="Upload a JPG, PNG or WebP image.")

    from utils.s3_utils import upload_file_to_s3

    key = await upload_file_to_s3(file, prefix=f"vendors/{vendor.id}")
    if not key:
        raise HTTPException(status_code=500, detail="Could not save that image. Please try again.")

    return {"url": key, "secure_url": key}


@router.get("/dashboard")
async def vendor_dashboard(
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(get_active_store),
):
    clerk_id = user["sub"]
    return await get_vendor_dashboard(session=db, clerk_id=clerk_id, vendor_id=vendor.id)


@router.put("/orders/{order_id}/cancel")
async def vendor_cancel_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(require_permission("manage_orders")),
):
    """Cancel an order before preparation"""
    clerk_id = user["sub"]
    result = await cancel_order(session=db, clerk_id=clerk_id, order_id=order_id, vendor_id=vendor.id)
    return result

@router.put("/orders/{order_id}/assign-rider")
async def vendor_assign_rider(
    order_id: UUID,
    body: AssignRiderRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
    vendor: Vendor = Depends(require_permission("manage_orders")),
):
    """Assign an order to a specific rider"""
    clerk_id = user["sub"]
    result = await assign_order_rider(session=db, clerk_id=clerk_id, order_id=order_id, rider_id=body.deliverer_id, vendor_id=vendor.id)
    return result
