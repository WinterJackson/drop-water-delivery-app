from db.session import Base
from datetime import datetime, timezone
import uuid
from sqlalchemy import Column, String, TIMESTAMP, ForeignKey, Enum, func, Text
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship
from enum import Enum as PyEnum

class RejectionStatus(str, PyEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved" # meaning rejection is approved, bottle is rejected
    DENIED = "denied" # meaning rejection is denied, bottle is acceptable

class BottleRejectionTicket(Base):
    __tablename__ = "Bottle_Rejection_Tickets"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("Orders.id"), nullable=False, index=True)
    rider_id = Column(UUID(as_uuid=True), ForeignKey("Deliverers.id"), nullable=False, index=True)
    
    status = Column(Enum(RejectionStatus), default=RejectionStatus.PENDING_REVIEW, nullable=False)
    reason_text = Column(Text, nullable=False)
    photo_urls = Column(ARRAY(String), nullable=False)
    
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=datetime.now(timezone.utc))
    
    # Relationships
    order = relationship("Order", lazy="raise_on_sql")
    rider = relationship("Deliverer", lazy="raise_on_sql")
