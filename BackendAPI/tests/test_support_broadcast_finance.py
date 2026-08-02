"""Support, broadcast, the map, and adjusting a balance by hand.

Four surfaces added for the admin console, with four different failure modes:

* **Support** is the first place on this platform where one person reads
  something another person wrote. A ticket must be filed against an account the
  token actually owns, and internal notes must never be served back to the
  requester.
* **Broadcast** is the only action here that reaches everybody and cannot be
  recalled. It honours notification preferences unless the sender explicitly
  claims otherwise, and it must reach each account exactly once.
* **The map** shows where every rider and every store is, which is its own
  capability rather than a free extra on `riders.read`.
* **A wallet adjustment** is the only endpoint on the platform that creates
  money from nothing.
"""
import ast
import pathlib
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _request() -> "Request":
    """A minimal real `Request`.

    The rate-limited handlers are wrapped by slowapi, which reaches into the
    argument list for one and refuses a stand-in — so a handler called directly
    needs the genuine article rather than a mock.
    """
    from starlette.requests import Request

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 5000),
            "server": ("test", 80),
        }
    )


# ── Shared harness ────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def console(monkeypatch):
    """The real app, the real gate, a mocked session.

    `permissions` is set per test through `console.grant(...)`, so a capability
    test exercises `require_admin` itself rather than an override standing in
    for it.
    """
    monkeypatch.setenv("ADMIN_2FA_REQUIRED", "false")

    from main import app
    from dependencies.dependencies import get_db
    from models.admin_model import ALL_PERMISSIONS
    from utils.verify_user_token import get_current_user

    admin = SimpleNamespace(
        id=uuid4(),
        clerk_id="admin_clerk",
        email="owner@drop.invalid",
        name="Owner",
        role="super_admin",
        permissions=list(ALL_PERMISSIONS),
        is_active=True,
        revoked_at=None,
        last_seen_at=datetime.now(timezone.utc),
    )

    result = MagicMock()
    result.scalars.return_value.first.return_value = admin
    result.scalars.return_value.all.return_value = []
    result.all.return_value = []
    result.scalar.return_value = 0

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.get = AsyncMock(return_value=None)
    db.add = MagicMock()

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: {"sub": "admin_clerk", "tfa": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SimpleNamespace(
            client=client,
            db=db,
            admin=admin,
            result=result,
            grant=lambda *permissions: setattr(admin, "permissions", list(permissions)),
        )

    app.dependency_overrides.clear()


# ── Capabilities ──────────────────────────────────────────────────────────


def test_the_new_capabilities_exist_and_are_labelled():
    """`require_admin` refuses to start on an unknown permission, and the roster
    screen renders `PERMISSION_LABELS`. A capability with no label appears there
    as a raw slug."""
    from models.admin_model import ALL_PERMISSIONS, PERMISSION_LABELS

    for permission in (
        "support.read",
        "support.respond",
        "broadcast.send",
        "finance.adjust",
        "geo.view",
    ):
        assert permission in ALL_PERMISSIONS
        assert PERMISSION_LABELS.get(permission), f"{permission} has no label"


def test_adjusting_a_balance_by_hand_belongs_to_nobody_but_the_super_admin():
    """Approving a payout moves money the platform already owed. This creates the
    obligation, so it is deliberately not part of the finance preset — somebody
    who reconciles accounts all day should not also be able to invent a
    balance."""
    from models.admin_model import ALL_PERMISSIONS, ROLE_PRESETS, ROLE_SUPER_ADMIN

    for role, permissions in ROLE_PRESETS.items():
        if role == ROLE_SUPER_ADMIN:
            continue
        assert "finance.adjust" not in permissions, f"{role} can create money"

    assert "finance.adjust" in ALL_PERMISSIONS


def test_support_agents_can_see_the_map_and_the_queue_but_not_change_pricing():
    from models.admin_model import ROLE_PRESETS, ROLE_SUPPORT

    support = ROLE_PRESETS[ROLE_SUPPORT]
    assert {"support.read", "support.respond", "geo.view"} <= set(support)
    assert "settings.manage" not in support
    assert "pii.view" not in support


def test_every_map_endpoint_requires_its_own_capability():
    """Structural. Rider positions are live location data for identified people;
    reading the KYC queue is not a reason to have it."""
    source = (BACKEND / "routes" / "admin_geo_routes.py").read_text()
    tree = ast.parse(source)

    handlers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
        and any(
            isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr == "get"
            for d in node.decorator_list
        )
    ]
    assert handlers, "no map handlers found — the scan is broken, not the code"

    for handler in handlers:
        # Either in the signature — `Depends(require_admin(PERM_GEO_VIEW))` — or
        # in the body, where a layer that joins two domains asks for both
        # capabilities explicitly.
        names = {sub.id for sub in ast.walk(handler) if isinstance(sub, ast.Name)}
        assert "PERM_GEO_VIEW" in names, f"{handler.name} is not gated on geo.view"


def test_the_live_order_layer_needs_both_geo_view_and_orders_read():
    """It is order data placed on a map. Holding one half should not grant the
    other — someone who may see where riders are should not thereby learn who
    ordered what."""
    source = (BACKEND / "routes" / "admin_geo_routes.py").read_text()
    tree = ast.parse(source)

    orders = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "map_orders"
    )
    required = {
        node.args[0].id
        for node in ast.walk(orders)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "require"
        and node.args
        and isinstance(node.args[0], ast.Name)
    }
    assert required == {"PERM_GEO_VIEW", "PERM_ORDERS_READ"}


@pytest.mark.asyncio
async def test_an_admin_without_geo_view_is_refused_the_map(console):
    console.grant("riders.read", "orders.read")

    response = await console.client.get("/api/admin/map/riders")

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["type"] == "permission_required"
    assert detail["permission"] == "geo.view"


# ── Support: a ticket belongs to one account ──────────────────────────────


def test_a_ticket_cannot_name_its_own_requester():
    """Identity comes from the token. A `requester_id` in the body would let any
    signed-in customer file — and then read — tickets as somebody else."""
    from routes.support_routes import TicketRequest

    assert set(TicketRequest.model_fields) == {
        "subject",
        "body",
        "category",
        "related_order_id",
    }


@pytest.mark.asyncio
async def test_reading_someone_elses_ticket_is_a_404_not_a_403():
    """Confirming a ticket id exists is itself a leak, and 403 confirms it."""
    from models.platform_setting_model import SupportTicket
    from routes import support_routes

    mine = SimpleNamespace(id=uuid4(), clerk_id="customer_clerk")
    theirs = SupportTicket(
        requester_type="customer",
        requester_id=uuid4(),  # somebody else
        subject="Where is my water",
        body="It never arrived.",
        category="delivery",
        messages=[],
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=theirs)

    with patch.object(support_routes, "_resolve_account", AsyncMock(return_value=mine)):
        with pytest.raises(HTTPException) as excinfo:
            await support_routes.my_ticket(
                ticket_id=uuid4(),
                user_type="customer",
                db=db,
                user={"sub": "customer_clerk"},
            )

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_a_vendor_ticket_resolves_the_active_store_not_the_first_one():
    """A `Vendor` row is a store, not an account.

    Resolving by `clerk_id` would file every ticket against whichever branch was
    created first, however the app's store switcher was set — and would answer
    "you don't have a vendor account" to **staff**, who hold no `clerk_id` on any
    Vendor row and are the people actually standing in the shop.

    So vendors go through the same `X-Store-Id` resolver every other vendor route
    uses, which also 404s a store the caller neither owns nor staffs.
    """
    from routes import support_routes

    branch = SimpleNamespace(id=uuid4(), business_name="Branch B")
    access = SimpleNamespace(vendor=branch)
    resolver = AsyncMock(return_value=access)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=AssertionError("a vendor must not be looked up by clerk_id"))

    with patch.object(support_routes, "_resolve_access", resolver):
        resolved = await support_routes._resolve_account(
            db, "vendor", "staff_clerk", "store-b-uuid"
        )

    assert resolved is branch
    resolver.assert_awaited_once()
    # The header the caller sent, and staff standing (not owner-only).
    assert resolver.await_args.args[2] == "store-b-uuid"
    assert resolver.await_args.kwargs["owner_only"] is False


@pytest.mark.asyncio
async def test_a_customer_is_still_resolved_by_clerk_id():
    """The store resolver is for vendors alone — a customer has no store, and
    routing them through it would 403 every ticket."""
    from routes import support_routes

    customer = SimpleNamespace(id=uuid4(), email="someone@example.invalid")
    result = MagicMock()
    result.scalars.return_value.first.return_value = customer

    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)

    resolved = await support_routes._resolve_account(db, "customer", "customer_clerk", None)

    assert resolved is customer
    db.execute.assert_awaited_once()


def test_every_support_handler_accepts_the_store_header():
    """Structural. A handler that forgets `X-Store-Id` silently falls back to the
    caller's first store, which is the bug the resolver exists to prevent — and
    it fails as a wrong answer, not as an error."""
    source = (BACKEND / "routes" / "support_routes.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        resolves = any(
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Name)
            and sub.func.id == "_resolve_account"
            for sub in ast.walk(node)
        )
        if not resolves:
            continue
        names = {argument.arg for argument in node.args.args + node.args.kwonlyargs}
        assert "x_store_id" in names, f"{node.name} does not take the store header"


@pytest.mark.asyncio
async def test_internal_notes_are_stripped_before_the_thread_reaches_the_app():
    """Support staff write "rider says the customer sounds confused" in the same
    thread. Filtered at the boundary, not left to the client to not render."""
    from models.platform_setting_model import SupportTicket
    from routes import support_routes

    account = SimpleNamespace(id=uuid4(), clerk_id="customer_clerk")
    ticket = SupportTicket(
        requester_type="customer",
        requester_id=account.id,
        subject="Refund",
        body="I was charged twice.",
        category="payment",
        status="pending",
        messages=[
            {"author": "admin", "body": "Looking into it.", "at": "now", "internal": False},
            {"author": "admin", "body": "Customer seems confused.", "at": "now", "internal": True},
        ],
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=ticket)

    with patch.object(support_routes, "_resolve_account", AsyncMock(return_value=account)):
        payload = await support_routes.my_ticket(
            ticket_id=ticket.id,
            user_type="customer",
            db=db,
            user={"sub": "customer_clerk"},
        )

    bodies = [message["body"] for message in payload["messages"]]
    assert bodies == ["Looking into it."]
    assert all("internal" not in message for message in payload["messages"])


@pytest.mark.asyncio
async def test_a_follow_up_reopens_a_resolved_ticket():
    """Someone replying to something marked resolved is saying it is not
    resolved. Leaving it closed loses them in the queue, which is the quietest
    way a support system fails the people using it."""
    from models.platform_setting_model import SupportTicket
    from routes import support_routes

    account = SimpleNamespace(id=uuid4(), clerk_id="customer_clerk")
    ticket = SupportTicket(
        requester_type="customer",
        requester_id=account.id,
        subject="Refund",
        body="I was charged twice.",
        category="payment",
        status="resolved",
        resolved_at=datetime.now(timezone.utc),
        messages=[],
    )

    db = AsyncMock()
    db.get = AsyncMock(return_value=ticket)

    with patch.object(support_routes, "_resolve_account", AsyncMock(return_value=account)):
        result = await support_routes.reply_to_own_ticket(
            request=_request(),
            ticket_id=ticket.id,
            body=support_routes.FollowUp(body="Still not refunded."),
            user_type="customer",
            db=db,
            user={"sub": "customer_clerk"},
        )

    assert result["status"] == "open"
    assert ticket.resolved_at is None
    assert ticket.messages[-1]["author"] == "customer"
    assert ticket.messages[-1]["internal"] is False


@pytest.mark.asyncio
async def test_an_admin_reply_moves_the_ticket_to_pending_and_notifies_the_requester():
    """`pending` means waiting on *them*. It is what keeps the queue badge
    honest — it counts only tickets somebody still has to answer."""
    from models.platform_setting_model import SupportTicket
    from services import support_service

    ticket = SupportTicket(
        requester_type="customer",
        requester_id=uuid4(),
        subject="Refund",
        body="Charged twice.",
        category="payment",
        status="open",
        messages=[],
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=ticket)

    with patch.object(support_service, "create_notification", AsyncMock()) as notify:
        await support_service.reply(
            session,
            ticket_id=ticket.id,
            admin_email="ops@drop.invalid",
            body="Refunded today.",
            internal=False,
        )

    assert ticket.status == "pending"
    assert ticket.assigned_admin_email == "ops@drop.invalid"
    notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_an_internal_note_neither_notifies_nor_changes_the_status():
    """A note to a colleague is not an answer to the customer. Moving the ticket
    to `pending` would drop it off the queue while nobody had replied."""
    from models.platform_setting_model import SupportTicket
    from services import support_service

    ticket = SupportTicket(
        requester_type="customer",
        requester_id=uuid4(),
        subject="Refund",
        body="Charged twice.",
        category="payment",
        status="open",
        messages=[],
    )

    session = AsyncMock()
    session.get = AsyncMock(return_value=ticket)

    with patch.object(support_service, "create_notification", AsyncMock()) as notify:
        await support_service.reply(
            session,
            ticket_id=ticket.id,
            admin_email="ops@drop.invalid",
            body="Checking the rider's GPS trail.",
            internal=True,
        )

    assert ticket.status == "open"
    notify.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_closed_ticket_is_reopened_before_it_can_be_replied_to():
    from models.platform_setting_model import SupportTicket
    from services import support_service

    ticket = SupportTicket(
        requester_type="customer",
        requester_id=uuid4(),
        subject="Refund",
        body="Charged twice.",
        category="payment",
        status="closed",
        messages=[],
    )
    session = AsyncMock()
    session.get = AsyncMock(return_value=ticket)

    with pytest.raises(HTTPException) as excinfo:
        await support_service.reply(
            session, ticket_id=ticket.id, admin_email="ops@drop.invalid", body="Hello"
        )

    assert excinfo.value.status_code == 409


# ── Broadcast ─────────────────────────────────────────────────────────────


def test_every_audience_declares_which_kind_of_account_it_addresses():
    """`USER_TYPE_OF` decides what `Notification.user_type` is written as, and
    that column is how the three apps find their own notifications. A missing
    entry is a `KeyError` mid-campaign, after some of it has already sent."""
    from services import broadcast_service

    assert set(broadcast_service.AUDIENCES) == set(broadcast_service.USER_TYPE_OF)
    assert set(broadcast_service.USER_TYPE_OF.values()) <= {"customer", "rider", "vendor"}


def test_there_is_no_everyone_audience():
    """"Everyone" invites sending a rider shift notice to customers. The segments
    are deliberately concrete."""
    from services import broadcast_service

    assert "everyone" not in broadcast_service.AUDIENCES
    assert "all" not in broadcast_service.AUDIENCES


def test_no_audience_reaches_a_suspended_account():
    """Somebody suspended should not receive marketing from the platform that
    suspended them — and the one time you do want to reach them, it is a
    one-to-one message."""
    from services import broadcast_service

    for audience in broadcast_service.AUDIENCES:
        sql = str(
            broadcast_service._audience_query(audience).compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        assert "suspended_at IS NULL" in sql, f"{audience} would reach suspended accounts"


def test_an_unknown_audience_is_refused_by_both_the_query_and_the_model_lookup():
    from services import broadcast_service

    with pytest.raises(ValueError):
        broadcast_service._audience_query("everyone")
    with pytest.raises(ValueError):
        broadcast_service._audience_model("everyone")


def test_a_campaign_walks_the_audience_by_key_never_by_offset():
    """Structural. The send loop commits between batches, and an OFFSET with no
    total ordering may return rows in a different order on the next query — on a
    campaign that means one person is messaged twice and another never hears
    from us at all."""
    source = (BACKEND / "services" / "broadcast_service.py").read_text()
    tree = ast.parse(source)

    run = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_campaign"
    )
    calls = {
        node.func.attr
        for node in ast.walk(run)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "offset" not in calls, "run_campaign is paginating with OFFSET again"
    assert "order_by" in calls


def test_a_marketing_campaign_respects_a_muted_recipient_and_a_transactional_one_does_not():
    """The default is `transactional=False`, which routes the push through the
    same preference check a promotion from anywhere else uses. Ticking the box
    is a claim the sender makes, and the audit row records it."""
    from services.broadcast_service import PROMOTIONAL_TYPE, TRANSACTIONAL_TYPE
    from services.notification_service import push_allowed

    muted = SimpleNamespace(preferences={"promotions": False})
    opted_in = SimpleNamespace(preferences={"promotions": True})

    assert push_allowed(muted, PROMOTIONAL_TYPE) is False
    assert push_allowed(opted_in, PROMOTIONAL_TYPE) is True

    # Unmapped message types are transactional and always delivered.
    assert push_allowed(muted, TRANSACTIONAL_TYPE) is True


@pytest.mark.asyncio
async def test_sending_without_typing_the_audience_creates_nothing(console):
    response = await console.client.post(
        "/api/admin/broadcast/send",
        json={
            "channel": "in_app",
            "audience": "customers",
            "subject": "Delivery hours are changing",
            "body": "From Monday we deliver until 9pm.",
            "confirm": "",
        },
    )

    assert response.status_code == 400
    console.db.add.assert_not_called()
    console.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_an_unknown_audience_is_a_refusal_not_a_500(console):
    response = await console.client.post(
        "/api/admin/broadcast/send",
        json={
            "channel": "in_app",
            "audience": "everyone",
            "subject": "Delivery hours are changing",
            "body": "From Monday we deliver until 9pm.",
            "confirm": "everyone",
        },
    )

    assert response.status_code == 400
    assert "audience" in response.json()["detail"].lower()


# ── Adjusting a wallet ────────────────────────────────────────────────────


def _owner(balance="500.00"):
    return SimpleNamespace(
        id=uuid4(),
        clerk_id="rider_clerk",
        wallet_balance=Decimal(balance),
        full_name="A Rider",
    )


@pytest.mark.asyncio
async def test_an_adjustment_of_zero_is_refused(console):
    response = await console.client.post(
        f"/api/admin/finance/riders/{uuid4()}/adjust",
        json={"amount": "0", "reason": "Correcting a duplicated refund"},
    )

    assert response.status_code == 400
    console.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_an_adjustment_needs_a_real_explanation(console):
    """Ten characters. "fix" is not an explanation, and this row is read a year
    later by somebody reconciling."""
    response = await console.client.post(
        f"/api/admin/finance/riders/{uuid4()}/adjust",
        json={"amount": "100", "reason": "fix"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_adjustment_above_the_ceiling_is_refused_rather_than_warned_about(console):
    """A credited balance that has been spent cannot be taken back, so the
    misplaced decimal has to fail closed."""
    from routes.admin_finance_routes import MAX_ADJUSTMENT

    response = await console.client.post(
        f"/api/admin/finance/riders/{uuid4()}/adjust",
        json={
            "amount": str(MAX_ADJUSTMENT + Decimal("1")),
            "reason": "Settling the December reconciliation gap",
        },
    )

    assert response.status_code == 400
    console.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_an_adjustment_is_refused_when_the_balance_has_moved_underneath_it(console):
    """Two people working the same complaint would otherwise both apply it."""
    console.db.get = AsyncMock(return_value=_owner("500.00"))

    response = await console.client.post(
        f"/api/admin/finance/riders/{uuid4()}/adjust",
        json={
            "amount": "100",
            "reason": "Refunding the disputed delivery fee",
            "expected_balance": "400.00",
        },
    )

    assert response.status_code == 409
    assert "500.00" in response.json()["detail"]
    console.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_a_debit_cannot_push_an_account_into_arrears(console):
    """A negative balance created here hides a real debt in the wrong place, and
    nothing downstream expects one."""
    console.db.get = AsyncMock(return_value=_owner("50.00"))

    response = await console.client.post(
        f"/api/admin/finance/riders/{uuid4()}/adjust",
        json={"amount": "-100", "reason": "Recovering an overpaid delivery fee"},
    )

    assert response.status_code == 400
    console.db.commit.assert_not_called()


@pytest.mark.asyncio
async def test_a_valid_adjustment_moves_the_balance_audits_it_and_tells_the_account_holder(console):
    """A silent balance change is indistinguishable from a bug to the person it
    happens to — and it generates the support ticket it was meant to close."""
    from routes import admin_finance_routes

    owner = _owner("500.00")
    console.db.get = AsyncMock(return_value=owner)

    transaction = SimpleNamespace(id=uuid4())

    with (
        patch.object(
            admin_finance_routes.wallet_service,
            "apply_wallet_delta",
            AsyncMock(return_value=transaction),
        ) as delta,
        patch.object(
            admin_finance_routes.admin_service, "record_audit", MagicMock()
        ) as audit,
        patch.object(admin_finance_routes, "create_notification", AsyncMock()) as notify,
    ):
        response = await console.client.post(
            f"/api/admin/finance/riders/{owner.id}/adjust",
            json={
                "amount": "150.50",
                "reason": "Refunding the disputed delivery fee",
                "expected_balance": "500.00",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["balance_before"] == "500.00"
    assert body["balance_after"] == "650.50"

    # The balance and the ledger row move together, through the one function
    # that does both.
    delta.assert_awaited_once()
    assert delta.await_args.kwargs["clerk_id"] == "rider_clerk"
    assert delta.await_args.kwargs["amount"] == Decimal("150.50")

    audit.assert_called_once()
    assert audit.call_args.kwargs["action"] == "finance.wallet_adjust"
    assert audit.call_args.kwargs["reason"] == "Refunding the disputed delivery fee"

    notify.assert_awaited_once()
    console.db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_an_admin_without_finance_adjust_cannot_move_a_balance(console):
    console.grant("finance.read", "finance.payout_approve")

    response = await console.client.post(
        f"/api/admin/finance/riders/{uuid4()}/adjust",
        json={"amount": "100", "reason": "Refunding the disputed delivery fee"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["permission"] == "finance.adjust"


def test_the_account_ledger_is_filtered_by_clerk_id_not_by_the_row_uuid():
    """`WalletTransaction.user_id` holds the Clerk id — `record_wallet_movement`
    writes `user_id=clerk_id`. Filtering by the path's UUID matches nothing and
    shows every account an empty ledger, which reads as "no activity" rather
    than as a bug."""
    source = (BACKEND / "routes" / "admin_finance_routes.py").read_text()
    tree = ast.parse(source)

    ledger = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "account_ledger"
    )
    names = {node.id for node in ast.walk(ledger) if isinstance(node, ast.Name)}
    assert "clerk_id" in names
    assert "owner_id" not in {
        node.attr for node in ast.walk(ledger) if isinstance(node, ast.Attribute)
    }
