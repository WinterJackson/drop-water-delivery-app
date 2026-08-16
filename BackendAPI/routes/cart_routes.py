from dotenv import load_dotenv

load_dotenv()

import re
from decimal import Decimal

from fastapi import APIRouter, Depends, Request, HTTPException, Query
from dependencies.dependencies import get_db
from dependencies.auth_dependencies import get_current_customer, authorise_order_access
from core.redis_client import redis_limiter as limiter
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from services.user_service import get_user
from services.cart_services import add_to_cart_service, fetch_cart, fetch_detailed_cart, change_cart_item_quantity_service, delete_cart_item_service, delete_cart_service
from services.dispatch_policy import DispatchPolicy
from utils.money import money_str
from schemas.common_schemas import RequestBodyIdAndQuantity, RequestBodyId
from schemas.cart_schemas import CartDetailed
from services.payment_service import initiate_stk_push, check_payment, order_callback_url
from services.order_service import OrderStatusEnum, create_order, fetch_orders_by_id, update_orders_payment_status_by_checkout_id, cancel_customer_order
from uuid import UUID

# payment imports
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from services.payment_service import reject_mpesa_callback

logger = logging.getLogger(__name__)


# order imports
from schemas.order_schema import BaseOrder


router = APIRouter()

# CART ROUTES[
                  # NB / BEWARE OF THE TOTALS WHENEVER YOU ARE MANIPULATING THE CART 
  # >ADD TO CART 
      # POSSIBILITIES [ CART DOES NOT EXIST, CART EXISTS, ITEM DOES NOT EXIST IN THE CART, ITEM EXISTS IN THE CART]
        # CART DOES NOT EXIST [ >--> CREATE THE CART AND ADD THE ITEM IN THE CART ]
        # CART EXISTS [ >--> CHECK IF ITEM EXISTS IN THE CART OR NOT ]
        # ITEM DOESN'T EXIST IN CART [ >--> ADD THE ITEM TO THE EXISTING CART AND UPDATE THE TOTAL ACCORDINGLY ]
        # ITEM EXISTS [ >--> JUST INCREASE ITS QUANTITY AND UPDATE THE TOTAL ACCORDINGLY ]
        
  # >FETCH CART AND CART ITEMS FO A SPECIFIC USER 
      # POSSIBILITIES [ CART EXISTS , CART DOES NOT EXIST ]
        # CART DOESN'T EXIST [ JUST RETURN NOTHING ]
        # CART EXISTS [ RETURN THE CART  ]
  # >ADD ITEMS TO CART [ NEW ITEM AND INCREASING QUANTITY ]
  # >CHANGE QUANTITY OF ANT ITEM IN THE CART [ INCREASE & DECREASE ]
  # >DELETE CART 
# ]

class AddToCartRequest(BaseModel):
  id: str | UUID
  quantity: int
  force_replace: bool = False

@router.post("/add_to_cart")
@limiter.limit("15/minute")
async def add_to_cart(request: Request, request_body: AddToCartRequest, db: AsyncSession = Depends(get_db), user = Depends(get_current_customer)):
  clerkId = user["sub"]
  db_user = await get_user(session=db, clerk_id=clerkId)
  if not db_user:
    raise HTTPException(status_code=403, detail="Customer profile not found.")
  await add_to_cart_service(
    user_id=db_user.id,
    session=db,
    product_id=request_body.id,
    quantity=request_body.quantity,
    force_replace=request_body.force_replace
  )
  return {
    "message": "Item added to cart"
  }

class Id(BaseModel):
  id: str | UUID
@router.get("/get_cart")
# async def get_cart( request: Id, db: AsyncSession = Depends(get_db)):
async def get_cart( db: AsyncSession = Depends(get_db), user = Depends(get_current_customer)):
  clerkId = user["sub"]
  user = await get_user(session=db, clerk_id=clerkId)
  cart = await fetch_cart(user_id=user.id, session=db)
  return cart

@router.get("/get_detailed_cart", response_model=CartDetailed | None)
async def get_detailed_cart(db: AsyncSession = Depends(get_db), user = Depends(get_current_customer)):
  clerk_id = user["sub"]
  db_user = await get_user(session=db, clerk_id=clerk_id)
  cart = await fetch_detailed_cart(user_id=db_user.id, session=db)
  return cart

@router.post("/change_cart_item_quantity")
async def change_cart_item_quantity(request_body: RequestBodyIdAndQuantity, db: AsyncSession= Depends(get_db), user = Depends(get_current_customer)):
  clerkId = user["sub"]
  user = await get_user(session=db, clerk_id=clerkId)
  await change_cart_item_quantity_service(user_id=user.id, session=db, quantity=request_body.quantity, id=request_body.id)
  return {
    "message": "Cart Quantity Updated"
  }

@router.post("/delete_cart_item")
async def delete_cart_item(request_body: RequestBodyId, db: AsyncSession = Depends(get_db), user = Depends(get_current_customer)):
  clerkId = user["sub"]
  user_obj = await get_user(session=db, clerk_id=clerkId)
  await delete_cart_item_service(cart_item_id=request_body.id, user_id=user_obj.id, session=db)
  return {
    "message": "item deleted successfully"
  }

ALLOWED_PAYMENT_METHODS = {"mpesa", "cash"}
KENYAN_MSISDN = re.compile(r"^254[17]\d{8}$")


class OrderRequest(BaseModel):
    phone: str  # Format: 2547XXXXXXXX
    # NOTE: `amount` is intentionally absent. The server prices the cart itself —
    # a client-supplied total is a price-manipulation vector.
    id: UUID
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    delivery_type: str = "quick_swap"
    payment_method: str = "mpesa"


class QuoteRequest(BaseModel):
    """Price the current cart for display. No side effects."""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    delivery_type: str = "quick_swap"
    #: Quoted, not charged. The cart shows both prices so the customer can see
    #: what paying by M-Pesa saves them before they choose.
    payment_method: str = "mpesa"


async def _load_priced_cart(db: AsyncSession, user_id, lat: float, lng: float, delivery_type: str, payment_method: str = "mpesa"):
    """Fetch the cart, resolve its vendor, and price it.

    Shared by `/quote` and `/mpesa_payment` so the number the customer sees in the
    checkout sheet is produced by the identical code path that charges them.
    """
    from models.user_model import User
    from models.vendor_model import Vendor
    from services.cart_services import fetch_detailed_cart
    from services.pricing_service import compute_order_quote, single_vendor_or_400

    cart = await fetch_detailed_cart(user_id=user_id, session=db)
    if not cart or not cart.cart_item:
        raise HTTPException(
            status_code=400,
            detail="Your cart is empty. Add an item before checking out.",
        )

    vendor_id = single_vendor_or_400(cart.cart_item)
    vendor = await db.get(Vendor, vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="This vendor is no longer available.")

    db_user = await db.get(User, user_id)

    quote = await compute_order_quote(
        db,
        items=cart.cart_item,
        user=db_user,
        vendor=vendor,
        delivery_type=delivery_type,
        lat=lat,
        lng=lng,
        # The method changes the price: paying by M-Pesa earns a discount, and
        # a cash order costs the platform handling instead of a Safaricom
        # tariff. Quoting without it would show one number and charge another.
        payment_method=payment_method,
    )
    return cart, db_user, vendor, quote


@router.post("/quote")
@limiter.limit("30/minute")
async def quote_cart(
    request: Request,
    body: QuoteRequest,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_customer),
):
    """Authoritative, fully itemised price for the current cart.

    The client renders this verbatim instead of recomputing the total locally.
    Four independent implementations of this arithmetic used to disagree, so the
    customer was shown one figure and charged another.
    """
    from services.pricing_service import validate_quote

    db_user = await get_user(session=db, clerk_id=user["sub"])
    if not db_user:
        raise HTTPException(status_code=403, detail="Customer profile not found.")

    cart, db_user, vendor, quote = await _load_priced_cart(
        db, db_user.id, body.lat, body.lng, body.delivery_type, body.payment_method
    )

    # Surface rule violations as advisory warnings rather than hard failures, so
    # the cart screen can explain "you need 38 kg more" instead of showing an
    # error page before the customer has even pressed Checkout.
    warnings: list[str] = []
    try:
        validate_quote(quote, cart.cart_item, user=db_user, vendor=vendor)
        checkout_ready = True
    except HTTPException as exc:
        checkout_ready = False
        detail = exc.detail
        warnings.append(detail if isinstance(detail, str) else str(detail))

    payload = quote.as_dict()
    payload["checkout_ready"] = checkout_ready
    payload["warnings"] = warnings
    # Both through the accessors: these two figures are what the cart shows the
    # customer as the rule, and a shipped default shown beside a configured
    # enforcement is a cart that explains a refusal with the wrong number.
    payload["moq_kg"] = (
        DispatchPolicy.wholesale_moq_kg() if quote.vendor_type == "wholesale_b2b" else None
    )
    payload["max_units"] = 4 if quote.vendor_type == "retail_refill" else None
    payload["max_distance_km"] = DispatchPolicy.max_distance_km(quote.vendor_type)

    # Whether cash is offered on *this* basket, decided by the same function
    # checkout will use. Answered here so the cart can grey the option out with
    # the reason attached, rather than letting somebody pick it, fill in a phone
    # number and be refused — the refusal is identical either way, and the only
    # difference is whether the customer wasted the trip.
    from services import cod_policy

    try:
        await cod_policy.assert_customer_may_pay_cash(
            db, user=db_user, total=quote.total, distance_km=quote.distance_km,
            vendor=vendor,
        )
        payload["cash"] = {"available": True, "reason": None}
    except HTTPException as exc:
        payload["cash"] = {
            "available": False,
            # The server's own sentence, rendered verbatim. The app must never
            # compose its own: these rules are settings rows and the wording
            # moves with them.
            "reason": exc.detail if isinstance(exc.detail, str) else str(exc.detail),
        }

    # Whether the *store* is taking this order, for the same reason. The
    # minimum-order shortfall arrives through `warnings` above, from
    # `validate_quote`, so the cart's existing "you need 38 kg more" treatment
    # covers "add KSH 120 more" without a second mechanism; this block is what
    # lets the screen render a closed shop as closed instead of as a failure.
    from services import vendor_availability

    payload["store"] = (await vendor_availability.store_state(db, vendor)).as_dict()

    return payload


@router.post("/mpesa_payment")
@limiter.limit("5/minute")
async def payment_request(request: Request, order: OrderRequest, db: AsyncSession = Depends(get_db), user = Depends(get_current_customer)):
    """Price the cart, validate everything, then move money — in that order.

    Sequencing matters: every gate runs *before* `initiate_stk_push`, because a
    validation error raised after the push leaves the customer with a PIN prompt
    for an order that will never exist. The single `quote` computed here is both
    the amount pushed to M-Pesa and the amount written to `order.total_amount`,
    which is what makes the callback's amount cross-check pass.
    """
    from services.pricing_service import validate_quote

    if order.payment_method not in ALLOWED_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail="Unsupported payment method.")

    if not KENYAN_MSISDN.match(order.phone or ""):
        raise HTTPException(
            status_code=400,
            detail="Enter a valid Kenyan M-Pesa number in the format 2547XXXXXXXX.",
        )

    db_user = await get_user(session=db, clerk_id=user["sub"])
    if not db_user:
        raise HTTPException(status_code=403, detail="Customer profile not found.")
    authenticated_user_id = db_user.id

    cart, db_user, vendor, quote = await _load_priced_cart(
        db, authenticated_user_id, order.lat, order.lng, order.delivery_type,
        order.payment_method,
    )

    if getattr(cart, "is_locked", False):
        raise HTTPException(
            status_code=409,
            detail="A checkout is already in progress for this cart. Please wait for the M-PESA prompt or check your orders."
        )

    if str(cart.id) != str(order.id):
        raise HTTPException(status_code=400, detail="Cart mismatch. Please refresh your cart and try again.")

    # Every gate, before any money moves.
    validate_quote(quote, cart.cart_item, user=db_user, vendor=vendor)

    # Is the shop actually open? A store can pause between the quote the
    # customer is looking at and the tap that charges them, and the failure
    # this prevents is the expensive one: a paid order sitting in a closed
    # store until it auto-cancels, with a refund to process and a customer who
    # has been waiting for water.
    from services import vendor_availability

    await vendor_availability.assert_store_accepting(db, vendor)

    # Cash has its own gates, and they are about *who is asking* rather than
    # what is in the basket — so they sit here rather than in `validate_quote`,
    # which never sees the payment method. Refused before an order exists, so
    # there is nothing to unwind: a first-time account plus a fake address plus
    # cash costs the rider a wasted trip and the vendor a prepared order, and
    # it is free to attempt.
    if order.payment_method == "cash":
        from services import cod_policy

        await cod_policy.assert_customer_may_pay_cash(
            db, user=db_user, total=quote.total, distance_km=quote.distance_km,
            vendor=vendor,
        )

    # Lock the cart so it cannot be mutated during the STK Push window.
    cart.is_locked = True
    await db.commit()

    checkout_request_id = None
    try:
        if order.payment_method == "cash":
            logger.info("Cash order requested, amount: %s", quote.total)
            created = await create_order(
                session=db, id=cart.id, type="cart",
                CheckoutRequestID=None, user_id=authenticated_user_id,
                phone=order.phone, lat=order.lat, lng=order.lng,
                delivery_type=order.delivery_type, payment_method="cash",
                quote=quote,
            )
            if not created:
                raise HTTPException(status_code=400, detail="Order not created. Please try again.")

            # Cash orders defer payment, so the cart is consumed immediately.
            try:
                from services.cart_services import delete_cart_service
                await delete_cart_service(cart_id=str(cart.id), db=db)
            except Exception as e:
                logger.error("Failed to clear cart after cash order creation: %s", e)

            return {
                "message": "order created",
                "payment_method": "cash",
                "CheckoutRequestID": None,
                "order_id": str(created.id),
                "amount": money_str(quote.total),
            }

        # ── M-PESA STK Push ────────────────────────────────────────────────
        response = await initiate_stk_push(
            phone=order.phone,
            amount=quote.stk_amount,
            # An order is settled by the order callback. Named explicitly: this
            # used to be a module-level default that the wallet top-up path
            # inherited, and inheriting it sent every top-up's confirmation to
            # this endpoint, which resolves the id against `Orders`.
            callback_url=order_callback_url(),
        )
        checkout_request_id = response.get("CheckoutRequestID")
        if not checkout_request_id:
            # Safaricom refused the request outright — nothing was charged.
            logger.error("STK push did not return a CheckoutRequestID: %s", response)
            raise HTTPException(
                status_code=502,
                detail="M-PESA could not start this payment. Please try again in a moment.",
            )

        logger.info(
            "STK push initiated: CheckoutRequestID=%s amount=%s", checkout_request_id, quote.stk_amount
        )

        created = await create_order(
            session=db, id=cart.id, type="cart",
            CheckoutRequestID=checkout_request_id, user_id=authenticated_user_id,
            phone=order.phone, lat=order.lat, lng=order.lng,
            delivery_type=order.delivery_type, payment_method="mpesa",
            quote=quote,
        )
        if not created:
            raise HTTPException(status_code=400, detail="Order not created. Please try again.")

        # The cart is deleted only once payment settles (in /confirm_payment or
        # the callback), so a failed payment leaves the customer's cart intact.
        return {
            "message": "order created",
            "payment_method": "mpesa",
            "CheckoutRequestID": checkout_request_id,
            "order_id": str(created.id),
            "amount": money_str(quote.total),
        }

    except Exception as e:
        await db.rollback()
        # Release the cart so the customer can retry.
        try:
            fresh_cart = await fetch_cart(user_id=authenticated_user_id, session=db)
            if fresh_cart:
                fresh_cart.is_locked = False
                await db.commit()
        except Exception as unlock_err:
            logger.error("Failed to unlock cart after checkout failure: %s", unlock_err)

        # If the push already went out, the customer may still be prompted for a
        # PIN. Record the exposure so the refund sweep can reverse anything that
        # actually gets collected — this must never be a silent loss.
        if checkout_request_id:
            logger.error(
                "Order creation failed AFTER STK push %s — recording orphaned payment.",
                checkout_request_id,
            )
            try:
                from models.payment_model import Payment
                db.add(Payment(
                    order_id=None,
                    checkout_request_id=checkout_request_id,
                    phone=order.phone,
                    amount=quote.total,
                    status="orphaned",
                    failure_reason=str(getattr(e, "detail", e))[:500],
                ))
                await db.commit()
            except Exception as audit_err:
                logger.error("Failed to record orphaned payment: %s", audit_err)
            raise HTTPException(
                status_code=409,
                detail=(
                    "We could not complete your order. If you were charged, the amount "
                    "will be reversed automatically. Please check your orders before retrying."
                ),
            )
        raise e

class RequestCheckoutRequestID(BaseModel):
  CheckoutRequestID: str  
@router.post("/confirm_payment")
@limiter.limit("20/minute")
async def payment_confirmation(request: Request, body: RequestCheckoutRequestID, db: AsyncSession = Depends(get_db), user = Depends(get_current_customer)):
  """Poll Safaricom for the outcome of *the caller's own* checkout.

  The checkout id names an order, so this is an order-scoped action and has to
  be authorised as one. It took any `CheckoutRequestID` from any signed-in
  customer: the ids are unguessable, so nothing could be forged, but a leaked or
  logged id let one account drive another's payment transition and clear its own
  cart off the back of it. Authenticating proves who is calling, not that they
  have anything to do with that payment.
  """
  from sqlalchemy import select as sa_select

  from models.order_model import Order

  CheckoutRequestID = body.CheckoutRequestID

  user_obj = await get_user(session=db, clerk_id=user["sub"])
  if not user_obj:
      raise HTTPException(status_code=403, detail="Customer profile not found.")

  owns_it = (
      await db.execute(
          sa_select(Order.id)
          .where(
              Order.checkout_request_ID == CheckoutRequestID,
              Order.customer_id == user_obj.id,
          )
          .limit(1)
      )
  ).scalars().first()
  if owns_it is None:
      # 404 rather than 403: confirming the id exists is not ours to do.
      raise HTTPException(status_code=404, detail="No payment found for this checkout.")

  response = await check_payment(checkout_request_id=CheckoutRequestID, session=db)

  # BUG-04 FIX: Purge cart after successful manual payment confirmation
  if response.get("code") == "0":
      try:
          cart = await fetch_cart(user_id=user_obj.id, session=db)
          if cart:
              await delete_cart_service(cart_id=str(cart.id), db=db)
      except Exception as e:
          logger.error(f"Failed to clear cart after confirm_payment: {e}")

  return response

@router.get("/get_orders",response_model=list[BaseOrder])
async def get_orders_by_id(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: str | None = Query(
        None,
        description="Comma-separated order statuses, e.g. 'delivered' or 'cancelled,rejected'.",
    ),
    db: AsyncSession= Depends(get_db),
    user = Depends(get_current_customer)
):
  clerkId = user["sub"]
  user = await get_user(session=db, clerk_id=clerkId)

  # Validated against the enum rather than passed through. An unknown status
  # would produce an empty page, which the screen can only render as "you have
  # no orders" — a typo in a client's filter table reads to the customer as
  # their history having been lost.
  statuses: list[str] | None = None
  if status:
    statuses = [part.strip().lower() for part in status.split(",") if part.strip()]
    known = {member.value for member in OrderStatusEnum}
    unknown = sorted(set(statuses) - known)
    if unknown:
      raise HTTPException(
          status_code=400,
          detail=f"Unknown order status: {', '.join(unknown)}.",
      )

  orders = await fetch_orders_by_id(
      session=db, user_id=user.id, skip=skip, limit=limit, statuses=statuses
  )
  return orders

@router.get("/orders/last-completed", response_model=BaseOrder | None)
async def fetch_last_completed_order(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_customer)
):
    from services.order_service import get_last_completed_order
    clerkId = user["sub"]
    user_obj = await get_user(session=db, clerk_id=clerkId)
    order = await get_last_completed_order(session=db, user_id=user_obj.id)
    return order

@router.get("/orders/active", response_model=BaseOrder | None)
async def fetch_active_order(
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_customer)
):
    from services.order_service import get_active_order
    clerkId = user["sub"]
    user_obj = await get_user(session=db, clerk_id=clerkId)
    order = await get_active_order(session=db, user_id=user_obj.id)
    return order


@router.post("/mpesa/callback")
async def mpesa_callback(request: Request, db: AsyncSession = Depends(get_db), secret: str | None = Query(default=None)):
    rejected = reject_mpesa_callback(request, secret, "Order payment callback")
    if rejected:
        return rejected

    try:
        data = await request.json()
        callback = data["Body"]["stkCallback"]
        result_code = callback["ResultCode"]
        result_desc = callback["ResultDesc"]
        checkout_request_id = callback["CheckoutRequestID"]

        if result_code == 0:
            metadata = callback["CallbackMetadata"]["Item"]
            callback_amount = next(item["Value"] for item in metadata if item["Name"] == "Amount")
            callback_phone = str(next(item["Value"] for item in metadata if item["Name"] == "PhoneNumber"))
            receipt = next(item["Value"] for item in metadata if item["Name"] == "MpesaReceiptNumber")

            # --- Cross-validate callback against original order record ---
            from sqlalchemy import select as sa_select
            from models.order_model import Order
            stmt = sa_select(Order).where(Order.checkout_request_ID == checkout_request_id)
            result = await db.execute(stmt)
            order = result.scalars().first()

            if not order:
                logger.error(f"M-PESA callback: No order found for CheckoutRequestID {checkout_request_id}")
                return JSONResponse(status_code=400, content={"message": "Order not found"})

            # Validate phone matches (compare last 9 digits to handle country code variations)
            order_phone_suffix = order.phone[-9:] if order.phone else ""
            callback_phone_suffix = callback_phone[-9:] if callback_phone else ""
            if order_phone_suffix != callback_phone_suffix:
                logger.error(f"M-PESA callback phone mismatch: order={order.phone}, callback={callback_phone}")
                return JSONResponse(status_code=400, content={"message": "Phone mismatch"})

            # Validate amount matches. Since `pricing_service` quantizes the order
            # total to whole shillings and hands that same integer to the STK push,
            # this is now an exact comparison; the ±1 tolerance is kept only to
            # absorb any rounding Safaricom applies on their side.
            if abs(float(order.total_amount) - float(callback_amount)) > 1.0:
                logger.error(
                    "M-PESA callback amount mismatch: order=%s, callback=%s, checkout=%s",
                    order.total_amount, callback_amount, checkout_request_id,
                )
                return JSONResponse(status_code=400, content={"message": "Amount mismatch"})

            from utils.redaction import redact_phone
            logger.info(f"M-PESA Payment Verified: receipt={receipt}, amount={callback_amount}, phone={redact_phone(str(callback_phone))}")

            # --- Idempotency, keyed on the collection itself ------------------
            #
            # Safaricom retries this callback until it gets a 200, and the client
            # polls `/confirm_payment` every few seconds in parallel. Both mark
            # the order paid through `update_orders_payment_status_by_checkout_id`,
            # which is idempotent under a row lock — so the *side effects* were
            # safe. Everything in this handler around that call was not.
            #
            # The poll usually wins, and then the status update returns early —
            # before its own `commit()` — so the `Payment` row added here was
            # never flushed. The payments audit table was therefore missing rows
            # for precisely the ordinary case, and the customer got another
            # confirmation email on every retry.
            #
            # `checkout_request_id` is UNIQUE, so it is the natural idempotency
            # key: one row per collection attempt, updated rather than inserted
            # twice, and committed here rather than riding on somebody else's
            # transaction.
            from models.payment_model import Payment

            existing = (
                await db.execute(
                    sa_select(Payment).where(Payment.checkout_request_id == checkout_request_id)
                )
            ).scalars().first()

            if existing is not None and existing.status == "paid":
                logger.info(
                    "M-PESA callback for %s already recorded as paid — no-op.",
                    checkout_request_id,
                )
                return {"message": "Callback received"}

            if existing is not None:
                # A `failed` row for this attempt, now superseded by a success.
                existing.order_id = order.id
                existing.mpesa_receipt = receipt
                existing.phone = callback_phone
                existing.amount = Decimal(str(callback_amount))
                existing.status = "paid"
                existing.failure_reason = None
            else:
                db.add(
                    Payment(
                        order_id=order.id,
                        checkout_request_id=checkout_request_id,
                        mpesa_receipt=receipt,
                        phone=callback_phone,
                        # `Decimal(str(...))`, never the raw JSON number: this is
                        # money, and `amount` is a NUMERIC column. A float here is
                        # the same defect the rest of the platform goes out of its
                        # way to avoid, with nothing to grep for.
                        amount=Decimal(str(callback_amount)),
                        status="paid",
                    )
                )

            # Commit the audit row on its own, so it survives regardless of
            # whether the transition below finds the order already settled.
            await db.commit()

            # Did *this* call settle the order? The status update is a no-op when
            # the poll got there first, and the follow-up work below — an email
            # to the customer, purging their cart — must happen once, not once
            # per retry.
            settled_here = order.payment_status != "paid"

            await update_orders_payment_status_by_checkout_id(
                session=db, checkout_request_id=checkout_request_id, new_status="paid"
            )

            if not settled_here:
                return {"message": "Callback received"}

            # --- Send Order Confirmation Email ---
            try:
                from models.user_model import User
                from services.email_service import send_order_confirmation
                # EDGE-02 FIX: customer_id is a UUID (User.id), not a Clerk ID
                stmt_user = sa_select(User).where(User.id == order.customer_id)
                user_res = await db.execute(stmt_user)
                customer = user_res.scalars().first()
                if customer and customer.email:
                    order_details = {
                        "id": str(order.id)[:8].upper(),
                        "total_amount": money_str(order.total_amount),
                        "date": order.created_at.strftime("%b %d, %Y") if order.created_at else "Today"
                    }
                    send_order_confirmation(
                        to=customer.email, 
                        name=customer.full_name or "Valued Customer", 
                        order_details=order_details
                    )
            except Exception as email_err:
                logger.error(f"Failed to send order confirmation email: {email_err}")

            # Safely clear the original cart payload since the order is finalized
            try:
                from services.cart_services import delete_cart_service
                # Use the order details. In create_order, the order.user_id matches the Cart user
                # We can fetch the cart by user ID and delete it.
                from services.cart_services import fetch_cart
                cart_record = await fetch_cart(user_id=order.customer_id, session=db)
                if cart_record:
                    await delete_cart_service(cart_id=str(cart_record.id), db=db)
            except Exception as cart_e:
                logger.error(f"Error purging active cart after callback success: {cart_e}")
        else:
            logger.warning(f"M-PESA Payment Failed: {result_desc} (Code: {result_code})")
            # --- Create Payment audit record for failed transaction ---
            try:
                from models.payment_model import Payment
                from sqlalchemy import select as sa_select
                from models.order_model import Order
                stmt = sa_select(Order).where(Order.checkout_request_ID == checkout_request_id)
                result = await db.execute(stmt)
                order = result.scalars().first()
                payment = Payment(
                    order_id=order.id if order else None,
                    checkout_request_id=checkout_request_id,
                    phone=order.phone if order else "unknown",
                    # Money, on a NUMERIC column — see the success branch above.
                    amount=Decimal(str(order.total_amount)) if order else Decimal("0"),
                    status="failed",
                    failure_reason=result_desc,
                )
                db.add(payment)
                
                # EDGE-01 FIX: Unlock the cart so the user can try again
                if order:
                    from services.cart_services import fetch_cart
                    cart_record = await fetch_cart(user_id=order.customer_id, session=db)
                    if cart_record:
                        cart_record.is_locked = False
                
                await db.commit()
            except Exception as pay_e:
                logger.error(f"Error creating failed payment record: {pay_e}")

    except Exception as e:
        logger.error("Error processing M-PESA callback", exc_info=True)
        try:
            import sentry_sdk
            from utils.redaction import redact_payload
            raw_body = await request.body()
            payload_str = raw_body.decode("utf-8")
            redacted_payload = redact_payload(payload_str)
            sentry_sdk.set_context("webhook_payload", {"raw": redacted_payload})
            sentry_sdk.capture_exception(e)
            
            # DLQ: Store in database
            from dependencies.dependencies import get_db_session
            from models.failed_webhook_model import FailedWebhook
            async with get_db_session() as session:
                dlq_entry = FailedWebhook(
                    source="mpesa",
                    payload=redacted_payload,
                    error_message=str(e)
                )
                session.add(dlq_entry)
                await session.commit()
                logger.info(f"Saved failed webhook to DLQ: {dlq_entry.id}")
        except Exception as dlq_err:
            logger.error(f"Failed to save webhook to DLQ: {dlq_err}", exc_info=True)
        return JSONResponse(status_code=400, content={"message": "Invalid payload"})

    return {"message": "Callback received"}


@router.put("/orders/{order_id}/cancel")
async def customer_cancel_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_customer),
):
    """Customer cancels their own order"""
    clerk_id = user["sub"]
    user_obj = await get_user(session=db, clerk_id=clerk_id)
    result = await cancel_customer_order(session=db, user_id=user_obj.id, order_id=order_id)
    return result

@router.get("/orders/{order_id}", response_model=BaseOrder)
async def get_one_order(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_customer),
):
    """One of the caller's own orders, by id.

    The detail screen and the live map both used to find their order by
    searching the list already in the cache. That worked only while the list was
    every order the customer had, and stopped working the moment it became one
    page: an order older than the newest 25 simply did not exist as far as those
    screens were concerned, so a push notification about it opened a spinner
    that never resolved. The vendor app had exactly this defect and it was fixed
    the same way — see `useVendorOrder`.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload
    from services.order_service import annotate_is_rated
    from models.order_model import Order as OrderModel, OrderItem as OrderItemModel

    # Authenticating proves who is calling, not that they have anything to do
    # with this order.
    await authorise_order_access(db, order_id, user["sub"], allowed_roles=("customer",))

    result = await db.execute(
        select(OrderModel)
        .where(OrderModel.id == order_id)
        .options(
            joinedload(OrderModel.order_item).joinedload(OrderItemModel.product),
            joinedload(OrderModel.vendor),
            joinedload(OrderModel.deliverer),
        )
    )
    order = result.unique().scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    await annotate_is_rated(db, [order])
    return order


@router.get("/orders/{order_id}/tracking-logs")
async def get_order_tracking_logs(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_customer),
):
    """Fetch tracking logs for an order (historical route to draw the polyline)."""
    from services.order_service import fetch_order_tracking_logs

    # Without this the endpoint took any order id from any signed-in customer and
    # returned that order's GPS breadcrumb trail — i.e. somebody else's home.
    await authorise_order_access(db, order_id, user["sub"], allowed_roles=("customer",))

    logs = await fetch_order_tracking_logs(session=db, order_id=order_id)
    return logs


@router.get("/orders/{order_id}/rider-location")
async def get_order_rider_location(
    order_id: UUID,
    db: AsyncSession = Depends(get_db),
    user=Depends(get_current_customer),
):
    """Current rider position for one of the caller's own orders.

    The customer app needs this as the initial paint before its tracking socket
    opens, and as the fallback when the socket cannot connect. It previously
    called the rider app's equivalent under `/api/rider/...`, which is guarded by
    `get_current_rider` and so returned 403 for every customer.
    """
    from models.deliverer_model import Deliverer
    from models.order_model import Order

    await authorise_order_access(db, order_id, user["sub"], allowed_roles=("customer",))

    order = await db.get(Order, order_id)
    if not order or not order.deliverer_id:
        raise HTTPException(status_code=404, detail="No rider is assigned to this order yet.")

    deliverer = await db.get(Deliverer, order.deliverer_id)
    if not deliverer:
        raise HTTPException(status_code=404, detail="Rider not found")

    return {
        "rider_id": str(deliverer.id),
        "rider_name": getattr(deliverer, "name", None) or getattr(deliverer, "full_name", None) or "Rider",
        "lat": deliverer.current_lat,
        "lng": deliverer.current_lng,
        "is_available": deliverer.is_available,
    }


class ResolveMismatchPayload(BaseModel):
    action: str  # "approve_charge" | "leave_ground"

@router.patch("/orders/{order_id}/resolve-mismatch")
async def customer_resolve_mismatch(
    order_id: UUID,
    payload: ResolveMismatchPayload,
    db: AsyncSession = Depends(get_db),
    user = Depends(get_current_customer),
):
    """Customer responds to an Address Mismatch flag"""
    clerk_id = user["sub"]
    user_obj = await get_user(session=db, clerk_id=clerk_id)
    from services.order_service import resolve_address_mismatch
    result = await resolve_address_mismatch(session=db, user_id=user_obj.id, order_id=order_id, action=payload.action)
    return result
