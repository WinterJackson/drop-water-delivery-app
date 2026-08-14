from db.session import Base
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, TIMESTAMP, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship


class VendorFavorite(Base):
    __tablename__ = "Vendor_Favorites"
    __table_args__ = (
        UniqueConstraint('user_id', 'vendor_id', name='uq_user_vendor_favorite'),
    )
    id = Column(UUID(as_uuid=True), unique=True, default=uuid.uuid4, primary_key=True, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("Users.id"), index=True, nullable=False)
    vendor_id = Column(UUID(as_uuid=True), ForeignKey("Vendors.id"), index=True, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # relationships
    user = relationship("User", back_populates="vendor_favorites", lazy="raise_on_sql")
    vendor = relationship("Vendor", back_populates="vendor_favorites", lazy="raise_on_sql")
