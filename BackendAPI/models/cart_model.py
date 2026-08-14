from db.session import Base
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, Boolean,Enum, TIMESTAMP, Float, Numeric, DateTime,Integer, ARRAY , ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from enum import Enum as PyEnum
from sqlalchemy.orm import relationship


class Cart(Base):
  __tablename__ = "Carts"
  id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
  customer_id = Column(UUID(as_uuid=True),ForeignKey("Users.id"), index=True)
  # vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id"), index=True)
  items_count = Column(Integer, default=0, nullable=False)
  total_amount = Column(Numeric(10, 2), nullable=False, default=0)
  is_locked = Column(Boolean, default=False, nullable=False) # EDGE-01 FIX: Prevent modifications during checkout
  created_at= Column(TIMESTAMP(timezone=True), server_default=func.now())  # F-036 FIX
  updated_at= Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=datetime.now(timezone.utc))
  
  # relationships
  user = relationship("User", back_populates="cart", lazy="raise_on_sql")
  # vendor = relationship("Vendor", back_populates="cart")
  cart_item = relationship("CartItem" , back_populates="cart", cascade="all, delete-orphan", lazy="raise_on_sql")


class CartItem(Base):
  __tablename__ = "Cart_Items"
  __table_args__ = (
      UniqueConstraint('cart_id', 'product_id', name='uq_cart_product'),  # F-005 FIX
  )
  id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
  cart_id = Column(UUID(as_uuid=True),ForeignKey("Carts.id"), index=True, nullable=False)
  vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id"), index=True)
  product_id = Column(UUID(as_uuid=True), ForeignKey("Products.id"), index=True)
  quantity = Column(Integer, nullable=False, default=1)
  price = Column(Numeric(10, 2), nullable=False)
  Subtotal = Column(Numeric(10, 2), nullable=False)
  
  # relationships
  cart = relationship("Cart" , back_populates="cart_item", lazy="raise_on_sql")
  vendor = relationship("Vendor" , back_populates="cart_item", lazy="raise_on_sql")
  product = relationship("Product" , back_populates="cart_item", lazy="raise_on_sql")