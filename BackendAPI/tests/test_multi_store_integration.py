"""
Two stores, one owner, one staff member — against a real database.

Everything else in this suite mocks the session, which is right for logic but
cannot prove the thing multi-store actually turns on: that the WHERE clauses
compile, that `X-Store-Id` reaches them, and that naming somebody else's store
returns nothing. Every vendor on the platform today owns exactly one store, so
the fallback path is the only one production exercises — this file is the only
place the second store is ever real.

Its rows are created under a unique random `clerk_id` prefix and deleted again in
the fixture teardown, so it leaves nothing behind and cannot collide with real
data. Point it at a scratch database with `TEST_DATABASE_URL` if you would rather
it never touched the configured one at all; it skips entirely when neither is
reachable.

Deliberately **not** the usual "open a transaction and roll it back" harness. The
service layer commits, so that pattern needs SAVEPOINTs — and this repository's
local `venv/` has had `savepoint` corrupted to `sadropint` by a stray global
find/replace, which makes every nested transaction a Postgres syntax error. See
the note in `docs/vendor-app-remediation-plan.md`. Explicit cleanup works either
way, and does not quietly depend on a healthy virtualenv.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from dependencies.dependencies import get_db
from main import app
from utils.verify_user_token import get_current_user

def _database_url() -> str | None:
    """Prefer a scratch database; fall back to the configured one.

    `db.session` is what loads `.env`, so importing it is how the configured URL
    becomes visible — reading `os.environ` alone finds nothing when the value
    lives in the dotenv file rather than the shell.
    """
    explicit = os.getenv("TEST_DATABASE_URL")
    if explicit:
        return explicit
    try:
        from db.session import DATABASE_URL as configured

        return configured
    except Exception:  # pragma: no cover - environment dependent
        return None


DATABASE_URL = _database_url()

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not DATABASE_URL.startswith("postgresql"),
    reason="needs a reachable Postgres; set TEST_DATABASE_URL or DATABASE_URL",
)

OWNER = f"user_owner_{uuid.uuid4().hex[:12]}"
STAFF = f"user_staff_{uuid.uuid4().hex[:12]}"
OUTSIDER = f"user_outsider_{uuid.uuid4().hex[:12]}"


@pytest_asyncio.fixture
async def world():
    """Two stores for one owner, plus a product in each. Removed on teardown.

    Every row is keyed to a random `clerk_id` generated per run, so a leaked row
    from a hard crash belongs to a Clerk subject that does not exist and can
    never be signed in as.
    """
    engine = create_async_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    try:
        async with engine.connect() as probe:
            await probe.execute(text("select 1"))
    except Exception as e:  # pragma: no cover - environment dependent
        await engine.dispose()
        pytest.skip(f"database not reachable: {e}")

    from models.product_model import Product
    from models.vendor_model import Vendor

    session = Session()
    base = datetime.now(timezone.utc)

    def _store(clerk_id, name, age_days):
        return Vendor(
            id=uuid.uuid4(), clerk_id=clerk_id, business_name=name,
            owners_name="Test Owner", email=f"{uuid.uuid4().hex[:10]}@drop.test",
            vendor_type="retail_refill",
            # `created_at` decides which store the no-header fallback picks, so
            # it is set explicitly rather than left to insertion order.
            created_at=base - timedelta(days=age_days),
        )

    first = _store(OWNER, "First Branch", 2)
    second = _store(OWNER, "Second Branch", 1)
    stranger = _store(OUTSIDER, "Someone Else's Shop", 0)

    session.add_all([first, second, stranger])
    await session.flush()
    session.add_all([
        Product(
            id=uuid.uuid4(), vendor_id=first.id, name="First Branch 20L",
            image_url="products/first.webp", price=300, discount=0, capacity=20,
            unit="L", stock=40, low_stock_threshold=5,
        ),
        Product(
            id=uuid.uuid4(), vendor_id=second.id, name="Second Branch 20L",
            image_url="products/second.webp", price=350, discount=0, capacity=20,
            unit="L", stock=2, low_stock_threshold=5,
        ),
    ])
    await session.commit()

    store_ids = [first.id, second.id, stranger.id]
    try:
        yield {"session": session, "first": first, "second": second, "stranger": stranger}
    finally:
        await session.rollback()
        # Children first: `Products` has no cascade, and `Vendor_Staff` does but
        # is deleted explicitly so the statement reads the same either way.
        for table in ("Vendor_Staff", "Products"):
            await session.execute(
                text(f'DELETE FROM "{table}" WHERE vendor_id = ANY(:ids)'), {"ids": store_ids}
            )
        await session.execute(
            text('DELETE FROM "Vendors" WHERE id = ANY(:ids)'), {"ids": store_ids}
        )
        await session.commit()
        await session.close()
        await engine.dispose()


def _client(session, clerk_id: str) -> AsyncClient:
    """The real app, with the database and the token holder substituted."""
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_user] = lambda: {"sub": clerk_id}
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture(autouse=True)
async def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── Multi-store ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_each_store_answers_for_itself(world):
    """The header decides. Without it, both requests hit the same row."""
    async with _client(world["session"], OWNER) as client:
        first = await client.get(
            "/api/vendor/profile", headers={"X-Store-Id": str(world["first"].id)}
        )
        second = await client.get(
            "/api/vendor/profile", headers={"X-Store-Id": str(world["second"].id)}
        )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["business_name"] == "First Branch"
    assert second.json()["business_name"] == "Second Branch"


@pytest.mark.asyncio
async def test_products_are_scoped_to_the_named_store(world):
    """The catalogue is the clearest tell: it used to be whichever row came first."""
    async with _client(world["session"], OWNER) as client:
        first = await client.get(
            "/api/vendor/products", headers={"X-Store-Id": str(world["first"].id)}
        )
        second = await client.get(
            "/api/vendor/products", headers={"X-Store-Id": str(world["second"].id)}
        )

    first_names = [p["name"] for p in first.json()["items"]]
    second_names = [p["name"] for p in second.json()["items"]]
    assert first_names == ["First Branch 20L"]
    assert second_names == ["Second Branch 20L"]


@pytest.mark.asyncio
async def test_naming_no_store_is_deterministic_and_picks_the_first(world):
    """Single-store vendors — everyone today — must be unaffected.

    Called twice: the point is not only *which* store, but that two identical
    requests cannot disagree. The old query had no ORDER BY at all.
    """
    async with _client(world["session"], OWNER) as client:
        one = await client.get("/api/vendor/profile")
        two = await client.get("/api/vendor/profile")

    assert one.json()["id"] == two.json()["id"] == str(world["first"].id)


@pytest.mark.asyncio
async def test_a_store_you_do_not_own_is_a_404(world):
    """404, not 403: whether that id exists is not this caller's to learn."""
    async with _client(world["session"], OWNER) as client:
        response = await client.get(
            "/api/vendor/profile", headers={"X-Store-Id": str(world["stranger"].id)}
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_store_list_returns_both_and_is_not_scoped(world):
    """`GET /stores` is the one endpoint that must ignore `X-Store-Id`.

    Scoping it would narrow it to the store the switcher is trying to leave.
    """
    async with _client(world["session"], OWNER) as client:
        response = await client.get(
            "/api/vendor/stores", headers={"X-Store-Id": str(world["second"].id)}
        )

    names = sorted(s["business_name"] for s in response.json())
    assert names == ["First Branch", "Second Branch"]


@pytest.mark.asyncio
async def test_a_malformed_store_id_is_rejected(world):
    async with _client(world["session"], OWNER) as client:
        response = await client.get("/api/vendor/profile", headers={"X-Store-Id": "nonsense"})
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_the_dashboard_reports_the_named_store_low_stock(world):
    """Second Branch has 2 of a product whose threshold is 5; First Branch has 40."""
    async with _client(world["session"], OWNER) as client:
        first = await client.get(
            "/api/vendor/dashboard", headers={"X-Store-Id": str(world["first"].id)}
        )
        second = await client.get(
            "/api/vendor/dashboard", headers={"X-Store-Id": str(world["second"].id)}
        )

    assert first.json()["low_stock_products"] == []
    low = second.json()["low_stock_products"]
    assert [p["name"] for p in low] == ["Second Branch 20L"]
    assert low[0]["stock"] == 2


# ── Staff ────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def staffed(world):
    """A live staff member on the *second* store only, with orders but not products.

    Deliberately not the store the fallback would pick, so a test that passes by
    accident — because both stores resolve the same way — cannot.
    """
    from models.vendor_staff_model import VendorStaff

    session = world["session"]
    member = VendorStaff(
        id=uuid.uuid4(),
        vendor_id=world["second"].id,
        clerk_id=STAFF,
        email="assistant@example.com",
        permissions=["manage_orders"],
    )
    session.add(member)
    await session.commit()
    # No teardown of its own: `world` deletes `Vendor_Staff` for these stores.
    return {**world, "member": member}


@pytest.mark.asyncio
async def test_staff_reach_only_the_store_they_staff(staffed):
    """They are not staff of First Branch, so naming it is a 404 for them too."""
    async with _client(staffed["session"], STAFF) as client:
        theirs = await client.get(
            "/api/vendor/profile", headers={"X-Store-Id": str(staffed["second"].id)}
        )
        not_theirs = await client.get(
            "/api/vendor/profile", headers={"X-Store-Id": str(staffed["first"].id)}
        )

    assert theirs.status_code == 200
    assert theirs.json()["business_name"] == "Second Branch"
    assert theirs.json()["role"] == "staff"
    assert not_theirs.status_code == 404


@pytest.mark.asyncio
async def test_staff_permissions_are_enforced_per_capability(staffed):
    """The whole reason for the table.

    `staff_clerk_id` was one nullable column: handing someone the till handed
    them the catalogue, the bottle ledger and the wallet balance as well.
    """
    headers = {"X-Store-Id": str(staffed["second"].id)}
    async with _client(staffed["session"], STAFF) as client:
        # Granted.
        assert (await client.get("/api/vendor/orders", headers=headers)).status_code == 200
        # Not granted — and refused machine-readably.
        refused = await client.post(
            "/api/vendor/products",
            headers=headers,
            json={
                "name": "Sneaky Product", "image_url": "x.webp", "price": 1,
                "capacity": 20, "unit": "L", "stock": 1,
            },
        )
        wallet = await client.get("/api/vendor/wallet-summary", headers=headers)

    assert refused.status_code == 403
    assert refused.json()["detail"]["type"] == "permission_required"
    assert refused.json()["detail"]["permission"] == "manage_products"
    assert wallet.status_code == 403


@pytest.mark.asyncio
async def test_the_profile_tells_the_app_what_this_caller_may_do(staffed):
    """So screens hide what would be refused instead of guessing from a role name."""
    headers = {"X-Store-Id": str(staffed["second"].id)}
    async with _client(staffed["session"], STAFF) as client:
        staff_profile = (await client.get("/api/vendor/profile", headers=headers)).json()
    async with _client(staffed["session"], OWNER) as client:
        owner_profile = (await client.get("/api/vendor/profile", headers=headers)).json()

    assert staff_profile["permissions"] == ["manage_orders"]
    assert owner_profile["role"] == "owner"
    # Owners hold every capability implicitly; spelling them out means the app
    # checks one thing rather than "is owner, or has permission".
    assert "manage_products" in owner_profile["permissions"]
    assert "view_finances" in owner_profile["permissions"]


@pytest.mark.asyncio
async def test_staff_cannot_reach_owner_only_routes(staffed):
    headers = {"X-Store-Id": str(staffed["second"].id)}
    async with _client(staffed["session"], STAFF) as client:
        profile_write = await client.put(
            "/api/vendor/profile", headers=headers, json={"business_name": "Renamed"}
        )
        staff_list = await client.get("/api/vendor/staff", headers=headers)

    assert profile_write.status_code == 403
    assert profile_write.json()["detail"]["type"] == "owner_only"
    assert staff_list.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_sees_and_can_revoke_the_staff_member(staffed):
    headers = {"X-Store-Id": str(staffed["second"].id)}
    async with _client(staffed["session"], OWNER) as client:
        listed = (await client.get("/api/vendor/staff", headers=headers)).json()
        assert [s["email"] for s in listed["staff"]] == ["assistant@example.com"]
        # The capability set travels with the list, so the management screen can
        # never hardcode one that has drifted from the server's.
        assert {p["key"] for p in listed["available_permissions"]} >= {
            "manage_orders", "manage_products", "manage_bottles", "view_finances"
        }

        promoted = await client.patch(
            f"/api/vendor/staff/{staffed['member'].id}",
            headers=headers,
            json={"permissions": ["manage_orders", "manage_products"]},
        )
        revoked = await client.delete(
            f"/api/vendor/staff/{staffed['member'].id}", headers=headers
        )
        after = (await client.get("/api/vendor/staff", headers=headers)).json()

    assert sorted(promoted.json()["permissions"]) == ["manage_orders", "manage_products"]
    assert revoked.status_code == 200
    assert after["staff"] == []

    # Revocation is a soft delete: the row survives for the audit trail behind
    # every order and bottle movement they touched.
    from sqlalchemy import select

    from models.vendor_staff_model import VendorStaff

    row = (
        await staffed["session"].execute(
            select(VendorStaff).where(VendorStaff.id == staffed["member"].id)
        )
    ).scalars().first()
    assert row is not None and row.revoked_at is not None


@pytest.mark.asyncio
async def test_a_revoked_member_loses_access_immediately(staffed):
    headers = {"X-Store-Id": str(staffed["second"].id)}
    async with _client(staffed["session"], OWNER) as client:
        await client.delete(f"/api/vendor/staff/{staffed['member'].id}", headers=headers)

    async with _client(staffed["session"], STAFF) as client:
        response = await client.get("/api/vendor/profile", headers=headers)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_staff_list_is_scoped_to_the_store(staffed):
    """First Branch has no staff; the member belongs to Second Branch alone."""
    async with _client(staffed["session"], OWNER) as client:
        first = await client.get(
            "/api/vendor/staff", headers={"X-Store-Id": str(staffed["first"].id)}
        )
    assert first.json()["staff"] == []


@pytest.mark.asyncio
async def test_a_staff_id_from_another_store_cannot_be_revoked(staffed):
    """Scoped by `vendor_id`, so it is a 404 and reveals nothing about the id."""
    async with _client(staffed["session"], OWNER) as client:
        response = await client.delete(
            f"/api/vendor/staff/{staffed['member'].id}",
            headers={"X-Store-Id": str(staffed["first"].id)},
        )
    assert response.status_code == 404
