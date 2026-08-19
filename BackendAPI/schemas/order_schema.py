from pydantic import BaseModel
from uuid import UUID
from decimal import Decimal
from schemas.user_schemas import CustomerPublicProfile
from datetime import datetime
from pydantic import field_validator
from utils.s3_utils import generate_presigned_url
from utils.money import MoneyField, OptionalMoneyField
from schemas.product_schemas import OrderProductDetail
from typing import List, Optional


class OrderItemBase(BaseModel):
  id: UUID
  order_id: UUID
  product_id: UUID
  quantity: int
  price: MoneyField
  Subtotal: MoneyField
  product: Optional[OrderProductDetail] = None
  
  model_config = {"from_attributes": True}


class OrderVendorSnippet(BaseModel):
  """Vendor data embedded in order responses — includes location_address for display (M-06 FIX)."""
  id: UUID
  business_name: str
  profile_pic: str | None = None
  vendor_type: str | None = None
  location_address: str | None = None
  lat: float | None = None
  lng: float | None = None
  rating: float | None = None
  phone_number: str | None = None

  model_config = {"from_attributes": True, "use_enum_values": True}


class OrderDelivererSnippet(BaseModel):
  """Rider data embedded in order responses."""
  id: UUID
  full_name: str | None = None
  phone_number: str | None = None
  vehicle_details: str | None = None

  model_config = {"from_attributes": True}


class BaseOrder(BaseModel):
  id: UUID
  customer_id: UUID
  vendor_id: UUID
  deliverer_id: UUID | None = None
  delivery_address: str | None = None
  checkout_request_ID: str | None = None
  phone: str | None = None
  lat_from: float | None = None
  lng_from: float | None = None
  lat: float | None = None
  lng: float | None = None
  total_amount: OptionalMoneyField = None
  order_status: str | None = None
  payment_status: str | None = None
  payment_method: str | None = None
  delivery_fee: OptionalMoneyField = None
  delivery_time: int | None = None
  delivery_type: str | None = "quick_swap"
  bottle_source: str | None = "platform"
  is_welcome_offer: bool | None = False
  customer_note: str | None = None
  proof_url: str | None = None

  # ── Financial Breakdown ──
  rider_net: MoneyField = Decimal("0")
  rider_commission: MoneyField = Decimal("0")
  vendor_commission: MoneyField = Decimal("0")
  service_fee: MoneyField = Decimal("0")
  surge_fee: MoneyField = Decimal("0")
  delivery_markup: MoneyField = Decimal("0")
  platform_total: MoneyField = Decimal("0")
  vendor_net: MoneyField = Decimal("0")
  payload_surcharge: MoneyField = Decimal("0")
  staircase_surcharge: MoneyField = Decimal("0")
  distance_km: float | None = 0.0
  vehicle_class: str | None = "motorbike"

  # ── Discount Audit Trail (H-07 FIX) ──
  wallet_discount: MoneyField = Decimal("0")
  welcome_discount: MoneyField = Decimal("0")
  product_subtotal: MoneyField = Decimal("0")

  # ── Deposits and debt ──
  # Both are columns on `Orders`, written by `create_order` from the quote, and
  # neither was on this schema — so no screen anywhere could render them. On any
  # `new_bottle` order the deposit is the largest single line on the bill, and it
  # was simply absent from the customer's order detail and from the vendor's copy
  # of the same order: two breakdowns that could not add up to the
  # `total_amount` printed underneath them, on the record a delivery dispute is
  # settled from weeks later.
  bottle_deposit: MoneyField = Decimal("0")
  debt_settlement: MoneyField = Decimal("0")

  #: What approving an address mismatch would add to this order, from
  #: `order_service.staircase_shortfall` — the same function that applies it.
  #: The app quoted a flat "KSh 30" in the explanation and on the approve
  #: button, which is a consent control naming a figure the platform does not
  #: necessarily charge.
  pending_staircase_charge: MoneyField = Decimal("0")

  # ── Review state ──
  # The client has always typed `is_rated` on its Order interface, but nothing
  # ever populated it, so the "Rate this order" action was offered forever.
  # Computed from the order's reviews; see `fetch_orders_by_id`.
  is_rated: bool = False

  # ── Relationships (C-02 FIX) ──
  vendor: Optional[OrderVendorSnippet] = None
  deliverer: Optional[OrderDelivererSnippet] = None
  order_item: List[OrderItemBase] = []

  created_at: datetime
  updated_at: datetime | None = None

  @field_validator('proof_url', mode='after')
  @classmethod
  def secure_proof_url(cls, v: str | None) -> str | None:
      if v and not v.startswith('http') and not v.startswith('/api/uploads/'):
          return generate_presigned_url(v)
      return v

  model_config = {"from_attributes": True}


class OrderWithDetails(BaseOrder):
    user: Optional[CustomerPublicProfile] = None
    distance_km: Optional[float] = None
    
    model_config = {"from_attributes": True}


class PaginatedOrders(BaseModel):
    """One page of orders, described honestly.

    This used to be `pages: List[List[OrderWithDetails]]` — the server imitating
    React Query's `InfiniteData` envelope. It carried no page metadata at all, so
    the client inferred "there is more" from `page.length === limit` *after*
    unwrapping `data.pages[0]`, and one caller dropped every page but the first.
    """

    items: List[OrderWithDetails]
    limit: int
    offset: int
    #: A full page implies there may be another. Deliberately not a COUNT(*):
    #: an exact total costs a second scan of the orders table on every poll.
    has_more: bool

    model_config = {"from_attributes": True}

