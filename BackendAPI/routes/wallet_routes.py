import logging

from fastapi import APIRouter, Depends, Header, Request, HTTPException, Query
from fastapi.responses import JSONResponse
from decimal import Decimal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.dependencies import get_db
from services.payment_service import reject_mpesa_callback
from services.wallet_service import (
    get_wallet_transactions,
    handle_mpesa_topup_callback,
    initiate_wallet_topup,
    initiate_wallet_withdrawal,
)
from utils.verify_user_token import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wallet", tags=["Wallet"])



class TopUpRequest(BaseModel):
    # `Decimal`, not `float`. Money annotated `float` on a Pydantic model is the
    # quiet version of a `float(...)` cast — there is nothing to grep for,
    # because Pydantic does the coercion. It is the *inbound* half of the rule
    # the schemas already follow, and it was invisible to
    # `test_money_serialisation.py` because that walk only ever looked at
    # `schemas/`, and these two models are declared in a route file.
    amount: Decimal = Field(gt=0, le=150_000)
    phone_number: str
    # Which of the caller's wallets to act on. Verified against the token in
    # `resolve_wallet_owner` — a client cannot name an account it does not own.
    user_type: str = "customer"


class WithdrawRequest(BaseModel):
    amount: Decimal = Field(gt=0, le=150_000)
    phone_number: str
    user_type: str = "customer"


@router.post("/top-up")
@limiter.limit("5/minute")
async def top_up_wallet(
    request: Request,
    body: TopUpRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_current_user),
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
):
    clerk_id = auth.get("sub")
    if not clerk_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return await initiate_wallet_topup(
        session=db,
        user_id=clerk_id,
        user_type=body.user_type,
        amount=body.amount,
        phone=body.phone_number,
        store_id=x_store_id,
    )


@router.post("/withdraw")
@limiter.limit("5/minute")
async def withdraw_wallet(
    request: Request,
    body: WithdrawRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_current_user),
    x_store_id: str | None = Header(default=None, alias="X-Store-Id"),
):
    """Cash out. Each `Vendor` row carries its own balance, so a multi-store
    owner must say which store they are withdrawing from — `X-Store-Id`, the
    same header every other vendor endpoint takes."""
    clerk_id = auth.get("sub")
    if not clerk_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return await initiate_wallet_withdrawal(
        session=db,
        user_id=clerk_id,
        user_type=body.user_type,
        amount=body.amount,
        phone=body.phone_number,
        store_id=x_store_id,
    )


@router.get("/transactions")
async def fetch_wallet_transactions(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str | None = None,
    type: str | None = None,
    user_type: str = Query("customer"),
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_current_user),
):
    clerk_id = auth.get("sub")
    if not clerk_id:
        raise HTTPException(status_code=401, detail="Unauthorized")

    return await get_wallet_transactions(
        session=db,
        user_id=clerk_id,
        limit=limit,
        offset=offset,
        search=search,
        transaction_type=type,
        user_type=user_type,
    )


@router.post("/mpesa-callback")
async def mpesa_topup_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    secret: str | None = Query(default=None),
):
    """Safaricom STK callback for wallet top-ups.

    Guarded identically to the order callback. Previously this endpoint was fully
    open: because `POST /top-up` hands the CheckoutRequestID back to the caller,
    anyone could replay it here with `ResultCode: 0` and credit their own wallet
    without paying — and wallet credit is spendable at checkout.
    """
    rejected = reject_mpesa_callback(request, secret, "Wallet top-up callback")
    if rejected:
        return rejected

    try:
        payload = await request.json()
    except Exception:
        logger.warning("Wallet top-up callback rejected: unparseable body")
        return JSONResponse(status_code=400, content={"message": "Invalid payload"})

    try:
        return await handle_mpesa_topup_callback(session=db, payload=payload)
    except Exception as e:
        # Never leak internals to Safaricom, but do not swallow the incident.
        logger.error("Error handling wallet top-up callback: %s", e, exc_info=True)
        try:
            import sentry_sdk
            from utils.redaction import redact_payload

            sentry_sdk.set_context(
                "webhook_payload", {"raw": redact_payload(str(payload)[:2000])}
            )
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        return JSONResponse(status_code=500, content={"message": "Callback processing failed"})
