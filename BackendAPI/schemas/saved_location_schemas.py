from pydantic import BaseModel
from uuid import UUID
from datetime import datetime


class SavedLocationCreate(BaseModel):
    """Create a new saved location."""
    label: str | None = None  # 'Home', 'Work', or custom
    address: str
    lat: float
    lng: float
    is_default: bool = False


class SavedLocationUpdate(BaseModel):
    """Update an existing saved location."""
    label: str | None = None
    address: str | None = None
    lat: float | None = None
    lng: float | None = None
    is_default: bool | None = None


class SavedLocationOut(BaseModel):
    """Response schema for a saved location."""
    id: UUID
    label: str | None
    address: str
    lat: float
    lng: float
    is_default: bool
    use_count: int
    last_used_at: datetime | None

    model_config = {"from_attributes": True}
