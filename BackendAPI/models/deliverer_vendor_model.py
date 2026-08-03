from db.session import Base
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, TIMESTAMP, ForeignKey, Enum, func
from sqlalchemy.dialects.postgresql import UUID

from enum import Enum as PyEnum

class VendorRiderStatus(str, PyEnum):
    PENDING = "pending"
    APPROVED = "approved"

class DelivererVendor(Base):
    __tablename__ = "Deliverer_Vendors"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    deliverer_id = Column(UUID(as_uuid=True), ForeignKey("Deliverers.id"), nullable=False, index=True)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id"), nullable=False, index=True)
    status = Column(Enum(VendorRiderStatus), default=VendorRiderStatus.PENDING, nullable=False)
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=datetime.now(timezone.utc))

    # No relationships. The two that were here — `back_populates="vendors"` on
    # Deliverer and `back_populates="deliverers"` on Vendor — named properties
    # that do not exist on either mapper, so *importing this module from the
    # application* raised InvalidRequestError on the first ORM query in the
    # process and took every unrelated query down with it.
    #
    # It went unnoticed because the only importer is `alembic/env.py`, which
    # wants the metadata for autogenerate and never compiles an ORM query, so
    # mapper configuration was never triggered. The first module to read this
    # table would have found out the hard way.
    #
    # The table itself is dead: nothing in `services/` or `routes/` touches it.
    # `VendorRiderRegistry` is the live rider/store relationship and is what
    # dispatch, the rider app and the vendor app all use. The declaration stays
    # so the table Alembic created is still described; the trap does not.
