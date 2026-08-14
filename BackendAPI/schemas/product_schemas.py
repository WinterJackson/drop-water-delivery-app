from pydantic import BaseModel, computed_field, field_validator
from uuid import UUID
from typing import Optional

from utils.s3_utils import public_asset_url
from utils.money import MoneyField


def _presign(v: str | None) -> str | None:
    """Turn a stored S3 key into a 15-minute signed URL.

    Product images used to go to an unsigned Cloudinary preset and were stored as
    public `https://` URLs; those still pass through untouched, so existing rows
    keep working. Anything that is not already a URL is an S3 key and must be
    signed here — `BaseVendor.profile_pic` has always done this, and product
    images were the one image on the platform that did not.
    """
    if v and not v.startswith("http") and not v.startswith("/api/uploads/"):
        # `public_asset_url`, not `generate_presigned_url`. This is a
        # photograph, not a document: presigning it produced a different URL
        # in every response, which changes the cache key in every response,
        # which means every client re-downloads every image on every refresh.
        # See `utils/s3_utils.public_asset_url`.
        return public_asset_url(v)
    return v


class BaseProduct(BaseModel):
  id: UUID
  vendor_id: UUID
  name: str
  image_url: str
  capacity: float
  weight_kg: float = 20.0
  minimum_order_qty: int = 1
  price: MoneyField
  discount: MoneyField
  stock: int

  @computed_field
  @property
  def stock_quantity(self) -> int:
    """Alias for `stock` — the frontend references this field name."""
    return self.stock

  @field_validator('image_url', mode='after')
  @classmethod
  def secure_urls(cls, v: str) -> str:
    return _presign(v) or v

  model_config = {"from_attributes": True}

class ProductThin(BaseModel):
  id: UUID
  vendor_id: UUID
  image_url: str

  @field_validator('image_url', mode='after')
  @classmethod
  def secure_urls(cls, v: str) -> str:
    return _presign(v) or v

  model_config = {"from_attributes": True}

class VendorSnippet(BaseModel):
  """Lightweight vendor data embedded in product detail responses."""
  id: UUID
  vendor_type: str | None = None
  business_name: str
  location_address: str | None = None
  lat: float | None = None
  lng: float | None = None
  rating: float | None = None
  profile_pic: str | None = None

  @field_validator('profile_pic', mode='after')
  @classmethod
  def secure_urls(cls, v: str | None) -> str | None:
    return _presign(v)

  model_config = {"from_attributes": True}


class OrderProductDetail(BaseProduct):
  description: str | None
  unit: str | None 
  is_available: bool
  
  model_config = {"from_attributes": True}


class ProductFull(BaseProduct):
  description: str | None
  unit: str | None 
  is_available: bool
  vendor: Optional[VendorSnippet] = None
  
  model_config = {"from_attributes": True}

class RequestBodyProductId(BaseModel):
  id: UUID
  
  model_config = {"from_attributes": True}