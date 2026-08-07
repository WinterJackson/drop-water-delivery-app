"""
Vendors, products and riders — seeded so the platform's own rules accept them.

The previous version produced data that was individually plausible and
collectively unusable. Every fault below was real, and each one silently broke a
feature that looked fine in the database:

* **Riders were scattered over the whole of Nairobi** (`lat -1.45..-1.10`,
  `lng 36.65..37.00`) while every vendor sat in Ngong and Matasia. Retail
  dispatch searches 2 km, so almost no rider was ever eligible for any order.
* **Neither vendors nor riders had an `h3_index_res8`.** Every discovery and
  dispatch query pre-filters on that column, so a null one is invisible to all
  of them — the seeded rows could not be found at all, at any distance.
* **Riders were `is_active=False`, `is_verified=False` and `kyc_status` defaulted
  to `unsubmitted`,** which is exactly the state `VerificationWall` blocks. None
  of them could have accepted a delivery.
* **Riders had no `wallet_balance`,** so every one of them failed the cash-order
  float check the moment they tried.
* **Wholesale was priced above retail** — a 20 L bulk unit at KSH 500–600 against
  the same bottle at KSH 100–200 retail. Buying in bulk cost more than buying one.
* **`total_sales` and `sales_amount` were random numbers** unconnected to any
  order, so the vendor dashboard and the admin console disagreed with the orders
  table on day one.
* **`deposit_fee` was 600** against a `bottle_deposit_by_capacity` of 300 for
  20 L, so the vendor's own screen and the quote the customer saw differed.

Everything here is now derived from the same constants the application uses, and
the figures are Kenyan retail prices for drinking water rather than placeholder
ranges. Run `seed_orders.py` afterwards to lay real orders on top.
"""
import asyncio
import math
import random
import uuid
from datetime import datetime, time, timezone

import h3
from faker import Faker
from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select

from db.session import AsyncSessionLocal
from models.deliverer_model import Deliverer
from models.product_model import Product
from models.vendor_model import Vendor
from models.vendor_rider_model import VendorRiderRegistry

faker = Faker()

# Deterministic by default. A seed run that produces different data every time
# cannot be used to reproduce a bug someone reported against it.
random.seed(20260807)
Faker.seed(20260807)

# Cloudinary Image URLs
productImages = [
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749059743/zjfoz5vc9pw9dzn7jpuh.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749059894/wsoofb5s4g9yct2vflzl.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749059929/rm2385bzx9z6exlagnnb.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749059961/f7gcwn9morh82qxrqez6.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749059986/urtwpykytnl6ilwpppgm.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060012/qi85i3x93rndfzj3ns3r.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060048/kwcms2i9ezc33qn3a5il.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060077/qroz7nc5gzmbp5eoknjk.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060111/cogawqlc2vhypwrflrxn.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060134/hdpjyjykk5oqi6jd7kdw.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060169/rctalphfnadgl3dscsfa.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060201/bmpltj6ls6gytzxfblnk.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060228/grj3hiy2y4cjefodlden.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060251/veowb8nguwwlboirlgho.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060281/vwioru36ccaxa2vwrat9.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060308/vwbrtlmth8wtbllnlmac.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060330/dquatvstkcpxbepwiiv7.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060365/an2uop1xk4gg7zk3pqx2.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060380/tci21dklgnygb1uaocju.jpg",
]

vendorProfilePics = [
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749060801/kzhsjnh5e4ka30jr0qtv.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749065804/inei0y4cgkfjum6qy0hk.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749065832/dhocfdjhnxrrsukbqw0k.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749065850/htookfvdhxsgmm8zp5d0.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1749065901/grykkgxrdfxqd5fxxs65.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751196927/pumoscycxnpcdawqvjw6.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751196965/ckrydko59jcjpwgfa281.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751196993/jph6edbeygnpeybc2gda.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751197089/tyy6re4fbabmrgrfr3h4.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751197120/ahex7trvp8prpuhnurpc.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751197145/tsy3ynpathioxw5gulyi.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751197167/j7io7ev3xvnjqesnv0x7.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751197189/gks6j8oon4lsaw1ozcph.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751197238/bjndizyuli3mrxo030zg.jpg",
    "https://res.cloudinary.com/dn5f0jksu/image/upload/v1751197261/eqdvvigrij2iv3rjmcpv.jpg",
]

# ─── Realistic Kenyan Locations ──────────────────────────────────────────────
# Strictly around Ngong Town and Matasia. The whole cluster spans about 4 km, so
# retail's 2 km radius reaches a meaningful subset of it and wholesale's 15 km
# reaches all of it — which is what makes the two tiers behave differently in a
# seeded environment instead of both matching everything.
KENYA_VENDOR_LOCATIONS = [
    ("Ngong Town, Oloolua Road", -1.3615, 36.6570),
    ("Ngong Town, Milele Mall Area", -1.3630, 36.6555),
    ("Ngong Town, Zambia Road", -1.3650, 36.6540),
    ("Ngong Town, Scheme", -1.3590, 36.6600),
    ("Ngong Town, Lemelepo", -1.3670, 36.6520),
    ("Matasia, Magadi Road", -1.3850, 36.6667),
    ("Matasia, Memusi Area", -1.3870, 36.6680),
    ("Matasia, Olkeri", -1.3820, 36.6640),
    ("Matasia, Merisho Road", -1.3890, 36.6700),
    ("Matasia, Kiserian Road Junction", -1.3910, 36.6720),
]

#: The middle of the cluster. Riders are placed around this so they are inside
#: somebody's delivery radius rather than somewhere in Nairobi County.
CLUSTER_CENTRE = (-1.3750, 36.6620)

KENYA_VENDOR_NAMES = [
    ("John Ole Kipito", "Ngong Springs Water Co."),
    ("Mary Wanjiku", "Matasia Pure Drops"),
    ("David Njoroge", "Oloolua Aqua Suppliers"),
    ("Sarah Nekesa", "Milele Fresh Water"),
    ("Peter Kamau", "Zambia Road Water Hub"),
    ("Faith Mutheu", "Memusi Crystal Water"),
    ("Joseph Ndung'u", "Olkeri Safe Water"),
    ("Grace Akinyi", "Ngong Hills Pure Water"),
    ("Daniel Ochieng", "Merisho Flow Suppliers"),
    ("Rose Wambui", "Kiserian Junction Aqua"),
]

WHOLESALE_VENDOR_NAMES = [
    ("Samuel Mwangi", "Mega Bulk Waters Ngong"),
    ("Grace Atieno", "Lake Bulk Supplies Matasia"),
    ("Peter Ochieng", "Oloolua Water Depot"),
    ("Dennis Njoroge", "Matasia Mega Wholesale"),
    ("John Kariuki", "Kiserian Bulk Water Hub"),
    ("Kevin Wanjala", "Ngong Town Water Wholesalers"),
]

# ─── Products ────────────────────────────────────────────────────────────────
# `(name, capacity_l, weight_kg, unit, min_qty, (price_low, price_high), category)`
#
# Prices are what these actually cost in Ngong, and — critically — **wholesale
# is cheaper per unit than retail for the same goods**. It was not: a 20 L unit
# was KSH 500–600 wholesale against KSH 100–200 retail, so the bulk tier was a
# worse deal than the shop, which makes every wholesale figure on every screen
# nonsense.
#
# Weights are the *filled* weight: 20 L of water is 20 kg plus about half a kilo
# of bottle. That matters because `required_vehicle_class` reconciles weight
# against unit count, and a 20 kg understatement changes which vehicle an order
# demands.
RETAIL_PRODUCTS = [
    ("20L Purified Refill",            20.0, 20.5, "bottle",   1, (150, 200), "dispenser_refill"),
    ("20L Spring Water Refill",        20.0, 20.5, "bottle",   1, (180, 220), "dispenser_refill"),
    ("20L Alkaline Refill",            20.0, 20.5, "bottle",   1, (220, 280), "dispenser_refill"),
    ("10L Purified Refill",            10.0, 10.3, "bottle",   1, (90, 130),  "dispenser_refill"),
    ("10L Family Jerrycan",            10.0, 10.3, "jerrycan", 1, (100, 140), "jerrycan"),
    ("5L Household Jerrycan",           5.0,  5.2, "jerrycan", 2, (60, 90),   "jerrycan"),
]

#: Sold by retail stores but not water: an appliance, priced like one.
#:
#: Kept separate from the refill catalogue because the order seeder must never
#: pick one for a "customer orders water" scenario. Four dispensers is a
#: legitimate KSH 60,000 retail order and a nonsensical seeded one — this is
#: where the implausibly large totals in the old seed data came from.
RETAIL_APPLIANCES = [
    ("Hot & Cold Water Dispenser",      0.0, 15.0, "unit", 1, (8_500, 14_000), "dispensers_coolers"),
    ("Manual Bottle Pump Dispenser",    0.0,  0.5, "unit", 1, (450, 900),      "accessories"),
]

WHOLESALE_PRODUCTS = [
    ("20L Bulk Dispatch",              20.0, 20.5, "bottle", 5,  (95, 130),  "bulk_wholesale"),
    ("10L Bulk Dispatch",              10.0, 10.3, "bottle", 10, (55, 80),   "bulk_wholesale"),
    ("Bale 500ml Branded (24-pack)",    0.5, 12.5, "pack",   8,  (330, 400), "bulk_wholesale"),
    ("Bale 1L Branded (12-pack)",       1.0, 12.5, "pack",   8,  (360, 430), "bulk_wholesale"),
]


def _offset(lat: float, lng: float, max_km: float) -> tuple[float, float]:
    """A random point within `max_km` of the given one, corrected for latitude.

    A naive `uniform(-0.005, 0.005)` on both axes is an ellipse whose east-west
    extent shrinks with `cos(lat)`, and the size of it is a guess. This states
    the distance in kilometres, which is the unit every radius in the platform
    is expressed in.
    """
    distance = max_km * math.sqrt(random.random())
    bearing = random.uniform(0, 2 * math.pi)
    d_lat = (distance / 111.32) * math.cos(bearing)
    d_lng = (distance / (111.32 * math.cos(math.radians(lat)))) * math.sin(bearing)
    return lat + d_lat, lng + d_lng


def _price(low: int, high: int) -> float:
    """A price in whole 5-shilling steps, the way a shop actually prices."""
    return float(random.randrange(low, high + 1, 5))


async def seed_deliverers(session, count: int = 30) -> list[Deliverer]:
    """Riders who can actually be dispatched.

    Placed inside the vendor cluster, KYC-approved, active, and holding enough
    float to accept a cash order. A rider missing any one of those is a row that
    exists and can never receive work — which is what the previous seed produced,
    thirty times over.
    """
    riders: list[Deliverer] = []
    centre_lat, centre_lng = CLUSTER_CENTRE

    for index in range(count):
        # Mostly motorbikes: retail is the volume tier and a motorbike is the
        # only vehicle its 4-bottle cap ever needs. The tuk-tuks and trucks exist
        # so wholesale orders have somebody to match against.
        if index < count * 0.7:
            vehicle = "motorbike"
        elif index < count * 0.9:
            vehicle = "tuktuk"
        else:
            vehicle = "truck"

        # Motorbike riders stay tight to the cluster so they fall inside a 2 km
        # retail radius; the larger vehicles range wider, matching wholesale.
        radius_km = 2.0 if vehicle == "motorbike" else 8.0
        lat, lng = _offset(centre_lat, centre_lng, radius_km)

        rider = Deliverer(
            id=uuid.uuid4(),
            name=faker.name(),
            email=faker.unique.email(),
            phone_number=f"2547{random.randint(10_000_000, 99_999_999)}",
            profile_pic=random.choice(vendorProfilePics),
            driver_license=faker.file_path(extension="pdf"),
            ID_number=str(random.randint(20_000_000, 39_999_999)),
            vehicle_type=vehicle,
            employment_model="gig_economy",
            plate_number=f"K{random.choice('ABCDEFG')}{random.choice('ABCDEFG')} "
                         f"{random.randint(100, 999)}{random.choice('ABCDEFGHJKLMNP')}",
            current_lat=lat,
            current_lng=lng,
            # The base a rider registers from, which is what bounds which vendors
            # they may apply to. Same point as their current position on a fresh
            # seed; `apply-vendor` refuses outright when it is null.
            operation_lat=lat,
            operation_lng=lng,
            location=from_shape(Point(lng, lat), srid=4326),
            # Every dispatch query pre-filters on this. A null one is invisible
            # to all three tiers, so the rider is undispatchable at any distance.
            h3_index_res8=str(h3.latlng_to_cell(lat, lng, 8)),
            is_available=True,
            is_active=True,
            is_verified=True,
            kyc_status="approved",
            kyc_reviewed_at=datetime.now(timezone.utc),
            # Enough float to accept a cash order. A retail cash order settles at
            # roughly KSH 420 of vendor cut plus platform cut, so anything under
            # that is a rider who is refused at every accept with a 402.
            wallet_balance=float(random.randrange(1_500, 6_000, 500)),
            rating=round(random.uniform(4.2, 5.0), 2),
            rating_count=0,
            rating_sum=0.0,
            shift_start=time(7, 0),
            shift_end=time(19, 0),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        session.add(rider)
        riders.append(rider)

    await session.flush()
    print(f"✅ {len(riders)} riders seeded — KYC approved, located, and funded.")
    return riders


def _build_products(vendor: Vendor, templates: list) -> list[Product]:
    products = []
    for name, capacity, weight, unit, min_qty, (low, high), category in templates:
        price = _price(low, high)
        # A discount on about a fifth of the catalogue, always strictly below the
        # price — `create_product` refuses anything else, and seeded data that
        # the application's own validator would reject is data that hides bugs.
        discount = float(random.randrange(5, max(10, int(price * 0.15)), 5)) if random.random() < 0.2 else 0.0

        products.append(
            Product(
                vendor_id=vendor.id,
                name=name,
                description=(
                    f"{name} from {vendor.business_name}. "
                    "Purified and bottled to KEBS standards."
                ),
                image_url=random.choice(productImages),
                price=price,
                discount=discount,
                capacity=capacity,
                weight_kg=weight,
                minimum_order_qty=min_qty,
                unit=unit,
                stock=random.randint(40, 250),
                low_stock_threshold=random.choice([5, 10, 20]),
                is_available=True,
                category=category,
            )
        )
    return products


async def seed_vendors_and_products(session) -> list[Vendor]:
    vendors: list[Vendor] = []

    # ── Retail ────────────────────────────────────────────────────────────
    for index in range(15):
        address, base_lat, base_lng = KENYA_VENDOR_LOCATIONS[index % len(KENYA_VENDOR_LOCATIONS)]
        owner, business = KENYA_VENDOR_NAMES[index % len(KENYA_VENDOR_NAMES)]
        lat, lng = _offset(base_lat, base_lng, 0.4)

        vendor = Vendor(
            owners_name=owner,
            vendor_type="retail_refill",
            business_name=business if index < len(KENYA_VENDOR_NAMES) else f"{business} (Branch {index // len(KENYA_VENDOR_NAMES) + 1})",
            email=faker.unique.email(),
            phone_number=f"2547{random.randint(10_000_000, 99_999_999)}",
            profile_pic=random.choice(vendorProfilePics),
            business_license=faker.file_path(),
            location_address=address,
            lat=lat,
            lng=lng,
            location=from_shape(Point(lng, lat), srid=4326),
            # Discovery pre-filters on this before it measures anything. Null
            # meant none of these stores appeared in search, "near you" or the
            # directory — the customer app looked empty against a full table.
            h3_index_res8=str(h3.latlng_to_cell(lat, lng, 8)),
            delivery_radius=2.0,
            shift_start=time(7, 0),
            shift_end=time(19, 0),
            verification_status="verified",
            is_active=True,
            is_online=True,
            rating=0.0,
            rating_count=0,
            rating_sum=0.0,
            # Derived from real orders by `seed_orders.py`, not invented here.
            # Random figures put the vendor dashboard and the orders table into
            # disagreement from the first run.
            total_sales=0,
            sales_amount=0,
            preferred_payment_method=["cash", "mpesa"],
            # The 20 L figure from `bottle_deposit_by_capacity`. It was 600
            # against a platform schedule of 300, so the vendor's own screen and
            # the customer's quote showed different deposits for one bottle.
            deposit_fee=300.0,
        )
        session.add(vendor)
        await session.flush()

        catalogue = random.sample(RETAIL_PRODUCTS, k=random.randint(4, len(RETAIL_PRODUCTS)))
        # Only some stores carry appliances, which is how it works in practice.
        if random.random() < 0.4:
            catalogue = catalogue + [random.choice(RETAIL_APPLIANCES)]
        for product in _build_products(vendor, catalogue):
            session.add(product)

        vendors.append(vendor)

    # ── Wholesale ─────────────────────────────────────────────────────────
    for index in range(6):
        address, base_lat, base_lng = KENYA_VENDOR_LOCATIONS[index % len(KENYA_VENDOR_LOCATIONS)]
        owner, business = WHOLESALE_VENDOR_NAMES[index]
        lat, lng = _offset(base_lat, base_lng, 0.4)

        vendor = Vendor(
            owners_name=owner,
            vendor_type="wholesale_b2b",
            business_name=business,
            email=faker.unique.email(),
            phone_number=f"2547{random.randint(10_000_000, 99_999_999)}",
            profile_pic=random.choice(vendorProfilePics),
            business_license=faker.file_path(),
            location_address=address,
            lat=lat,
            lng=lng,
            location=from_shape(Point(lng, lat), srid=4326),
            h3_index_res8=str(h3.latlng_to_cell(lat, lng, 8)),
            delivery_radius=15.0,
            shift_start=time(6, 0),
            shift_end=time(18, 0),
            verification_status="verified",
            is_active=True,
            is_online=True,
            rating=0.0,
            rating_count=0,
            rating_sum=0.0,
            total_sales=0,
            sales_amount=0,
            preferred_payment_method=["cash", "mpesa"],
            deposit_fee=300.0,
            # Only some wholesalers have negotiated their own rate. The rest fall
            # through to the platform's per-vehicle schedule, so both branches of
            # `DispatchPolicy.get_delivery_fee` are exercised by seeded data.
            wholesale_base_delivery_fee=150.0 if index % 2 == 0 else 0.0,
            wholesale_per_km_fee=90.0 if index % 2 == 0 else 0.0,
        )
        session.add(vendor)
        await session.flush()

        for product in _build_products(vendor, WHOLESALE_PRODUCTS):
            session.add(product)

        vendors.append(vendor)

    await session.flush()
    print(f"✅ {len(vendors)} vendors seeded with catalogues (15 retail, 6 wholesale).")
    return vendors


async def seed_rider_registrations(session, vendors, riders) -> int:
    """Approve riders onto the vendors they are genuinely close enough to serve.

    Tier 1 of dispatch only offers an order to riders in `VendorRiderRegistry`.
    Without these rows every order falls through to the Trip Radar broadcast
    after a twenty-second wait, so the tiering the platform is built around never
    happens in a seeded environment.

    The distance and vehicle rules are the ones `POST /api/rider-vendor/apply-vendor`
    enforces, applied here rather than assumed — a registration the API would
    have refused is a row that makes a broken query look like it works.
    """
    from services.dispatch_policy import DispatchPolicy

    created = 0
    for rider in riders:
        eligible = []
        for vendor in vendors:
            vendor_type = vendor.vendor_type.value if hasattr(vendor.vendor_type, "value") else str(vendor.vendor_type)

            # Retail is motorbike work; the bigger vehicles serve wholesale.
            if vendor_type == "retail_refill" and rider.vehicle_type.value != "motorbike":
                continue
            if vendor_type == "wholesale_b2b" and rider.vehicle_type.value == "motorbike":
                continue

            limit_km = (
                DispatchPolicy.WHOLESALE_RIDER_REGISTRATION_MAX_RADIUS_KM
                if vendor_type == "wholesale_b2b"
                else DispatchPolicy.RETAIL_RIDER_REGISTRATION_MAX_RADIUS_KM
            )
            distance = _haversine_km(rider.operation_lat, rider.operation_lng, vendor.lat, vendor.lng)
            if distance <= limit_km:
                eligible.append((distance, vendor))

        # The API caps a rider at 10 vendors. Nearest first, so the registrations
        # are the ones a real rider would actually choose.
        eligible.sort(key=lambda pair: pair[0])
        for distance, vendor in eligible[:10]:
            session.add(
                VendorRiderRegistry(
                    rider_id=rider.id,
                    vendor_id=vendor.id,
                    status="approved",
                    distance_km=round(distance, 2),
                    h3_index=rider.h3_index_res8,
                    approved_at=datetime.now(timezone.utc),
                )
            )
            created += 1

    await session.flush()
    print(f"✅ {created} rider–vendor registrations approved (within the API's own radius rules).")
    return created


def _haversine_km(lat_from, lng_from, lat_to, lng_to) -> float:
    d_lat = math.radians(lat_to - lat_from)
    d_lng = math.radians(lng_to - lng_from)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat_from)) * math.cos(math.radians(lat_to)) * math.sin(d_lng / 2) ** 2
    )
    return 6371.0 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def main():
    async with AsyncSessionLocal() as session:
        existing = (await session.execute(select(Vendor).limit(1))).scalars().first()
        if existing is not None:
            print("⚠️  Vendors already exist. Run seed/wipe_db.py first if you want a clean set.")
            return

        vendors = await seed_vendors_and_products(session)
        riders = await seed_deliverers(session)
        await seed_rider_registrations(session, vendors, riders)
        await session.commit()

    print("\nNext: `python -m seed.seed_orders` to lay real, priced orders on top.")


if __name__ == "__main__":
    asyncio.run(main())
