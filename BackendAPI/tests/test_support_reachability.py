"""Whether a support reply actually reaches the person who asked.

The support queue was complete on the console side and complete on the intake
side, and the join between them leaked. Three separate defects, all of which
had the same shape — the thing was *recorded* and never *delivered*:

1. **No push was ever sent.** `reply` wrote a `Notification` row and the route
   emailed. Every other user-visible event on this platform also pushes; this
   one, the single message a person is actively waiting for, did not. An
   exhaustive walk of `queue_push` and `dispatch_background` call sites found
   orders, refunds, riders, vendors and broadcast — and no support anywhere.

2. **The deep link pointed at the admin console.** `action_url` was
   `/support/{id}`. Every other `action_url` in the backend is an Expo Router
   path (`/(screens)/…`). The customer app's whitelist blocked it silently, and
   the rider and vendor apps pushed an unmatched route.

3. **A requester's follow-up left the ticket `pending`.** `pending` means
   "waiting on them". The nav badge counts only `open`, so somebody replying to
   an answer flipped nothing, badged nothing, and stayed labelled as somebody
   else's turn.

Plus `priority`, which nothing on the platform could write while the queue
filtered on it and the console coloured a badge from it.
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import HTTPException

BACKEND = pathlib.Path(__file__).resolve().parent.parent

TOKEN = "ExponentPushToken[requester-device]"
STAFF_TOKEN = "ExponentPushToken[staff-device]"


def _code_only(path: pathlib.Path) -> str:
    """Source with docstrings and comments stripped.

    The assertions below search for strings that must *not* appear, and the
    comments explaining why they were removed inevitably name them. This is the
    same trap the settlement and remediation suites both hit.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


class _Session:
    """Enough session to observe `queue_push`, which parks on `session.info`.

    A plain `AsyncMock` cannot stand in here: `info.setdefault(...)` on a mock
    returns another mock, so the queued message vanishes into it and the test
    passes whether or not anything was queued. `info` has to be a real dict.
    """

    def __init__(self, account=None):
        self.info: dict = {}
        self.added: list = []
        self._account = account
        self.get = AsyncMock(side_effect=self._get)

    async def _get(self, model, pk):
        return self._account

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None

    @property
    def pushes(self) -> list[dict]:
        return self.info.get("pending_pushes", [])


def _ticket(*, requester_type="customer", status="open", messages=None, subject="Where is my water"):
    """A real transient `SupportTicket`, not a stand-in.

    `reply` calls `flag_modified`, which needs genuine instance state and raises
    on a `SimpleNamespace`. That call is load-bearing — a JSONB list mutated in
    place is invisible to the ORM without it — so a fixture that cannot execute
    it would be testing a different function from the one that ships.
    """
    from models.platform_setting_model import SupportTicket

    ticket = SupportTicket(
        id=uuid4(),
        requester_type=requester_type,
        requester_id=uuid4(),
        requester_email="someone@example.com",
        subject=subject,
        body="It never arrived.",
        category="delivery",
        priority="normal",
        status=status,
        messages=list(messages or []),
    )
    return ticket


# ── The push that was never sent ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_reply_pushes_to_the_person_who_raised_the_ticket():
    """The defect this file exists for. A row is not a notification."""
    from services import support_service

    account = SimpleNamespace(id=uuid4(), push_token=TOKEN, preferences={})
    session = _Session(account)
    ticket = _ticket()
    session.get = AsyncMock(side_effect=[ticket, account])

    await support_service.reply(
        session, ticket_id=ticket.id, admin_email="agent@drop.invalid", body="On its way."
    )

    assert len(session.pushes) == 1, "a support reply must interrupt, not only record"
    assert session.pushes[0]["to"] == TOKEN
    assert session.pushes[0]["body"] == "On its way."
    assert ticket.subject in session.pushes[0]["title"]


@pytest.mark.asyncio
async def test_the_push_carries_an_app_route_not_the_console_one():
    """`/support/{id}` is a Next.js path. The apps route on `/(screens)/…`."""
    from services import support_service

    account = SimpleNamespace(id=uuid4(), push_token=TOKEN, preferences={})
    session = _Session(account)
    ticket = _ticket()
    session.get = AsyncMock(side_effect=[ticket, account])

    await support_service.reply(
        session, ticket_id=ticket.id, admin_email="agent@drop.invalid", body="Sorted."
    )

    url = session.pushes[0]["data"]["url"]
    assert url.startswith("/(screens)/"), url
    assert str(ticket.id) in url
    # The customer app whitelists "/(screens)" and blocks everything else, so a
    # console path was a silent no-op rather than a visible error.
    assert not url.startswith("/support/")


@pytest.mark.asyncio
async def test_an_internal_note_pushes_nothing_and_writes_nothing():
    """The distinction the whole screen turns on. A colleague-facing note
    reaching the customer is the worst outcome this feature has."""
    from services import support_service

    account = SimpleNamespace(id=uuid4(), push_token=TOKEN, preferences={})
    session = _Session(account)
    ticket = _ticket()
    session.get = AsyncMock(side_effect=[ticket, account])

    await support_service.reply(
        session,
        ticket_id=ticket.id,
        admin_email="agent@drop.invalid",
        body="Checking the GPS trail — customer sounds confused.",
        internal=True,
    )

    assert session.pushes == []
    assert session.added == [], "an internal note must not write a Notification row"


@pytest.mark.asyncio
async def test_a_store_reply_reaches_its_staff_as_well_as_its_owner():
    """Staff raise and read the store's tickets, so a reply only the owner is
    interrupted by is a reply the person in the shop never sees."""
    from services import support_service

    store = SimpleNamespace(id=uuid4(), push_token=TOKEN, preferences={})
    session = _Session(store)
    ticket = _ticket(requester_type="vendor")
    session.get = AsyncMock(side_effect=[ticket, store])

    with patch(
        "services.vendor_staff_service.push_tokens_for_store",
        AsyncMock(return_value=[STAFF_TOKEN]),
    ):
        await support_service.reply(
            session, ticket_id=ticket.id, admin_email="agent@drop.invalid", body="Refilled."
        )

    assert {push["to"] for push in session.pushes} == {TOKEN, STAFF_TOKEN}


@pytest.mark.asyncio
async def test_staff_tokens_are_not_gated_on_a_capability():
    """Support is not one of the four staff permissions. Asking for one would
    silence whoever holds none of them — which is most of them."""
    from services import support_service

    store = SimpleNamespace(id=uuid4(), push_token=None, preferences={})
    session = _Session(store)
    ticket = _ticket(requester_type="vendor")
    session.get = AsyncMock(side_effect=[ticket, store])

    spy = AsyncMock(return_value=[STAFF_TOKEN])
    with patch("services.vendor_staff_service.push_tokens_for_store", spy):
        await support_service.reply(
            session, ticket_id=ticket.id, admin_email="agent@drop.invalid", body="Done."
        )

    # Called positionally with no `permission` — every live staff member.
    assert spy.await_args.kwargs.get("permission") is None
    assert len(spy.await_args.args) == 2


@pytest.mark.asyncio
async def test_a_deleted_account_still_gets_its_row_and_does_not_raise():
    """The thread is evidence and survives the account. There is simply nobody
    left to push to."""
    from services import support_service

    session = _Session(None)
    ticket = _ticket()
    session.get = AsyncMock(side_effect=[ticket, None])

    await support_service.reply(
        session, ticket_id=ticket.id, admin_email="agent@drop.invalid", body="Closing this."
    )

    assert session.pushes == []
    assert len(session.added) == 1, "the notification row is the history"


@pytest.mark.asyncio
async def test_a_reply_to_a_closed_ticket_is_refused():
    from services import support_service

    session = _Session(None)
    ticket = _ticket(status="closed")
    session.get = AsyncMock(return_value=ticket)

    with pytest.raises(HTTPException) as caught:
        await support_service.reply(
            session, ticket_id=ticket.id, admin_email="agent@drop.invalid", body="Hello?"
        )
    assert caught.value.status_code == 409


# ── Whose turn it is ──────────────────────────────────────────────────────


def test_a_ticket_nobody_has_answered_is_waiting_on_us():
    from services.support_service import _awaiting_us

    assert _awaiting_us(_ticket(messages=[])) is True


def test_a_ticket_we_answered_last_is_not_waiting_on_us():
    from services.support_service import _awaiting_us

    ticket = _ticket(status="pending", messages=[{"author": "admin", "body": "Looking into it."}])
    assert _awaiting_us(ticket) is False


def test_a_ticket_they_answered_last_is_waiting_on_us_again():
    """The signal that did not exist. `pending` said "waiting on them" while the
    person had already replied."""
    from services.support_service import _awaiting_us

    ticket = _ticket(
        status="pending",
        messages=[
            {"author": "admin", "body": "Looking into it."},
            {"author": "customer", "body": "It still has not arrived."},
        ],
    )
    assert _awaiting_us(ticket) is True


def test_an_internal_note_does_not_count_as_answering_them():
    """A colleague writing "checking the GPS" is not a reply to the customer,
    and counting it as one marks a ticket handled while they still wait."""
    from services.support_service import _awaiting_us

    ticket = _ticket(
        status="open",
        messages=[
            {"author": "customer", "body": "Any news?"},
            {"author": "admin", "body": "Checking the trail.", "internal": True},
        ],
    )
    assert _awaiting_us(ticket) is True


def test_a_finished_ticket_is_waiting_on_nobody():
    from services.support_service import _awaiting_us

    for status in ("resolved", "closed"):
        assert _awaiting_us(_ticket(status=status, messages=[])) is False


def test_the_queue_reports_whose_turn_it_is():
    """`awaiting_us` has to reach the console or the fix is invisible."""
    source = _code_only(BACKEND / "services" / "support_service.py")
    # Unquoted needles: `ast.unparse` rewrites double quotes to single ones, so
    # searching for the literal as written in the source never matches.
    assert "awaiting_us" in source
    assert "_awaiting_us" in source


# ── Priority, which nothing could write ───────────────────────────────────


@pytest.mark.asyncio
async def test_priority_can_be_set():
    from services import support_service

    session = _Session(None)
    ticket = _ticket()
    session.get = AsyncMock(return_value=ticket)

    await support_service.set_priority(
        session, ticket_id=ticket.id, priority="urgent", admin_email="agent@drop.invalid"
    )
    assert ticket.priority == "urgent"


@pytest.mark.asyncio
async def test_priority_can_be_lowered_again():
    """De-escalation must be as easy as escalation, or the queue ratchets up
    until the field means nothing."""
    from services import support_service

    session = _Session(None)
    ticket = _ticket()
    ticket.priority = "urgent"
    session.get = AsyncMock(return_value=ticket)

    await support_service.set_priority(
        session, ticket_id=ticket.id, priority="low", admin_email="agent@drop.invalid"
    )
    assert ticket.priority == "low"


@pytest.mark.asyncio
async def test_an_unknown_priority_is_refused():
    from services import support_service

    session = _Session(None)
    ticket = _ticket()
    session.get = AsyncMock(return_value=ticket)

    with pytest.raises(HTTPException) as caught:
        await support_service.set_priority(
            session, ticket_id=ticket.id, priority="catastrophic", admin_email="a@b.c"
        )
    assert caught.value.status_code == 400


@pytest.mark.asyncio
async def test_setting_priority_on_a_missing_ticket_is_a_404():
    from services import support_service

    session = _Session(None)
    session.get = AsyncMock(return_value=None)

    with pytest.raises(HTTPException) as caught:
        await support_service.set_priority(
            session, ticket_id=uuid4(), priority="high", admin_email="a@b.c"
        )
    assert caught.value.status_code == 404


@pytest_asyncio.fixture
async def console(monkeypatch):
    """The real app and the real gate, so a capability test exercises
    `require_admin` rather than an override standing in for it."""
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
        last_seen_at=None,
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

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client,
            db=db,
            grant=lambda *permissions: setattr(admin, "permissions", list(permissions)),
        )

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_escalating_needs_support_respond_not_merely_support_read(console):
    """Reading the queue and changing somebody else's workload are different
    acts. `support.read` alone must not reorder the queue."""
    console.grant("support.read")

    response = await console.client.post(
        f"/api/admin/support/tickets/{uuid4()}/priority", json={"priority": "urgent"}
    )

    assert response.status_code == 403
    detail = response.json()["detail"]
    assert detail["type"] == "permission_required"
    assert detail["permission"] == "support.respond"


@pytest.mark.asyncio
async def test_an_analyst_cannot_reach_the_support_queue_at_all(console):
    """The analyst preset answers business questions and identifies nobody. A
    ticket is one person writing to another."""
    console.grant("analytics.read", "orders.read")

    for path in ("/api/admin/support/tickets", "/api/admin/support/meta"):
        response = await console.client.get(path)
        assert response.status_code == 403, path
        assert response.json()["detail"]["permission"] == "support.read"


@pytest.mark.asyncio
async def test_the_priority_endpoint_refuses_a_value_outside_the_set(console):
    """Rejected by the schema before it reaches a ticket lookup — an unknown
    priority is not a 404 about a ticket that may well exist."""
    console.grant("support.respond")

    response = await console.client.post(
        f"/api/admin/support/tickets/{uuid4()}/priority", json={"priority": "catastrophic"}
    )
    assert response.status_code == 422


def test_every_support_endpoint_is_gated_and_write_is_separated_from_read():
    """Walks the router rather than trusting a decorator read once by eye.

    Read and write are always separate capabilities on this platform; a new
    endpoint that quietly accepts `support.read` for a mutation would pass every
    other test in this file.
    """
    tree = ast.parse((BACKEND / "routes" / "admin_support_routes.py").read_text())

    gates: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        methods = {
            decorator.func.attr
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr in {"get", "post", "patch", "delete"}
        }
        if not methods:
            continue
        required = {
            argument.id
            for argument in ast.walk(node.args)
            if isinstance(argument, ast.Name) and argument.id.startswith("PERM_")
        }
        assert required, f"{node.name} has no require_admin gate"
        gates[node.name] = required

        if methods & {"post", "patch", "delete"}:
            assert "PERM_SUPPORT_READ" not in required, (
                f"{node.name} mutates but is gated on a read capability"
            )

    assert "set_ticket_priority" in gates
    assert gates["set_ticket_priority"] == {"PERM_SUPPORT_RESPOND"}


def test_escalation_is_audited():
    """Moving one ticket up an oldest-first queue moves every other one down.
    That carries a name."""
    source = _code_only(BACKEND / "routes" / "admin_support_routes.py")
    assert "support.priority" in source
    assert "set_priority" in source


# ── Structural: the rules that must not quietly regress ───────────────────


def test_no_action_url_on_the_platform_points_at_the_console():
    """Every `action_url` is read by an app, so every one has to be an app route.

    Searched across the whole backend rather than only the support service: this
    was one line, and the next one will be somewhere else.
    """
    offenders = []
    for path in list((BACKEND / "services").rglob("*.py")) + list(
        (BACKEND / "routes").rglob("*.py")
    ) + list((BACKEND / "jobs").rglob("*.py")):
        source = _code_only(path)
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.keyword) or node.arg != "action_url":
                continue
            value = node.value
            literal = None
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                literal = value.value
            elif isinstance(value, ast.JoinedStr):
                first = value.values[0] if value.values else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    literal = first.value
            if literal and literal.startswith("/") and not literal.startswith("/(screens)"):
                offenders.append(f"{path.name}: {literal}")

    assert not offenders, (
        "these are console paths, not app routes — the apps cannot navigate to them: "
        + ", ".join(offenders)
    )


def test_a_reply_always_fans_out_through_one_place():
    """`reply` must not grow a second, partial notification path beside
    `_notify_requester` — that is how the email got sent and the push did not."""
    tree = ast.parse((BACKEND / "services" / "support_service.py").read_text())
    reply = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "reply"
    )
    called = {
        node.func.id
        for node in ast.walk(reply)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_notify_requester" in called
    assert "create_notification" not in called, "notify through the one helper"


def test_support_uses_the_pre_commit_push_path():
    """The route commits after `reply` returns. `dispatch_background` there
    would tell somebody about a reply that could still roll back."""
    source = _code_only(BACKEND / "services" / "support_service.py")
    assert "queue_push" in source
    assert "dispatch_background" not in source
    assert "asyncio.create_task" not in source


def test_a_follow_up_reopens_a_pending_ticket():
    """`pending` means waiting on them. The moment they answer it is ours, and
    the nav badge counts only `open` — so leaving it pending told nobody."""
    source = _code_only(BACKEND / "routes" / "support_routes.py")
    # Single quotes: `ast.unparse` normalises them, so the needle has to be
    # written the way it comes back out, not the way it went in.
    assert "ticket.status in ('resolved', 'closed')" not in source, (
        "reopening only from resolved/closed leaves a pending ticket pending"
    )
    assert "ticket.status != 'open'" in source
