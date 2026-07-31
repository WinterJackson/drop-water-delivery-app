import logging
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from fastapi import HTTPException
from models.payout_model import Payout
from services.vendor_management_service import get_vendor_by_clerk_id, get_vendor_dashboard
from services.deliverer_service import get_deliverer_by_clerk_id, get_deliverer_earnings
from schemas.payout_schemas import PayoutCreate

logger = logging.getLogger(__name__)

async def _get_provider_details(session: AsyncSession, clerk_id: str):
    vendor = await get_vendor_by_clerk_id(session, clerk_id)
    if vendor:
        return vendor.id, "vendor"
    
    rider = await get_deliverer_by_clerk_id(session, clerk_id)
    if rider:
        return rider.id, "rider"
    
    raise HTTPException(status_code=404, detail="Provider account not found associated with this user.")

async def _refund_failed_payout(session, *, payout, owner, clerk_id: str, provider_type: str, reason: str):
    """Return a debited payout to the balance when the disbursement never left.

    The debit happens up front so the money cannot be spent twice while the B2C
    call is in flight. That makes refunding on failure mandatory — without it a
    failed payout silently confiscates the amount.
    """
    from services.wallet_service import apply_wallet_delta
    from models.wallet_transaction_model import TransactionType

    await apply_wallet_delta(
        session,
        owner=owner,
        clerk_id=clerk_id,
        user_type=provider_type,
        amount=Decimal(str(payout.amount)),
        transaction_type=TransactionType.refund,
        description=f"Withdrawal failed, amount returned ({reason})",
        reference_id=str(payout.id),
    )


async def _get_provider_row(session: AsyncSession, provider_id, provider_type: str):
    """The provider's row, locked FOR UPDATE so the balance cannot move between
    the availability check and the debit."""
    from models.deliverer_model import Deliverer
    from models.vendor_model import Vendor

    model = Vendor if provider_type == "vendor" else Deliverer
    result = await session.execute(
        select(model).where(model.id == provider_id).with_for_update()
    )
    row = result.scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Payout account not found.")
    return row


async def _get_available_balance(session: AsyncSession, clerk_id: str, provider_id, provider_type: str, owner=None) -> Decimal:
    """
    Withdrawable amount = wallet_balance − float committed to open cash orders.

    This used to be computed from a *derived* sum of earnings over delivered
    orders, minus prior payouts — a number with no connection to `wallet_balance`,
    which is what the cash-order float check reads. Nothing reconciled the two, so
    the same money could be withdrawn by M-Pesa **and** spent as float to accept a
    cash order: the rider kept the customer's cash and the platform funded the
    vendor's cut. Payouts now debit `wallet_balance`, making it the single
    spendable balance, and `settlement_service` owns the committed-float subtraction.
    """
    from services.settlement_service import available_for_payout

    if owner is None:
        owner = await _get_provider_row(session, provider_id, provider_type)

    return await available_for_payout(
        session,
        provider_id=provider_id,
        provider_type=provider_type,
        wallet_balance=owner.wallet_balance,
    )

async def get_payout_limits(session: AsyncSession, clerk_id: str, provider_id, provider_type: str):
    """
    Determine minimum withdrawal threshold and transaction fee.
    Transaction fee is borne by the provider (deducted from withdrawn amount) 
    to ensure the platform does not lose margin on B2C charges.
    """
    minimum_threshold = 500.0
    transaction_fee = 15.0  # Standard M-Pesa B2C tariff

    if provider_type == "rider":
        minimum_threshold = 250.0
    else:
        vendor = await get_vendor_by_clerk_id(session, clerk_id)
        if vendor and vendor.vendor_type == "wholesale_b2b":
            minimum_threshold = 1000.0
        else:
            minimum_threshold = 500.0
            
    return minimum_threshold, transaction_fee


async def request_payout(session: AsyncSession, clerk_id: str, data: PayoutCreate):
    provider_id, provider_type = await _get_provider_details(session, clerk_id)

    if data.amount <= 0:
        raise HTTPException(status_code=400, detail="Payout amount must be greater than zero.")

    # ── Idempotency Check ──
    if data.idempotency_key:
        existing_payout_q = select(Payout).where(Payout.idempotency_key == data.idempotency_key)
        existing_payout = (await session.execute(existing_payout_q)).scalar_one_or_none()
        if existing_payout:
            # Already processed, return it (idempotent success)
            return existing_payout

    # Get limits
    min_threshold, tx_fee = await get_payout_limits(session, clerk_id, provider_id, provider_type)
    
    # ── Fee Waiver Logic (Anti-Fraud / Float Retention) ──
    if provider_type == "rider" and data.amount >= 1000.0:
        tx_fee = 0.0
    elif provider_type == "vendor":
        vendor = await get_vendor_by_clerk_id(session, clerk_id)
        if vendor and vendor.vendor_type == "wholesale_b2b" and data.amount >= 5000.0:
            tx_fee = 0.0
        elif vendor and vendor.vendor_type != "wholesale_b2b" and data.amount >= 2500.0:
            tx_fee = 0.0

    if data.amount < min_threshold:
        raise HTTPException(status_code=400, detail=f"Minimum withdrawal is KSH {min_threshold}")

    if data.amount <= tx_fee:
        raise HTTPException(status_code=400, detail=f"Amount must be greater than the transaction fee (KSH {tx_fee})")

    # BUG-FIN-01 FIX: Serialize payout creation per-provider using PostgreSQL advisory lock
    from sqlalchemy import text
    lock_key = abs(hash(str(provider_id))) % (2**31)  # Convert UUID to int32 for pg_advisory_xact_lock
    await session.execute(text(f"SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    # Lock the balance row before reading it, so a concurrent payout or a cash
    # order settling cannot move it between the check and the debit.
    owner = await _get_provider_row(session, provider_id, provider_type)
    available_balance = await _get_available_balance(
        session, clerk_id, provider_id, provider_type, owner=owner
    )

    requested = Decimal(str(data.amount))
    if requested > available_balance:
        from services.settlement_service import committed_cash_float, committed_cash_float_for_vendor

        committed = (
            await committed_cash_float_for_vendor(session, provider_id)
            if provider_type == "vendor"
            else await committed_cash_float(session, provider_id)
        )
        detail = f"Insufficient balance. Available: KSH {available_balance:.2f}"
        if committed > 0:
            # Say why, or a rider stares at a balance they cannot withdraw.
            detail += (
                f" (KSH {committed:.2f} of your KSH {Decimal(str(owner.wallet_balance or 0)):.2f}"
                " is held as float for cash orders you are carrying, and is released"
                " when you deliver them)."
            )
        raise HTTPException(status_code=400, detail=detail)

    payout = Payout(
        provider_id=provider_id,
        provider_type=provider_type,
        amount=data.amount, # Full amount is deducted from ledger
        payment_method=data.payment_method,
        account_details=data.account_details,
        idempotency_key=data.idempotency_key,
        status="pending"
    )
    session.add(payout)

    # Debit immediately, in the same transaction as the Payout row. Leaving the
    # balance untouched until the B2C callback is what let the same money be spent
    # twice; a failed disbursement refunds it below.
    from services.wallet_service import apply_wallet_delta
    from models.wallet_transaction_model import TransactionType

    await apply_wallet_delta(
        session,
        owner=owner,
        clerk_id=clerk_id,
        user_type=provider_type,
        amount=-requested,
        transaction_type=TransactionType.withdrawal,
        description=f"Withdrawal to {data.payment_method}",
        reference_id=str(payout.id),
    )

    await session.commit()
    await session.refresh(payout)

    # Calculate actual disbursement (Withdrawal - Tx Fee)
    disbursement_amount = data.amount - tx_fee

    # If payment method is M-Pesa, initiate B2C disbursement immediately
    if data.payment_method.lower() == "mpesa":
        try:
            from services.payment_service import initiate_b2c_payout
            b2c_result = await initiate_b2c_payout(
                phone=data.account_details,
                amount=disbursement_amount, # Actual cash hitting the phone
                payout_id=str(payout.id),
            )
            if b2c_result.get("success"):
                payout.status = "processing"
                payout.conversation_id = b2c_result.get("ConversationID")
            else:
                payout.status = "failed"
                payout.failure_reason = b2c_result.get("error", "B2C initiation failed")
                await _refund_failed_payout(
                    session, payout=payout, owner=owner, clerk_id=clerk_id,
                    provider_type=provider_type, reason="disbursement declined",
                )
            await session.commit()
            await session.refresh(payout)
        except Exception as e:
            logger.error(f"B2C payout initiation failed for {payout.id}: {e}")
            payout.status = "failed"
            payout.failure_reason = str(e)
            await _refund_failed_payout(
                session, payout=payout, owner=owner, clerk_id=clerk_id,
                provider_type=provider_type, reason="disbursement error",
            )
            await session.commit()

    # Send notification to provider about payout status
    try:
        from services.notification_service import create_notification
        status_label = "is being processed" if payout.status == "processing" else f"status: {payout.status}"
        await create_notification(
            session=session,
            user_id=provider_id,
            user_type=provider_type,
            title="Payout Request 💰",
            message=f"Your payout of KSH {data.amount} (Net: {disbursement_amount}) {status_label}.",
            message_type="payout_update",
            action_url="/(screens)/Cashout",
        )
    except Exception as e:
        logger.error(f"Payout notification failed: {e}")

    return payout

async def get_provider_payouts(session: AsyncSession, clerk_id: str):
    provider_id, provider_type = await _get_provider_details(session, clerk_id)
    
    query = select(Payout).where(Payout.provider_id == provider_id).order_by(Payout.created_at.desc())
    result = await session.execute(query)
    payouts = result.scalars().all()
    
    available_balance = await _get_available_balance(session, clerk_id, provider_id, provider_type)
    min_threshold, tx_fee = await get_payout_limits(session, clerk_id, provider_id, provider_type)
    
    if provider_type == "vendor":
        total_earnings = (await get_vendor_dashboard(session, clerk_id))["total_revenue"]
    else:
        total_earnings = (await get_deliverer_earnings(session, clerk_id))["total_earnings"]

    completed_q = select(func.sum(Payout.amount)).where(
        Payout.provider_id == provider_id, Payout.status == "completed"
    )
    pending_q = select(func.sum(Payout.amount)).where(
        Payout.provider_id == provider_id, Payout.status.in_(["pending", "processing"])
    )

    completed = float((await session.execute(completed_q)).scalar() or 0)
    pending = float((await session.execute(pending_q)).scalar() or 0)

    balance_summary = {
        "lifetime_earnings": float(total_earnings),
        "pending_payouts": pending,
        "completed_payouts": completed,
        "available_balance": available_balance,
        "minimum_threshold": min_threshold,
        "transaction_fee": tx_fee
    }

    return {"balance": balance_summary, "history": payouts}
