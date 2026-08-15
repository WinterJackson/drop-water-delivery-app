from pydantic import BaseModel, EmailStr
from uuid import UUID
from pydantic import field_validator
from utils.s3_utils import generate_presigned_url, public_asset_url
from decimal import Decimal
from utils.money import MoneyField
from typing import Literal

class CreateDeliverer(BaseModel):
    clerk_id: str
    email: EmailStr
    name: str
    phone_number: str | None = None
    vehicle_type: Literal["motorbike", "tuktuk", "truck"] = "motorbike"
    plate_number: str | None = None
    employment_model: Literal["gig_economy", "in_house"] = "gig_economy"
    employer_vendor_id: UUID | None = None
    ID_number: str | None = None
    
    model_config = {"from_attributes": True}

class DelivererProfileResponse(BaseModel):
    id: UUID
    clerk_id: str | None = None
    name: str
    email: EmailStr
    phone_number: str | None = None
    profile_pic: str | None = None
    driver_license: str | None = None
    vehicle_type: str | None = None
    employment_model: str | None = None
    plate_number: str | None = None
    kyc_status: str | None = None
    current_lat: float | None = None
    current_lng: float | None = None
    operation_lat: float | None = None
    operation_lng: float | None = None
    preferences: dict | None = None
    payment_methods: list | None = None
    zone_changes_this_month: int | None = 0
    is_available: bool | None = None
    is_active: bool | None = None
    is_verified: bool | None = None
    is_platinum: bool | None = None
    rating: float | None = None
    acceptance_rate: float | None = None
    employer_vendor_id: UUID | None = None
    wallet_balance: MoneyField = Decimal("0")
    #: How far from their base a rider is offered work, in km — the same figure
    #: `rider_search_bounds` searches with, so the circle on `OperationBase`
    #: matches what dispatch actually does.
    #:
    #: Served rather than drawn from a literal because it is a business value,
    #: and this screen had it twice as a hardcoded `2`: once as the polygon it
    #: renders and once in the sentence "you will receive requests from vendors
    #: within a 2KM radius". Moving `retail_max_distance_km` on the console
    #: would have left a rider looking at a map, and reading a promise, that
    #: were both a kilometre short of the truth.
    operation_radius_km: float | None = None
    # Two fields, two treatments, and the difference is the whole point.
    #
    # A rider's avatar is a photograph shown to a customer watching a delivery —
    # not a secret, and re-signed on every response it was re-downloaded on every
    # response. A driving licence is an identity document: it stays presigned,
    # short-lived and unguessable, exactly as before.
    @field_validator('profile_pic', mode='after')
    @classmethod
    def public_image_urls(cls, v: str | None) -> str | None:
        if v and not v.startswith('http') and not v.startswith('/api/uploads/'):
            return public_asset_url(v)
        return v

    @field_validator('driver_license', mode='after')
    @classmethod
    def secure_urls(cls, v: str | None) -> str | None:
        if v and not v.startswith('http') and not v.startswith('/api/uploads/'):
            return generate_presigned_url(v)
        return v

    model_config = {"from_attributes": True}
