from db.session import Base
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, Boolean,Enum, TIMESTAMP, Float, Double, DateTime,Integer, ARRAY , ForeignKey, Numeric, func, Index, text
from sqlalchemy.dialects.postgresql import UUID
from enum import Enum as PyEnum
from sqlalchemy.orm import relationship



class Order(Base):
  __tablename__ = "Orders"
  __table_args__ = (
      Index('idx_orders_customer_created', 'customer_id', 'created_at'),
      Index('idx_orders_vendor_created', 'vendor_id', 'created_at'),
      Index('idx_orders_deliverer_created', 'deliverer_id', 'created_at'),
      Index('idx_orders_customer_status', 'customer_id', 'order_status'),
      Index('idx_orders_payment_status', 'payment_status'),
      # One order per M-Pesa transaction. Partial so cash orders — which have no
      # CheckoutRequestID — are unconstrained.
      Index(
          'uq_orders_checkout_request_id',
          'checkout_request_ID',
          unique=True,
          postgresql_where=text('"checkout_request_ID" IS NOT NULL'),
      ),
  )
  id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
  customer_id = Column(UUID(as_uuid=True),ForeignKey("Users.id"), index=True)
  vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id"), index=True) 
  deliverer_id = Column(UUID(as_uuid=True), ForeignKey("Deliverers.id"), index=True) 
  delivery_address= Column(Text, nullable=True)
  checkout_request_ID= Column(String, nullable=True, index=True)
  phone= Column(String, nullable=True, index=True)
  lat_from= Column(Float, nullable=True)
  lng_from= Column(Float, nullable=True)
  lat= Column(Float, nullable=True)
  lng= Column(Float, nullable=True)
  h3_index_res8 = Column(String(16), nullable=True, index=True)
  distance_km = Column(Double, nullable=True)
  total_amount = Column(Numeric(10, 2), nullable=False, default=0)
  order_status = Column(String, nullable=False, default="pending")
  payment_status = Column(String, nullable=False, default="pending")
  payment_method = Column(String, nullable=True)
  delivery_fee = Column(Double, nullable=True, index=True)
  vehicle_class = Column(String(20), nullable=True, default="motorbike")  # V6: motorbike / tuktuk / truck
  delivery_time = Column(Integer, nullable=True)
  
  # Delivery Flow Configuration
  delivery_type = Column(String, nullable=False, default="quick_swap")
  bottle_source = Column(String, nullable=False, default="platform")

  # Welcome Offer Tracking
  is_welcome_offer = Column(Boolean, nullable=False, default=False)

  # ── Revenue Split Ledger (Platform Profitability) ──────────────────────
  vendor_commission = Column(Numeric(10, 2), nullable=True, default=0)
  service_fee = Column(Numeric(10, 2), nullable=True, default=0)
  rider_commission = Column(Numeric(10, 2), nullable=True, default=0)
  platform_total = Column(Numeric(10, 2), nullable=True, default=0)
  vendor_net = Column(Numeric(10, 2), nullable=True, default=0)
  rider_net = Column(Numeric(10, 2), nullable=True, default=0)
  surge_fee = Column(Numeric(10, 2), nullable=True, default=0)
  delivery_markup = Column(Numeric(10, 2), nullable=True, default=0)
  commission_lost = Column(Numeric(10, 2), nullable=True, default=0)
  
  # ── Discount Audit Trail (H-07 FIX) ────────────────────────────────────
  wallet_discount = Column(Numeric(10, 2), nullable=False, default=0.0)
  welcome_discount = Column(Numeric(10, 2), nullable=False, default=0.0)
  product_subtotal = Column(Numeric(10, 2), nullable=False, default=0.0)
  
  # ── Rider Specific Allowances ──────────────────────────────────────────
  staircase_surcharge = Column(Numeric(10, 2), nullable=False, default=0.0)
  payload_surcharge = Column(Numeric(10, 2), nullable=False, default=0.0)

  customer_note = Column(Text, nullable=True)
  actual_floor_level = Column(Integer, nullable=True)
  proof_url = Column(String, nullable=True)
  cancellation_reason = Column(String, nullable=True)
  created_at= Column(TIMESTAMP(timezone=True), server_default=func.now())
  updated_at= Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
  
  # relationships
  order_item = relationship("OrderItem", back_populates="order")
  user = relationship("User", back_populates="order")
  vendor = relationship("Vendor", back_populates="order")
  deliverer = relationship("Deliverer", back_populates="order")

class OrderItem(Base):
  __tablename__ = "Order_Items"
  id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
  order_id = Column(UUID(as_uuid=True),ForeignKey("Orders.id"), index=True)
  # vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id"), index=True)
  product_id = Column(UUID(as_uuid=True), ForeignKey("Products.id"), index=True)
  quantity = Column(Integer, nullable=False, default=1)
  price = Column(Double, nullable=False)
  Subtotal = Column(Double, nullable=False)
  
  # relationships
  order = relationship("Order", back_populates="order_item")
  product = relationship("Product", back_populates="order_item")