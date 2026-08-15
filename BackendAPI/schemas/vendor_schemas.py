from pydantic  import BaseModel, EmailStr
from uuid import UUID
from datetime import datetime, time
from utils.money import OptionalMoneyField
from schemas.product_schemas import ProductThin, BaseProduct
from models.vendor_model import VendorBusinessType
from pydantic import field_validator
from utils.s3_utils import public_asset_url
from typing import List

class CreateVendor(BaseModel):
    clerk_id: str
    email: EmailStr
    owners_name: str
    business_name: str
    phone_number: str | None = None
    vendor_type: VendorBusinessType = VendorBusinessType.retail_refill
    business_license: str | None = None
    profile_pic: str | None = None
    location_address: str | None = None
    lat: float | None = None
    lng: float | None = None
    shift_start: time | None = None
    shift_end: time | None = None


class StorefrontState(BaseModel):
  """Is this store taking orders, and on what terms?

  Stamped on by `vendor_availability.annotate`, never derived here. A
  `@computed_field` reading `is_online` and `paused_until` off the row would be
  a second implementation of the same question, and the second one is the one
  that forgets a suspension or the platform-wide cash override.

  Defaulted permissively so a read that forgets to annotate renders a store as
  open rather than silently closing it — enforcement lives at checkout and in
  `create_order`, both of which load the row and ask properly. These fields
  decide what a card *says*, not what the platform *allows*.

  One mixin rather than the same six fields on two schemas: the customer's list
  and the customer's store page are the two surfaces that have to agree, and a
  store shown open in the list and closed on its own page is the version of
  this bug people screenshot.
  """

  is_accepting_orders: bool = True
  #: open | paused | offline | closed_hours | suspended
  store_state: str = "open"
  #: The server's own sentence, rendered verbatim. `None` when open.
  store_reason: str | None = None
  reopens_at: datetime | None = None
  accepts_cash: bool = True
  min_order_value: OptionalMoneyField = None


class BaseVendor(StorefrontState):
  id: UUID
  business_name : str
  profile_pic : str | None = None
  vendor_type : VendorBusinessType | None = None
  lat: float | None = None
  lng: float | None = None
  rating : float | None = None

  @field_validator('profile_pic', mode='after')
  @classmethod
  def secure_urls(cls, v: str | None) -> str | None:
      if v and not v.startswith('http') and not v.startswith('/api/uploads/'):
          # `public_asset_url`, not `generate_presigned_url`. This is a
          # photograph, not a document: presigning it produced a different URL
          # in every response, which changes the cache key in every response,
          # which means every client re-downloads every image on every refresh.
          # See `utils/s3_utils.public_asset_url`.
          return public_asset_url(v)
      return v
  
  model_config = {"from_attributes": True, "use_enum_values": True}


class VendorWithProductsThin(BaseVendor):
  products : List[ProductThin]
  
  model_config = {"from_attributes": True}

class VendorStorefront(BaseVendor):
  """A store as a *customer* sees it — the shop, not the person who owns it.

  This replaces `VendorOut`, which was serving customer-facing reads. That
  carried `owners_name`, `email`, `phone_number` and `preferred_payment_method` — and
  that last one is the vendor's **payout destination** despite the name: their
  M-Pesa till, paybill or bank account. `POST /api/vendor_details_and_products`
  returned all four with no authentication dependency at all, and `GET
  /api/vendors` handed out every store id unauthenticated, so the two together
  were an owner-name-plus-phone-plus-till list for the whole vendor base,
  available to anyone who could reach the API. Name, number and till is
  precisely the kit for a convincing "Drop support" call.

  A customer needs the shop: what it is called, where it is, when it opens,
  what it sells and how it is rated. None of the four is rendered anywhere in
  the customer app — checked field by field before this was narrowed.

  `VendorOut` is deleted rather than left unused, because an existing schema
  that already has the fields is what the next customer-facing read would
  reach for.

  `verification_status` is also absent: it is an internal moderation state, and
  the storefront already tells a customer whether the shop is trading.
  """
  location_address: str | None = None
  shift_start: time
  shift_end: time

  model_config = {"from_attributes": True, "use_enum_values": True}

class VendorWithProductsFull(VendorStorefront):
  products : List[BaseProduct]

  model_config = {"from_attributes": True, "use_enum_values": True}

class RequestBodyCoordinates(BaseModel):
  lat: float
  lng: float
  location_address: str | None = None
  floor_level: int | None = None
  has_elevator: bool | None = None

  model_config = {"from_attributes": True}


class RequestBodyVendorId(BaseModel):
  id: UUID
  
  model_config = {"from_attributes": True}


class VendorType(BaseModel):
  vendor_type: VendorBusinessType
  # lat: float | None
  # lng: float | None
  
  model_config = {"from_attributes": True, "use_enum_values": True}