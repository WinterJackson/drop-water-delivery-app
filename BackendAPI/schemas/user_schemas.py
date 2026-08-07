from pydantic import BaseModel, EmailStr
from uuid import UUID
from datetime import time
from typing import List, Optional, Any
from pydantic import field_validator
from utils.s3_utils import generate_presigned_url

class BaseUser(BaseModel):
    clerk_id: str | None = None
    full_name : str | None = None
    email : str 
    phone_number : str | None = None
    profile_pic : str | None = None
    #: The handset this account was created on. Recorded once, at registration,
    #: and never updated — it gates the one-per-device welcome offer, and letting
    #: a client rewrite it would be the same as not having it.
    device_id : str | None = None
    
    @field_validator('profile_pic', mode='after')
    @classmethod
    def secure_urls(cls, v: str | None) -> str | None:
        if v and not v.startswith('http') and not v.startswith('/api/uploads/'):
            return generate_presigned_url(v)
        return v
    
    model_config = {"from_attributes": True}

class BasicUser(BaseUser):
    lat: float | None
    lng: float | None
    location_address: str | None
    id: UUID
    bottle_purchased_at: str | None = None
    bottle_refill_count: int | None = 0
    wallet_balance: float | None = 0.0
    floor_level: int | None = 0
    has_elevator: bool | None = False
    preferences: dict | None = None
    payment_methods: list | None = None
    
    model_config = {"from_attributes": True}

class CustomerPublicProfile(BaseModel):
    id: UUID
    full_name : str | None = None
    phone_number : str | None = None
    location_address: str | None = None
    floor_level: int | None = 0
    has_elevator: bool | None = False
    profile_pic : str | None = None

    @field_validator('profile_pic', mode='after')
    @classmethod
    def secure_urls(cls, v: str | None) -> str | None:
        if v and not v.startswith('http') and not v.startswith('/api/uploads/'):
            return generate_presigned_url(v)
        return v

    model_config = {"from_attributes": True}

class CreateUserResponse(BaseModel):
    message: str
    data: BaseUser
    
    model_config = {"from_attributes": True}
