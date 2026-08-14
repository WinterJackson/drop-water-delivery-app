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
      # Added by migration and recorded here so the model and the database agree.
      # `(order_status, created_at)` serves the sweeps, which always name a status
      # first; `created_at DESC` alone serves the console's analytics, which never
      # do. Without the second, every date-ranged panel is a sequential scan of the
      # whole order history.
      Index('ix_orders_status_created_at', 'order_status', 'created_at'),
      Index('ix_orders_created_at_desc', text('created_at DESC')),
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
  # `Numeric`, not `Double`. This is summed into vendor and rider payouts, and a
  # binary float cannot represent a fee like 68.30 exactly.
  # Not indexed. It carried `index=True` and nothing has ever filtered, joined or
  # sorted on a delivery fee — pure write cost on the fastest-growing table on the
  # platform, paid on every order forever. Dropped in `a7f4e29b81c6`.
  delivery_fee = Column(Numeric(10, 2), nullable=True)
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

  # ── Deposits and debt ──────────────────────────────────────────────────
  #: The refundable deposit charged on this order. Folded into `vendor_net`,
  #: but recorded separately because it is a liability to the customer and the
  #: platform previously had no way to answer "how much deposit have they paid?"
  bottle_deposit = Column(Numeric(10, 2), nullable=False, server_default="0", default=0.0)
  #: An unpaid balance from an earlier order collected on this one. Cleared from
  #: `Users.debt_balance` when the order is created, and restored if it is
  #: cancelled — the customer is refunded, so the debt comes back with it.
  debt_settlement = Column(Numeric(10, 2), nullable=False, server_default="0", default=0.0)
  
  # ── Rider Specific Allowances ──────────────────────────────────────────
  staircase_surcharge = Column(Numeric(10, 2), nullable=False, default=0.0)
  payload_surcharge = Column(Numeric(10, 2), nullable=False, default=0.0)

  customer_note = Column(Text, nullable=True)
  actual_floor_level = Column(Integer, nullable=True)
  proof_url = Column(String, nullable=True)
  #: What this order cost the platform to process — Safaricom's C2B tariff on
  #: an M-Pesa order, or the handling cost of a cash one — and what was left
  #: after it. Frozen at quote time like every other split beside it: changing
  #: the tariff setting tomorrow must not restate yesterday's margin.
  #:
  #: Neither was modelled at all before, so every profitability figure on the
  #: console was gross presented as net. Nullable, and null means *unknown* on a
  #: historic order rather than zero.
  platform_cost = Column(Numeric(10, 2), nullable=True)
  platform_net = Column(Numeric(10, 2), nullable=True)

  cancellation_reason = Column(String, nullable=True)
  created_at= Column(TIMESTAMP(timezone=True), server_default=func.now())
  updated_at= Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
  
  # relationships
  order_item = relationship("OrderItem", back_populates="order", lazy="raise_on_sql")
  user = relationship("User", back_populates="order", lazy="raise_on_sql")
  vendor = relationship("Vendor", back_populates="order", lazy="raise_on_sql")
  deliverer = relationship("Deliverer", back_populates="order", lazy="raise_on_sql")

class OrderItem(Base):
  __tablename__ = "Order_Items"
  id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
  order_id = Column(UUID(as_uuid=True),ForeignKey("Orders.id"), index=True)
  # vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id"), index=True)
  product_id = Column(UUID(as_uuid=True), ForeignKey("Products.id"), index=True)
  quantity = Column(Integer, nullable=False, default=1)
  # `Numeric`, not `Double`. `Subtotal` is what `_cart_payload` sums into
  # `product_subtotal`, which is the base of every commission on the platform.
  price = Column(Numeric(10, 2), nullable=False)
  Subtotal = Column(Numeric(10, 2), nullable=False)
  
  # relationships
  order = relationship("Order", back_populates="order_item", lazy="raise_on_sql")
  product = relationship("Product", back_populates="order_item", lazy="raise_on_sql")