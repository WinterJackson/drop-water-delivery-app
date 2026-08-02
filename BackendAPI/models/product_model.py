from db.session import Base
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, Boolean, Enum, TIMESTAMP, Float, Double, DateTime, Integer, ARRAY, ForeignKey, func, Numeric, Index
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from enum import Enum as PyEnum
from sqlalchemy.orm import relationship


class ProductCategory(str, PyEnum):
    """
    Product categories tailored for the Kenyan water delivery market.
    
    Research-based segments covering:
    - Dispenser refills (18.9L/20L) — the dominant segment in Nairobi
    - Small bottled water (500ml–2L) — retail convenience
    - Mineral & spring water — premium natural sources (e.g., Keringet, Kilimanjaro)
    - Purified/treated water — budget-friendly filtered options
    - Alkaline & specialty — health-conscious premium segment
    - 5L/10L jerrycans — mid-size household refills
    - Bulk/wholesale — B2B large-volume orders
    - Dispensers & coolers — hardware for water dispensing
    - Accessories — cups, bottle caps, pump dispensers, stands
    - Ice & cold water — chilled/frozen water products
    """
    dispenser_refill = "dispenser_refill"
    bottled_water = "bottled_water"
    mineral_spring = "mineral_spring"
    purified_water = "purified_water"
    alkaline_specialty = "alkaline_specialty"
    jerrycan = "jerrycan"
    bulk_wholesale = "bulk_wholesale"
    dispensers_coolers = "dispensers_coolers"
    accessories = "accessories"
    ice_cold = "ice_cold"


class Product(Base):
  __tablename__ = "Products"
  __table_args__ = (
      Index('idx_product_category_available', 'category', 'is_available', 'created_at'),
      Index('idx_product_discount_created', 'discount', 'created_at'),
      Index('idx_products_search_vector', 'search_vector', postgresql_using='gin'),
      Index('idx_products_vendor_low_stock', 'vendor_id', 'stock'),
  )
  id = Column(UUID(as_uuid=True), unique=True, primary_key=True, default=uuid.uuid4, index=True)
  vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id"), index=True)
  name = Column(String, nullable=False, index=True)
  description = Column(Text, nullable=True)  #OPTIONAL
  image_url= Column(Text, nullable=False)
  price = Column(Double, nullable=False, index=True)
  discount = Column(Double, nullable=False, index=True , default=0)
  capacity = Column(Double, nullable=False, index=True)
  weight_kg = Column(Numeric(5, 2), nullable=False, default=20.0, index=True)
  minimum_order_qty = Column(Integer, nullable=False, default=1, index=True)
  unit = Column(String, nullable=False, index=True)
  stock = Column(Integer, nullable=False, index=True)
  #: Warn the vendor at or below this level. 0 disables the warning entirely —
  #: some products (a dispenser the vendor orders in on request) have no
  #: meaningful "low".
  low_stock_threshold = Column(Integer, nullable=False, server_default="5", default=5)
  #: When the vendor was last told about this product. One notification per
  #: crossing, not one per unit sold below the line.
  low_stock_notified_at = Column(TIMESTAMP(timezone=True), nullable=True)
  is_available = Column(Boolean, default=True, index=True)
  category = Column(
      Enum(ProductCategory, name="product_category", create_type=False),
      nullable=True,
      default=None,
      index=True,
      comment="Kenya market water product category"
  )
  search_vector = Column(TSVECTOR)
  created_at= Column(TIMESTAMP(timezone=True), server_default=func.now())
  updated_at= Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now())
  
  # relationships
  vendor = relationship("Vendor", back_populates="products")
  cart_item = relationship("CartItem", back_populates="product")
  order_item = relationship("OrderItem", back_populates="product")
  favorite = relationship("Favorite", back_populates="product")
  