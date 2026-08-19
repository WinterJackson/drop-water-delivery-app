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

class ProductsPage(BaseModel):
  """The offers envelope: a page of products and the window that produced it.

  These listings had no `response_model` at all, so FastAPI serialised the ORM
  rows through `jsonable_encoder` — every loaded column, whatever it was. That
  was survivable only while `Product.vendor` was unloaded. The moment it is
  eager-loaded (and it must be, because these cards quote a delivery estimate
  measured from the store) the encoder walks into the `Vendors` row and emits
  `owners_name`, `email`, `phone_number` and `preferred_payment_method` — the
  store's payout destination — to every customer, and into the Redis copy.

  Naming the shape is what stops that: `ProductFull.vendor` is a
  `VendorSnippet`, which is the storefront a customer may see.
  """
  data: list[ProductFull]
  limit: int
  offset: int


class CategoryProductsPage(ProductsPage):
  """The category envelope, which also reports how many products matched.

  `total_count`, not `total`. On this platform `total` is money — it is the
  frozen order total on `Orders` and the charged figure on a quote — and
  `MONEY_FIELDS` in `test_money_serialisation.py` treats a field of that name
  as a decimal string. A row count called `total` is both a guard failure and,
  worse, a genuinely ambiguous name sitting two lines from `limit` and
  `offset`.
  """
  total_count: int


class RequestBodyProductId(BaseModel):
  id: UUID
  
  model_config = {"from_attributes": True}