import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, TIMESTAMP, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import backref, relationship

from db.session import Base

class VendorRiderRegistry(Base):
    """
    Registry to strictly bind a Rider to a maximum of 5 Vendors.
    Both Rider and Vendor must be within the same H3 resolution grid (approx 1.5km).
    """
    __tablename__ = "VendorRiderRegistry"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    rider_id = Column(UUID(as_uuid=True), ForeignKey("Deliverers.id", ondelete="CASCADE"), index=True, nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id", ondelete="CASCADE"), index=True, nullable=False)
    
    status = Column(String(20), nullable=False, default="pending")  # pending, approved, rejected, suspended
    priority = Column(Integer, default=1)
    
    pending_10L_empties = Column(Integer, nullable=False, default=0)
    pending_20L_empties = Column(Integer, nullable=False, default=0)
    
    # H3 hex index referencing the origin zone this rider/vendor bind acts in.
    # At resolution 9, hex edge length is ~174m (area is ~0.10 sq km)
    # At resolution 8, hex edge is ~461m (area is ~0.73 sq km) -> suitable for hyper local routing filtering.
    h3_index = Column(String(20), nullable=True, index=True)
    distance_km = Column(Float, nullable=True)

    requested_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    approved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    
    # `lazy=` on the declaration governs only the *forward* direction. A bare
    # `backref="…"` string builds the reverse relationship with the library
    # default, so `Deliverer.vendor_registrations` and `Vendor.rider_registrations`
    # were the only two of the platform's 38 relationships still lazy-loading —
    # and they are collections on the two rows most likely to be held across a
    # long-running request. `backref()` states the reverse side explicitly.
    rider = relationship(
        "Deliverer",
        backref=backref("vendor_registrations", lazy="raise_on_sql"),
        lazy="raise_on_sql",
    )
    vendor = relationship(
        "Vendor",
        backref=backref("rider_registrations", lazy="raise_on_sql"),
        lazy="raise_on_sql",
    )

