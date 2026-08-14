from db.session import Base
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, Text, Float, TIMESTAMP, ForeignKey, Boolean, Integer, func, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship


class SavedLocation(Base):
    """Stores multiple delivery addresses per user (like Uber's Home/Work/Recent).
    
    The User.location_address / User.lat / User.lng fields remain the 'active' delivery
    address. This table holds the user's saved/recent addresses for quick selection.
    
    Design:
      - label: 'Home', 'Work', or custom name (nullable for recent/unnamed)
      - is_default: only one per user — the fallback delivery address
      - use_count: tracks popularity for 'Recent' sorting
      - last_used_at: enables time-based recency sorting
    """
    __tablename__ = "Saved_Locations"
    __table_args__ = (
        Index('idx_saved_loc_user_default_last_used', 'user_id', 'is_default', 'last_used_at'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("Users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(50), nullable=True)  # 'Home', 'Work', or custom
    address = Column(Text, nullable=False)
    lat = Column(Float, nullable=False)
    lng = Column(Float, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    use_count = Column(Integer, default=1, nullable=False)
    last_used_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    # Relationship
    user = relationship("User", back_populates="saved_locations", lazy="raise_on_sql")
