from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel
from services.auth_service import  createUser
from services.user_service import  update_user_location, update_user_profile_pic
from services.vendor_auth_service import create_vendor as svc_create_vendor, get_existing_vendor
from services.rider_auth_service import create_rider as svc_create_rider, get_existing_rider
from services.email_service import send_welcome_email, send_vendor_approved
from models.user_model import User
from models.vendor_model import Vendor
from models.deliverer_model import Deliverer
from schemas.user_schemas import BaseUser
from schemas.vendor_schemas import RequestBodyCoordinates, CreateVendor
from schemas.deliverer_schemas import CreateDeliverer
from schemas.common_schemas import RequestBodyProfilePic
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from utils.find_user import get_existing_user, get_existing_user_by_email, get_user
from utils.serializers import safe_serialize
import asyncio
import logging
import os

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Account deletion: Clerk identity removal ──────────────────────────────────
# Anonymising the local row is only half of a deletion. While the Clerk identity
# survives, the user can sign in again and be re-provisioned as a brand new
# account, and their existing sessions stay valid. This used to be wrapped in a
# bare `if clerk_secret:` in all three delete flows, so an unset CLERK_SECRET_KEY
# skipped it silently while the endpoint still reported permanent deletion.


def _require_clerk_secret() -> str:
    """Read CLERK_SECRET_KEY, refusing the request when it is not configured.

    Called *before* any row is mutated. Discovering the misconfiguration after
    the local PII has already been anonymised would leave nothing to retry with:
    the row's `clerk_id` has been rewritten by then, so a second attempt cannot
    even find the account.
    """
    secret = os.getenv("CLERK_SECRET_KEY")
    if not secret:
        logger.error("Account deletion refused: CLERK_SECRET_KEY is not configured.")
        raise HTTPException(
            status_code=503,
            detail="Account deletion is temporarily unavailable. Please contact support.",
        )
    return secret


async def _delete_clerk_identity(clerk_secret: str, clerk_id: str) -> bool:
    """Delete the Clerk user and invalidate its sessions. True when it worked.

    `clerk_backend_api` is a synchronous SDK, so the call goes to a worker thread
    rather than blocking the event loop for the duration of an outbound HTTPS
    request.

    A failure here is not raised. The local anonymisation has already committed,
    which is the part the data-protection obligation actually attaches to, and
    reporting a 500 would tell the user their deletion failed when their PII is
    in fact gone — prompting a retry that can no longer find the account.
    """
    from clerk_backend_api import Clerk

    try:
        clerk = Clerk(bearer_auth=clerk_secret)
        await asyncio.to_thread(clerk.users.delete, clerk_id)
        return True
    except Exception as e:
        # Distinctive prefix: this needs manual cleanup in the Clerk dashboard,
        # so it should be alertable rather than lost among ordinary errors.
        logger.error(
            "CLERK_DELETE_FAILED clerk_id=%s — local data anonymised but the "
            "Clerk identity survives and must be removed manually: %s",
            clerk_id,
            e,
            exc_info=True,
        )
        return False


def _deletion_response(message: str, clerk_deleted: bool) -> dict:
    """Report honestly when the Clerk half did not complete."""
    if clerk_deleted:
        return {"message": message}
    return {
        "message": message,
        "warning": (
            "Your personal data has been erased, but sign-out across devices "
            "could not be completed automatically. Please contact support."
        ),
        "clerk_identity_deleted": False,
    }

def sanitize_phone_number(phone: str) -> str:
    if not phone:
        return phone
    # Strip spaces
    phone = phone.replace(" ", "").replace("-", "")
    # If starts with 0, replace with +254
    if phone.startswith("0") and len(phone) == 10:
        return "+254" + phone[1:]
    # If starts with 254 (no +)
    if phone.startswith("254") and len(phone) == 12:
        return "+" + phone
    return phone

# Import limiter from main app
from core.redis_client import redis_limiter as limiter

# CREATE USER 
@router.post("/create_user")
@limiter.limit("5/minute")
async def create_user(request: Request, user_data: BaseUser, session: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
  
  user_data.clerk_id = user["sub"]

  # check if user exists in the database 
  existing_user = await get_existing_user(clerk_id=user_data.clerk_id, db=session)
  if existing_user: 
    if user_data.phone_number:
        existing_user.phone_number = sanitize_phone_number(user_data.phone_number)
    if user_data.full_name:
        existing_user.full_name = user_data.full_name
    await session.commit()
    await session.refresh(existing_user)
    return {
      "message" : "User updated successfully",
      "data" : safe_serialize(existing_user)
    }

  existing_user_by_email = await get_existing_user_by_email(email=user_data.email, db=session)
  if existing_user_by_email: 
    raise HTTPException(status_code=400, detail="User by this email already exists")

  # if not create new user 
  if user_data.phone_number:
      user_data.phone_number = sanitize_phone_number(user_data.phone_number)
  user = await createUser(db=session, data= user_data)
  
  # Send welcome email asynchronously-ish (fire and forget for now)
  send_welcome_email(to=user_data.email, name=user_data.full_name, app_type="customer")

  return{
    "message" : "user created successfully",
    "data" : safe_serialize(user) 
  }


@router.post("/update_user_location")
async def update_location(coordinates : RequestBodyCoordinates , db : AsyncSession = Depends(get_db), user = Depends(get_current_user)):
  clerk_id = user["sub"]
  await update_user_location(session=db, data=coordinates, clerk_id=clerk_id)
  return {
    "message": "location updated successfully"
  }

@router.post("/revoke_user_location")
async def revoke_location(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
  clerk_id = user["sub"]
  existing_user = await get_existing_user(clerk_id=clerk_id, db=db)
  if existing_user:
      existing_user.lat = None
      existing_user.lng = None
      existing_user.location_address = None
      existing_user.location = None
      await db.commit()
  return {"message": "Location revoked successfully"}

@router.get("/get_user_details")
async def get_user_details(db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
  clerk_id = user["sub"]
  user = await get_user(clerk_id= clerk_id , db=db)
  return user

@router.post("/update_profile_pic")
async def change_user_profile_pic( response_body: RequestBodyProfilePic, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
  clerk_id = user["sub"]
  await update_user_profile_pic(session=db, profile_pic=response_body.profile_pic, clerk_id=clerk_id)
  return {
    "message" : "Profile Picture Updated Successfully"
  }

@router.post("/create_vendor")
@limiter.limit("5/minute")
async def register_vendor(request: Request, vendor_data: CreateVendor, session: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
  # Identity comes from the verified token, never the request body.
  #
  # This endpoint had no auth dependency at all and trusted `vendor_data.clerk_id`.
  # Two consequences: any Clerk user could mint themselves a Vendor row and
  # instantly pass `get_current_vendor` (customer → vendor privilege escalation),
  # and anyone who learned a vendor's clerk_id could POST here unauthenticated to
  # overwrite that vendor's phone number, business name, location and licence via
  # the update branch below. Both apps already send the bearer token; only the
  # server was not checking it.
  vendor_data.clerk_id = user["sub"]

  existing_vendor = await get_existing_vendor(clerk_id=vendor_data.clerk_id, db=session)
  if existing_vendor:
    if vendor_data.phone_number:
        existing_vendor.phone_number = sanitize_phone_number(vendor_data.phone_number)
    if vendor_data.business_name:
        existing_vendor.business_name = vendor_data.business_name
    if vendor_data.vendor_type:
        existing_vendor.vendor_type = vendor_data.vendor_type
    if vendor_data.lat and vendor_data.lng:
        existing_vendor.lat = vendor_data.lat
        existing_vendor.lng = vendor_data.lng
        existing_vendor.location_address = vendor_data.location_address
        existing_vendor.location = f"POINT({vendor_data.lng} {vendor_data.lat})"
    if vendor_data.profile_pic:
        existing_vendor.profile_pic = vendor_data.profile_pic
    if vendor_data.shift_start:
        existing_vendor.shift_start = vendor_data.shift_start
    if vendor_data.shift_end:
        existing_vendor.shift_end = vendor_data.shift_end
    if vendor_data.business_license:
        existing_vendor.business_license = vendor_data.business_license
    
    # Auto-activate vendor instantly after onboarding
    existing_vendor.verification_status = "verified"
    await session.commit()
    await session.refresh(existing_vendor)
    return {"message" : "Vendor updated successfully", "data": safe_serialize(existing_vendor)}

  if vendor_data.phone_number:
      vendor_data.phone_number = sanitize_phone_number(vendor_data.phone_number)
  vendor = await svc_create_vendor(db=session, data=vendor_data)
  
  # Send welcome email
  send_welcome_email(to=vendor_data.email, name=vendor_data.owners_name, app_type="vendor")
  send_vendor_approved(to=vendor_data.email, name=vendor_data.owners_name)
  
  return {
    "message" : "Vendor created successfully",
    "data" : safe_serialize(vendor) 
  }

@router.post("/create_rider")
@limiter.limit("5/minute")
async def register_rider(request: Request, rider_data: CreateDeliverer, session: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
  # Identity comes from the verified token, never the request body. Unauthenticated
  # callers could previously overwrite an existing rider's phone number, ID number,
  # vehicle and plate by supplying their clerk_id, and flip is_active/is_verified.
  rider_data.clerk_id = user["sub"]

  existing_rider = await get_existing_rider(clerk_id=rider_data.clerk_id, db=session)
  if existing_rider: 
    if rider_data.phone_number:
        existing_rider.phone_number = sanitize_phone_number(rider_data.phone_number)
    if rider_data.ID_number:
        existing_rider.ID_number = rider_data.ID_number
    if rider_data.vehicle_type:
        existing_rider.vehicle_type = rider_data.vehicle_type
    if rider_data.plate_number:
        existing_rider.plate_number = rider_data.plate_number
    
    # Auto-activate rider instantly after onboarding
    existing_rider.is_active = True
    existing_rider.is_verified = True
    await session.commit()
    await session.refresh(existing_rider)
    return {"message" : "Rider updated successfully", "data": safe_serialize(existing_rider)}

  if not rider_data.ID_number:
      raise HTTPException(status_code=422, detail="ID_number is required for new riders.")

  if rider_data.phone_number:
      rider_data.phone_number = sanitize_phone_number(rider_data.phone_number)
  rider = await svc_create_rider(db=session, data=rider_data)
  
  # Send welcome email
  send_welcome_email(to=rider_data.email, name=rider_data.name, app_type="rider")
  
  return {
    "message" : "Rider created successfully",
    "data" : safe_serialize(rider) 
  }

# ─── Customer Profile Update ────────────────────────────────────────────────
class UpdateUserRequest(BaseModel):
    full_name: str | None = None
    phone_number: str | None = None
    preferences: dict | None = None
    payment_methods: list | None = None
    floor_level: int | None = None
    has_elevator: bool | None = None

@router.put("/update_user")
async def update_user(
    body: UpdateUserRequest,
    session: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    clerk_id = user["sub"]
    result = await session.execute(select(User).where(User.clerk_id == clerk_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.full_name is not None:
        db_user.full_name = body.full_name
    if body.phone_number is not None:
        db_user.phone_number = sanitize_phone_number(body.phone_number)
    if body.preferences is not None:
        db_user.preferences = body.preferences
    if body.payment_methods is not None:
        db_user.payment_methods = body.payment_methods
    if body.floor_level is not None:
        db_user.floor_level = body.floor_level
    if body.has_elevator is not None:
        db_user.has_elevator = body.has_elevator

    await session.commit()
    await session.refresh(db_user)
    return {"message": "Profile updated successfully", "data": safe_serialize(db_user)}


# ─── GDPR-Compliant Account Deletion (Soft Delete + Anonymization) ──────────
class DeleteAccountRequest(BaseModel):
    app_type: str  # "customer" | "vendor" | "rider"
    confirmation: str  # Must be "DELETE MY ACCOUNT"

@router.delete("/delete_account")
async def delete_account(
    body: DeleteAccountRequest,
    session: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Soft-deletes a user account by anonymizing all PII and deactivating the record.
    Preserves the UUID for referential integrity with Orders, Payments, and Payouts.
    Blocks deletion if the user has active/pending orders.
    """
    clerk_id = user["sub"]

    if body.confirmation != "DELETE MY ACCOUNT":
        raise HTTPException(status_code=400, detail="Confirmation text must be exactly 'DELETE MY ACCOUNT'")

    # Fail before touching a single row. Once the anonymisation commits, the
    # row's clerk_id is rewritten and the Clerk identity can no longer be
    # located from it — so a missing secret has to stop the request here.
    clerk_secret = _require_clerk_secret()

    from models.order_model import Order
    from services.order_service import ACTIVE_ORDER_STATUSES, IN_FLIGHT_DELIVERY_STATUSES

    if body.app_type == "customer":
        result = await session.execute(select(User).where(User.clerk_id == clerk_id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Block if pending orders exist
        pending = await session.execute(
            select(Order).where(
                Order.customer_id == db_user.id,
                Order.order_status.in_(ACTIVE_ORDER_STATUSES)
            )
        )
        if pending.scalars().first():
            raise HTTPException(status_code=400, detail="Cannot delete account while you have active orders. Please wait for all orders to complete.")

        # Anonymize PII
        db_user.full_name = "Deleted User"
        db_user.email = f"deleted_{db_user.id}@drop.local"
        db_user.phone_number = None
        db_user.profile_pic = None
        db_user.clerk_id = f"deleted_{db_user.id}"
        db_user.push_token = None
        db_user.is_active = False
        db_user.location_address = None
        db_user.lat = None
        db_user.lng = None
        db_user.location = None
        db_user.payment_methods = []
        db_user.preferences = {}

        await session.commit()
        
        # SEC-05 FIX: Invalidate Clerk Sessions
        clerk_deleted = await _delete_clerk_identity(clerk_secret, clerk_id)

        return _deletion_response(
            "Your account has been permanently deleted and all personal data anonymized.",
            clerk_deleted,
        )

    elif body.app_type == "vendor":
        # Every store this account owns, not one of them. `scalar_one_or_none()`
        # raised MultipleResultsFound for an owner with a second store, so
        # deleting the account 500'd; and had it not, the request would have
        # anonymised one store and left the other trading under an account whose
        # Clerk identity was about to be destroyed.
        result = await session.execute(
            select(Vendor)
            .where(Vendor.clerk_id == clerk_id)
            .order_by(Vendor.created_at.asc(), Vendor.id.asc())
        )
        stores = result.scalars().all()
        if not stores:
            raise HTTPException(status_code=404, detail="Vendor not found")

        # Block if unfulfilled orders exist — on any of them.
        pending = await session.execute(
            select(Order).where(
                Order.vendor_id.in_([s.id for s in stores]),
                Order.order_status.in_(ACTIVE_ORDER_STATUSES)
            )
        )
        if pending.scalars().first():
            raise HTTPException(status_code=400, detail="Cannot delete account while you have unfulfilled orders. Please complete or cancel all pending orders first.")

        from services.vendor_staff_service import revoke_all_for_store

        for db_vendor in stores:
            # Anonymize PII
            db_vendor.owners_name = "Deleted Vendor"
            db_vendor.business_name = "Deleted Store"
            db_vendor.email = f"deleted_{db_vendor.id}@drop.local"
            db_vendor.phone_number = None
            db_vendor.profile_pic = None
            db_vendor.clerk_id = f"deleted_{db_vendor.id}"
            # Otherwise every staff member keeps a live grant to a deleted
            # store: the resolver matches their membership row and never looks
            # at `verification_status`.
            await revoke_all_for_store(session, db_vendor.id)
            db_vendor.push_token = None
            db_vendor.verification_status = "deleted"
            db_vendor.location_address = None
            db_vendor.lat = None
            db_vendor.lng = None
            db_vendor.location = None
            db_vendor.business_license = None
            db_vendor.payment_methods = []

        await session.commit()
        
        # SEC-05 FIX: Invalidate Clerk Sessions
        clerk_deleted = await _delete_clerk_identity(clerk_secret, clerk_id)

        return _deletion_response(
            "Your vendor account has been permanently deleted and all personal data anonymized.",
            clerk_deleted,
        )

    elif body.app_type == "rider":
        result = await session.execute(select(Deliverer).where(Deliverer.clerk_id == clerk_id))
        db_rider = result.scalar_one_or_none()
        if not db_rider:
            raise HTTPException(status_code=404, detail="Rider not found")

        # Block if mid-delivery
        pending = await session.execute(
            select(Order).where(
                Order.deliverer_id == db_rider.id,
                Order.order_status.in_(IN_FLIGHT_DELIVERY_STATUSES)
            )
        )
        if pending.scalars().first():
            raise HTTPException(status_code=400, detail="Cannot delete account while you have active deliveries. Please complete all deliveries first.")

        # Anonymize PII
        db_rider.name = "Deleted Rider"
        db_rider.email = f"deleted_{db_rider.id}@drop.local"
        db_rider.phone_number = None
        db_rider.profile_pic = None
        db_rider.clerk_id = f"deleted_{db_rider.id}"
        db_rider.push_token = None
        db_rider.is_active = False
        db_rider.is_available = False
        db_rider.is_verified = False
        db_rider.ID_number = "REDACTED"
        db_rider.driver_license = None
        db_rider.plate_number = "REDACTED"
        db_rider.current_lat = None
        db_rider.current_lng = None
        db_rider.operation_lat = None
        db_rider.operation_lng = None
        db_rider.location = None
        db_rider.payment_methods = []
        db_rider.preferences = {}

        await session.commit()
        
        # SEC-05 FIX: Invalidate Clerk Sessions
        clerk_deleted = await _delete_clerk_identity(clerk_secret, clerk_id)

        return _deletion_response(
            "Your rider account has been permanently deleted and all personal data anonymized.",
            clerk_deleted,
        )

    raise HTTPException(status_code=400, detail="Invalid app_type. Must be 'customer', 'vendor', or 'rider'.")


@router.get("/profile-status")
async def get_profile_status(app_type: str, db: AsyncSession = Depends(get_db), user = Depends(get_current_user)):
    clerk_id = user["sub"]
    missing_fields = []
    
    if app_type == "customer":
        result = await db.execute(select(User).where(User.clerk_id == clerk_id))
        db_user = result.scalar_one_or_none()
        if not db_user:
            return {"exists": False, "missing_fields": ["phone_number"]}
        if not db_user.phone_number:
            missing_fields.append("phone_number")
        
        return {"exists": True, "missing_fields": missing_fields, "data": safe_serialize(db_user)}
        
    elif app_type == "vendor":
        # Ordered + `.first()`, never `scalar_one_or_none()`: an owner may hold
        # several stores and `GET /api/vendor/stores` exists to list them.
        # `scalar_one_or_none` raised MultipleResultsFound on the second one, so
        # opening a branch turned app startup — which calls this first — into a
        # 500, and the client's `catch` sent the vendor back through onboarding.
        from services.vendor_management_service import get_all_vendors_by_clerk_id

        stores = await get_all_vendors_by_clerk_id(db, clerk_id)

        if not stores:
            # Signing in is where a pending staff invitation becomes real: the
            # owner invited an email address, and only now can the Clerk subject
            # behind it be learned. Attempted only on the no-store path, so the
            # Clerk round trip stays off every other request.
            from services.vendor_staff_service import bind_invitations_for_caller

            if await bind_invitations_for_caller(db, clerk_id):
                stores = await get_all_vendors_by_clerk_id(db, clerk_id)

        db_vendor = stores[0] if stores else None
        if not db_vendor:
            return {"exists": False, "missing_fields": ["business_name", "phone_number", "vendor_type", "location", "shift"]}
            
        if not db_vendor.business_name or db_vendor.business_name == "My Store":
            missing_fields.append("business_name")
        if not db_vendor.phone_number:
            missing_fields.append("phone_number")
        if not db_vendor.vendor_type:
            missing_fields.append("vendor_type")
        if not db_vendor.location_address or not db_vendor.lat or not db_vendor.lng:
            missing_fields.append("location")
            
        role = "owner" if db_vendor.clerk_id == clerk_id else "staff"
        vendor_data = safe_serialize(db_vendor)
        vendor_data["role"] = role
        return {"exists": True, "missing_fields": missing_fields, "data": vendor_data}
        
    elif app_type == "rider":
        result = await db.execute(select(Deliverer).where(Deliverer.clerk_id == clerk_id))
        db_rider = result.scalar_one_or_none()
        if not db_rider:
            return {"exists": False, "missing_fields": ["phone_number", "ID_number", "vehicle_type", "plate_number"]}
            
        if not db_rider.phone_number:
            missing_fields.append("phone_number")
        if not db_rider.ID_number or db_rider.ID_number == "PENDING":
            missing_fields.append("ID_number")
        if not db_rider.plate_number:
            missing_fields.append("plate_number")
            
        rider_data = safe_serialize(db_rider)
        rider_data.pop("ID_number", None)
        rider_data.pop("account_details", None)
        return {"exists": True, "missing_fields": missing_fields, "data": rider_data}

    raise HTTPException(status_code=400, detail="Invalid app_type")


# ─── Push Token Registration ─────────────────────────────────────────────────
class PushTokenBody(BaseModel):
    push_token: str
    app_type: str

@router.post("/push-token")
@limiter.limit("5/minute")
async def register_push_token(
    request: Request,
    body: PushTokenBody,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    """
    Register an Expo push token for the authenticated user.
    Searches User → Vendor → Deliverer tables by clerk_id.
    Called by all 3 mobile apps after sign-in.
    """
    clerk_id: str = user["sub"]
    token: str = body.push_token
    app_type: str = body.app_type

    if not token or not token.startswith("ExponentPushToken"):
        raise HTTPException(status_code=400, detail="Invalid Expo push token format")

    if app_type == "customer":
        result = await db.execute(select(User).where(User.clerk_id == clerk_id))
        db_user = result.scalar_one_or_none()
        if db_user:
            db_user.push_token = token
            await db.commit()
            logger.info(f"Push token saved for customer {clerk_id}")
            return {"message": "Push token registered"}
            
    elif app_type == "vendor":
        # Every store this account can reach, not one of them. The token belongs
        # to the *device*, and `Vendor.push_token` is per store — so an owner
        # with two branches only ever received notifications for whichever row
        # came back first, and `scalar_one_or_none` made the request 500 anyway.
        from services.vendor_staff_service import set_push_token

        owned = await db.execute(
            select(Vendor)
            .where(Vendor.clerk_id == clerk_id)
            .order_by(Vendor.created_at.asc(), Vendor.id.asc())
        )
        stores = owned.scalars().all()
        for store in stores:
            store.push_token = token

        # Staff hold their token on their own membership row, so a store with
        # several of them can reach all of them. `Vendor.staff_push_token` was
        # one column on the *store* and addressed whoever registered last.
        staffed = await set_push_token(db, clerk_id=clerk_id, token=token)

        if stores or staffed:
            await db.commit()
            logger.info(
                "Push token saved for vendor %s across %d owned / %d staffed store(s)",
                clerk_id, len(stores), staffed,
            )
            return {"message": "Push token registered"}
            
    elif app_type == "rider":
        result = await db.execute(select(Deliverer).where(Deliverer.clerk_id == clerk_id))
        db_rider = result.scalar_one_or_none()
        if db_rider:
            db_rider.push_token = token
            await db.commit()
            logger.info(f"Push token saved for rider {clerk_id}")
            return {"message": "Push token registered"}

    raise HTTPException(status_code=404, detail=f"Authenticated user not found for app_type: {app_type}")

@router.delete("/push-token")
async def clear_push_token(
    app_type: str = "customer",
    session: AsyncSession = Depends(get_db),
    user = Depends(get_current_user),
):
    clerk_id = user["sub"]
    if app_type == "vendor":
        # Mirror of registration: clear it everywhere it was written, or signing
        # out on one device leaves a second store still pushing to it.
        from services.vendor_staff_service import set_push_token

        result = await session.execute(select(Vendor).where(Vendor.clerk_id == clerk_id))
        for entity in result.scalars().all():
            entity.push_token = None
        await set_push_token(session, clerk_id=clerk_id, token=None)
    elif app_type == "rider":
        result = await session.execute(select(Deliverer).where(Deliverer.clerk_id == clerk_id))
        entity = result.scalar_one_or_none()
        if entity:
            entity.push_token = None
    else:
        result = await session.execute(select(User).where(User.clerk_id == clerk_id))
        entity = result.scalar_one_or_none()
        if entity:
            entity.push_token = None

    await session.commit()
    return {"message": "Push token cleared"}