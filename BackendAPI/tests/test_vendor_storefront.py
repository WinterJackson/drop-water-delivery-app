"""What a store decides for itself, and whether the platform hears it.

Three controls belong to whoever is standing in the shop — *are we open*, *what
is the smallest order worth preparing*, and *will we take cash today*.

Two of them did not exist. The third is the one worth the docstring: `is_online`
existed, the vendor app shipped a swipe control wired to it, and **nothing on
the ordering path ever read it**. A vendor could swipe their store closed, watch
the toggle turn grey, and keep receiving orders. `shift_start`/`shift_end` were
in the same position — on every store since the first migration, rendered on the
console, enforced nowhere.

So the tests here come in two halves. The first is that each control bites. The
second, and the reason this file is long, is *structural*: that the decision has
exactly one implementation, that every path which creates an order passes
through it, and that every surface which tells somebody a shop is open is asking
the same function. A control that reaches the user but not the platform is worse
than no control, because the person operating it believes it worked.
"""
from __future__ import annotations

import ast
import pathlib
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from services import platform_config_service as config
from services import vendor_availability

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _code_only(path: pathlib.Path) -> str:
    """Source minus docstrings.

    Any "must not appear" assertion needs it: the note explaining a rule has to
    name the thing it forbids, and a docstring that says "never read
    `is_online` directly" would otherwise fail the test enforcing exactly that.
    """
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body = node.body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _store(**over):
    """An ordinary open shop. Every test changes exactly one thing about it."""
    base = dict(
        id=uuid4(),
        business_name="Mama Njeri Water",
        is_active=True,
        is_online=True,
        paused_until=None,
        pause_reason=None,
        accepts_cash=True,
        min_order_value=Decimal("0"),
        shift_start=time(7, 0),
        shift_end=time(19, 0),
        push_token=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.fixture(autouse=True)
def _shipped_defaults():
    """Evaluate against the shipped configuration, not whatever a prior test left.

    `_cache.values` is process-global and `evaluate` reads it synchronously, so
    without this a test that switches `vendor_hours_enforced` on would close
    every store in every test that ran after it.
    """
    previous = dict(config._cache.values)
    config._cache.values = {}
    yield config._cache.values
    config._cache.values = previous


# ── Each control, on its own ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "label,store,state",
    [
        ("open shop", _store(), "open"),
        ("switched offline", _store(is_online=False), "offline"),
        (
            "paused",
            _store(paused_until=datetime.now(timezone.utc) + timedelta(minutes=30)),
            "paused",
        ),
        ("suspended by an administrator", _store(is_active=False), "suspended"),
    ],
)
def test_each_reason_a_store_is_shut_is_named_separately(label, store, state):
    """"Closed" is four different situations with four different answers.

    A customer told "closed" cannot tell a shop on a 20-minute break from one
    the platform has suspended, and neither can whoever picks up the support
    call.
    """
    result = vendor_availability.evaluate(store)
    assert result.state == state
    assert result.accepting is (state == "open")
    if state != "open":
        assert result.reason, f"{label} was refused without saying why"


def test_a_suspension_outranks_the_stores_own_state():
    """A suspended store is not "closed until 07:00".

    Ordered by how permanent the reason is, so the customer is told the most
    useful thing rather than the first thing that matched — and so a suspended
    store cannot present itself as briefly paused.
    """
    store = _store(
        is_active=False,
        is_online=False,
        paused_until=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    assert vendor_availability.evaluate(store).state == "suspended"


def test_an_expired_pause_does_not_close_the_shop():
    """The expiry is the truth; the sweep only tidies up after it.

    Checked against the clock rather than a flag precisely so a worker that
    never ran cannot leave a store shut. If this inverted, one failed cron
    would silently close every shop that had ever tapped Pause.
    """
    store = _store(paused_until=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert vendor_availability.evaluate(store).accepting is True


def test_a_pause_says_when_it_ends_and_carries_the_stores_own_note():
    store = _store(
        paused_until=datetime.now(timezone.utc) + timedelta(minutes=30),
        pause_reason="Restocking",
    )
    result = vendor_availability.evaluate(store)
    assert "Paused until" in result.reason
    assert "Restocking" in result.reason
    assert result.reopens_at is not None


def test_a_naive_pause_timestamp_does_not_take_checkout_down():
    """Comparing naive to aware raises rather than answering wrongly.

    A `TypeError` here would be a 500 on the customer's checkout, caused by a
    store having once tapped Pause. Naive values are read as UTC.
    """
    store = _store(paused_until=datetime.utcnow() + timedelta(minutes=30))
    assert vendor_availability.evaluate(store).state == "paused"


def test_an_unreadable_pause_or_minimum_fails_open():
    """A store's own convenience control must not stop the platform selling.

    Both fail to the permissive value — no pause, no minimum — which is also
    each column's default. The alternative is a 500 at checkout over an
    optional courtesy a shop set for itself.
    """
    store = _store(paused_until="not a date", min_order_value="not a number")
    result = vendor_availability.evaluate(store)
    assert result.accepting is True
    assert result.min_order_value == Decimal("0")


# ── Opening hours ─────────────────────────────────────────────────────────


def test_opening_hours_are_not_enforced_by_default(_shipped_defaults):
    """Off by default, deliberately.

    Switching this on retrospectively closes every store whose hours were never
    real — and every store on the platform carries the 07:00–19:00 default it
    was created with, whether or not anybody looked at it.
    """
    assert config.DEFAULTS["vendor_hours_enforced"] is False

    at_three_am = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)  # 03:00 EAT
    assert vendor_availability.evaluate(_store(), moment=at_three_am).accepting is True


def test_opening_hours_close_the_shop_once_switched_on(_shipped_defaults):
    _shipped_defaults["vendor_hours_enforced"] = True
    at_three_am = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)  # 03:00 EAT

    result = vendor_availability.evaluate(_store(), moment=at_three_am)
    assert result.state == "closed_hours"
    assert "07:00" in result.reason


def test_hours_are_read_in_east_africa_time(_shipped_defaults):
    """A container's clock is UTC, three hours behind Nairobi.

    Comparing a shopkeeper's `08:00` against UTC would shut every store on the
    platform for its first three trading hours, every day.
    """
    _shipped_defaults["vendor_hours_enforced"] = True
    # 05:30 UTC is 08:30 EAT — inside a 07:00–19:00 shift, outside it in UTC.
    inside = datetime(2026, 8, 10, 5, 30, tzinfo=timezone.utc)
    assert vendor_availability.evaluate(_store(), moment=inside).accepting is True


def test_an_overnight_shift_is_a_union_rather_than_a_range(_shipped_defaults):
    """22:00–06:00 is a real thing a shop by a matatu stage does.

    `start <= now < end` reads it as *closed all day*, which is the opposite of
    what the vendor entered.
    """
    _shipped_defaults["vendor_hours_enforced"] = True
    store = _store(shift_start=time(22, 0), shift_end=time(6, 0))

    at_midnight = datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc)  # 00:00 EAT
    at_noon = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)  # 12:00 EAT

    assert vendor_availability.evaluate(store, moment=at_midnight).accepting is True
    assert vendor_availability.evaluate(store, moment=at_noon).accepting is False


@pytest.mark.parametrize(
    "label,store",
    [
        ("never set", _store(shift_start=None, shift_end=None)),
        ("equal endpoints", _store(shift_start=time(0, 0), shift_end=time(0, 0))),
    ],
)
def test_hours_that_were_never_entered_never_close_a_shop(_shipped_defaults, label, store):
    """This gate closes shops, so it must only act on hours somebody set.

    Equal endpoints are how "always open" arrives from a form with two untouched
    fields; absent ones are a store that never opened the screen. Refusing on
    either would be the opposite reading of both.
    """
    _shipped_defaults["vendor_hours_enforced"] = True
    at_three_am = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
    assert vendor_availability.evaluate(store, moment=at_three_am).accepting is True


# ── The minimum order ─────────────────────────────────────────────────────


def test_a_basket_under_the_stores_minimum_is_refused_by_the_shortfall():
    """"Add KSH 120 more" is something a customer can do; "too small" is not."""
    store = _store(min_order_value=Decimal("300"))
    with pytest.raises(HTTPException) as exc:
        vendor_availability.assert_meets_minimum(store, Decimal("180"))

    assert exc.value.status_code == 400
    assert "120" in exc.value.detail
    assert "Mama Njeri Water" in exc.value.detail


def test_the_minimum_is_measured_on_the_goods_not_the_total():
    """A minimum counting delivery would move with the customer's address.

    The same basket would clear a store's minimum from one address and fail
    from another, and a customer could meet a shop's minimum by living further
    away — which is not a thing the shop asked for.
    """
    store = _store(min_order_value=Decimal("300"))
    # Goods exactly at the minimum: passes, whatever the delivery fee is.
    vendor_availability.assert_meets_minimum(store, Decimal("300"))


def test_no_minimum_refuses_nothing():
    vendor_availability.assert_meets_minimum(_store(min_order_value=Decimal("0")), Decimal("1"))


# ── The vendor's own writes, and the platform's bounds ────────────────────


def _writable_session(store):
    session = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_a_minimum_above_the_platform_ceiling_is_refused(_shipped_defaults):
    """Self-service with no bound is not self-service.

    A store setting KSH 50,000 has delisted itself while still appearing open
    and still ranking in search — the customer taps through, fills a basket and
    is refused at the last step, which reads as the platform being broken
    rather than the shop being shut.
    """
    store = _store()
    ceiling = config.DEFAULTS["vendor_max_min_order_value"]

    with pytest.raises(HTTPException) as exc:
        await vendor_availability.set_controls(
            _writable_session(store), store, min_order_value=ceiling + 1
        )

    assert exc.value.status_code == 400
    assert f"{ceiling:,.0f}" in exc.value.detail
    assert store.min_order_value == Decimal("0"), "the refused value must not be written"


@pytest.mark.asyncio
async def test_a_pause_longer_than_the_ceiling_is_refused_and_names_the_alternative(
    _shipped_defaults,
):
    """Beyond about a trading day it is not a pause, it is a closure.

    And a closure should be the explicit offline switch, so it is visible as one
    on the console rather than looking like a shop about to reopen.
    """
    store = _store()
    hours = config.DEFAULTS["vendor_max_pause_hours"]

    with pytest.raises(HTTPException) as exc:
        await vendor_availability.set_controls(
            _writable_session(store), store, pause_minutes=hours * 60 + 1
        )

    assert "offline" in exc.value.detail
    assert store.paused_until is None


@pytest.mark.asyncio
async def test_a_store_may_decline_cash_and_the_platform_may_take_that_back(
    _shipped_defaults,
):
    """A shop with no float — or one that has just been robbed — must be able
    to say no, and the platform must be able to say no to *that*."""
    store = _store()
    session = _writable_session(store)

    await vendor_availability.set_controls(session, store, accepts_cash=False)
    assert store.accepts_cash is False
    assert vendor_availability.evaluate(store).accepts_cash is False

    _shipped_defaults["vendor_may_decline_cash"] = False
    with pytest.raises(HTTPException) as exc:
        await vendor_availability.set_controls(session, store, accepts_cash=False)
    assert exc.value.status_code == 403


def test_a_stored_decline_stops_being_honoured_when_the_platform_withdraws_it(
    _shipped_defaults,
):
    """Otherwise a store stays opted out of an offer the platform has decided
    is not optional, with nothing on any screen explaining why."""
    store = _store(accepts_cash=False)
    assert vendor_availability.evaluate(store).accepts_cash is False

    _shipped_defaults["vendor_may_decline_cash"] = False
    assert vendor_availability.evaluate(store).accepts_cash is True


@pytest.mark.asyncio
async def test_only_the_fields_supplied_are_written(_shipped_defaults):
    """A pause screen must not clear the minimum somebody set on another one.

    The shape that made `preferred_payment_method` overwrite a vendor's payout
    account every time an unrelated screen saved.
    """
    store = _store(min_order_value=Decimal("250"), accepts_cash=False)
    await vendor_availability.set_controls(
        _writable_session(store), store, pause_minutes=30
    )

    assert store.min_order_value == Decimal("250")
    assert store.accepts_cash is False
    assert store.paused_until is not None


@pytest.mark.asyncio
async def test_resuming_clears_the_pause_and_its_note(_shipped_defaults):
    store = _store(
        paused_until=datetime.now(timezone.utc) + timedelta(hours=1),
        pause_reason="Restocking",
    )
    await vendor_availability.set_controls(_writable_session(store), store, resume=True)

    assert store.paused_until is None
    assert store.pause_reason is None


# ── Structural: one implementation, reached everywhere ────────────────────


def test_only_vendor_availability_decides_whether_a_store_is_accepting():
    """No second implementation anywhere in `services/` or `routes/`.

    The second one is always the one that forgets a suspension, or the
    platform-wide cash override, and it is reached from the surface nobody
    tested. `is_online` may still be *written* and *displayed* — what may not
    happen is somebody deciding from it.
    """
    offenders = []
    for directory in ("services", "routes"):
        for path in sorted((BACKEND / directory).glob("*.py")):
            if path.name in ("vendor_availability.py", "vendor_management_service.py"):
                continue
            tree = ast.parse(_code_only(path))
            for node in ast.walk(tree):
                # `x.is_online is False` / `not x.is_online` / `if x.paused_until`
                # are all somebody re-deriving the answer.
                if isinstance(node, ast.Attribute) and node.attr == "paused_until":
                    offenders.append(f"{path.name}: reads paused_until")
    assert offenders == [], (
        "these modules derive a store's trading state themselves instead of "
        f"calling vendor_availability: {offenders}"
    )


@pytest.mark.parametrize(
    "module,function,call",
    [
        # Checkout, before the STK push and before an order exists.
        ("routes/cart_routes.py", "payment_request", "assert_store_accepting"),
        # The locked re-check. A store can pause between the quote the customer
        # is looking at and the tap that charges them, and everything after this
        # point is a refund.
        ("services/order_service.py", "create_order", "assert_store_accepting"),
    ],
)
def test_every_path_that_creates_an_order_asks_whether_the_shop_is_open(
    module, function, call
):
    tree = ast.parse((BACKEND / module).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == function:
            assert call in ast.unparse(node), (
                f"{module}::{function} creates an order without calling {call} — "
                "a paid order at a closed store is a refund, a waiting customer "
                "and a support ticket"
            )
            return
    pytest.fail(f"{function} not found in {module}")


def test_the_minimum_is_enforced_inside_validate_quote():
    """One call site rather than three.

    `validate_quote` runs at the quote, again before the STK push, and a third
    time under `create_order`'s row lock. Putting the store's minimum there
    reaches every checkout path that already exists *and* every one somebody
    adds later.
    """
    source = _code_only(BACKEND / "services/pricing_service.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "validate_quote":
            body = ast.unparse(node)
            assert "assert_meets_minimum" in body
            assert "product_subtotal" in body, (
                "the store's minimum must be measured on the goods, not a total "
                "that moves with the customer's address"
            )
            return
    pytest.fail("validate_quote not found")


def test_the_cash_decision_still_lives_in_cod_policy():
    """A store declining cash is a cash decision, and `cod_policy` owns those.

    Reading `accepts_cash` from a second place would mean a decline the
    platform had withdrawn kept being honoured on whichever path forgot.
    """
    source = _code_only(BACKEND / "services/cod_policy.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "assert_customer_may_pay_cash"
        ):
            body = ast.unparse(node)
            assert "vendor_availability" in body
            assert "cash_reason" in body
            return
    pytest.fail("assert_customer_may_pay_cash not found")


@pytest.mark.parametrize(
    "function",
    [
        "get_all_vendors",
        "get_nearby_vendors",
        "get_top_rated_vendors",
        "get_vendors_by_type_service",
        "get_vendor_by_id_service",
        "get_top_brands_service",
        "get_vendor_directory",
    ],
)
def test_every_customer_facing_vendor_read_carries_the_store_state(function):
    """Seven functions, and the one that gets missed is the bug.

    The same discipline `discoverable_vendor()` exists for: a store shown as
    open in the directory and closed on its own page is what people screenshot.
    """
    tree = ast.parse((BACKEND / "services/vendor_service.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function:
            assert "_annotated" in ast.unparse(node), (
                f"{function} returns stores to a customer without saying whether "
                "they are open"
            )
            return
    pytest.fail(f"{function} not found in vendor_service")


@pytest.mark.asyncio
async def test_discovery_marks_closed_stores_rather_than_hiding_them(monkeypatch):
    """`annotate` stamps; it never selects.

    Hiding a closed store tells the customer looking for the shop they always
    use that it has left the platform, and costs a shop that paused for twenty
    minutes its place in everybody's list rather than twenty minutes of orders.

    Asserted on behaviour rather than on the source: a version that returned a
    filtered list, or that skipped stamping the closed ones, both read fine.
    """
    monkeypatch.setattr(config, "ensure_fresh", AsyncMock())

    open_shop = _store(business_name="Open")
    shut_shop = _store(
        business_name="Shut",
        paused_until=datetime.now(timezone.utc) + timedelta(minutes=30),
    )
    rows = [open_shop, shut_shop]

    await vendor_availability.annotate(AsyncMock(), rows)

    assert len(rows) == 2, "annotate must not remove closed stores from a listing"
    assert open_shop.is_accepting_orders is True
    assert shut_shop.is_accepting_orders is False
    assert shut_shop.store_state == "paused"
    assert shut_shop.store_reason, "a closed store must carry the reason it is closed"
    # Every row gets stamped, including the open one — a card that renders
    # `store_state` cannot distinguish "open" from "nobody set this".
    assert open_shop.store_state == "open"


@pytest.mark.asyncio
async def test_annotating_an_empty_or_null_listing_does_nothing(monkeypatch):
    """`get_vendor_by_id_service` passes `[]` when the store was not found."""
    ensure = AsyncMock()
    monkeypatch.setattr(config, "ensure_fresh", ensure)

    await vendor_availability.annotate(AsyncMock(), [])
    await vendor_availability.annotate(AsyncMock(), None)

    ensure.assert_not_awaited()


#: Every customer surface that renders a store, and must therefore say whether
#: it is open. Not a list anybody would guess: the store page was done first and
#: the five *listings* were not, which is precisely the "the card says open and
#: the page says paused" defect the design set out to avoid — committed by the
#: person who wrote that comment.
#:
#: The server already stamps all of these (`vendor_service._annotated`,
#: `vendor_favorites_service`), so the data was there and unread. Add a surface,
#: add it here.
CUSTOMER_STORE_SURFACES = (
    "app/(screens)/vendor/[id].tsx",          # the store page
    "app/(screens)/VendorDirectory.tsx",      # browse all
    "app/(screens)/Search.tsx",               # searching by name
    "app/(screens)/repeat-order.tsx",         # a whole basket in one tap
    "components/common/HorizontalList.tsx",   # "near you" on the home screen
    "components/common/FullHorizontalList.tsx",
    "components/common/FavouritesList.tsx",   # the shop they already chose
)


@pytest.mark.parametrize("surface", CUSTOMER_STORE_SURFACES)
def test_every_customer_surface_that_shows_a_store_says_whether_it_is_open(surface):
    """A listing that omits this sends the customer to a shop that is shut.

    Worse on the surfaces that exist *because* the customer already knows which
    shop they want — search, favourites, reorder. There the closed state is the
    only thing on the card that matters.
    """
    path = BACKEND.parent / "drop-customer-app" / surface
    source = path.read_text()

    assert "StoreClosedNotice" in source, (
        f"{surface} renders stores without ever saying whether they are taking "
        "orders — the server stamps every one of these reads with the answer"
    )
    assert "<StoreClosedNotice" in source, (
        f"{surface} imports StoreClosedNotice but never renders it"
    )


def test_the_apps_never_compose_their_own_closed_message():
    """The sentence is the server's, once.

    It carries the store's own note and its reopening time in the shop's local
    hours; a message assembled on a client goes stale the moment a setting or
    the store's text moves — the mistake both apps made with the withdrawal
    fee.
    """
    customer = BACKEND.parent / "drop-customer-app"
    notice = (customer / "components/common/StoreClosedNotice.tsx").read_text()
    assert "store_reason" in notice
    for invented in ("Closed until", "Opens at", "Back at"):
        assert invented not in notice, (
            f"StoreClosedNotice composes {invented!r} itself instead of rendering "
            "the server's sentence"
        )


def test_the_vendor_app_takes_every_bound_from_the_server():
    """No pause duration and no maximum minimum as a literal in the app.

    An app offering "4 hours" against a server that caps at two is a button
    that always fails, and a maximum stated in the app is a number that goes
    stale when an administrator moves the setting.
    """
    vendor_app = BACKEND.parent / "drop-vendor-app"
    card = (vendor_app / "components/dashboard/StorePauseCard.tsx").read_text()
    assert "limits.pause_presets_minutes" in card
    assert "[15, 30" not in card and "[30, 60" not in card, (
        "the pause durations are hardcoded in the app instead of arriving from "
        "the server already filtered against the platform's ceiling"
    )

    terms = (vendor_app / "app/(screens)/business/StoreTerms.tsx").read_text()
    assert "limits.max_min_order_value" in terms
    assert "limits.may_decline_cash" in terms


def test_the_pause_is_reachable_by_staff_and_the_terms_are_not():
    """The split is the point.

    Whoever has just run out of 20 L bottles at 11am is standing behind the
    counter; a pause they cannot apply until they reach the owner arrives after
    the orders do. Whether the shop takes cash at all is a term of trade and
    sits with the payout account.
    """
    source = ast.parse((BACKEND / "routes/vendor_management_routes.py").read_text())
    gates = {}
    for node in ast.walk(source):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and dec.args and isinstance(dec.args[0], ast.Constant):
                path = dec.args[0].value
                if isinstance(path, str) and path.startswith("/storefront"):
                    gates[(dec.func.attr.upper(), path)] = ast.unparse(node.args)

    assert "get_owned_store" in gates[("PUT", "/storefront")]
    assert "manage_orders" in gates[("POST", "/storefront/pause")]
    assert "manage_orders" in gates[("POST", "/storefront/resume")]
    assert "get_active_store" in gates[("GET", "/storefront")]


def test_the_storefront_routes_take_no_bare_request_parameter():
    """FastAPI turns an un-annotated parameter into a *required query field*.

    The bottle-return endpoints shipped that way and the whole feature was
    unreachable — every call answered 422 for a query string nobody sends.
    """
    tree = ast.parse((BACKEND / "routes/vendor_management_routes.py").read_text())
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if not node.name.startswith("vendor_") or "storefront" not in node.name.lower():
            continue
        for arg in node.args.args + node.args.kwonlyargs:
            assert arg.annotation is not None, (
                f"{node.name}({arg.arg}) has no type annotation, so FastAPI will "
                "demand it as a query parameter and the endpoint is unreachable"
            )


# ── The resume sweep ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_sweep_reopens_expired_pauses_and_says_so(monkeypatch):
    """The state is already correct without the sweep — this is about the vendor.

    A shop that paused for twenty minutes and heard nothing has no way to know
    it worked, and the usual response to that is to pause again.
    """
    store = _store(paused_until=datetime.now(timezone.utc) - timedelta(minutes=1))

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [store]
    session.execute = AsyncMock(return_value=result)

    told = {}

    async def _fake_tell(_session, vendor, *, title, message):
        told["title"] = title

    monkeypatch.setattr(vendor_availability, "_tell_store", _fake_tell)

    outcome = await vendor_availability.resume_expired_pauses(session)

    assert outcome == {"stores_resumed": 1}
    assert store.paused_until is None
    assert "open again" in told["title"]


@pytest.mark.asyncio
async def test_a_store_that_went_offline_during_its_pause_is_not_told_it_is_open(
    monkeypatch,
):
    """It is not. Saying so would send a vendor to a shop that is still shut."""
    store = _store(
        is_online=False,
        paused_until=datetime.now(timezone.utc) - timedelta(minutes=1),
    )

    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [store]
    session.execute = AsyncMock(return_value=result)

    told = []
    monkeypatch.setattr(
        vendor_availability,
        "_tell_store",
        AsyncMock(side_effect=lambda *a, **k: told.append(k)),
    )

    await vendor_availability.resume_expired_pauses(session)
    assert told == []


def test_the_sweep_claims_rows_and_commits_per_store():
    """The platform's rule for every sweep.

    `SKIP LOCKED` so two workers cannot fight over the same shop, and a commit
    per row so one bad store cannot discard the batch.
    """
    source = _code_only(BACKEND / "services/vendor_availability.py")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "resume_expired_pauses":
            body = ast.unparse(node)
            assert "skip_locked=True" in body
            assert "rollback" in body
            return
    pytest.fail("resume_expired_pauses not found")


def test_the_resume_sweep_has_a_schedule():
    """A sweep nobody calls is a function, not a job."""
    from routes import cron_routes

    assert "resume-paused-stores" in cron_routes._job_table()


# ── The settings that bound all of this ───────────────────────────────────


def test_every_bound_on_a_vendors_control_is_a_settings_row():
    """A figure that belongs to the business and sits in the source is a defect."""
    keys = {spec.key for spec in config.SPECS if spec.group == "storefront"}
    assert keys == {
        "vendor_max_min_order_value",
        "vendor_max_pause_hours",
        "vendor_may_decline_cash",
        "vendor_hours_enforced",
    }
    assert "storefront" in config.GROUP_LABELS


def test_the_pause_presets_all_fit_inside_the_default_ceiling():
    """The app is offered these; every one must be acceptable to the server.

    If a preset outgrew the ceiling the app would render a button that returns
    400 — the class of defect this whole file exists to catch.
    """
    ceiling_minutes = config.DEFAULTS["vendor_max_pause_hours"] * 60
    assert max(vendor_availability.PAUSE_PRESET_MINUTES) <= ceiling_minutes


def test_vendors_still_cannot_set_their_own_delivery_fee_or_radius():
    """Deliberately absent, and worth a test because it looks like an omission.

    The rider is paid out of the delivery fee, so a store undercutting to win
    orders would be spending the rider's money; and the retail radius protects
    water temperature and rider time. Both stay on the console.
    """
    body = ast.parse((BACKEND / "routes/vendor_management_routes.py").read_text())
    for node in ast.walk(body):
        if isinstance(node, ast.ClassDef) and node.name == "StorefrontTermsRequest":
            fields = {
                target.target.id
                for target in node.body
                if isinstance(target, ast.AnnAssign) and isinstance(target.target, ast.Name)
            }
            assert fields == {"accepts_cash", "min_order_value"}
            return
    pytest.fail("StorefrontTermsRequest not found")
