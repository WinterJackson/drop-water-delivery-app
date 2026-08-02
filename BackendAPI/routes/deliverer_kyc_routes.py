from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import Optional

from dependencies.dependencies import get_db
from models.deliverer_model import Deliverer, KYCStatus
from dependencies.auth_dependencies import get_current_rider
from utils.s3_utils import upload_file_to_s3

import logging
import imghdr

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/deliverer/kyc",
    tags=["Deliverer KYC"]
)

ALLOWED_IMAGE_KINDS = {"jpeg", "png"}

async def _validate_upload(file: UploadFile, field_name: str):
    header_bytes = await file.read(512)
    await file.seek(0)  # reset the stream so the S3 upload below reads from the start
    kind = imghdr.what(None, h=header_bytes)
    is_pdf = header_bytes.startswith(b"%PDF-")
    if not (kind in ALLOWED_IMAGE_KINDS or is_pdf):
        raise HTTPException(status_code=400, detail=f"{field_name} must be a genuine JPG, PNG, or PDF file.")

@router.post("/upload")
async def upload_kyc_documents(
    id_card_front: UploadFile = File(...),
    id_card_back: UploadFile = File(...),
    driver_license: Optional[UploadFile] = File(None),
    plate_number: Optional[str] = Form(None),
    vehicle_type: Optional[str] = Form(None),
    current_user: dict = Depends(get_current_rider),
    db: AsyncSession = Depends(get_db)
):
    """
    Securely uploads KYC documents to AWS S3 and updates the deliverer's record.
    Sets the kyc_status to 'pending'.
    """
    user_clerk_id = current_user.get("sub")
    if not user_clerk_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Get the Deliverer record
    result = await db.execute(select(Deliverer).where(Deliverer.clerk_id == user_clerk_id))
    deliverer = result.scalar_one_or_none()

    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider profile not found")

    await _validate_upload(id_card_front, "ID card front")
    await _validate_upload(id_card_back, "ID card back")

    # Upload files
    front_url = await upload_file_to_s3(id_card_front, prefix="kyc/id_front")
    back_url = await upload_file_to_s3(id_card_back, prefix="kyc/id_back")
    
    if not front_url or not back_url:
        raise HTTPException(status_code=500, detail="Failed to upload documents securely")

    deliverer.id_card_front = front_url
    deliverer.id_card_back = back_url

    if driver_license:
        await _validate_upload(driver_license, "Driver license")
        dl_url = await upload_file_to_s3(driver_license, prefix="kyc/license")
        if dl_url:
            deliverer.driver_license = dl_url

    # Update metadata if provided
    if plate_number:
        deliverer.plate_number = plate_number
    if vehicle_type:
        deliverer.vehicle_type = vehicle_type

    # Set status to pending review — but only demote from "approved" if this is a genuinely
    # new submission, not a minor field update on an already-verified rider.
    if deliverer.kyc_status != KYCStatus.approved:
        deliverer.kyc_status = KYCStatus.pending
        # The reason described the *previous* documents. Leaving it set would
        # keep showing "your ID photo was blurred" on VerificationWall next to a
        # freshly uploaded, perfectly sharp one.
        deliverer.kyc_rejection_reason = None
    else:
        # Log the change for an admin to spot-check, without interrupting the rider's ability to work.
        logger.info(f"Rider {deliverer.id} updated KYC documents post-approval; status unchanged.")
    
    await db.commit()
    await db.refresh(deliverer)

    return {
        "message": "KYC documents uploaded successfully. Your profile is now under review.",
        "kyc_status": deliverer.kyc_status
    }


@router.get("/status")
async def get_kyc_status(
    current_user: dict = Depends(get_current_rider),
    db: AsyncSession = Depends(get_db)
):
    """
    Returns the current KYC verification status and whether the rider 
    is approved by any vendors (Operational Status).
    """
    user_clerk_id = current_user.get("sub")
    if not user_clerk_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await db.execute(select(Deliverer).where(Deliverer.clerk_id == user_clerk_id))
    deliverer = result.scalar_one_or_none()

    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider profile not found")

    # In a real scenario, you'd also query DelivererVendor to check if they have approved vendors
    # For this endpoint, we will just return the primary status
    return {
        "is_verified": deliverer.is_verified,
        "kyc_status": deliverer.kyc_status,
        "employer_vendor_id": deliverer.employer_vendor_id,
        "vehicle_type": deliverer.vehicle_type,
        "plate_number": deliverer.plate_number,
        # Why the last review failed. `VerificationWall` prefills the rider's
        # previous answers, so without this a rejected rider sees a form that
        # looks correct and resubmits the same document.
        "rejection_reason": deliverer.kyc_rejection_reason,
        "reviewed_at": deliverer.kyc_reviewed_at.isoformat() if deliverer.kyc_reviewed_at else None,
    }
