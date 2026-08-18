from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from models.vendor_model import Vendor
from schemas.vendor_schemas import CreateVendor
from services.vendor_service import set_vendor_position

async def get_existing_vendor(clerk_id: str, db: AsyncSession):
    """This caller's own store — the oldest one, deterministically.

    Never `scalar_one_or_none()`: a `Vendor` row is a store, not an account, and
    one Clerk identity may own several. That call raises `MultipleResultsFound`
    on the second store, and this function backs `POST /api/auth/create_vendor`
    — the endpoint the vendor app's onboarding posts to — so an owner who had
    opened a branch got a 500 from the one screen they cannot get past.

    Ordered rather than a bare `.first()` so the store resolved is the same one
    on every request, whatever plan Postgres picks. `created_at` is NULL on rows
    predating that column and Postgres sorts NULLs last for ASC, so the id
    tiebreak keeps the answer stable either way.
    """
    query = (
        select(Vendor)
        .where(Vendor.clerk_id == clerk_id)
        .order_by(Vendor.created_at.asc(), Vendor.id.asc())
        .limit(1)
    )
    result = await db.execute(query)
    return result.scalars().first()

async def create_vendor(db: AsyncSession, data: CreateVendor):
    new_vendor = Vendor(
        clerk_id=data.clerk_id,
        email=data.email,
        owners_name=data.owners_name,
        business_name=data.business_name,
        phone_number=data.phone_number,
        vendor_type=data.vendor_type,
        business_license=data.business_license,
        profile_pic=data.profile_pic,
        location_address=data.location_address,
        verification_status="pending"
    )
    if data.lat is not None and data.lng is not None:
        # Through the one writer. This path set `lat`, `lng` and the H3 cell and
        # never `location` — the PostGIS column every distance query measures
        # against — so a store created here was in the ring and outside every
        # radius test that follows it.
        set_vendor_position(new_vendor, data.lat, data.lng)
    if data.shift_start is not None:
        new_vendor.shift_start = data.shift_start
    if data.shift_end is not None:
        new_vendor.shift_end = data.shift_end
    db.add(new_vendor)
    await db.commit()
    await db.refresh(new_vendor)
    return new_vendor
