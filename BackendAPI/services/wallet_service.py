import logging
from decimal import Decimal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, func
from fastapi import HTTPException
from models.wallet_transaction_model import WalletTransaction, UserType, TransactionType, TransactionStatus
from models.user_model import User
from models.vendor_model import Vendor
from models.deliverer_model import Deliverer
from services.payment_service import initiate_stk_push, initiate_b2c_payout

logger = logging.getLogger(__name__)

# The three wallet-bearing entities, keyed by the `user_type` a client may claim.
_WALLET_OWNER_MODELS = {"customer": User, "vendor": Vendor, "rider": Deliverer}

MIN_TOPUP_KSH = Decimal("10")
MIN_WITHDRAWAL_KSH = Decimal("500")


async def resolve_wallet_owner(
    session: AsyncSession, clerk_id: str, requested_type: str, store_id: str | None = None
):
    """Verify the caller actually owns a wallet of the type they are claiming.

    `user_type` arrives from the request body, so it is untrusted. A token is only
    permitted to act on a wallet that has a row for its own clerk id — without
    this check a client could name any entity type and operate on the matching
    wallet.

    Matching on `clerk_id` alone is deliberate for vendors: `staff_clerk_id` must
    never resolve here. A staff member operating the shop may not move the
    owner's money, and this function has always been the path that got that
    right — `payout_service` was the one that did not.

    `store_id` names *which* of the owner's stores when they hold more than one.
    Each `Vendor` row carries its own `wallet_balance`, so without it a
    withdrawal debited whichever row the database returned first — an unordered
    `.first()`, so not even consistently the same one between two requests.
    """
    normalised = (requested_type or "").lower()
    model = _WALLET_OWNER_MODELS.get(normalised)
    if model is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid account type. Expected one of: customer, vendor, rider.",
        )

    query = select(model).where(model.clerk_id == clerk_id)
    if store_id and model is Vendor:
        from uuid import UUID

        try:
            query = query.where(Vendor.id == UUID(str(store_id)))
        except (ValueError, TypeError, AttributeError):
            raise HTTPException(status_code=400, detail="Invalid store id.")

    result = await session.execute(query.order_by(model.created_at.asc(), model.id.asc()))
    owner = result.scalars().first()
    if owner is None:
        if store_id and model is Vendor:
            # Their account is fine; that store is not theirs. 404 rather than
            # 403 — confirming the id exists is not ours to do.
            raise HTTPException(status_code=404, detail="Store not found.")
        raise HTTPException(
            status_code=403,
            detail=f"This account is not registered as a {normalised}.",
        )
    return normalised, model, owner


async def record_wallet_movement(
    session: AsyncSession,
    *,
    clerk_id: str,
    user_type: str,
    transaction_type: TransactionType,
    amount,
    description: str,
    reference_id: str | None = None,
    status: TransactionStatus = TransactionStatus.completed,
) -> WalletTransaction:
    """Append a ledger row for a wallet balance change.

    Every mutation of `wallet_balance` must go through here. Balances used to move
    silently when an order consumed wallet credit or a cancellation returned it,
    so the customer's Transactions screen could not explain its own numbers.
    Does not commit — the caller owns the transaction boundary.
    """
    entry = WalletTransaction(
        user_id=clerk_id,
        user_type=UserType[user_type.lower()],
        transaction_type=transaction_type,
        amount=Decimal(str(amount)),
        status=status,
        reference_id=reference_id,
        description=description,
    )
    session.add(entry)
    return entry


async def apply_wallet_delta(
    session: AsyncSession,
    *,
    owner,
    clerk_id: str,
    user_type: str,
    amount,
    transaction_type: TransactionType,
    description: str,
    reference_id: str | None = None,
    status: TransactionStatus = TransactionStatus.completed,
) -> WalletTransaction:
    """Move a balance **and** write its ledger row, as one operation.

    `record_wallet_movement` only appends the ledger row; callers still had to
    remember to adjust the balance, and several did the reverse — adjusting the
    balance and forgetting the row. Use this wherever both must happen.

    `amount` is signed: negative debits. The stored ledger amount keeps that sign,
    so summing a user's transactions reproduces their balance movement exactly.
    Does not commit — the caller owns the transaction boundary.
    """
    delta = Decimal(str(amount))
    if delta == 0:
        # Nothing moved; a zero-value ledger row would be noise in the history.
        return None

    owner.wallet_balance = Decimal(str(owner.wallet_balance or 0)) + delta

    return await record_wallet_movement(
        session,
        clerk_id=clerk_id,
        user_type=user_type,
        transaction_type=transaction_type,
        amount=delta,
        description=description,
        reference_id=reference_id,
        status=status,
    )


async def initiate_wallet_topup(session: AsyncSession, user_id: str, user_type: str, amount: float, phone: str, store_id: str | None = None):
    import re

    amount_dec = Decimal(str(amount))
    if amount_dec < MIN_TOPUP_KSH:
        raise HTTPException(status_code=400, detail=f"Minimum top-up amount is {MIN_TOPUP_KSH:.0f} KSH.")
    if amount_dec != amount_dec.to_integral_value():
        raise HTTPException(status_code=400, detail="Top-up amount must be a whole number of shillings.")
    if not re.match(r"^254[17]\d{8}$", phone or ""):
        raise HTTPException(
            status_code=400,
            detail="Phone number must be in the format 2547XXXXXXXX or 2541XXXXXXXX.",
        )

    # Confirms the caller owns a wallet of this type before any money moves.
    await resolve_wallet_owner(session, user_id, user_type, store_id=store_id)

    # Trigger M-Pesa STK Push
    response = await initiate_stk_push(phone=phone, amount=int(amount))
    if "error" in response or response.get("ResponseCode") != "0":
        logger.error(f"STK Push Failed: {response}")
        raise HTTPException(status_code=400, detail="Failed to initiate STK push. Please try again.")

    checkout_request_id = response.get("CheckoutRequestID")

    # Log pending transaction
    transaction = WalletTransaction(
        user_id=user_id,
        user_type=UserType[user_type.lower()],
        transaction_type=TransactionType.top_up,
        amount=amount,
        status=TransactionStatus.pending,
        reference_id=checkout_request_id,
        description="M-Pesa STK Push Top Up"
    )
    session.add(transaction)
    await session.commit()
    
    return {"message": "STK Push initiated", "checkout_request_id": checkout_request_id}

async def handle_mpesa_topup_callback(session: AsyncSession, payload: dict):
    """Settle a wallet top-up from a Safaricom STK callback.

    The transport-level guards (shared secret + Safaricom IP allow-list) live in
    the route. This function adds the guards that survive a compromised
    transport: the transaction must still be pending (replay protection, enforced
    with a row lock), and the amount Safaricom says it collected must match the
    amount we asked for. Previously any caller who started a top-up could POST a
    synthetic success for their own CheckoutRequestID and be credited without
    paying.
    """
    stk_callback = (payload or {}).get("Body", {}).get("stkCallback", {})
    checkout_request_id = stk_callback.get("CheckoutRequestID")
    result_code = stk_callback.get("ResultCode")

    if not checkout_request_id:
        return {"status": "ignored"}

    # Lock the transaction row so two concurrent callbacks cannot both credit it.
    result = await session.execute(
        select(WalletTransaction)
        .where(WalletTransaction.reference_id == checkout_request_id)
        .where(WalletTransaction.transaction_type == TransactionType.top_up)
        .with_for_update()
    )
    transaction = result.scalars().first()

    if not transaction:
        logger.warning("No top-up transaction found for CheckoutRequestID %s", checkout_request_id)
        return {"status": "not_found"}

    if transaction.status != TransactionStatus.pending:
        # Already settled — a Safaricom retry or a replay attempt. Idempotent no-op.
        logger.info(
            "Top-up %s already in state '%s'; ignoring duplicate callback.",
            checkout_request_id, transaction.status,
        )
        return {"status": "already_settled"}

    if result_code == 0:
        callback_metadata = stk_callback.get("CallbackMetadata", {}).get("Item", [])

        def _meta(name: str):
            return next((i.get("Value") for i in callback_metadata if i.get("Name") == name), None)

        mpesa_receipt = _meta("MpesaReceiptNumber")
        callback_amount = _meta("Amount")

        # The collected amount must match what we requested. Without this, a
        # forged callback could claim any amount at all.
        if callback_amount is None:
            logger.error("Top-up callback %s reported success with no Amount.", checkout_request_id)
            transaction.status = TransactionStatus.failed
            transaction.failure_reason = "Callback missing Amount"
            await session.commit()
            return {"status": "rejected", "reason": "missing_amount"}

        expected = Decimal(str(transaction.amount))
        received = Decimal(str(callback_amount))
        if abs(expected - received) > Decimal("1"):
            logger.error(
                "Top-up amount mismatch for %s: expected %s, callback reported %s.",
                checkout_request_id, expected, received,
            )
            transaction.status = TransactionStatus.failed
            transaction.failure_reason = f"Amount mismatch (expected {expected}, got {received})"
            await session.commit()
            return {"status": "rejected", "reason": "amount_mismatch"}

        if not mpesa_receipt:
            logger.error("Top-up callback %s reported success with no receipt.", checkout_request_id)
            transaction.status = TransactionStatus.failed
            transaction.failure_reason = "Callback missing MpesaReceiptNumber"
            await session.commit()
            return {"status": "rejected", "reason": "missing_receipt"}

        # Credit the wallet of whichever entity started the top-up.
        model = {
            UserType.vendor: Vendor,
            UserType.rider: Deliverer,
            UserType.customer: User,
        }.get(transaction.user_type)

        if model is None:
            logger.error("Top-up %s has unknown user_type %s", checkout_request_id, transaction.user_type)
            return {"status": "rejected", "reason": "unknown_user_type"}

        owner_res = await session.execute(
            select(model).where(model.clerk_id == transaction.user_id).with_for_update()
        )
        owner = owner_res.scalars().first()
        if owner is None:
            logger.error("Top-up %s references a missing account.", checkout_request_id)
            transaction.status = TransactionStatus.failed
            transaction.failure_reason = "Account not found"
            await session.commit()
            return {"status": "rejected", "reason": "account_not_found"}

        owner.wallet_balance = Decimal(str(owner.wallet_balance or 0)) + received
        transaction.amount = received
        transaction.status = TransactionStatus.completed
        transaction.mpesa_receipt_number = mpesa_receipt

        await session.commit()
        logger.info("Wallet top-up %s completed: %s credited.", checkout_request_id, received)
        return {"status": "success"}

    # Failure path
    transaction.status = TransactionStatus.failed
    transaction.failure_reason = stk_callback.get("ResultDesc") or "Payment failed"
    await session.commit()
    return {"status": "failed"}

async def initiate_wallet_withdrawal(session: AsyncSession, user_id: str, user_type: str, amount: float, phone: str, store_id: str | None = None):
    import re

    amount = Decimal(str(amount))
    if amount < MIN_WITHDRAWAL_KSH:
        raise HTTPException(
            status_code=400, detail=f"Minimum withdrawal amount is {MIN_WITHDRAWAL_KSH:.0f} KSH."
        )
    if amount != amount.to_integral_value():
        raise HTTPException(status_code=400, detail="Withdrawal amount must be a whole number of shillings.")

    if not re.match(r"^254[17]\d{8}$", phone or ""):
        raise HTTPException(status_code=400, detail="Phone number must be in the format 2547XXXXXXXX or 2541XXXXXXXX.")

    # Confirms the caller owns a wallet of this type — `user_type` is client input.
    user_type, model, owner = await resolve_wallet_owner(
        session, user_id, user_type, store_id=store_id
    )

    # Lock the row for the duration of this transaction to prevent concurrent
    # double-withdrawal. Locked by primary key, so it is provably the same row
    # `resolve_wallet_owner` approved — re-selecting on `clerk_id` and taking
    # `.first()` could lock the owner's *other* store.
    result = await session.execute(
        select(model).where(model.id == owner.id).with_for_update()
    )
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")

    current_balance = Decimal(str(user.wallet_balance or 0))
    if current_balance < amount:
        raise HTTPException(status_code=400, detail="Insufficient wallet balance.")

    transaction_fee = Decimal("15")
    if user_type == "vendor":
        raw_vendor_type = getattr(user, "vendor_type", "")
        vendor_type_str = raw_vendor_type.value if hasattr(raw_vendor_type, "value") else str(raw_vendor_type)
        threshold = Decimal("5000") if vendor_type_str == "wholesale_b2b" else Decimal("2500")
        if current_balance >= threshold:
            transaction_fee = Decimal("0")
    elif user_type == "rider":
        if current_balance >= Decimal("1000"):
            transaction_fee = Decimal("0")
    elif user_type == "customer":
        transaction_fee = Decimal("0")

    if amount <= transaction_fee:
        raise HTTPException(status_code=400, detail=f"Withdrawal amount must be greater than network fee (KSH {transaction_fee}).")

    user.wallet_balance = current_balance - amount
    disbursement_amount = amount - transaction_fee

    transaction = WalletTransaction(
        user_id=user_id,
        user_type=UserType[user_type],
        transaction_type=TransactionType.withdrawal,
        # Signed: money leaving is negative. `transaction_type` cannot carry the
        # direction because `order_payment` goes both ways — it debits a rider
        # settling a cash order and credits them for delivery earnings.
        amount=-amount,
        status=TransactionStatus.pending,
        description=f"M-Pesa B2C Withdrawal (Net: {disbursement_amount}, Fee: {transaction_fee})",
    )
    session.add(transaction)
    await session.commit()
    await session.refresh(transaction)

    response = await initiate_b2c_payout(phone=phone, amount=disbursement_amount, payout_id=str(transaction.id))

    if not response.get("success"):
        # Re-fetch and lock again — never trust the stale `current_balance` closure on revert,
        # since another transaction may have touched this wallet in the meantime.
        result = await session.execute(select(model).where(model.clerk_id == user_id).with_for_update())
        fresh_user = result.scalars().first()
        if fresh_user is not None:
            fresh_user.wallet_balance = Decimal(str(fresh_user.wallet_balance or 0)) + amount
        transaction.status = TransactionStatus.failed
        transaction.failure_reason = response.get("error")
        await session.commit()
        raise HTTPException(status_code=400, detail=response.get("error", "Withdrawal failed"))

    # Safaricom has only ACCEPTED the request into its queue here — real confirmation
    # arrives asynchronously via the B2C result callback. Do NOT mark completed yet.
    transaction.reference_id = response.get("ConversationID")
    transaction.status = TransactionStatus.processing
    await session.commit()

    return {"message": "Withdrawal is processing and will complete shortly", "transaction": transaction}

async def get_wallet_transactions(
    session: AsyncSession,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
    search: str = None,
    transaction_type: str = None,
    user_type: str = "customer",
):
    """Paginated wallet ledger for one entity.

    Scoped by `user_type` as well as clerk id: one person can legitimately be a
    customer and a vendor, and their two wallets are separate ledgers that must
    not be interleaved.
    """
    query = select(WalletTransaction).where(WalletTransaction.user_id == user_id)

    if user_type:
        try:
            query = query.where(WalletTransaction.user_type == UserType[user_type.lower()])
        except KeyError:
            raise HTTPException(status_code=400, detail="Invalid account type.")

    if search:
        query = query.where(
            or_(
                WalletTransaction.mpesa_receipt_number.ilike(f"%{search}%"),
                WalletTransaction.reference_id.ilike(f"%{search}%"),
                WalletTransaction.description.ilike(f"%{search}%")
            )
        )

    if transaction_type and transaction_type != "All":
        # Client-supplied filter — reject unknown values instead of letting the
        # driver raise a LookupError deep in query compilation.
        try:
            query = query.where(WalletTransaction.transaction_type == TransactionType[transaction_type.lower()])
        except KeyError:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown transaction type '{transaction_type}'.",
            )

    total_query = select(func.count()).select_from(query.subquery())
    total_count = (await session.execute(total_query)).scalar() or 0

    result = await session.execute(
        query.order_by(WalletTransaction.created_at.desc())
        .limit(limit).offset(offset)
    )

    transactions = result.scalars().all()
    next_offset = offset + limit

    return {
        "data": transactions,
        "nextCursor": next_offset if next_offset < total_count else None,
        "hasNextPage": next_offset < total_count,
        "total": total_count
    }
