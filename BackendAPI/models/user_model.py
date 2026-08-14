from db.session import Base
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, Boolean, Enum, TIMESTAMP, Float, func, Integer, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from enum import Enum as PyEnum
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography


class VerificationStatus(str, PyEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class User(Base):
  __tablename__= "Users"
  __table_args__ = (
      Index('idx_user_location_gist', 'location', postgresql_using='gist'),
  )
  id = Column(UUID(as_uuid=True), primary_key=True, default= uuid.uuid4, index=True)
  clerk_id = Column(String, nullable=False, unique=True, index=True)
  full_name = Column(String, nullable=True, index=True)
  email= Column(String, nullable=False, unique=True)
  phone_number= Column(String, nullable=True)
  profile_pic= Column(Text, nullable=True)
  location_address= Column(Text, nullable=True)
  lat= Column(Float, nullable=True)
  lng= Column(Float, nullable=True)
  location = Column(Geography(geometry_type="POINT", srid=4326))
  h3_index_res8 = Column(String(16), nullable=True, index=True)
  is_active= Column(Boolean, default=True)
  verification_status= Column(Enum(VerificationStatus), default=VerificationStatus.PENDING)

  # ── Suspension, set by an administrator ───────────────────────────────
  #: `is_active` already existed but carried no explanation, so a disabled
  #: account was indistinguishable from one disabled by accident.
  suspended_at = Column(TIMESTAMP(timezone=True), nullable=True)
  suspension_reason = Column(Text, nullable=True)
  suspended_by = Column(UUID(as_uuid=True), nullable=True)
  push_token = Column(String(255), nullable=True)
  
  # Empty Bottle Management
  bottle_purchased_at = Column(TIMESTAMP(timezone=True), nullable=True)
  bottle_refill_count = Column(Integer, nullable=False, default=0)
  last_order_date = Column(TIMESTAMP(timezone=True), nullable=True)
  #: What the customer owes the platform: a late-cancellation penalty, or a
  #: staircase charge they approved after M-Pesa had already taken the total.
  #: Collected on their next order as a visible line item and cleared there; a
  #: balance at or above `max_customer_debt_before_block` refuses checkout
  #: instead. It is never the *only* way out — `finance.adjust` can write it off.
  debt_balance = Column(Numeric(10, 2), nullable=False, default=0)
  #: Refundable bottle deposits this customer has paid and not had back. The
  #: platform's liability to them, and the counterpart of the deposit folded
  #: into `vendor_net` on every order that charged one.
  bottle_deposit_balance = Column(Numeric(10, 2), nullable=False, server_default="0", default=0)
  #: How many bottles that deposit covers. Moves only in lockstep with
  #: `bottle_deposit_balance`, through `customer_bottle_service` — the count and
  #: the money are two views of one fact and must never be written apart.
  #:
  #: An earlier `empty_bottles_held` column was dropped by migration
  #: `3ba669eb21f3` while `jobs/stale_asset_monitor.py` was left reading it, so
  #: that job raised `AttributeError` on every run rather than merely finding
  #: nothing. The job now reads this column.
  bottles_held = Column(Integer, nullable=False, server_default="0", default=0)

  #: An office or a shop legitimately holds more bottles than a household, and
  #: the ceiling that protects the platform from one account farming deposits
  #: would otherwise refuse them at four. Set by an administrator; there is no
  #: self-service path to it, because it is a limit on our own exposure.
  is_commercial = Column(Boolean, nullable=False, server_default="false", default=False)

  #: The part of `wallet_balance` that may be **spent** but not **withdrawn**.
  #:
  #: A returned deposit is the platform giving back money it was holding, and if
  #: it came back as cash the deposit would be a money-transfer service: pay
  #: KSH 300 by M-Pesa, hand the bottle back, take KSH 300 out to a different
  #: phone. With the welcome discount on top it was profitable — 300 in, less a
  #: 90 discount, 300 back out. Credit that can buy water and cannot buy a
  #: withdrawal closes that without ever taking value away from the customer.
  #:
  #: Withdrawable is `wallet_balance − non_withdrawable_balance`, exactly the
  #: shape `settlement_service` already uses for a rider's committed cash float.
  #: Spending consumes this portion first, so the money genuinely does turn into
  #: water rather than sitting there restricting an ordinary top-up.
  non_withdrawable_balance = Column(Numeric(10, 2), nullable=False, server_default="0", default=0)

  #: Last time this customer's deposit position moved in either direction.
  #: Dormancy is measured from here rather than from `last_order_date`: someone
  #: who orders bottled water weekly on `exchange` never touches their deposit,
  #: and converting it while they are an active customer would be indefensible.
  deposit_last_activity_at = Column(TIMESTAMP(timezone=True), nullable=True)
  #: Latches the dormancy warnings so the sweep sends each one once rather than
  #: once per nightly run — the same mistake `low_stock_notified_at` exists to
  #: prevent on the vendor side.
  deposit_dormancy_warned_at = Column(TIMESTAMP(timezone=True), nullable=True)

  # Welcome Offer (First-Time Customer Incentive)
  has_used_welcome_offer = Column(Boolean, nullable=False, default=False)
  #: Anti-fraud: one welcome offer per handset.
  #:
  #: **Not unique.** It was, and that made the gate it exists for unreachable:
  #: `welcome_offer_available` looks for *another* account sharing this device,
  #: and a UNIQUE constraint guarantees there is never one. The check could not
  #: fire under any circumstances. It also meant a second person registering on
  #: a shared handset — a household with one phone, which is ordinary here —
  #: hit an integrity error on signup.
  #:
  #: Indexed, because the gate queries it on every first quote.
  device_id = Column(String, nullable=True, index=True)

  # Loyalty & Gamification (Anti-Poaching)
  wallet_balance = Column(Numeric(10, 2), nullable=False, default=0.0)
  
  # Address Modifiers (Surcharge Logic)
  floor_level = Column(Integer, nullable=False, default=0)  # 0 = Ground
  has_elevator = Column(Boolean, nullable=False, default=False)

  # Settings & Preferences
  preferences = Column(JSONB, nullable=False, server_default='{"order_updates": true, "promotions": false, "delivery_reminders": true, "analytics": true}')
  payment_methods = Column(JSONB, nullable=False, server_default='[]')

  created_at= Column(TIMESTAMP(timezone=True), server_default=func.now())
  updated_at= Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
  
  # relationships
  cart = relationship("Cart", back_populates="user", lazy="raise_on_sql")
  order = relationship("Order", back_populates="user", lazy="raise_on_sql")
  favorite = relationship("Favorite", back_populates="user", lazy="raise_on_sql")
  vendor_favorites = relationship("VendorFavorite", back_populates="user", lazy="raise_on_sql")
  saved_locations = relationship("SavedLocation", back_populates="user", cascade="all, delete-orphan", lazy="raise_on_sql")