"""Test identities for the three mobile apps, provisioned end to end.

`admin_access.py` writes administrator rows and deliberately does **not** touch
Clerk, because an `Admin_Users` row binds by **email** on first sign-in — so the
dashboard can own the credential and the script never needs to know a password.

The three apps cannot work that way. `Users`, `Deliverers` and `Vendors` bind by
**`clerk_id`**, written from the token's `sub` by each app's own registration
call. A row created ahead of time with a guessed id binds to nobody, and a tester
who signs in instead walks the whole onboarding flow — KYC uploads for a rider,
business details and a catalogue for a vendor — before they can exercise anything.

So this script does the one thing the admin script would not: it creates the
Clerk users through the Backend API, reads their real subjects back, and writes
the matching rows already bound and already set up. The trade is deliberate and
narrow — these are unprivileged test identities on a **development** instance,
they hold no capability an ordinary customer does not, and the password is
published in the README precisely because it protects nothing.

    python scripts/test_accounts.py provision          # idempotent
    python scripts/test_accounts.py list
    python scripts/test_accounts.py prune --apply      # removes Clerk users + rows

Every address carries Clerk's `+clerk_test` subaddress, which is what makes the
fixed `424242` verification code work and stops Clerk emailing a mailbox that
does not exist. That behaviour is development-instance only.
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime, time, timedelta as _timedelta, timezone
from decimal import Decimal

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import h3
import httpx
from dotenv import load_dotenv
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select

load_dotenv()

from db.session import AsyncSessionLocal  # noqa: E402
from models.deliverer_model import Deliverer  # noqa: E402
from models.product_model import Product  # noqa: E402
from models.user_model import User  # noqa: E402
from models.vendor_model import Vendor  # noqa: E402
from models.vendor_rider_model import VendorRiderRegistry  # noqa: E402
from models.vendor_staff_model import (  # noqa: E402
    DEFAULT_PERMISSIONS,
    VendorStaff,
)
from models.cart_model import Cart, CartItem  # noqa: E402
from models.notification_model import Notification  # noqa: E402
from models.saved_location_model import SavedLocation  # noqa: E402
from models.vendor_favorite_model import VendorFavorite  # noqa: E402
from models.wallet_transaction_model import WalletTransaction  # noqa: E402

CLERK_API = "https://api.clerk.com/v1"
TIMEOUT = 30.0

#: Published in the README. These identities can do nothing a real customer
#: cannot, on an instance that mints no production tokens.
PASSWORD = "Drop2026!!"

#: Clerk's marker for a test identity. Any address carrying it receives no email
#: and accepts `424242` as its verification code, every time.
SUBADDRESS = "+clerk_test"
DOMAIN = "example.com"

#: Ngong Town, where the seeded vendors are. A test rider parked in Nairobi CBD
#: is outside every retail store's retail radius and will never be offered work —
#: which looks exactly like dispatch being broken.
NGONG = (-1.3615, 36.6570)
MATASIA = (-1.3850, 36.6667)


def address(slug: str) -> str:
    return f"{slug}{SUBADDRESS}@{DOMAIN}"


#: `(slug, kind, first name, last name)`. One identity per surface the platform
#: actually distinguishes — the two vendor tiers behave differently in pricing,
#: dispatch and settlement, and staff are a real trust boundary rather than a
#: display role, so testing "a vendor" alone leaves most of the platform unseen.
ROSTER = [
    ("customer",         "customer",         "Amina",  "Wanjiru"),
    ("rider",            "rider",            "Brian",  "Otieno"),
    ("vendor-retail",    "vendor_retail",    "Cynthia", "Njeri"),
    ("vendor-wholesale", "vendor_wholesale", "Dennis", "Kiplagat"),
    ("vendor-staff",     "vendor_staff",     "Esther", "Mwikali"),
]


# ── Clerk ─────────────────────────────────────────────────────────────────


def _client() -> httpx.AsyncClient:
    secret = (os.getenv("CLERK_SECRET_KEY") or "").strip()
    if not secret:
        raise SystemExit(
            "CLERK_SECRET_KEY is not set. It is the one Clerk value that cannot "
            "be derived — take it from the dashboard's API keys page."
        )
    if not secret.startswith("sk_test_"):
        raise SystemExit(
            "CLERK_SECRET_KEY is not a development key. `+clerk_test` and the "
            "424242 code do nothing on a production instance, so this script "
            "would create five real accounts that can never verify."
        )
    return httpx.AsyncClient(
        base_url=CLERK_API,
        headers={"Authorization": f"Bearer {secret}"},
        timeout=TIMEOUT,
    )


async def _find(client: httpx.AsyncClient, email: str) -> dict | None:
    response = await client.get("/users", params={"email_address": [email]})
    response.raise_for_status()
    found = response.json()
    return found[0] if found else None


async def _create(client: httpx.AsyncClient, email: str, first: str, last: str) -> dict:
    response = await client.post(
        "/users",
        json={
            "email_address": [email],
            "password": PASSWORD,
            "first_name": first,
            "last_name": last,
            # The password is published, so Clerk's breach check will reject it
            # on principle. That check protects a real user's account, which
            # this is not.
            "skip_password_checks": True,
        },
    )
    if response.status_code >= 400:
        raise SystemExit(f"Clerk refused to create {email}: {response.text}")
    return response.json()


async def _ensure_clerk_user(client, email: str, first: str, last: str) -> tuple[str, bool]:
    """`(clerk_id, created)`. Idempotent — an existing account is reused."""
    existing = await _find(client, email)
    if existing:
        return existing["id"], False
    return (await _create(client, email, first, last))["id"], True


# ── The backend rows ──────────────────────────────────────────────────────


def _geo(lat: float, lng: float) -> dict:
    """Location, PostGIS point and H3 cell together.

    All three or none. Every discovery and dispatch query pre-filters on
    `h3_index_res8` before it measures anything, so a row with coordinates and a
    null cell is invisible to all of them — which is precisely how the old seed
    data managed to be undiscoverable while looking perfectly fine in the table.
    """
    return {
        "lat": lat,
        "lng": lng,
        "location": from_shape(Point(lng, lat), srid=4326),
        "h3_index_res8": str(h3.latlng_to_cell(lat, lng, 8)),
    }


async def _upsert_customer(session, clerk_id: str, email: str, name: str) -> str:
    row = (await session.execute(select(User).where(User.email == email))).scalars().first()
    geo = _geo(*NGONG)
    if row is None:
        row = User(email=email)
        session.add(row)
    row.clerk_id = clerk_id
    row.full_name = name
    row.phone_number = "254700000101"
    row.location_address = "House 12, Ngong Town"
    row.lat, row.lng = geo["lat"], geo["lng"]
    row.location = geo["location"]
    row.h3_index_res8 = geo["h3_index_res8"]
    # Third floor, no lift: exercises the staircase surcharge on every quote.
    row.floor_level = 3
    row.has_elevator = False
    row.wallet_balance = Decimal("500.00")
    row.device_id = f"clerk-test-device-{clerk_id[-8:]}"
    # Returning customer: the welcome offer has been used. This means the
    # tester sees the normal pricing path, not the first-order discount.
    row.has_used_welcome_offer = True
    row.debt_balance = Decimal("0")
    # 2 × 20 L bottles at KSH 300 each = KSH 600 deposit on file.
    # Populates the Bottle Wallet's "Bottles you're holding" and
    # "Refundable deposit" cards.
    row.bottle_deposit_balance = Decimal("600.00")
    row.bottles_held = 2
    row.bottle_purchased_at = datetime.now(timezone.utc) - _timedelta(days=45)
    row.bottle_refill_count = 8  # shows "4.0 kg Plastic Waste Saved"
    row.last_order_date = datetime.now(timezone.utc) - _timedelta(days=3)
    await session.flush()
    return "customer"


async def _upsert_rider(session, clerk_id: str, email: str, name: str) -> str:
    row = (
        await session.execute(select(Deliverer).where(Deliverer.email == email))
    ).scalars().first()
    geo = _geo(*NGONG)
    if row is None:
        # `ID_number` is NOT NULL and encrypted at rest.
        row = Deliverer(email=email, name=name, ID_number="30000101")
        session.add(row)
    row.clerk_id = clerk_id
    row.name = name
    row.phone_number = "254700000102"
    row.vehicle_type = "motorbike"
    row.employment_model = "gig_economy"
    row.plate_number = "KDA 101A"
    row.current_lat, row.current_lng = geo["lat"], geo["lng"]
    # The base a rider registers from. `apply-vendor` refuses outright when null.
    row.operation_lat, row.operation_lng = geo["lat"], geo["lng"]
    row.location = geo["location"]
    row.h3_index_res8 = geo["h3_index_res8"]
    # `VerificationWall` blocks a rider until this is positively `approved`, so
    # anything else means the tester cannot reach a single screen behind it.
    row.kyc_status = "approved"
    row.kyc_reviewed_at = datetime.now(timezone.utc)
    row.is_active = True
    row.is_verified = True
    row.is_available = True
    # Enough float to accept a cash order: the check is
    # `vendor_net + platform_total`, roughly KSH 420 on a typical retail order.
    row.wallet_balance = Decimal("5000.00")
    # Gamification — a rider who has been working the platform.
    # `rating` must equal `rating_sum / rating_count` or review_service will
    # produce a discontinuity on the next submitted review.
    row.rating = 4.85
    row.rating_count = 120
    row.rating_sum = 582.0  # 120 × 4.85
    row.acceptance_rate = 97.5
    row.is_platinum = True
    row.shift_start, row.shift_end = time(7, 0), time(19, 0)
    await session.flush()
    return "rider"


RETAIL_CATALOGUE = [
    ("20L Purified Refill", 20.0, 20.5, "bottle", 180.0, 120, "dispenser_refill"),
    ("10L Purified Refill", 10.0, 10.3, "bottle", 110.0, 90, "dispenser_refill"),
    ("5L Household Jerrycan", 5.0, 5.2, "jerrycan", 70.0, 60, "jerrycan"),
]

WHOLESALE_CATALOGUE = [
    ("20L Bulk Dispatch", 20.0, 20.5, "bottle", 110.0, 400, "bulk_wholesale"),
    ("Bale 500ml Branded (24-pack)", 0.5, 12.5, "pack", 360.0, 300, "bulk_wholesale"),
]


async def _upsert_vendor(
    session, clerk_id: str, email: str, owner: str, *, wholesale: bool
) -> str:
    row = (await session.execute(select(Vendor).where(Vendor.email == email))).scalars().first()
    geo = _geo(*(MATASIA if wholesale else NGONG))
    business = "Kiplagat Bulk Waters" if wholesale else "Ngong Springs Test Store"

    if row is None:
        row = Vendor(email=email, owners_name=owner, business_name=business)
        session.add(row)
    row.clerk_id = clerk_id
    row.owners_name = owner
    row.business_name = business
    row.phone_number = "254700000104" if wholesale else "254700000103"
    row.location_address = "Matasia, Magadi Road" if wholesale else "Ngong Town, Oloolua Road"
    row.lat, row.lng = geo["lat"], geo["lng"]
    row.location = geo["location"]
    row.h3_index_res8 = geo["h3_index_res8"]
    row.vendor_type = "wholesale_b2b" if wholesale else "retail_refill"
    row.shift_start, row.shift_end = time(6, 0), time(19, 0)
    row.verification_status = "verified"
    row.is_active = True
    row.is_online = True
    # The 20 L figure from `bottle_deposit_by_capacity`, so the vendor's own
    # screen and the customer's quote agree.
    row.deposit_fee = Decimal("300.00")
    row.wallet_balance = Decimal("10000.00")
    row.preferred_payment_method = ["cash", "mpesa"]
    # Social proof — stores with no reviews look abandoned in the directory.
    # `rating` = `rating_sum / rating_count`, kept consistent so review_service
    # does not produce a jump on the first real review.
    if wholesale:
        row.rating = 4.6
        row.rating_count = 85
        row.rating_sum = 391.0  # 85 × 4.6
        row.total_sales = 34
        row.sales_amount = Decimal("45600.00")
        row.full_bottle_inventory = 400
        row.empty_bottle_inventory = 120
        row.wholesale_base_delivery_fee = Decimal("150.00")
        row.wholesale_per_km_fee = Decimal("90.00")
    else:
        row.rating = 4.8
        row.rating_count = 340
        row.rating_sum = 1632.0  # 340 × 4.8
        row.total_sales = 127
        row.sales_amount = Decimal("21590.00")
        row.full_bottle_inventory = 150
        row.empty_bottle_inventory = 45
    await session.flush()

    # A store with no catalogue cannot be ordered from, which makes it useless
    # as a test fixture.
    catalogue = WHOLESALE_CATALOGUE if wholesale else RETAIL_CATALOGUE
    existing = {
        name
        for (name,) in (
            await session.execute(select(Product.name).where(Product.vendor_id == row.id))
        ).all()
    }
    for name, capacity, weight, unit, price, stock, category in catalogue:
        if name in existing:
            continue
        session.add(
            Product(
                vendor_id=row.id,
                name=name,
                description=f"{name} — test catalogue for {business}.",
                image_url=(
                    "https://res.cloudinary.com/dn5f0jksu/image/upload/"
                    "v1749059743/zjfoz5vc9pw9dzn7jpuh.jpg"
                ),
                price=Decimal(str(price)),
                discount=Decimal("0"),
                capacity=capacity,
                weight_kg=Decimal(str(weight)),
                minimum_order_qty=5 if wholesale else 1,
                unit=unit,
                stock=stock,
                low_stock_threshold=10,
                is_available=True,
                category=category,
            )
        )

    await session.flush()
    return "vendor"


async def _upsert_staff(session, clerk_id: str, email: str, name: str) -> str:
    """A staff member of the retail test store.

    Staff are a real trust boundary — they may run the shop floor and may not
    move its money — so a roster without one leaves the whole capability layer
    untested. `view_finances` is not in the default set, deliberately: seeing the
    balance is a decision the owner makes.
    """
    store = (
        await session.execute(select(Vendor).where(Vendor.email == address("vendor-retail")))
    ).scalars().first()
    if store is None:
        return "staff (skipped — retail store not provisioned yet)"

    row = (
        await session.execute(
            select(VendorStaff).where(
                VendorStaff.email == email, VendorStaff.vendor_id == store.id
            )
        )
    ).scalars().first()
    if row is None:
        row = VendorStaff(vendor_id=store.id, email=email)
        session.add(row)
    row.clerk_id = clerk_id
    row.name = name
    row.permissions = list(DEFAULT_PERMISSIONS)
    row.is_active = True
    row.revoked_at = None
    row.accepted_at = datetime.now(timezone.utc)
    await session.flush()
    return "vendor staff"


async def _register_rider_with_stores(session) -> int:
    """Approve the test rider onto both test stores.

    Tier 1 of dispatch only offers an order to riders in `VendorRiderRegistry`.
    Without these rows every test order waits the full twenty seconds and then
    arrives by Trip Radar, so the tiering never appears at all.
    """
    rider = (
        await session.execute(select(Deliverer).where(Deliverer.email == address("rider")))
    ).scalars().first()
    if rider is None:
        return 0

    created = 0
    for slug in ("vendor-retail", "vendor-wholesale"):
        store = (
            await session.execute(select(Vendor).where(Vendor.email == address(slug)))
        ).scalars().first()
        if store is None:
            continue
        exists = (
            await session.execute(
                select(VendorRiderRegistry).where(
                    VendorRiderRegistry.rider_id == rider.id,
                    VendorRiderRegistry.vendor_id == store.id,
                )
            )
        ).scalars().first()
        if exists:
            exists.status = "approved"
            continue
        session.add(
            VendorRiderRegistry(
                rider_id=rider.id,
                vendor_id=store.id,
                status="approved",
                h3_index=rider.h3_index_res8,
                approved_at=datetime.now(timezone.utc),
            )
        )
        created += 1
    return created


async def _enrich_demo_data(session) -> int:
    """Seed the ancillary rows that make every test account feel lived-in.

    Called after all identities and registrations exist. Everything here is
    idempotent — re-provisioning overwrites or skips, never duplicates.
    """
    enriched = 0

    # ── Resolve the test identities ───────────────────────────────────
    customer = (
        await session.execute(select(User).where(User.email == address("customer")))
    ).scalars().first()
    rider = (
        await session.execute(select(Deliverer).where(Deliverer.email == address("rider")))
    ).scalars().first()
    retail_store = (
        await session.execute(select(Vendor).where(Vendor.email == address("vendor-retail")))
    ).scalars().first()

    if not all([customer, rider, retail_store]):
        print("  ⚠ Enrichment skipped — core identities not found.")
        return 0

    # ── Rider: set employer_vendor_id (unlocks Trip Radar + Active Delivery) ──
    rider.employer_vendor_id = retail_store.id
    enriched += 1

    # ── Customer: saved locations ─────────────────────────────────────
    existing_locs = (
        await session.execute(
            select(SavedLocation).where(SavedLocation.user_id == customer.id)
        )
    ).scalars().all()
    if not existing_locs:
        session.add(SavedLocation(
            user_id=customer.id, label="Home",
            address="House 12, Ngong Town", lat=NGONG[0], lng=NGONG[1],
            is_default=True, use_count=14,
        ))
        session.add(SavedLocation(
            user_id=customer.id, label="Office",
            address="Matasia, Magadi Road", lat=MATASIA[0], lng=MATASIA[1],
            is_default=False, use_count=3,
        ))
        enriched += 1

    # ── Customer: favourite the retail store ───────────────────────────
    existing_fav = (
        await session.execute(
            select(VendorFavorite).where(
                VendorFavorite.user_id == customer.id,
                VendorFavorite.vendor_id == retail_store.id,
            )
        )
    ).scalars().first()
    if not existing_fav:
        session.add(VendorFavorite(user_id=customer.id, vendor_id=retail_store.id))
        enriched += 1

    # ── Customer: pre-filled cart ──────────────────────────────────────
    existing_cart = (
        await session.execute(select(Cart).where(Cart.customer_id == customer.id))
    ).scalars().first()
    if not existing_cart:
        # Pick the first retail product (20L Purified Refill, KSH 180)
        product = (
            await session.execute(
                select(Product).where(Product.vendor_id == retail_store.id).limit(1)
            )
        ).scalars().first()
        if product:
            unit_price = Decimal(str(product.price)) - Decimal(str(product.discount or 0))
            qty = 2
            cart = Cart(
                customer_id=customer.id,
                items_count=qty,
                total_amount=unit_price * qty,
            )
            session.add(cart)
            await session.flush()
            session.add(CartItem(
                cart_id=cart.id,
                vendor_id=retail_store.id,
                product_id=product.id,
                quantity=qty,
                price=unit_price,
                Subtotal=unit_price * qty,
            ))
            enriched += 1

    # ── Customer: wallet transaction history ───────────────────────────
    existing_tx = (
        await session.execute(
            select(WalletTransaction).where(
                WalletTransaction.wallet_owner_id == customer.id
            ).limit(1)
        )
    ).scalars().first()
    if not existing_tx:
        now = datetime.now(timezone.utc)
        for tx_data in [
            {
                "user_id": customer.clerk_id, "user_type": "customer",
                "wallet_owner_id": customer.id,
                "transaction_type": "top_up", "amount": Decimal("500.00"),
                "status": "completed", "description": "M-Pesa top-up",
                "mpesa_receipt_number": "TES1234567",
                "created_at": now - _timedelta(days=10),
            },
            {
                "user_id": customer.clerk_id, "user_type": "customer",
                "wallet_owner_id": customer.id,
                "transaction_type": "order_payment", "amount": Decimal("-442.00"),
                "status": "completed", "description": "Order payment — 2× 20L Purified Refill",
                "created_at": now - _timedelta(days=7),
            },
            {
                "user_id": customer.clerk_id, "user_type": "customer",
                "wallet_owner_id": customer.id,
                "transaction_type": "refund", "amount": Decimal("50.00"),
                "status": "completed", "description": "Refund — cancelled order",
                "created_at": now - _timedelta(days=4),
            },
        ]:
            session.add(WalletTransaction(**tx_data))
        enriched += 1

    # ── Customer: notifications ───────────────────────────────────────
    existing_notif = (
        await session.execute(
            select(Notification).where(
                Notification.user_id == customer.id,
                Notification.user_type == "customer",
            ).limit(1)
        )
    ).scalars().first()
    if not existing_notif:
        now = datetime.now(timezone.utc)
        session.add(Notification(
            user_id=customer.id, user_type="customer",
            title="Your order was delivered! 🎉",
            message="Your 2× 20L Purified Refill from Ngong Springs has arrived.",
            message_type="delivery_complete", is_read=True,
            created_at=now - _timedelta(days=3),
        ))
        session.add(Notification(
            user_id=customer.id, user_type="customer",
            title="Welcome back, Amina!",
            message="Your bottles are due for a refill. Tap to reorder.",
            message_type="promotion", is_read=False,
            created_at=now - _timedelta(hours=6),
        ))
        enriched += 1

    # ── Rider: wallet transactions ────────────────────────────────────
    existing_rider_tx = (
        await session.execute(
            select(WalletTransaction).where(
                WalletTransaction.wallet_owner_id == rider.id
            ).limit(1)
        )
    ).scalars().first()
    if not existing_rider_tx:
        now = datetime.now(timezone.utc)
        session.add(WalletTransaction(
            user_id=rider.clerk_id, user_type="rider",
            wallet_owner_id=rider.id,
            transaction_type="top_up", amount=Decimal("5000.00"),
            status="completed", description="M-Pesa float top-up",
            mpesa_receipt_number="TES7654321",
            created_at=now - _timedelta(days=14),
        ))
        enriched += 1

    # ── Rider: notifications ──────────────────────────────────────────
    existing_rider_notif = (
        await session.execute(
            select(Notification).where(
                Notification.user_id == rider.id,
                Notification.user_type == "rider",
            ).limit(1)
        )
    ).scalars().first()
    if not existing_rider_notif:
        session.add(Notification(
            user_id=rider.id, user_type="rider",
            title="KYC Approved ✅",
            message="Your documents have been verified. You can now accept deliveries.",
            message_type="kyc_update", is_read=True,
            created_at=datetime.now(timezone.utc) - _timedelta(days=30),
        ))
        session.add(Notification(
            user_id=rider.id, user_type="rider",
            title="Platinum Tier Achieved! 🏆",
            message="You've completed 20+ deliveries this week. Commission reduced to 7%.",
            message_type="tier_change", is_read=False,
            created_at=datetime.now(timezone.utc) - _timedelta(hours=12),
        ))
        enriched += 1

    # ── Vendor: notifications ─────────────────────────────────────────
    existing_vendor_notif = (
        await session.execute(
            select(Notification).where(
                Notification.user_id == retail_store.id,
                Notification.user_type == "vendor",
            ).limit(1)
        )
    ).scalars().first()
    if not existing_vendor_notif:
        session.add(Notification(
            user_id=retail_store.id, user_type="vendor",
            title="New Rider Registered",
            message="Brian Otieno has been approved to deliver for your store.",
            message_type="rider_approved", is_read=True,
            created_at=datetime.now(timezone.utc) - _timedelta(days=7),
        ))
        session.add(Notification(
            user_id=retail_store.id, user_type="vendor",
            title="Low Stock Alert ⚠️",
            message="5L Household Jerrycan is running low (60 left).",
            message_type="low_stock", is_read=False,
            created_at=datetime.now(timezone.utc) - _timedelta(hours=2),
        ))
        enriched += 1

    await session.flush()
    return enriched


# ── Commands ──────────────────────────────────────────────────────────────


async def cmd_provision() -> int:
    created_in_clerk, bound = [], []

    async with _client() as clerk, AsyncSessionLocal() as session:
        for slug, kind, first, last in ROSTER:
            email = address(slug)
            clerk_id, was_new = await _ensure_clerk_user(clerk, email, first, last)
            if was_new:
                created_in_clerk.append(email)

            name = f"{first} {last}"
            if kind == "customer":
                what = await _upsert_customer(session, clerk_id, email, name)
            elif kind == "rider":
                what = await _upsert_rider(session, clerk_id, email, name)
            elif kind == "vendor_retail":
                what = await _upsert_vendor(session, clerk_id, email, name, wholesale=False)
            elif kind == "vendor_wholesale":
                what = await _upsert_vendor(session, clerk_id, email, name, wholesale=True)
            else:
                what = await _upsert_staff(session, clerk_id, email, name)

            bound.append((email, what, clerk_id))

        registrations = await _register_rider_with_stores(session)
        enrichments = await _enrich_demo_data(session)
        await session.commit()

    print(f"Provisioned {len(bound)} test identities.\n")
    for email, what, clerk_id in bound:
        marker = "new" if email in created_in_clerk else "existing"
        print(f"  {email:<44} {what:<14} {clerk_id}  ({marker} in Clerk)")

    if registrations:
        print(f"\n  + {registrations} rider–vendor registration(s) approved.")
    if enrichments:
        print(f"  + {enrichments} demo-data enrichment(s) applied.")

    print(f"\nPassword for all of them: {PASSWORD}")
    print("Verification code: 424242 (development instance only).")
    return 0


async def cmd_list() -> int:
    async with _client() as clerk, AsyncSessionLocal() as session:
        print(f"{'Address':<44} {'Clerk':<8} {'Row':<8} Bound")
        print("-" * 78)
        for slug, kind, *_ in ROSTER:
            email = address(slug)
            clerk_user = await _find(clerk, email)
            clerk_id = clerk_user["id"] if clerk_user else None

            model = {
                "customer": User,
                "rider": Deliverer,
                "vendor_retail": Vendor,
                "vendor_wholesale": Vendor,
                "vendor_staff": VendorStaff,
            }[kind]
            row = (
                await session.execute(select(model).where(model.email == email))
            ).scalars().first()

            bound = "yes" if row is not None and row.clerk_id == clerk_id else "NO"
            if row is None or clerk_id is None:
                bound = "—"
            print(
                f"{email:<44} {'yes' if clerk_id else 'no':<8} "
                f"{'yes' if row else 'no':<8} {bound}"
            )
    return 0


async def cmd_prune(apply: bool) -> int:
    """Remove the test identities from Clerk and the database.

    Refuses anything without the `+clerk_test` marker, so a typo cannot delete a
    real account — the same guard `admin_access.py prune-tests` carries.
    """
    async with _client() as clerk, AsyncSessionLocal() as session:
        for slug, kind, *_ in ROSTER:
            email = address(slug)
            if SUBADDRESS not in email:
                print(f"Refusing {email}: not a test address.")
                continue

            model = {
                "customer": User,
                "rider": Deliverer,
                "vendor_retail": Vendor,
                "vendor_wholesale": Vendor,
                "vendor_staff": VendorStaff,
            }[kind]
            row = (
                await session.execute(select(model).where(model.email == email))
            ).scalars().first()
            clerk_user = await _find(clerk, email)

            print(f"{'DELETE' if apply else 'would delete'} {email}")
            if not apply:
                continue

            if row is not None:
                await session.delete(row)
            if clerk_user is not None:
                await clerk.delete(f"/users/{clerk_user['id']}")

        if apply:
            await session.commit()

    if not apply:
        print("\nDry run. Re-run with --apply to delete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("provision", help="Create the Clerk users and bind their rows (idempotent)")
    sub.add_parser("list", help="Show what exists and whether it is bound")
    prune = sub.add_parser("prune", help="Delete the test identities")
    prune.add_argument("--apply", action="store_true", help="Actually delete; omit for a dry run")

    args = parser.parse_args()
    if args.command == "provision":
        return asyncio.run(cmd_provision())
    if args.command == "list":
        return asyncio.run(cmd_list())
    return asyncio.run(cmd_prune(args.apply))


if __name__ == "__main__":
    raise SystemExit(main())
