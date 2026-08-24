"""
Orders priced by the platform's own engine, not by a script that guesses.

This replaces two seeders that between them produced data no live code path
could have created:

`seed_orders.py` picked products with `select(Product).limit(10)` and attached
them to a **randomly chosen vendor**, so most orders contained items from a
store that was not fulfilling them — a shape `single_vendor_or_400` refuses at
checkout. It used a flat `delivery_fee = 150.0` regardless of distance, left
every revenue-split column null, wrote `payment_method="card"` (the settlement
path knows only `mpesa` and `cash`, so those orders could never have paid
anybody), and put the customer in Nairobi CBD, roughly 10 km from vendors whose
retail limit is 2 km.

`seed_perfect_orders.py` was closer — it did call `calculate_delivery_fee` — but
still assembled the total by hand from six components, hardcoded surcharges that
did not match the formula (`payload: 500` where `(25-2)x10 = 230`), used
`delivery_type="standard"`, which is not one of the two the platform recognises,
and set neither `distance_km` nor `vehicle_class` on the order. It also drew
products at random, so a "customer orders water" scenario could pick a KSH 14,000
dispenser and produce a KSH 60,000 retail order. That is where the implausible
totals came from.

The approach here is different in kind: **build the cart, then ask
`compute_order_quote` what it costs**, exactly as `create_order` does. Every
line item, every commission and every net figure is whatever the live pricing
engine returns. When a rate changes in `Platform_Settings`, re-seeding produces
data consistent with the new rate for free, and seeded orders can never drift
from what the application would have charged.
"""
import asyncio
import math
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import h3
from faker import Faker
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db.session import AsyncSessionLocal
from models.deliverer_model import Deliverer
from models.order_model import Order, OrderItem
from models.product_model import Product
from models.user_model import User
from models.vendor_model import Vendor
from models.vendor_rider_model import VendorRiderRegistry
from services import platform_config_service as config
from services.pricing_service import compute_order_quote

faker = Faker()
random.seed(20260807)
Faker.seed(20260807)

#: Water, not appliances. A dispenser is a legitimate retail product and a
#: nonsensical thing for a delivery-scenario seeder to pick — four of them is a
#: KSH 56,000 order that tells you nothing about how the platform behaves.
DELIVERABLE_CATEGORIES = ("dispenser_refill", "jerrycan", "bulk_wholesale")


@dataclass
class _CartLine:
    """What `compute_order_quote` needs from a cart item.

    A plain object rather than a `CartItem`, because the quote is computed
    before any row is written and a half-populated ORM instance in the session
    is a flush waiting to fail.
    """

    product: Product
    quantity: int
    price: Decimal
    Subtotal: Decimal
    vendor_id: Any


def _point_at(lat: float, lng: float, distance_km: float) -> tuple[float, float]:
    """A point exactly `distance_km` from the given one, on a random bearing."""
    radius = 6371.0
    bearing = math.radians(random.uniform(0, 360))
    lat1, lng1 = math.radians(lat), math.radians(lng)

    lat2 = math.asin(
        math.sin(lat1) * math.cos(distance_km / radius)
        + math.cos(lat1) * math.sin(distance_km / radius) * math.cos(bearing)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(distance_km / radius) * math.cos(lat1),
        math.cos(distance_km / radius) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lng2)


async def _ensure_customers(session, count: int = 8) -> list[User]:
    existing = (await session.execute(select(User).limit(count))).scalars().all()
    if len(existing) >= count:
        return list(existing)

    from seed.seed_data import CLUSTER_CENTRE, _offset

    customers = list(existing)
    for index in range(count - len(existing)):
        lat, lng = _offset(*CLUSTER_CENTRE, 1.5)
        customer = User(
            clerk_id=f"user_seed_{uuid.uuid4().hex[:16]}",
            full_name=faker.name(),
            email=faker.unique.email(),
            phone_number=f"2547{random.randint(10_000_000, 99_999_999)}",
            lat=lat,
            lng=lng,
            location=from_shape(Point(lng, lat), srid=4326),
            h3_index_res8=str(h3.latlng_to_cell(lat, lng, 8)),
            location_address=f"House {random.randint(1, 90)}, Ngong",
            # A realistic spread. Floors above 2 without a lift are what make the
            # staircase surcharge appear in seeded quotes at all.
            floor_level=random.choice([0, 0, 0, 1, 2, 3, 5]),
            has_elevator=random.random() < 0.2,
            wallet_balance=Decimal(random.choice([0, 0, 0, 50, 120, 300])),
            # One device per account, so the one-per-device welcome check has
            # something meaningful to read.
            device_id=f"seed-device-{uuid.uuid4().hex[:12]}",
            # Most seeded customers are established, so a handful of orders carry
            # the welcome offer and the rest do not — both branches get exercised.
            has_used_welcome_offer=index >= 2,
        )
        session.add(customer)
        customers.append(customer)

    await session.flush()
    return customers


def _pick_cart(products: list[Product], vendor_type: str) -> list[_CartLine]:
    """A cart the platform's own validators would accept.

    Retail is capped at 4 units by the motorbike's capacity; wholesale must clear
    the 100 kg minimum. Building a cart that breaks either produces an order
    `validate_quote` would have refused — which then sits in the database
    contradicting the rule it violates.
    """
    deliverable = [p for p in products if (p.category.value if hasattr(p.category, "value") else p.category) in DELIVERABLE_CATEGORIES]
    if not deliverable:
        return []

    product = random.choice(deliverable)
    unit_price = Decimal(str(product.price)) - Decimal(str(product.discount or 0))

    if vendor_type == "wholesale_b2b":
        moq_kg = float(config.get("wholesale_moq_kg"))
        weight = float(product.weight_kg or 1)
        # Just over the minimum, then a little more, the way a real buyer orders.
        quantity = max(1, math.ceil(moq_kg / weight)) + random.randint(0, 6)
        quantity = min(quantity, 200)  # a truck's unit capacity
    else:
        quantity = random.randint(1, 4)

    quantity = min(quantity, product.stock)
    if quantity <= 0:
        return []

    return [
        _CartLine(
            product=product,
            quantity=quantity,
            price=unit_price,
            Subtotal=unit_price * quantity,
            vendor_id=product.vendor_id,
        )
    ]


async def seed_orders(session, target: int = 24) -> int:
    await config.ensure_fresh(session)

    vendors = (
        await session.execute(select(Vendor).options(selectinload(Vendor.products)))
    ).unique().scalars().all()
    if not vendors:
        print("❌ No vendors. Run `python -m seed.seed_data` first.")
        return 0

    riders = (await session.execute(select(Deliverer))).scalars().all()
    customers = await _ensure_customers(session)

    # Registrations decide which rider may serve which store, so an order's rider
    # is drawn from that store's approved fleet rather than picked at random.
    registrations: dict[Any, list[Deliverer]] = {}
    rider_by_id = {rider.id: rider for rider in riders}
    for vendor_id, rider_id in (
        await session.execute(
            select(VendorRiderRegistry.vendor_id, VendorRiderRegistry.rider_id).where(
                VendorRiderRegistry.status == "approved"
            )
        )
    ).all():
        rider = rider_by_id.get(rider_id)
        if rider is not None:
            registrations.setdefault(vendor_id, []).append(rider)

    # A realistic mix. Most orders complete; the rest are spread across the
    # states the console and the apps actually have to render.
    lifecycle = (
        ["delivered"] * 12
        + ["picked_up", "picked_up"]
        + ["ready", "preparing", "accepted", "accepted"]
        + ["unassigned", "unassigned"]
        + ["cancelled", "cancelled"]
        + ["pending_review", "mismatch_pending"]
    )

    created = 0
    for index in range(target):
        vendor = random.choice(vendors)
        vendor_type = vendor.vendor_type.value if hasattr(vendor.vendor_type, "value") else str(vendor.vendor_type)

        items = _pick_cart(list(vendor.products), vendor_type)
        if not items:
            continue

        customer = random.choice(customers)
        status = lifecycle[index % len(lifecycle)]

        # Inside the tier's radius, so `validate_quote` would have allowed it.
        # Retail's ceiling is 2 km; going beyond it produces an order the
        # platform refuses to create.
        max_km = 1.8 if vendor_type == "retail_refill" else 12.0
        distance_km = round(random.uniform(0.4, max_km), 2)
        drop_lat, drop_lng = _point_at(vendor.lat, vendor.lng, distance_km)

        delivery_type = (
            "quick_swap" if vendor_type == "wholesale_b2b"
            else random.choice(["quick_swap", "quick_swap", "quick_swap", "keep_my_bottle"])
        )
        payment_method = random.choice(["mpesa", "mpesa", "mpesa", "cash"])

        # ── The whole point of this file ──
        # Every figure below comes from the live engine, not from arithmetic
        # repeated here. `apply_wallet` is off because a seeded order should not
        # silently consume a customer's balance — the wallet path is exercised by
        # the test suite, where the consumption can be asserted.
        quote = await compute_order_quote(
            session,
            items=items,
            user=customer,
            vendor=vendor,
            delivery_type=delivery_type,
            lat=drop_lat,
            lng=drop_lng,
            apply_wallet=False,
        )

        rider = None
        if status not in ("unassigned",):
            fleet = registrations.get(vendor.id) or []
            if fleet:
                rider = random.choice(fleet)
            elif riders:
                rider = random.choice(riders)

        paid = payment_method == "mpesa" and status in (
            "delivered", "picked_up", "ready", "preparing", "pending_review", "mismatch_pending",
        )
        if status == "cancelled":
            payment_status = "refund_pending" if payment_method == "mpesa" else "failed"
        elif payment_method == "cash":
            payment_status = "paid" if status == "delivered" else "pending"
        else:
            payment_status = "paid" if paid else "pending"

        age = timedelta(hours=random.randint(1, 24 * 21))
        revenue = quote.revenue
        order_id = uuid.uuid4()

        order = Order(
            id=order_id,
            customer_id=customer.id,
            vendor_id=vendor.id,
            deliverer_id=rider.id if rider else None,
            checkout_request_ID=(
                f"ws_CO_{uuid.uuid4().hex[:20]}" if payment_method == "mpesa" else None
            ),
            delivery_address=customer.location_address,
            phone=customer.phone_number,
            lat_from=vendor.lat,
            lng_from=vendor.lng,
            lat=drop_lat,
            lng=drop_lng,
            h3_index_res8=str(h3.latlng_to_cell(drop_lat, drop_lng, 8)),
            # Set from the quote. Both were left null by the old seeders, so the
            # replay screen, the vehicle filter and every distance report saw
            # nothing on seeded data.
            distance_km=quote.distance_km,
            vehicle_class=quote.vehicle_class,
            delivery_time=quote.estimated_minutes,
            total_amount=quote.total,
            order_status=status,
            payment_status=payment_status,
            payment_method=payment_method,
            delivery_fee=quote.delivery_fee,
            delivery_type=delivery_type,
            bottle_source="platform" if quote.is_welcome_offer else "own",
            is_welcome_offer=quote.is_welcome_offer,
            vendor_commission=revenue["vendor_commission"],
            service_fee=revenue["service_fee"],
            rider_commission=revenue["rider_commission"],
            platform_total=revenue["platform_total"],
            vendor_net=revenue["vendor_net"],
            rider_net=revenue["rider_net"],
            surge_fee=quote.surge_fee,
            delivery_markup=quote.delivery_markup,
            commission_lost=quote.revenue["platform_total"] if status == "cancelled" else 0,
            wallet_discount=quote.wallet_discount,
            welcome_discount=quote.welcome_discount,
            product_subtotal=quote.product_subtotal,
            bottle_deposit=quote.bottle_deposit,
            debt_settlement=quote.debt_settlement,
            staircase_surcharge=quote.staircase_surcharge,
            payload_surcharge=quote.payload_surcharge,
            proof_url=(
                "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749059743/zjfoz5vc9pw9dzn7jpuh.jpg"
                if status == "delivered" and random.random() < 0.5 else None
            ),
            cancellation_reason="cancelled_by_customer" if status == "cancelled" else None,
            created_at=datetime.now(timezone.utc) - age,
        )
        session.add(order)

        for line in items:
            session.add(
                OrderItem(
                    order_id=order_id,
                    product_id=line.product.id,
                    quantity=line.quantity,
                    price=line.price,
                    Subtotal=line.Subtotal,
                )
            )
            # Stock actually moves. An order that took nothing off the shelf
            # leaves the catalogue claiming inventory that has been sold.
            if status != "cancelled":
                line.product.stock = max(0, line.product.stock - line.quantity)
                line.product.is_available = line.product.stock > 0

        # The customer's own counters, as `update_delivery_status` would set them.
        if status == "delivered":
            customer.bottle_refill_count = (customer.bottle_refill_count or 0) + 1
            customer.last_order_date = order.created_at
            if quote.is_welcome_offer:
                customer.has_used_welcome_offer = True
            if quote.bottle_deposit > 0:
                customer.bottle_deposit_balance = (
                    Decimal(str(customer.bottle_deposit_balance or 0)) + quote.bottle_deposit
                )
                customer.bottles_held = (customer.bottles_held or 0) + sum(
                    line.quantity for line in items
                )

        created += 1

    await session.flush()
    return created


# ── Test-account-specific orders ──────────────────────────────────────────

#: The `+clerk_test` addresses used by `scripts/test_accounts.py`.
_TEST_CUSTOMER_EMAIL = "customer+clerk_test@example.com"
_TEST_RIDER_EMAIL = "rider+clerk_test@example.com"
_TEST_RETAIL_EMAIL = "vendor-retail+clerk_test@example.com"


async def seed_test_account_orders(session) -> int:
    """Force specific orders for the test identities.

    The random seeder gives everyone a mix, but a tester logging into the rider
    app needs an active delivery **now**, the customer app needs order history
    to show, and the vendor dashboard needs an active queue. This function
    guarantees all three, using `compute_order_quote` for every figure.
    """
    await config.ensure_fresh(session)

    customer = (
        await session.execute(select(User).where(User.email == _TEST_CUSTOMER_EMAIL))
    ).scalars().first()
    rider = (
        await session.execute(select(Deliverer).where(Deliverer.email == _TEST_RIDER_EMAIL))
    ).scalars().first()
    retail = (
        await session.execute(
            select(Vendor).options(selectinload(Vendor.products))
            .where(Vendor.email == _TEST_RETAIL_EMAIL)
        )
    ).unique().scalars().first()

    if not all([customer, rider, retail]):
        print("⚠️  Test identities not found — run `scripts/test_accounts.py provision` first.")
        return 0

    products = list(retail.products)
    items = _pick_cart(products, "retail_refill")
    if not items:
        print("⚠️  No deliverable products in the retail test store.")
        return 0

    now = datetime.now(timezone.utc)
    created = 0

    # Each scenario: (status, rider_assigned, age_delta, payment_status)
    scenarios = [
        ("picked_up",  rider, timedelta(minutes=25), "paid"),      # active delivery for rider
        ("delivered",  rider, timedelta(days=3),      "paid"),      # history for customer + rate
        ("delivered",  rider, timedelta(days=7),      "paid"),      # second history item
        ("preparing",  rider, timedelta(minutes=10),  "paid"),      # vendor active queue
        ("accepted",   None,  timedelta(minutes=5),   "pending"),   # vendor queue, unassigned
    ]

    for status, assigned_rider, age, payment_status in scenarios:
        distance_km = round(random.uniform(0.4, 1.8), 2)
        drop_lat, drop_lng = _point_at(retail.lat, retail.lng, distance_km)
        delivery_type = "quick_swap"
        payment_method = "mpesa"

        cart_items = _pick_cart(products, "retail_refill")
        if not cart_items:
            cart_items = items  # fallback to the first working cart

        quote = await compute_order_quote(
            session,
            items=cart_items,
            user=customer,
            vendor=retail,
            delivery_type=delivery_type,
            lat=drop_lat,
            lng=drop_lng,
            apply_wallet=False,
        )

        revenue = quote.revenue
        order_id = uuid.uuid4()

        order = Order(
            id=order_id,
            customer_id=customer.id,
            vendor_id=retail.id,
            deliverer_id=assigned_rider.id if assigned_rider else None,
            checkout_request_ID=f"ws_CO_{uuid.uuid4().hex[:20]}",
            delivery_address=customer.location_address,
            phone=customer.phone_number,
            lat_from=retail.lat,
            lng_from=retail.lng,
            lat=drop_lat,
            lng=drop_lng,
            h3_index_res8=str(h3.latlng_to_cell(drop_lat, drop_lng, 8)),
            distance_km=quote.distance_km,
            vehicle_class=quote.vehicle_class,
            delivery_time=quote.estimated_minutes,
            total_amount=quote.total,
            order_status=status,
            payment_status=payment_status,
            payment_method=payment_method,
            delivery_fee=quote.delivery_fee,
            delivery_type=delivery_type,
            bottle_source="own",
            is_welcome_offer=False,
            vendor_commission=revenue["vendor_commission"],
            service_fee=revenue["service_fee"],
            rider_commission=revenue["rider_commission"],
            platform_total=revenue["platform_total"],
            vendor_net=revenue["vendor_net"],
            rider_net=revenue["rider_net"],
            surge_fee=quote.surge_fee,
            delivery_markup=quote.delivery_markup,
            commission_lost=0,
            wallet_discount=quote.wallet_discount,
            welcome_discount=Decimal("0"),
            product_subtotal=quote.product_subtotal,
            bottle_deposit=Decimal("0"),
            debt_settlement=Decimal("0"),
            staircase_surcharge=quote.staircase_surcharge,
            payload_surcharge=quote.payload_surcharge,
            proof_url=(
                "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749059743/zjfoz5vc9pw9dzn7jpuh.jpg"
                if status == "delivered" else None
            ),
            created_at=now - age,
        )
        session.add(order)

        for line in cart_items:
            session.add(
                OrderItem(
                    order_id=order_id,
                    product_id=line.product.id,
                    quantity=line.quantity,
                    price=line.price,
                    Subtotal=line.Subtotal,
                )
            )

        created += 1

    await session.flush()
    return created


async def reconcile_vendor_totals(session) -> None:
    """Set each store's lifetime figures from the orders that exist.

    `total_sales` and `sales_amount` were random integers, so the vendor
    dashboard, the admin console and the orders table disagreed from the first
    run and there was no way to tell which was wrong. Derived, they agree by
    construction.
    """
    from sqlalchemy import func

    totals = (
        await session.execute(
            select(
                Order.vendor_id,
                func.count(Order.id),
                func.coalesce(func.sum(Order.vendor_net), 0),
            )
            .where(Order.order_status == "delivered")
            .group_by(Order.vendor_id)
        )
    ).all()

    by_vendor = {vendor_id: (count, amount) for vendor_id, count, amount in totals}

    for vendor in (await session.execute(select(Vendor))).scalars().all():
        count, amount = by_vendor.get(vendor.id, (0, Decimal("0")))
        vendor.total_sales = int(count)
        vendor.sales_amount = Decimal(str(amount))

    await session.flush()
    print(f"✅ Vendor lifetime totals derived from {sum(c for c, _ in by_vendor.values())} delivered order(s).")


async def main():
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(Order).limit(1))).scalars().first()
        if existing is not None:
            print("⚠️  Orders already exist. Run seed/wipe_db.py first if you want a clean set.")
            return

        created = await seed_orders(session)
        test_created = await seed_test_account_orders(session)
        if created or test_created:
            await reconcile_vendor_totals(session)
            await session.commit()
            print(f"✅ {created} random + {test_created} test-account orders seeded.")


if __name__ == "__main__":
    asyncio.run(main())
