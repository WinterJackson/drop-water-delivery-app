import logging
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, func
from fastapi import HTTPException
from models.wallet_transaction_model import WalletTransaction, UserType, TransactionType, TransactionStatus
from models.user_model import User
from models.vendor_model import Vendor
from models.deliverer_model import Deliverer
from services.payment_service import initiate_stk_push, initiate_b2c_payout
from utils.money import money_str

logger = logging.getLogger(__name__)

# The three wallet-bearing entities, keyed by the `user_type` a client may claim.
_WALLET_OWNER_MODELS = {"customer": User, "vendor": Vendor, "rider": Deliverer}

# Shipped defaults only. Both limits are `Platform_Settings` rows read through
# `settlement_service.withdrawal_terms` / `platform_config_service`; these remain
# so the module is readable on its own and so a running process still refuses an
# absurd request with the settings table unreachable.
MIN_TOPUP_KSH = Decimal("10")
MIN_WITHDRAWAL_KSH = Decimal("250")


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


async def _locked_wallet_owner(session: AsyncSession, model, transaction: WalletTransaction):
    """The exact balance row a transaction belongs to, locked FOR UPDATE.

    Prefers `wallet_owner_id` — the row the money actually came off or is going
    to. One Clerk identity may own several stores, each with its own
    `wallet_balance`, so resolving a callback by `clerk_id` and taking `.first()`
    settles against an arbitrary one: a top-up paid into the second branch
    credited the first, and a failed withdrawal from the second refunded the
    first. Both leave two real balances wrong by the same amount, in opposite
    directions, with nothing in either ledger to explain it.

    Falls back to the clerk id for rows written before the column existed. Those
    are single-store owners in practice, and refusing to settle them would strand
    real money rather than merely misplace it.
    """
    owner_id = getattr(transaction, "wallet_owner_id", None)
    if owner_id is not None:
        result = await session.execute(
            select(model).where(model.id == owner_id).with_for_update()
        )
        owner = result.scalars().first()
        if owner is not None:
            return owner
        logger.warning(
            "Wallet transaction %s names owner %s, which no longer exists.",
            transaction.id, owner_id,
        )

    result = await session.execute(
        select(model)
        .where(model.clerk_id == transaction.user_id)
        .order_by(model.created_at.asc(), model.id.asc())
        .with_for_update()
    )
    return result.scalars().first()


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


def _rebalance_restricted_credit(owner, *, delta: Decimal, transaction_type, user_type=None) -> None:
    """Keep `non_withdrawable_balance` honest as the wallet moves.

    Only customers carry one; it is a returned bottle deposit, spendable on
    water and not withdrawable as cash (see
    `settlement_service.restricted_customer_credit`).

    Two rules, and the distinction between them is the whole point:

    * **Spending consumes the restricted part first.** Otherwise buying water
      out of a wallet holding 300 restricted and 200 free would eat the free
      money and leave the restriction intact — the customer's *withdrawable*
      balance falling because they bought water, which is precisely backwards.
      Consuming it first is what makes the deposit genuinely turn into water.
    * **A withdrawal consumes none of it.** `assert_withdrawable` has already
      limited the withdrawal to the unrestricted part, so treating it like a
      spend would release the restriction a shilling at a time and hand back
      exactly the cash-out path this exists to close.

    The clamp at the end holds in both cases: restricted can never exceed the
    balance it is a part of.

    Keyed on `user_type`, not on whether the attribute happens to exist. Only a
    customer has restricted credit; riders and vendors have committed cash float
    instead, which `settlement_service` owns. A `hasattr` check reads as
    equivalent and is not — it is true of anything duck-typed, and it would
    silently sweep in any future model that grows a similarly named column.

    An unreadable value leaves the field **untouched** rather than resetting it.
    Failing to zero here would release a restriction, which is the one direction
    this must never fail in; failing to leave it alone costs nothing.
    """
    if user_type is not None and user_type != "customer":
        return

    from models.wallet_transaction_model import TransactionType

    try:
        restricted = Decimal(str(owner.non_withdrawable_balance or 0))
        balance = Decimal(str(owner.wallet_balance or 0))
    except (AttributeError, InvalidOperation, TypeError, ValueError):
        return

    if delta < 0 and transaction_type != TransactionType.withdrawal:
        restricted = max(Decimal("0"), restricted + delta)   # delta is negative

    owner.non_withdrawable_balance = max(Decimal("0"), min(restricted, balance))


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
    _rebalance_restricted_credit(
        owner, delta=delta, transaction_type=transaction_type, user_type=user_type
    )

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
    from services import platform_config_service as config

    await config.ensure_fresh(session)
    minimum_topup = config.get_decimal("min_wallet_topup")
    if amount_dec < minimum_topup:
        raise HTTPException(status_code=400, detail=f"Minimum top-up amount is {minimum_topup:.0f} KSH.")
    if amount_dec != amount_dec.to_integral_value():
        raise HTTPException(status_code=400, detail="Top-up amount must be a whole number of shillings.")
    if not re.match(r"^254[17]\d{8}$", phone or ""):
        raise HTTPException(
            status_code=400,
            detail="Phone number must be in the format 2547XXXXXXXX or 2541XXXXXXXX.",
        )

    # Confirms the caller owns a wallet of this type before any money moves, and
    # tells us *which* row — `store_id` was resolved here and then thrown away,
    # so a two-branch owner topping up their second store had the first one
    # credited by the callback below.
    user_type, _model, owner = await resolve_wallet_owner(
        session, user_id, user_type, store_id=store_id
    )

    # Trigger M-Pesa STK Push
    response = await initiate_stk_push(phone=phone, amount=int(amount_dec))
    if "error" in response or response.get("ResponseCode") != "0":
        logger.error(f"STK Push Failed: {response}")
        raise HTTPException(status_code=400, detail="Failed to initiate STK push. Please try again.")

    checkout_request_id = response.get("CheckoutRequestID")

    # Log pending transaction
    transaction = WalletTransaction(
        user_id=user_id,
        user_type=UserType[user_type.lower()],
        wallet_owner_id=owner.id,
        transaction_type=TransactionType.top_up,
        amount=amount_dec,
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

        owner = await _locked_wallet_owner(session, model, transaction)
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

    # ── The one withdrawal schedule ──
    # Minimum, fee and waiver come from `settlement_service`, which
    # `payout_service` also reads. This function used to carry its own set of
    # literals: a flat 500 minimum against the other path's 250/500/1000, and a
    # fee waived on the *balance held* rather than the amount withdrawn. The same
    # withdrawal therefore cost a different amount depending on which endpoint
    # the app called.
    from services.settlement_service import (
        assert_withdrawable,
        banded_fee_for,
        withdrawal_terms,
    )

    raw_vendor_type = getattr(user, "vendor_type", None)
    vendor_type_str = (
        raw_vendor_type.value if hasattr(raw_vendor_type, "value")
        else (str(raw_vendor_type) if raw_vendor_type else None)
    )
    minimum, fee, waiver = await withdrawal_terms(
        session, provider_type=user_type, vendor_type=vendor_type_str
    )

    if amount < minimum:
        raise HTTPException(
            status_code=400, detail=f"Minimum withdrawal amount is {minimum:.0f} KSH."
        )

    transaction_fee = banded_fee_for(amount, fee, waiver)
    if amount <= transaction_fee:
        raise HTTPException(status_code=400, detail=f"Withdrawal amount must be greater than network fee (KSH {transaction_fee}).")

    # M-Pesa moves whole shillings only. The fee is a `Platform_Settings` row an
    # administrator may set to 15.50 at any time; the amount withdrawn is
    # integral, so the *net* need not be. `initiate_b2c_payout` used to
    # `int()` it — the wallet was debited 1000, the fee recorded as 15.50 and
    # 984 arrived on the phone, with the missing 50 cents in no ledger anywhere.
    # Round the fee up instead: the provider is told the exact figure below and
    # the debit, the disbursement and the fee reconcile to the shilling.
    disbursement_amount = (amount - transaction_fee).to_integral_value(rounding=ROUND_DOWN)
    transaction_fee = amount - disbursement_amount
    if disbursement_amount <= 0:
        raise HTTPException(
            status_code=400,
            detail=f"Withdrawal amount must be greater than network fee (KSH {transaction_fee}).",
        )

    # ── The float check this path was missing ──
    # `wallet_balance` alone is not what is spendable: a rider carrying open cash
    # orders has already promised part of it to the vendor's cut and the
    # platform's, settled when they deliver. Comparing against the raw balance
    # let them withdraw the float backing those orders and then deliver into a
    # negative balance the platform has no way to collect — while
    # `POST /api/payouts/request` refused the very same request.
    await assert_withdrawable(
        session,
        provider_id=user.id,
        provider_type=user_type,
        wallet_balance=current_balance,
        amount=amount,
    )

    # Balance and ledger row in one call, like every other movement on the
    # platform. This function used to assign `wallet_balance` and hand-build the
    # `WalletTransaction` beside it — the one pairing `apply_wallet_delta` exists
    # to make inseparable, on the single largest debit the platform performs.
    #
    # Signed: money leaving is negative. `transaction_type` cannot carry the
    # direction because `order_payment` goes both ways — it debits a rider
    # settling a cash order and credits them for delivery earnings.
    transaction = await apply_wallet_delta(
        session,
        owner=user,
        clerk_id=user_id,
        user_type=user_type,
        amount=-amount,
        transaction_type=TransactionType.withdrawal,
        description=f"M-Pesa B2C Withdrawal (Net: {disbursement_amount}, Fee: {transaction_fee})",
        status=TransactionStatus.pending,
    )
    #: The row this balance came off. `user_id` is a Clerk id, and one identity
    #: can own several stores — without this the callback re-resolved by clerk id
    #: and `.first()`, so a failed withdrawal from the second branch was refunded
    #: to the first. Two real balances, one wrong by the amount of the other.
    transaction.wallet_owner_id = user.id
    await session.commit()
    await session.refresh(transaction)

    response = await initiate_b2c_payout(phone=phone, amount=disbursement_amount, payout_id=str(transaction.id))

    if not response.get("success"):
        # Re-fetch and lock again — never trust the stale `current_balance`
        # closure on revert, since another transaction may have touched this
        # wallet in the meantime. **By primary key**, for the same reason the
        # debit above locks by primary key: `clerk_id` plus `.first()` credits
        # whichever of the owner's stores the database happens to return.
        result = await session.execute(
            select(model).where(model.id == user.id).with_for_update()
        )
        fresh_user = result.scalars().first()
        if fresh_user is not None:
            await apply_wallet_delta(
                session,
                owner=fresh_user,
                clerk_id=user_id,
                user_type=user_type,
                amount=amount,
                transaction_type=TransactionType.refund,
                description="Withdrawal failed before it left, amount returned",
                reference_id=str(transaction.id),
            )
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

    # Serialised explicitly rather than handed back as ORM rows. FastAPI's
    # encoder turns a `Numeric` `Decimal` into a JSON number, so the wallet
    # ledger — every top-up, withdrawal and refund a provider can inspect — was
    # the one history of their money that left here as a float.
    return {
        "data": [
            {
                "id": str(t.id),
                "transaction_type": t.transaction_type.value
                if hasattr(t.transaction_type, "value")
                else t.transaction_type,
                "status": t.status.value if hasattr(t.status, "value") else t.status,
                "amount": money_str(t.amount),
                "reference_id": t.reference_id,
                "mpesa_receipt_number": t.mpesa_receipt_number,
                "description": t.description,
                "failure_reason": t.failure_reason,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in transactions
        ],
        "nextCursor": next_offset if next_offset < total_count else None,
        "hasNextPage": next_offset < total_count,
        "total": total_count
    }
