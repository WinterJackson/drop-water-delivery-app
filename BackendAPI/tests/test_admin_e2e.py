"""End-to-end: the real FastAPI app, the real database, real rows.

The unit tests prove the pieces behave. These prove the *system* does — that a
request with a token belonging to an administrator with a given capability set
gets exactly what that capability set allows, through the real dependency graph,
against real Postgres.

That distinction has already caught things here. A capability check that looks
right in isolation is worthless if the route never invokes it, and a mocked
session answers every query truthfully by default — which is the opposite of
what an authorisation test needs.

Rows are created explicitly and removed in a `finally`, not rolled back: cleanup
that survives a hard failure is the only kind worth having on a shared database.
"""
import os
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

pytestmark = pytest.mark.skipif(
    not os.getenv("NEONDB_URL"),
    reason="Needs a real database; NEONDB_URL is unset.",
)


@pytest_asyncio.fixture
async def world():
    """Three administrators with different capability sets, and a rider to act on.

    Two-factor is switched off for the duration: the assertions here are about
    *capabilities*, and a synthetic token cannot carry a Clerk 2FA claim. The
    2FA branch itself is covered in `test_admin_rbac.py`.
    """
    import main  # noqa: F401  — imports the app and its routers
    from db.session import AsyncSessionLocal
    from models.admin_model import (
        ALL_PERMISSIONS,
        PERM_ANALYTICS_READ,
        PERM_ORDERS_READ,
        PERM_PII_VIEW,
        PERM_RIDERS_READ,
        AdminAuditLog,
        AdminUser,
    )
    from models.deliverer_model import Deliverer, KYCStatus

    from db.session import engine

    # pytest-asyncio gives each test its own event loop, but the engine's pool
    # is process-wide — so a connection opened in one test's loop gets handed to
    # the next test's loop and asyncpg raises "attached to a different loop".
    # Disposing on both sides of the fixture keeps each test's connections in
    # the loop that created them.
    await engine.dispose()

    previous_2fa = os.environ.get("ADMIN_2FA_REQUIRED")
    os.environ["ADMIN_2FA_REQUIRED"] = "false"

    tag = uuid.uuid4().hex[:8]
    made: dict[str, object] = {}

    async with AsyncSessionLocal() as session:
        superuser = AdminUser(
            clerk_id=f"e2e_super_{tag}",
            email=f"super.{tag}@e2e.invalid",
            name="E2E super",
            role="super_admin",
            permissions=list(ALL_PERMISSIONS),
            accepted_at=datetime.now(timezone.utc),
        )
        # Can read riders and analytics; explicitly cannot see personal data.
        analyst = AdminUser(
            clerk_id=f"e2e_analyst_{tag}",
            email=f"analyst.{tag}@e2e.invalid",
            name="E2E analyst",
            role="analyst",
            permissions=[PERM_ANALYTICS_READ, PERM_ORDERS_READ, PERM_RIDERS_READ],
            accepted_at=datetime.now(timezone.utc),
        )
        revoked = AdminUser(
            clerk_id=f"e2e_revoked_{tag}",
            email=f"revoked.{tag}@e2e.invalid",
            name="E2E revoked",
            role="operations",
            permissions=list(ALL_PERMISSIONS),
            accepted_at=datetime.now(timezone.utc),
        )
        revoked.revoke()

        rider = Deliverer(
            clerk_id=f"e2e_rider_{tag}",
            name=f"E2E Rider {tag}",
            email=f"rider.{tag}@e2e.invalid",
            phone_number="0712000999",
            ID_number="E2E12345678",
            kyc_status=KYCStatus.pending,
            vehicle_type="motorbike",
            plate_number=f"E2E {tag[:3]}",
        )

        session.add_all([superuser, analyst, revoked, rider])
        await session.commit()
        for row in (superuser, analyst, revoked, rider):
            await session.refresh(row)

        made = {
            "super": superuser,
            "analyst": analyst,
            "revoked": revoked,
            "rider": rider,
            "tag": tag,
        }

    try:
        yield made
    finally:
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(AdminAuditLog).where(AdminAuditLog.admin_email.like(f"%.{tag}@e2e.invalid"))
            )
            await session.execute(
                delete(AdminUser).where(AdminUser.email.like(f"%.{tag}@e2e.invalid"))
            )
            await session.execute(delete(Deliverer).where(Deliverer.clerk_id == f"e2e_rider_{tag}"))
            await session.commit()

        if previous_2fa is None:
            os.environ.pop("ADMIN_2FA_REQUIRED", None)
        else:
            os.environ["ADMIN_2FA_REQUIRED"] = previous_2fa

        await engine.dispose()


def _client_as(clerk_id: str) -> AsyncClient:
    """A client whose requests resolve to `clerk_id`.

    Clerk's JWT verification is overridden rather than a token forged — the
    thing under test is the authorisation layer, and standing up a real Clerk
    session per test would test Clerk.
    """
    import main
    from utils.verify_user_token import get_current_user

    main.app.dependency_overrides[get_current_user] = lambda: {"sub": clerk_id}
    return AsyncClient(transport=ASGITransport(app=main.app), base_url="http://e2e")


def _reset_overrides():
    import main

    main.app.dependency_overrides.clear()


# ── Who gets in ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_signed_in_non_admin_is_refused_everywhere(world):
    """The single most important assertion in this file.

    The console shares a Clerk instance with three consumer apps, so every
    customer holds a structurally valid token. Nothing but the `Admin_Users`
    lookup separates them from the customer table and every rider's national ID.
    """
    try:
        async with _client_as("user_an_ordinary_customer") as client:
            for path in (
                "/api/admin/me",
                "/api/admin/overview",
                "/api/admin/kyc/queue",
                "/api/admin/payouts",
                "/api/admin/people/customers",
                "/api/admin/orders",
                "/api/admin/analytics/summary",
                "/api/admin/admins",
                "/api/admin/audit",
            ):
                response = await client.get(path)
                assert response.status_code == 403, f"{path} let a non-admin through"
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_a_revoked_admin_is_refused_on_the_very_next_request(world):
    """Revocation filters on `revoked_at IS NULL` in the resolver, so it takes
    effect immediately rather than whenever some cache expires."""
    try:
        async with _client_as(world["revoked"].clerk_id) as client:
            assert (await client.get("/api/admin/me")).status_code == 403
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_an_admin_sees_their_own_capabilities(world):
    try:
        async with _client_as(world["super"].clerk_id) as client:
            response = await client.get("/api/admin/me")
            assert response.status_code == 200
            body = response.json()
            assert body["role"] == "super_admin"
            assert "pii.view" in body["permissions"]
            # Labels ship with the list so the UI cannot invent its own wording.
            assert body["permission_labels"]["pii.view"]
    finally:
        _reset_overrides()


# ── Capabilities are actually enforced ────────────────────────────────────


@pytest.mark.asyncio
async def test_the_analyst_matrix(world):
    """One capability set, checked against the endpoints it should and should
    not reach. This is the test that fails if a route forgets its gate."""
    try:
        async with _client_as(world["analyst"].clerk_id) as client:
            # Granted.
            assert (await client.get("/api/admin/analytics/summary")).status_code == 200
            assert (await client.get("/api/admin/overview")).status_code == 200
            assert (await client.get("/api/admin/kyc/queue")).status_code == 200
            assert (await client.get("/api/admin/orders")).status_code == 200

            # Withheld — each for a different reason.
            forbidden = {
                "/api/admin/payouts": "no finance.read",
                "/api/admin/people/customers": "no customers.read",
                "/api/admin/admins": "no admins.manage",
                "/api/admin/audit": "no admins.manage",
                f"/api/admin/riders/{world['rider'].id}/documents?reason=testing": "no pii.view",
            }
            for path, why in forbidden.items():
                response = await client.get(path)
                assert response.status_code == 403, f"{path} allowed despite {why}"

            # And the refusal is typed, so the console can explain it.
            body = (await client.get("/api/admin/payouts")).json()
            assert body["detail"]["type"] == "permission_required"
            assert body["detail"]["permission"] == "finance.read"
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_financial_analytics_are_withheld_without_breaking_the_page(world):
    """An analyst gets a *working* analytics screen minus the money.

    Refusing the whole endpoint for one section is how someone ends up being
    handed `finance.read` just to look at demand charts.
    """
    try:
        async with _client_as(world["analyst"].clerk_id) as client:
            body = (await client.get("/api/admin/analytics/summary")).json()
            assert body["finance_visible"] is False
            assert "payment_mix" not in body
            assert "float_exposure" not in body
            # The operational half is all there.
            assert body["timeseries"]["points"]
            assert "supply" in body and "customers" in body

        async with _client_as(world["super"].clerk_id) as client:
            body = (await client.get("/api/admin/analytics/summary")).json()
            assert body["finance_visible"] is True
            assert "payment_mix" in body and "float_exposure" in body
    finally:
        _reset_overrides()


# ── Personal data ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lists_never_carry_unmasked_contact_details(world):
    """Checked against a real row with a known phone number and email.

    The first implementation of the mask returned the value untouched — the
    guard passed, the slice returned everything, and it looked masked. Only a
    test that knows the real value catches that.
    """
    try:
        async with _client_as(world["super"].clerk_id) as client:
            body = (await client.get("/api/admin/people/riders?limit=200")).json()
            mine = [i for i in body["items"] if i["id"] == str(world["rider"].id)]
            assert mine, "the seeded rider was not returned"
            row = mine[0]

            assert row["phone_number"] != "0712000999"
            assert row["email"] != world["rider"].email
            assert row["phone_number"].startswith("••••")
            # Only the last three digits survive, so a phone number cannot be
            # reconstructed from a list.
            assert row["phone_number"] == "••••999"

            # The domain survives — it is what makes a row recognisable at a
            # glance — and exactly one character of the local part. The rest of
            # the address, which is the half that identifies a person, does not.
            local, _, domain = world["rider"].email.partition("@")
            assert row["email"] == f"{local[0]}••••@{domain}"
            assert local not in row["email"]
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_revealing_contact_details_requires_a_reason_and_is_audited(world):
    """The audit row is written *before* the data is returned, so a reveal
    cannot happen without a record of who did it and why."""
    from db.session import AsyncSessionLocal
    from models.admin_model import AdminAuditLog

    try:
        async with _client_as(world["super"].clerk_id) as client:
            rider_id = world["rider"].id

            # No reason at all is a validation error, not a silent default.
            assert (
                await client.get(f"/api/admin/people/riders/{rider_id}/contact")
            ).status_code == 422

            response = await client.get(
                f"/api/admin/people/riders/{rider_id}/contact",
                params={"reason": "E2E verification check"},
            )
            assert response.status_code == 200
            body = response.json()
            assert body["phone_number"] == "0712000999"
            # Decrypted by the ORM type — raw SQL would return ciphertext.
            assert body["ID_number"] == "E2E12345678"

        async with AsyncSessionLocal() as session:
            entry = (
                await session.execute(
                    select(AdminAuditLog).where(
                        AdminAuditLog.target_id == str(rider_id),
                        AdminAuditLog.action == "rider.pii.view",
                    )
                )
            ).scalars().first()
            assert entry is not None, "revealing PII left no audit record"
            assert entry.reason == "E2E verification check"
            assert entry.admin_email == world["super"].email
    finally:
        _reset_overrides()


# ── A real workflow, end to end ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_kyc_review_loop(world):
    """Reject with a reason, confirm the rider can see it, then approve.

    This is the loop that was broken: the reviewer's reason went into a push
    notification and nowhere else, so a rejected rider returned to a prefilled
    form with no idea what was wrong.
    """
    from db.session import AsyncSessionLocal
    from models.admin_model import AdminAuditLog
    from models.deliverer_model import Deliverer

    rider_id = world["rider"].id
    try:
        async with _client_as(world["super"].clerk_id) as client:
            # A rejection with no reason is refused.
            assert (
                await client.put(
                    f"/api/admin/riders/{rider_id}/kyc", json={"status": "rejected"}
                )
            ).status_code == 400

            response = await client.put(
                f"/api/admin/riders/{rider_id}/kyc",
                json={"status": "rejected", "rejection_reason": "The ID back is blurred."},
            )
            assert response.status_code == 200
            assert response.json()["kyc_status"] == "rejected"

            async with AsyncSessionLocal() as session:
                rider = await session.get(Deliverer, rider_id)
                assert rider.kyc_rejection_reason == "The ID back is blurred."
                assert rider.kyc_reviewed_at is not None

            # Approving clears the reason — a stale one would sit next to fresh
            # documents claiming they were blurred.
            approved = await client.put(
                f"/api/admin/riders/{rider_id}/kyc", json={"status": "approved"}
            )
            assert approved.status_code == 200

            async with AsyncSessionLocal() as session:
                rider = await session.get(Deliverer, rider_id)
                assert rider.kyc_rejection_reason is None

            # Approving twice is idempotent, not a second decision in the log.
            again = await client.put(
                f"/api/admin/riders/{rider_id}/kyc", json={"status": "approved"}
            )
            assert again.json()["unchanged"] is True

        async with AsyncSessionLocal() as session:
            entries = (
                await session.execute(
                    select(AdminAuditLog).where(AdminAuditLog.target_id == str(rider_id))
                )
            ).scalars().all()
            actions = [e.action for e in entries]
            assert actions.count("rider.kyc.approve") == 1, "the no-op wrote an audit row"
            assert "rider.kyc.reject" in actions
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_suspension_removes_a_rider_from_dispatch_and_reinstating_restores_it(world):
    from db.session import AsyncSessionLocal
    from models.deliverer_model import Deliverer

    rider_id = world["rider"].id
    try:
        async with _client_as(world["super"].clerk_id) as client:
            response = await client.post(
                f"/api/admin/people/riders/{rider_id}/suspend",
                json={"reason": "E2E suspension"},
            )
            assert response.status_code == 200

            async with AsyncSessionLocal() as session:
                rider = await session.get(Deliverer, rider_id)
                assert rider.suspended_at is not None
                assert rider.is_active is False
                # Otherwise they keep receiving offers until the shift ends.
                assert rider.is_available is False

            # Suspending twice would overwrite the original reason and timestamp.
            assert (
                await client.post(
                    f"/api/admin/people/riders/{rider_id}/suspend",
                    json={"reason": "again"},
                )
            ).status_code == 409

            assert (
                await client.post(
                    f"/api/admin/people/riders/{rider_id}/reinstate",
                    json={"reason": "Resolved"},
                )
            ).status_code == 200

            async with AsyncSessionLocal() as session:
                rider = await session.get(Deliverer, rider_id)
                assert rider.suspended_at is None
                assert rider.suspension_reason is None
                assert rider.is_active is True
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_search_is_scoped_to_what_the_caller_may_open(world):
    """The analyst can read riders but not customers, so the palette returns
    riders and nothing else — searching must not be a way around the permission
    guarding the detail page."""
    try:
        async with _client_as(world["analyst"].clerk_id) as client:
            body = (await client.get("/api/admin/search", params={"q": "0712000999"})).json()
            kinds = {hit["kind"] for hit in body["results"]}
            assert "customer" not in kinds
            assert "vendor" not in kinds
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_an_admin_cannot_remove_their_own_access(world):
    """The last super admin deleting themselves locks everybody out of the
    console permanently, recoverable only by editing the database by hand."""
    try:
        async with _client_as(world["super"].clerk_id) as client:
            response = await client.delete(f"/api/admin/admins/{world['super'].id}")
            assert response.status_code == 400
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_money_never_arrives_as_a_float(world):
    """Every monetary field crosses the wire as a decimal string.

    A JSON number would have been through a double by the time the console
    parses it, and a revenue figure that disagrees with the ledger by cents is
    one people argue with instead of using.
    """
    try:
        async with _client_as(world["super"].clerk_id) as client:
            revenue = (await client.get("/api/admin/revenue")).json()
            assert isinstance(revenue["total_platform_revenue"], str)
            assert isinstance(revenue["total_gmv"], str)
            for value in revenue["breakdown"].values():
                assert isinstance(value, str)

            overview = (await client.get("/api/admin/overview")).json()
            assert isinstance(overview["last_7_days"]["revenue"], str)

            unit = (await client.get("/api/admin/analytics/summary")).json()["unit_economics"]
            assert isinstance(unit["gmv"], str)
            assert isinstance(unit["take_rate_pct"], str)
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_the_kyc_queue_does_not_mint_document_urls(world):
    """Presigning per row would create live links to every identity document in
    the queue on every page load, whether or not anyone opened one."""
    try:
        async with _client_as(world["super"].clerk_id) as client:
            body = (await client.get("/api/admin/kyc/queue?status=pending&limit=200")).json()
            serialised = str(body)
            assert "X-Amz-Signature" not in serialised
            assert "id_card_front" not in serialised
    finally:
        _reset_overrides()


# ── The navigation badges ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nav_counts_only_reports_queues_the_caller_may_open(world):
    """A badge reading "3" on a page that would refuse the caller leaks the size
    of a table they cannot see, and invites a support ticket about a queue they
    cannot work.

    The analyst here holds `analytics.read`, `orders.read` and `riders.read` —
    so they get the rider and order queues and must not get the payout or
    dispute ones.
    """
    try:
        async with _client_as(world["analyst"].clerk_id) as client:
            response = await client.get("/api/admin/nav/counts")
            assert response.status_code == 200
            counts = response.json()

        assert "rider_kyc" in counts
        assert "orders_stuck" in counts
        # No finance.read, no vendors.read, no disputes.read.
        for withheld in ("payouts", "payouts_stuck", "vendor_verification", "disputes"):
            assert withheld not in counts, f"{withheld} leaked to an analyst"

        async with _client_as(world["super"].clerk_id) as client:
            everything = (await client.get("/api/admin/nav/counts")).json()

        for key in (
            "rider_kyc",
            "vendor_verification",
            "orders_stuck",
            "disputes",
            "payouts",
            "payouts_stuck",
        ):
            assert key in everything, f"a super admin did not get {key}"
            assert isinstance(everything[key], int)
    finally:
        _reset_overrides()


@pytest.mark.asyncio
async def test_the_rider_kyc_badge_agrees_with_the_queue_it_links_to(world):
    """A badge that disagrees with its own page is worse than no badge — the
    fixture's pending rider must be counted by both."""
    try:
        async with _client_as(world["super"].clerk_id) as client:
            badge = (await client.get("/api/admin/nav/counts")).json()["rider_kyc"]
            queue = (await client.get("/api/admin/kyc/queue?status=pending&limit=200")).json()

        assert badge >= 1, "the fixture's pending rider was not counted"
        assert badge == len(queue["items"]) or len(queue["items"]) == 200
    finally:
        _reset_overrides()


# ── Deployment settings ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_settings_needs_its_own_capability_and_leaks_no_secrets(world):
    """The page reports whether each credential is *configured*, never its value
    — that is the whole diagnostic benefit with none of the exposure."""
    try:
        async with _client_as(world["analyst"].clerk_id) as client:
            assert (await client.get("/api/admin/settings")).status_code == 403

        async with _client_as(world["super"].clerk_id) as client:
            response = await client.get("/api/admin/settings")
            assert response.status_code == 200
            body = response.json()

        keys = {switch["key"] for switch in body["switches"]}
        assert "ADMIN_2FA_REQUIRED" in keys
        assert all(isinstance(switch["enabled"], bool) for switch in body["switches"])

        # Deployment switches only. Vendor gating moved to `Platform_Settings`,
        # and reporting it from the environment here would show "off" while the
        # console had it on.
        assert "REQUIRE_VENDOR_VERIFICATION" not in keys

        for integration in body["integrations"]:
            assert set(integration) == {"key", "label", "configured"}
            assert isinstance(integration["configured"], bool)

        # Nothing that could be a credential came back.
        secret = os.getenv("CLERK_SECRET_KEY")
        if secret:
            assert secret not in str(body)
    finally:
        _reset_overrides()


# ── Vendor verification ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_vendor_queue_can_be_filtered_by_verification_status(world):
    """The console's verification queue asks "who is still waiting", which is a
    different axis from suspension: a store can be unverified and trading, or
    verified and suspended."""
    try:
        async with _client_as(world["super"].clerk_id) as client:
            pending = (await client.get("/api/admin/people/vendors?status=pending&limit=200")).json()
            verified = (await client.get("/api/admin/people/vendors?status=verified&limit=200")).json()

        assert all(item["verification_status"] == "pending" for item in pending["items"])
        assert all(item["verification_status"] == "verified" for item in verified["items"])
    finally:
        _reset_overrides()
