from sqlalchemy import Column, String, Float, ForeignKey, DateTime, func, Text, UniqueConstraint, CheckConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
import uuid
from db.session import Base

class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint('customer_clerk_id', 'order_id', 'target_type', name='uq_customer_order_target_review'),
        CheckConstraint('rating >= 1 AND rating <= 5', name='ck_review_rating_range'),
        # Supports the `is_rated` batch lookup on the orders list.
        Index('idx_reviews_order_id', 'order_id'),
        # Supports the average-rating recalculation after each new review.
        Index('idx_reviews_target', 'target_type', 'target_id'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    order_id = Column(UUID(as_uuid=True), ForeignKey("Orders.id"), nullable=False)
    customer_clerk_id = Column(String, nullable=False, index=True)  # Clerk user ID, no strict FK
    target_type = Column(String, nullable=False) # 'vendor' or 'rider'
    target_id = Column(UUID(as_uuid=True), nullable=False) # Not strict FK to allow both vendor and rider
    rating = Column(Float, nullable=False)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
