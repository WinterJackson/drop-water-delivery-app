from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from schemas.review_schemas import ReviewCreate, ReviewOut, TargetRatingSummary
from services.review_service import create_review, get_target_rating_summary

from sqlalchemy import select, desc
from uuid import UUID
from fastapi import Query
from models.review_model import Review

router = APIRouter()

@router.post("", response_model=ReviewOut)
@router.post("/", response_model=ReviewOut, include_in_schema=False)
async def submit_review(
    body: ReviewCreate,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_user)
):
    clerk_id = user["sub"]
    return await create_review(session=db, clerk_id=clerk_id, data=body)

@router.get("/target/{target_type}/{target_id}", response_model=list[ReviewOut])
async def list_reviews_for_target(
    target_type: str,
    target_id: UUID,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    if target_type not in ("vendor", "rider"):
        raise HTTPException(status_code=400, detail="target_type must be 'vendor' or 'rider'")
    query = (
        select(Review)
        .where(Review.target_type == target_type, Review.target_id == target_id)
        .order_by(desc(Review.created_at))
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/summary/{target_type}/{target_id}", response_model=TargetRatingSummary)
async def target_rating_summary(
    target_type: str,
    target_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Average, count and star distribution for a vendor or rider.

    The list endpoint returns individual reviews; a client wanting to show
    "4.8 (312)" and a distribution bar had to fetch every review and count them
    locally, which is why the customer app showed a bare average with no count.
    """
    return await get_target_rating_summary(db, target_type, target_id)
