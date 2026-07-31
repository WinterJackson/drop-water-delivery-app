from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime

class ReviewCreate(BaseModel):
    order_id: UUID
    target_type: str = Field(..., pattern="^(vendor|rider)$")
    target_id: UUID
    rating: float = Field(..., ge=1.0, le=5.0)
    comment: Optional[str] = Field(None, max_length=2000)


class ReviewOut(BaseModel):
    """What a review looks like to whoever is reading it.

    `customer_clerk_id` is deliberately absent. It used to be returned by
    `GET /api/reviews/target/{type}/{id}`, which is unauthenticated — so anyone
    could page through a vendor's reviews and collect the Clerk user id of every
    customer who left one, tying a named account to its opinions and to the fact
    that it ordered from that vendor. Nothing in any app read the field.
    """
    id: UUID
    order_id: UUID
    target_type: str
    target_id: UUID
    rating: float
    comment: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TargetRatingSummary(BaseModel):
    """Aggregate shown next to a vendor or rider.

    An average with no count is not decidable: one five-star review and three
    hundred both render as "5.0". `distribution` powers the bar chart the rider
    app already draws and the customer app can now draw too.
    """
    target_type: str
    target_id: UUID
    average_rating: float
    total_reviews: int
    distribution: dict[int, int]
