from pydantic import BaseModel
from uuid import UUID
from decimal import Decimal
from schemas.product_schemas import ProductFull
from typing import List, Optional
from utils.money import MoneyField


class CartBase(BaseModel):
  id : UUID
  customer_id: UUID
  items_count: int
  total_amount: MoneyField
  
  model_config = {"from_attributes": True}

class CartItemBase(BaseModel):
  id: UUID 
  cart_id: UUID 
  vendor_id: UUID 
  product_id: UUID 
  quantity: int 
  price: MoneyField
  product: Optional[ProductFull] 
  
  model_config = {"from_attributes": True}

class CartDetailed(CartBase):
  cart_item: List[CartItemBase]
  welcome_discount_amount: MoneyField = Decimal("0")
  service_fee: MoneyField = Decimal("0")
  delivery_fee_quick_swap: MoneyField = Decimal("0")
  delivery_fee_keep_my_bottle: MoneyField = Decimal("0")

  # ── Rule metadata, so the cart screen can show limits instead of surfacing
  # them for the first time as a checkout error ──
  vendor_type: Optional[str] = None
  total_quantity: Optional[int] = 0
  total_weight_kg: Optional[float] = 0.0
  moq_kg: Optional[float] = None          # wholesale minimum order quantity
  moq_met: Optional[bool] = True
  max_units: Optional[int] = None         # retail per-trip bottle cap
  is_locked: Optional[bool] = False

  model_config = {"from_attributes": True}