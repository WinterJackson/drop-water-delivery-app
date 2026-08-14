from db.session import Base
from datetime import time, datetime, timezone
import uuid
from geoalchemy2 import Geography
from sqlalchemy import Column, String, Text, Boolean, Numeric, TIMESTAMP, Float, Time, Integer, ARRAY, func, Index, Enum
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from enum import Enum as PyEnum
from sqlalchemy.orm import relationship

class VendorBusinessType(str, PyEnum):
    retail_refill = "retail_refill"
    wholesale_b2b = "wholesale_b2b"




class Vendor(Base):
  __tablename__ = "Vendors"
  __table_args__ = (
      Index('idx_vendor_location_gist', 'location', postgresql_using='gist'),
      Index('idx_vendor_type_rating', 'vendor_type', 'rating'),
      Index('idx_vendors_search_vector', 'search_vector', postgresql_using='gin'),
  )
  id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
  clerk_id = Column(String, nullable=True, index=True) # Removed unique constraint to allow multi-store
  staff_clerk_id = Column(String, nullable=True, unique=True, index=True) # Exactly 1 staff account allowed per store
  vendor_type = Column(Enum(VendorBusinessType, name="vendor_business_type", create_type=False), nullable=True, default=VendorBusinessType.retail_refill, index=True)
  owners_name = Column(String, nullable=False, index=True)
  business_name = Column(String, index=True, nullable=False)
  email = Column(String, unique=True, index=True, nullable=False) 
  phone_number = Column(String, index=True, nullable=True)  #will revisit 
  profile_pic = Column(Text, nullable=True)
  business_license = Column(Text, nullable=True)
  location_address = Column(Text, nullable=True, index=True)
  lat = Column(Float, nullable=True , index=True)
  lng = Column(Float, nullable=True , index=True)
  location = Column(Geography(geometry_type="POINT", srid=4326))
  shift_start = Column(Time, default=time(7,0), nullable=False, index=True)
  shift_end = Column(Time, default=time(19,0), nullable=False, index=True)
  verification_status = Column(String, default="pending")
  is_online = Column(Boolean, default=True, index=True)

  # ── Storefront controls, set by the vendor ────────────────────────────
  #
  # Three decisions that belong to whoever is standing in the shop, and that
  # the platform had no way to hear. `services/vendor_availability.py` is the
  # only thing that reads them; nothing else may re-derive "is this store
  # taking orders right now".
  #
  #: Whether this store will take a cash order. A store with no float, or one
  #: that has just been robbed, must be able to say no — and until this column
  #: existed it could not. **Not** `preferred_payment_method`: despite the
  #: name, that array is the vendor's *payout* destination (`MPESA_TILL`, a
  #: paybill, a bank account), written by `business/PayoutSettings.tsx`. The
  #: two have nothing to do with each other and conflating them would have
  #: pointed a customer's payment method at the vendor's bank details.
  accepts_cash = Column(Boolean, nullable=False, server_default="true", index=True)
  #: The smallest basket this store will prepare, before delivery and fees. A
  #: single KSH 60 bottle costs the store the same handling as a full crate.
  #: 0 means no minimum. Capped by `vendor_max_min_order_value` so a store
  #: cannot delist itself with a number while still appearing open.
  min_order_value = Column(Numeric(10, 2), nullable=False, server_default="0")
  #: A pause that ends by itself. `is_online` is the indefinite "we are shut"
  #: switch and it is the one people forget: a vendor taps it during a rush,
  #: the rush ends, and the store is dark until somebody notices the next
  #: morning. A pause carries its own expiry and the store reopens without
  #: anyone remembering to.
  paused_until = Column(TIMESTAMP(timezone=True), nullable=True, index=True)
  #: Shown to the customer. "Closed" with no reason reads as broken; "Back at
  #: 14:30 — restocking" reads as a shop.
  pause_reason = Column(String, nullable=True)

  # ── Account state, set by an administrator ─────────────────────────────
  #: A store had no way to be switched off. `verification_status` records how
  #: it *joined*; it says nothing about a store that has to stop trading today
  #: — for a health complaint, an unpaid arrears balance, or fraud. `is_online`
  #: is the vendor's own "we're closed right now" toggle and they can turn it
  #: straight back on, so it is not a control the platform can rely on.
  is_active = Column(Boolean, nullable=False, server_default="true", index=True)
  suspended_at = Column(TIMESTAMP(timezone=True), nullable=True)
  #: Shown to the vendor. A suspension nobody can explain becomes a support
  #: ticket, and an appeal with nothing to appeal against.
  suspension_reason = Column(Text, nullable=True)
  suspended_by = Column(UUID(as_uuid=True), nullable=True)
  # `rating` is the derived average. `rating_count`/`rating_sum` are what it is
  # derived *from*, maintained incrementally by `review_service` so submitting a
  # review costs one row update instead of an AVG over every review the target
  # has ever received. `rating_count` is also what the apps need to render
  # "4.8 (312)" — an average alone cannot distinguish one perfect review from
  # three hundred.
  rating = Column(Float, nullable=True, index=True, default=0)
  rating_count = Column(Integer, nullable=False, server_default='0')
  rating_sum = Column(Float, nullable=False, server_default='0')
  h3_index_res8 = Column(String(15), index=True, nullable=True)
  total_sales = Column(Integer, nullable=True, index=True)
  sales_amount = Column(Numeric(10, 2), nullable=True, index=True)
  wallet_balance = Column(Numeric(10, 2), nullable=False, default=0.0)
  deposit_fee = Column(Numeric(10, 2), nullable=False, default=600.0)
  wholesale_base_delivery_fee = Column(Numeric(10, 2), nullable=True, default=0.0)
  wholesale_per_km_fee = Column(Numeric(10, 2), nullable=True, default=0.0)
  empty_bottle_inventory = Column(Integer, nullable=False, default=0)
  full_bottle_inventory = Column(Integer, nullable=False, default=0)
  search_vector = Column(TSVECTOR)  # Optional if created directly in DB
  preferred_payment_method = Column(ARRAY(String), nullable=True, index=True)
  push_token = Column(String, nullable=True)
  staff_push_token = Column(String, nullable=True)  # Separate push token for staff member
  created_at= Column(TIMESTAMP(timezone=True), server_default=func.now())
  updated_at= Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
  
  # relationship
  # cart = relationship("Cart", back_populates="vendor")
  cart_item = relationship("CartItem", back_populates="vendor", lazy="raise_on_sql")
  products = relationship("Product", back_populates="vendor", lazy="raise_on_sql")
  order = relationship("Order", back_populates="vendor", lazy="raise_on_sql")
  vendor_favorites = relationship("VendorFavorite", back_populates="vendor", lazy="raise_on_sql")
  #: Many staff per store — see `models/vendor_staff_model.py`. The
  #: `staff_clerk_id` / `staff_push_token` columns below are the single-staff
  #: predecessor: they are backfilled into this table and no longer read.
  staff = relationship("VendorStaff", back_populates="vendor", cascade="all, delete-orphan", lazy="raise_on_sql")