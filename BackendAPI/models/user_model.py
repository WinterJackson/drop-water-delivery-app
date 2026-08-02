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
  debt_balance = Column(Numeric(10, 2), nullable=False, default=0)

  # Welcome Offer (First-Time Customer Incentive)
  has_used_welcome_offer = Column(Boolean, nullable=False, default=False)
  device_id = Column(String, nullable=True, unique=True, index=True)  # Anti-fraud: one offer per device

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
  cart = relationship("Cart", back_populates="user")
  order = relationship("Order", back_populates="user")
  favorite = relationship("Favorite", back_populates="user")
  vendor_favorites = relationship("VendorFavorite", back_populates="user")
  saved_locations = relationship("SavedLocation", back_populates="user", cascade="all, delete-orphan")