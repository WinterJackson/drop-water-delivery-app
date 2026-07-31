import logging
from fastapi import APIRouter, Depends, Request, Query
from fastapi.responses import JSONResponse
from decimal import Decimal
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from dependencies.dependencies import get_db
from utils.verify_user_token import get_current_user
from schemas.payout_schemas import PayoutCreate, PayoutResponse
from services.payout_service import request_payout, get_provider_payouts
from services.payment_service import reject_mpesa_callback

logger = logging.getLogger(__name__)

#: Legacy payout endpoints. **Not registered in `main.py`** — cashouts go through
#: `POST /api/wallet/withdraw` instead. Kept only because historic `Payout` rows
#: still exist and the callbacks below fall back to reconciling them.
router = APIRouter()

#: Safaricom's B2C callbacks. These *are* registered, under `/api/payouts`.
#:
#: They live on a separate router because `router` above was deliberately
#: dropped from the app, and that took the callbacks with it — while
#: `wallet_service.initiate_wallet_withdrawal` kept disbursing real money and
#: pointing `MPESA_B2C_RESULT_URL` at what had become a 404. Every withdrawal
#: was left `processing` forever, and a disbursement that failed *after*
#: Safaricom queued it never refunded the balance it had already debited.
callback_router = APIRouter()


@router.post("/request", response_model=PayoutResponse)
async def create_payout_request(
    data: PayoutCreate,
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Submit a withdrawal/cashout request with automatic M-Pesa B2C disbursement."""
    clerk_id = user["sub"]
    return await request_payout(session, clerk_id, data)


@router.get("/")
async def fetch_payouts(
    session: AsyncSession = Depends(get_db),
    user=Depends(get_current_user),
):
    """Fetch balance metrics and payout history for the authenticated provider."""
    clerk_id = user["sub"]
    return await get_provider_payouts(session, clerk_id)


# ── M-Pesa B2C Callback Endpoints ─────────────────────────────────────────────
# These are called by Safaricom servers when a B2C transaction completes or times out.

async def _reconcile_wallet_transaction(session, conversation_id: str, success: bool, result_desc: str, mpesa_receipt: str | None):
    from sqlalchemy.future import select
    from models.wallet_transaction_model import WalletTransaction, TransactionStatus, UserType
    from models.user_model import User
    from models.vendor_model import Vendor
    from models.deliverer_model import Deliverer

    stmt = select(WalletTransaction).where(
        WalletTransaction.reference_id == conversation_id,
        WalletTransaction.status == TransactionStatus.processing,
    ).with_for_update()
    tx = (await session.execute(stmt)).scalars().first()
    if not tx:
        return False  # not ours — let the Payout-table lookup handle it

    if success:
        tx.status = TransactionStatus.completed
        tx.mpesa_receipt_number = mpesa_receipt
    else:
        # Real payout failed after we'd already deducted the wallet balance — refund it now.
        model = {"vendor": Vendor, "rider": Deliverer, "customer": User}[tx.user_type.value]
        result = await session.execute(select(model).where(model.clerk_id == tx.user_id).with_for_update())
        user = result.scalars().first()
        if user:
            # `tx.amount` is signed and this was a debit, so returning it means
            # subtracting a negative. Decimal, not float — this is money.
            user.wallet_balance = Decimal(str(user.wallet_balance or 0)) - Decimal(str(tx.amount))
        tx.status = TransactionStatus.failed
        tx.failure_reason = result_desc

    await session.commit()
    return True


@callback_router.post("/mpesa/b2c_result")
async def b2c_result_callback(request: Request, session: AsyncSession = Depends(get_db), secret: str | None = Query(default=None)):
    """
    Safaricom B2C Result callback.
    Reconciles the wallet withdrawal, or a legacy Payout row, from the result.
    """
    rejected = reject_mpesa_callback(request, secret, "B2C result callback")
    if rejected:
        return rejected

    try:
        data = await request.json()
        result = data.get("Result", {})
        result_code = result.get("ResultCode")
        conversation_id = result.get("ConversationID")
        result_desc = result.get("ResultDesc", "")

        if not conversation_id:
            logger.error("B2C result callback missing ConversationID")
            return JSONResponse(status_code=400, content={"message": "Missing ConversationID"})
            
        handled = await _reconcile_wallet_transaction(session, conversation_id, result_code == 0, result_desc, mpesa_receipt=None)
        if handled:
            return {"message": "Wallet transaction reconciled"}

        # Find the payout record by ConversationID
        from sqlalchemy.future import select
        from models.payout_model import Payout
        # Lock it: Safaricom retries this callback, and the failure branch now
        # refunds the balance. Two concurrent deliveries of the same result must
        # not both refund.
        stmt = (
            select(Payout)
            .where(Payout.conversation_id == conversation_id)
            .with_for_update()
        )
        result_row = await session.execute(stmt)
        payout = result_row.scalars().first()

        if not payout:
            logger.error(f"B2C result: No payout found for ConversationID {conversation_id}")
            return JSONResponse(status_code=404, content={"message": "Payout not found"})

        # Terminal already? Then a previous delivery of this callback settled it and
        # any refund has already been issued.
        already_terminal = payout.status in ("completed", "failed")

        if result_code == 0:
            # Extract receipt number from ResultParameters
            payout.status = "completed"
            params = result.get("ResultParameters", {}).get("ResultParameter", [])
            for param in params:
                if param.get("Key") == "TransactionReceipt":
                    payout.mpesa_receipt = param.get("Value")
                    break

            # Notify provider about successful payout
            try:
                from services.notification_service import create_notification
                await create_notification(
                    session=session,
                    user_id=payout.provider_id,
                    user_type=payout.provider_type,
                    title="Payout Successful ✅",
                    message=f"KSH {payout.amount} has been sent to your M-Pesa.",
                    message_type="payout_update",
                    action_url="/(screens)/Cashout",
                )
            except Exception as e:
                logger.error(f"B2C success notification failed: {e}")

            logger.info(f"B2C payout {payout.id} completed. Receipt: {payout.mpesa_receipt}")
        else:
            payout.status = "failed"
            payout.failure_reason = result_desc

            # The balance was debited when the payout was created, so a failure at
            # the callback stage — after a successful initiation — must return it.
            # Guarded against replay: Safaricom retries callbacks, and a second
            # refund would mint money.
            if not already_terminal:
                from models.deliverer_model import Deliverer
                from models.vendor_model import Vendor
                from models.wallet_transaction_model import TransactionType
                from services.wallet_service import apply_wallet_delta

                model = Vendor if payout.provider_type == "vendor" else Deliverer
                owner = (
                    await session.execute(
                        select(model).where(model.id == payout.provider_id).with_for_update()
                    )
                ).scalars().first()
                if owner:
                    await apply_wallet_delta(
                        session,
                        owner=owner,
                        clerk_id=owner.clerk_id,
                        user_type=payout.provider_type,
                        amount=Decimal(str(payout.amount)),
                        transaction_type=TransactionType.refund,
                        description=f"Withdrawal failed, amount returned ({result_desc})",
                        reference_id=str(payout.id),
                    )

            # Notify provider about failed payout
            try:
                from services.notification_service import create_notification
                await create_notification(
                    session=session,
                    user_id=payout.provider_id,
                    user_type=payout.provider_type,
                    title="Payout Failed ❌",
                    message=f"Your payout of KSH {payout.amount} failed: {result_desc}",
                    message_type="payout_update",
                    action_url="/(screens)/Cashout",
                )
            except Exception as e:
                logger.error(f"B2C failure notification failed: {e}")

            logger.warning(f"B2C payout {payout.id} failed: {result_desc}")

        await session.commit()
        return {"message": "B2C result processed"}

    except Exception as e:
        logger.error(f"Error processing B2C result callback: {e}")
        return JSONResponse(status_code=500, content={"message": "Processing error"})


@callback_router.post("/mpesa/b2c_timeout")
async def b2c_timeout_callback(request: Request, session: AsyncSession = Depends(get_db), secret: str | None = Query(default=None)):
    """
    Safaricom B2C Timeout callback.
    Marks the payout as failed due to timeout if it hasn't already been resolved.
    """
    rejected = reject_mpesa_callback(request, secret, "B2C timeout callback")
    if rejected:
        return rejected

    try:
        data = await request.json()
        conversation_id = data.get("Result", {}).get("ConversationID")

        if conversation_id:
            handled = await _reconcile_wallet_transaction(session, conversation_id, success=False, result_desc="M-Pesa B2C request timed out", mpesa_receipt=None)
            if handled:
                return {"message": "Wallet transaction timeout reconciled"}

            from sqlalchemy.future import select
            from models.payout_model import Payout
            stmt = select(Payout).where(Payout.conversation_id == conversation_id)
            result_row = await session.execute(stmt)
            payout = result_row.scalars().first()

            if payout and payout.status == "processing":
                payout.status = "failed"
                payout.failure_reason = "M-Pesa B2C request timed out"
                await session.commit()
                logger.warning(f"B2C payout {payout.id} timed out")

        return {"message": "Timeout processed"}

    except Exception as e:
        logger.error(f"Error processing B2C timeout callback: {e}")
        return JSONResponse(status_code=500, content={"message": "Processing error"})
