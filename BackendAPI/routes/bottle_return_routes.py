"""Handing bottles back and getting the deposit returned.

Before this the only way a deposit came back was an administrator opening the
console under `finance.adjust` — a grant no preset but super admin holds. So a
deposit was refundable in principle and unreturnable in fact, which makes it a
price rather than a deposit, and the platform's liability only ever grew.

Two surfaces, one flow:

* **The customer** books a collection, then confirms what they handed over.
* **The rider** claims it, and confirms what they received.

Both state a **count**, and the money moves only when the two agree — or when
the timer resolves it in favour of the side that put a physical asset at risk.
The asymmetry is explained in `models/bottle_return_model.py`; the short version
is that a rider confirming a collection is a statement against their own
interest, and a customer confirming one alone is not.

Nothing here computes what a bottle is worth back. That lives in
`customer_bottle_service`, shared with the console's manual return, because the
rider app and the console quoting different figures for the same handover is a
dispute the platform cannot win.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.redis_client import redis_limiter as limiter
from dependencies.auth_dependencies import get_verified_rider
from dependencies.dependencies import get_db
from models.bottle_return_model import BottleReturnRequest, BottleReturnStatus
from models.deliverer_model import Deliverer
from models.user_model import User
from services import customer_bottle_service as deposits
from services.notification_service import create_notification, queue_push
from utils.money import money_str
from utils.verify_user_token import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter()


class ReturnRequest(BaseModel):
    bottles: int = Field(..., ge=1, le=100)


class ConfirmHandover(BaseModel):
    bottles: int = Field(..., ge=0, le=100)
    #: The store the rider will hand these in to. Required from the rider on a
    #: standalone pickup — a returned bottle the ledger cannot attribute is one
    #: the platform has stopped counting.
    vendor_id: UUID | None = None


def _serialise(request: BottleReturnRequest) -> dict:
    return {
        "id": str(request.id),
        "status": request.status,
        "bottles_requested": request.bottles_requested,
        "bottles_stated_by_customer": request.bottles_stated_by_customer,
        "bottles_stated_by_rider": request.bottles_stated_by_rider,
        "bottles_settled": request.bottles_settled,
        "amount_refunded": str(request.amount_refunded) if request.amount_refunded is not None else None,
        "rider_id": str(request.rider_id) if request.rider_id else None,
        "expires_at": request.expires_at.isoformat() if request.expires_at else None,
        "settled_at": request.settled_at.isoformat() if request.settled_at else None,
        "resolution_note": request.resolution_note,
        "created_at": request.created_at.isoformat() if request.created_at else None,
    }


async def _customer_row(db: AsyncSession, auth: dict) -> User:
    user = (
        await db.execute(select(User).where(User.clerk_id == auth["sub"]))
    ).scalars().first()
    if user is None:
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered customer.")
    return user


# ── The customer's side ───────────────────────────────────────────────────


@router.get("/bottle-returns/summary", summary="What I'm holding, and what it's worth back")
async def my_deposit_summary(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_current_user),
):
    """The figure the platform was maintaining correctly and showing to nobody.

    `bottle_deposit_balance` and `bottles_held` have been accurate since they
    existed and appeared on no screen the customer could open — a balance
    somebody cannot check is a balance they cannot trust.
    """
    from services import platform_config_service as config
    from services.settlement_service import withdrawal_terms

    user = await _customer_row(db, auth)
    ceiling = await deposits.bottle_ceiling(db, user)
    open_request = await deposits.open_request_for(db, user.id)

    # The terms this customer's withdrawal and top-up will actually be judged
    # by, from the same `withdrawal_terms` the withdrawal itself calls and the
    # same settings row `initiate_wallet_topup` enforces.
    #
    # The app had both as literals — `MIN_TOP_UP_KSH = 10` and
    # `MIN_WITHDRAWAL_KSH = 500`, under a comment claiming they mirrored the
    # server. The top-up figure happened to match; the withdrawal one was
    # invented. `withdrawal_terms` returns a minimum of **1** and a fee of
    # **0** for a customer — it is their own unspent credit coming back, not
    # earnings — so the screen was refusing, client-side and before any
    # request, every withdrawal under KSH 500 that the platform would have
    # paid. That is the same defect the rider and vendor wallets already had
    # fixed: a rule stated by an app that the platform does not implement.
    #
    # One load, before either read, so the two figures cannot come from two
    # different configurations. `withdrawal_terms` refreshes too, but reading a
    # settings row on the strength of another function having happened to load
    # it first is not a dependency worth having.
    await config.ensure_fresh(db)
    minimum, fee, waiver = await withdrawal_terms(db, provider_type="customer")
    min_topup = config.get_decimal("min_wallet_topup")

    return {
        "bottles_held": int(user.bottles_held or 0),
        "deposit_balance": money_str(user.bottle_deposit_balance or 0),
        "bottle_limit": ceiling,
        "wallet_balance": money_str(user.wallet_balance or 0),
        # Stated plainly rather than left to be discovered at the withdrawal
        # screen. Money you can spend and cannot cash out is a real condition
        # and the customer is entitled to know before they rely on it.
        "wallet_not_withdrawable": money_str(user.non_withdrawable_balance or 0),
        "withdrawal": {
            "minimum": money_str(minimum),
            "fee": money_str(fee),
            # Measured against the amount withdrawn, never the balance held.
            "fee_waiver_threshold": money_str(waiver),
        },
        "topup": {"minimum": money_str(min_topup)},
        "open_request": _serialise(open_request) if open_request else None,
    }


@router.post("/bottle-returns", summary="Book a collection")
@limiter.limit("10/minute")
async def book_collection(
    request: Request,
    body: ReturnRequest,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_current_user),
):
    user = await _customer_row(db, auth)
    created = await deposits.request_return(db, customer_id=user.id, bottles=body.bottles)
    await db.commit()
    await db.refresh(created)
    return _serialise(created)


@router.post("/bottle-returns/{request_id}/confirm", summary="Confirm what I handed over")
@limiter.limit("20/minute")
async def customer_confirm(
    request: Request,
    request_id: UUID,
    body: ConfirmHandover,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_current_user),
):
    user = await _customer_row(db, auth)
    result = await deposits.confirm_handover(
        db, request_id=request_id, bottles=body.bottles, by="customer", actor_id=user.id
    )
    await db.commit()
    return result


@router.delete("/bottle-returns/{request_id}", summary="Cancel a collection")
@limiter.limit("20/minute")
async def customer_cancel(
    request: Request,
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_current_user),
):
    user = await _customer_row(db, auth)
    result = await deposits.cancel_request(db, request_id=request_id, customer_id=user.id)
    await db.commit()
    return result


# ── The rider's side ──────────────────────────────────────────────────────


async def _rider_row(db: AsyncSession, auth: dict) -> Deliverer:
    """The rider row behind an already-KYC-verified token.

    Every rider endpoint here takes `get_verified_rider`, never
    `get_current_rider`. A collection moves **goods and money** — the rider
    takes physical bottles and their confirmation releases a customer's
    deposit — which is exactly the line that dependency's own docstring draws.
    An unverified rider being able to trigger a refund and accrue a bottle debt
    against a store they were never approved to work with is the same defect
    KYC enforcement exists to prevent, arriving through a new door.
    """
    rider = (
        await db.execute(select(Deliverer).where(Deliverer.clerk_id == auth["sub"]))
    ).scalars().first()
    if rider is None:
        raise HTTPException(status_code=403, detail="Access denied. Must be a registered rider.")
    return rider


@router.get("/rider/bottle-returns", summary="Collections waiting to be picked up")
async def open_collections(
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_verified_rider),
):
    """Unclaimed requests, plus anything this rider has already taken on.

    Deliberately not filtered by distance. A collection is not time-critical the
    way a delivery is — it rides along with whatever the rider is already
    doing — and a radius here would hide work from the rider best placed to do
    it on their way past.
    """
    rider = await _rider_row(db, auth)

    rows = (
        await db.execute(
            select(BottleReturnRequest).where(
                (BottleReturnRequest.status == BottleReturnStatus.REQUESTED.value)
                | (
                    (BottleReturnRequest.rider_id == rider.id)
                    & BottleReturnRequest.status.in_([
                        BottleReturnStatus.ASSIGNED.value,
                        BottleReturnStatus.AWAITING_COUNTERPARTY.value,
                    ])
                )
            ).order_by(BottleReturnRequest.created_at)
            .limit(100)
        )
    ).scalars().all()

    return {"items": [_serialise(row) for row in rows]}


@router.post("/rider/bottle-returns/{request_id}/claim", summary="Take on a collection")
@limiter.limit("30/minute")
async def rider_claim(
    request: Request,
    request_id: UUID,
    body: ConfirmHandover | None = None,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_verified_rider),
):
    rider = await _rider_row(db, auth)
    claimed = await deposits.assign_rider(
        db,
        request_id=request_id,
        rider_id=rider.id,
        vendor_id=body.vendor_id if body else None,
    )
    await db.commit()
    await db.refresh(claimed)
    return _serialise(claimed)


@router.post("/rider/bottle-returns/{request_id}/confirm", summary="Confirm what I collected")
@limiter.limit("30/minute")
async def rider_confirm(
    request: Request,
    request_id: UUID,
    body: ConfirmHandover,
    db: AsyncSession = Depends(get_db),
    auth: dict = Depends(get_verified_rider),
):
    """The rider states the count they took possession of.

    `vendor_id` names where the bottles are going. It is what lets
    `bottle_ledger_service` record that this rider is now holding them, so a
    returned bottle leaves the customer's count and arrives somewhere rather
    than leaving the platform's books entirely.
    """
    rider = await _rider_row(db, auth)

    result = await deposits.confirm_handover(
        db,
        request_id=request_id,
        bottles=body.bottles,
        by="rider",
        actor_id=rider.id,
        vendor_id=body.vendor_id,
    )

    # Tell the customer, before the commit, through the platform's own push
    # path — a settlement they only discover by opening the app is a settlement
    # they will raise a ticket about first.
    if result.get("status") == BottleReturnStatus.SETTLED.value:
        customer_id = (
            await db.execute(
                select(BottleReturnRequest.customer_id).where(BottleReturnRequest.id == request_id)
            )
        ).scalar()
        token = (
            await db.execute(select(User.push_token).where(User.id == customer_id))
        ).scalar()
        title = "Deposit returned 🍶"
        message = (
            f"KSH {result.get('amount_refunded')} is back in your wallet for "
            f"{result.get('bottles_returned')} bottle(s). Spend it on your next order."
        )
        await create_notification(
            session=db,
            user_id=customer_id,
            user_type="customer",
            title=title,
            message=message,
            message_type="system_alert",
            action_url="/(screens)/BottleWallet",
        )
        queue_push(db, to=token, title=title, body=message)

    await db.commit()
    return result
