"""
Every gated action in the vendor app is offered only to someone who holds it.

`require_permission("manage_orders")` and friends are the *control*; this is the
*courtesy*, and the vendor guide is explicit that both are required — "offering
an action that always fails is bad UX". The two had drifted apart:

* `OrderDetail/[id].tsx`, where the order buttons actually live, checked nothing.
  Accept, Reject, Start Prep, Mark as Ready, Cancel and Assign Fleet were all
  offered to a staff member holding only `manage_bottles`, and every one of the
  six 403'd at the tap. `Orders.tsx` had the check; the screen with the buttons
  did not.
* `AddProduct.tsx` and `EditProduct/[id].tsx` rendered the whole form to anyone
  and refused at submit — after a name, a price, a stock count and an image.
* `QuickActions.tsx` offered "Add Item" (`manage_products`) and "Riders"
  (`get_owned_store`) to everybody from the dashboard.

Structural, in the style of `test_vendor_api_client`: the defect is "somebody
added another screen and forgot", which no unit test catches.
"""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
VENDOR = REPO / "drop-vendor-app"

pytestmark = pytest.mark.skipif(
    not VENDOR.exists(), reason="vendor app not in this checkout"
)


def _strip_comments(source: str) -> str:
    """TypeScript source with `//` and block comments removed.

    Every assertion below that searches for something which must *not* appear
    needs this: the comment recording why it was removed inevitably names it.
    """
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", source, flags=re.M)


def _read(relative: str) -> str:
    path = VENDOR / relative
    assert path.exists(), f"{relative} has moved — update this test with it"
    return path.read_text()


#: Screen → the capability its writes need on the server. Taken from
#: `routes/vendor_management_routes.py`, where each is a `require_permission`.
GATED_SCREENS = {
    "app/(screens)/OrderDetail/[id].tsx": "manageOrders",
    "app/(screens)/Orders.tsx": "manageOrders",
    "app/(screens)/AddProduct.tsx": "manageProducts",
    "app/(screens)/EditProduct/[id].tsx": "manageProducts",
    "app/(screens)/BottleReconciliation.tsx": "manageBottles",
}


@pytest.mark.parametrize("screen,capability", sorted(GATED_SCREENS.items()))
def test_a_screen_that_writes_checks_the_capability_first(screen, capability):
    source = _read(screen)
    assert f"PERMISSIONS.{capability}" in source, (
        f"{screen} performs writes the server gates on {capability} and never asks "
        "whether this caller holds it"
    )


#: Every action on the order detail screen that the server refuses without
#: `manage_orders`. Each must be behind the flag, not merely on a screen that
#: computes it.
ORDER_ACTIONS = (
    'updateStatus("rejected")',
    'updateStatus("accepted")',
    'updateStatus("preparing")',
    'updateStatus("ready")',
)


def test_every_order_action_sits_behind_the_manage_orders_flag():
    """The flag existing is not the same as the buttons using it.

    Checked by walking the rendered blocks rather than trusting one `useCan`
    call near the top — that is exactly what `Orders.tsx` had while this screen
    handed out all six actions regardless.
    """
    source = _read("app/(screens)/OrderDetail/[id].tsx")

    for action in ORDER_ACTIONS:
        assert action in source, f"{action} has moved — update this test with it"

    # Only blocks that actually *mutate* need the flag. Several blocks are keyed
    # on the same status and are pure display — the float warning, the rider's
    # mismatch report, the Track Delivery link — and gating those would hide
    # information from a staff member who is entitled to see it while changing
    # nothing about what they can do.
    blocks = re.split(r"\n(?=\s*\{(?:canManageOrders && )?[(]?order\.order_status ===)", source)

    ungated = []
    for block in blocks:
        header = block.strip().split("&& (")[0]
        if "order.order_status ===" not in header:
            continue
        mutates = any(action in block for action in ORDER_ACTIONS) or "cancelOrder()" in block
        if mutates and "canManageOrders" not in header:
            ungated.append(" ".join(header.split())[:90])

    assert not ungated, (
        "these order-action blocks mutate without checking manage_orders: "
        + "; ".join(ungated)
    )


def test_the_cancel_button_is_gated_too():
    """Cancelling is `require_permission("manage_orders")` like the rest, and it
    is the one action here that cannot be undone."""
    source = _read("app/(screens)/OrderDetail/[id].tsx")
    assert re.search(
        r"canManageOrders &&\s*\(order\.order_status === \"accepted\"", source
    ), "the cancel block no longer checks manage_orders"


def test_the_product_forms_refuse_at_the_door():
    """Not at submit. Filling in a form and *then* being told you were never
    allowed to is the worst version of this."""
    for screen in ("app/(screens)/AddProduct.tsx", "app/(screens)/EditProduct/[id].tsx"):
        source = _read(screen)
        assert "CapabilityGate" in source, f"{screen} still refuses only at submit"
        assert "PERMISSIONS.manageProducts" in source


def test_the_dashboard_shortcuts_are_filtered():
    """`QuickActions` is the busiest surface in the app. It offered "Add Item"
    to staff without `manage_products` and "Riders" to staff at all, and the
    second is owner-only on the server."""
    source = _read("components/dashboard/QuickActions.tsx")
    assert "PERMISSIONS.manageProducts" in source
    assert 'role !== "staff"' in source, "the owner-only Riders shortcut is unfiltered"


def test_the_capability_gate_does_not_refuse_on_missing_data():
    """Fails *open* while the profile loads, unlike the rider KYC wall which
    fails closed.

    The two are different on purpose: the KYC gate protects the platform from an
    unverified rider, so an errored status is not permission. This one only
    decides whether to show a form the server will refuse anyway — so refusing
    on absent data would lock out a legitimate owner on a slow connection while
    protecting nothing.
    """
    source = _read("components/common/CapabilityGate.tsx")
    assert "isLoading" in source and "permissions" in source
    assert re.search(
        r"if \(isLoading \|\| !profile\?\.permissions\) return", source
    ), "CapabilityGate no longer passes through while the profile is loading"


def test_the_wallet_summary_is_only_asked_for_by_someone_who_may_see_it():
    """`GET /wallet-summary` is `require_permission("view_finances")`, so asking
    without it 403s on every open of the screen that asks."""
    for screen in (
        "app/(screens)/WalletScreen.tsx",
        "app/(screens)/OrderDetail/[id].tsx",
    ):
        source = _read(screen)
        if "useWalletSummary" not in source:
            continue
        assert re.search(r"useWalletSummary\(\s*can", source), (
            f"{screen} asks for the wallet summary unconditionally"
        )


def test_no_screen_gates_a_capability_on_the_staff_role():
    """`role !== "staff"` is the old all-or-nothing model.

    It is still correct for the owner-only *screens* below — those are not
    capabilities — but using it in place of one is what let anyone handed the
    till also reprice the products.
    """
    owner_only = {
        "OwnerProfile.tsx",
        "StoreProfile.tsx",
        "PayoutSettings.tsx",
        "OperatingHours.tsx",
        "ManageStaff.tsx",
        "RiderManagement.tsx",
        # The terms this store trades on — whether it takes cash, and its
        # minimum order. `get_owned_store` on the server, and a screen-level
        # restriction rather than a capability for the same reason the payout
        # account is one: it is what the business *is*, not how today is going.
        # Pausing the shop is deliberately **not** here — it lives on the
        # dashboard behind `manage_orders`, because whoever has just run out of
        # 20 L bottles at 11am is standing behind the counter.
        "StoreTerms.tsx",
        # Navigation *to* the owner-only screens. Hiding a link to a screen that
        # would bounce you is the same decision as the screen bouncing you, not
        # a capability standing in for one.
        "Profile.tsx",
        "QuickActions.tsx",
        # The dashboard's open/closed swipe. `PUT /profile` is `get_owned_store`,
        # so a staff member swiping it got `owner_only` every time — a
        # full-width control on the busiest screen in the app that could not
        # work for the person most likely to reach for it. There is no
        # capability for "switch the shop off indefinitely"; it is owner-only
        # outright, which is why this is a role check rather than one standing
        # in for a capability. The timed pause beside it *is* a capability
        # (`manage_orders`) and is what a staff member uses instead.
        "index.tsx",
    }

    offenders = []
    for path in (VENDOR / "app").rglob("*.tsx"):
        if path.name in owner_only:
            continue
        source = path.read_text()
        if re.search(r'role\s*[!=]==\s*"staff"', source):
            offenders.append(str(path.relative_to(VENDOR)))

    assert not offenders, (
        "these gate on the staff role rather than on a capability: "
        + ", ".join(offenders)
    )


def test_the_dead_payout_routes_are_gone():
    """Only the M-Pesa B2C *callback* router is mounted under `/api/payouts`.

    `RequestPayout` and `GetPayouts` were declared in the app, unused, pointing
    at routes that would 404 — a trap for whoever wires up "payout history"
    next. Cashouts go through `/api/wallet/withdraw` and their history is the
    wallet ledger.
    """
    # Comments stripped first: the note explaining *why* these are absent has
    # to name them, and a naive search matches the explanation. The settlement,
    # remediation and support suites have all hit this same trap.
    source = _strip_comments(_read("API/routes/VendorApiRoutes.ts"))
    assert "/api/payouts/request" not in source
    assert re.search(r"^\s*GetPayouts:", source, re.M) is None

    main = (REPO / "BackendAPI" / "main.py").read_text()
    assert "payout_routes.callback_router" in main
    assert "payout_routes.router" not in main, (
        "the payout router is mounted again — the app's routes should come back too"
    )
