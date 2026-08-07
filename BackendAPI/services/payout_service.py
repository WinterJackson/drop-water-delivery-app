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

async def _vendor_by_id(session: AsyncSession, vendor_id):
    """The exact store a payout belongs to, resolved from the id we already have."""
    from models.vendor_model import Vendor

    return await session.get(Vendor, vendor_id)


async def _get_provider_details(session: AsyncSession, clerk_id: str):
    """Resolve whose money this is.

    Ownership, never staff membership. This used to call
    `get_vendor_by_clerk_id`, which matches
    `Vendor.clerk_id == clerk_id OR Vendor.staff_clerk_id == clerk_id` — so a
    staff member resolved to the owner's vendor row, `request_payout` debited
    the owner's balance, and the B2C disbursement went to
    `data.account_details`, a phone number taken straight from the request body.
    A shop assistant with app access could withdraw the store's balance to their
    own number, blocked only by a `router.replace()` in a React screen.

    `wallet_service.resolve_wallet_owner` already matched on `clerk_id` alone
    and correctly refused staff; the two withdrawal paths disagreed and this was
    the permissive one.
    """
    from sqlalchemy.future import select

    from models.vendor_model import Vendor

    result = await session.execute(
        select(Vendor)
        .where(Vendor.clerk_id == clerk_id)
        .order_by(Vendor.created_at.asc(), Vendor.id.asc())
        .limit(1)
    )
    vendor = result.scalars().first()
    if vendor:
        return vendor.id, "vendor"

    rider = await get_deliverer_by_clerk_id(session, clerk_id)
    if rider:
        return rider.id, "rider"

    # A staff member is a real account being told this is not theirs to move.
    from models.vendor_staff_model import VendorStaff

    staff = await session.execute(
        select(VendorStaff.id)
        .where(VendorStaff.clerk_id == clerk_id, VendorStaff.revoked_at.is_(None))
        .limit(1)
    )
    if staff.scalars().first():
        raise HTTPException(
            status_code=403,
            detail={
                "type": "owner_only",
                "message": "Only the store owner can withdraw funds.",
            },
        )

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

async def _vendor_type_of(session: AsyncSession, provider_id, provider_type: str) -> str | None:
    """The store's business type, resolved **by id**.

    A clerk-id lookup returns an arbitrary one of the owner's stores, so a
    wholesale branch could be given the retail threshold — or vice versa —
    depending on row order.
    """
    if provider_type != "vendor":
        return None
    vendor = await _vendor_by_id(session, provider_id)
    if vendor is None or vendor.vendor_type is None:
        return None
    raw = vendor.vendor_type
    return raw.value if hasattr(raw, "value") else str(raw)


async def get_payout_limits(session: AsyncSession, clerk_id: str, provider_id, provider_type: str):
    """Minimum withdrawal and the transaction fee, from `Platform_Settings`.

    The fee is borne by the provider — deducted from the amount withdrawn — so
    the platform does not lose margin on the M-Pesa B2C tariff.

    Delegates to `settlement_service.withdrawal_terms`, which is also what
    `wallet_service` reads. These were two sets of hardcoded literals that
    disagreed on both the minimum and when the fee was waived.
    """
    from services.settlement_service import withdrawal_terms

    vendor_type = await _vendor_type_of(session, provider_id, provider_type)
    minimum, fee, _waiver = await withdrawal_terms(
        session, provider_type=provider_type, vendor_type=vendor_type
    )
    return float(minimum), float(fee)


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

    # ── Limits and fee, from the one schedule ──
    from services.settlement_service import fee_for, withdrawal_terms

    vendor_type = await _vendor_type_of(session, provider_id, provider_type)
    minimum, fee, waiver = await withdrawal_terms(
        session, provider_type=provider_type, vendor_type=vendor_type
    )
    requested = Decimal(str(data.amount))
    min_threshold = float(minimum)
    tx_fee = float(fee_for(requested, fee, waiver))

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

    from services.settlement_service import assert_withdrawable

    available_balance = await assert_withdrawable(
        session,
        provider_id=provider_id,
        provider_type=provider_type,
        wallet_balance=owner.wallet_balance,
        amount=requested,
    )

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
        # Scoped to the store the payout was resolved against. Without
        # `vendor_id` the dashboard re-resolves from the clerk id and, for an
        # owner with two stores, could report the *other* store's revenue beside
        # this store's balance.
        total_earnings = (
            await get_vendor_dashboard(session, clerk_id, vendor_id=provider_id)
        )["total_revenue"]
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
