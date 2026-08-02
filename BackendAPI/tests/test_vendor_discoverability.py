"""A suspended or deleted store must vanish from the customer app.

Nine customer-facing queries selected vendors and **not one of them looked at
account state**. Account deletion sets `verification_status = "deleted"` and
anonymises the row, and that row kept appearing in search, in "near you" and in
the directory. Suspension, added for the admin console, would have fallen into
the same hole — which is why the predicate and the suspend action shipped
together rather than the button arriving first.

The structural test is the one that matters. The behavioural checks below prove
the predicate is right today; the structural check is what stops the tenth
query from being written without it.
"""
import ast
import pathlib

from sqlalchemy import select

from models.vendor_model import Vendor
from services.vendor_service import UNDISCOVERABLE_STATUSES, discoverable_vendor

BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: Functions that answer a *customer*. Admin and vendor-owner queries
#: deliberately see suspended stores — an administrator cannot reinstate a store
#: they can no longer find, and an owner must still reach their own dashboard to
#: read why they were suspended.
CUSTOMER_FACING = {
    "get_all_vendors",
    "get_nearby_vendors",
    "get_top_rated_vendors",
    "get_vendors_by_type_service",
    "get_vendor_by_id_service",
    "get_top_brands_service",
    "get_vendor_directory",
    "search_vendors_service",
    "search_service",
}


def _functions(path: pathlib.Path) -> dict[str, ast.AST]:
    tree = ast.parse(path.read_text())
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_every_customer_facing_vendor_query_filters_on_account_state():
    """The check that stops this regressing.

    A new discovery endpoint is exactly the kind of thing that gets added
    without remembering a predicate written months earlier, and the omission is
    invisible until a customer orders from a store that no longer exists.
    """
    found: dict[str, bool] = {}

    for module in ("vendor_service.py", "query_service.py"):
        for name, node in _functions(BACKEND / "services" / module).items():
            if name not in CUSTOMER_FACING:
                continue
            found[name] = any(
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id == "discoverable_vendor"
                for sub in ast.walk(node)
            )

    missing = sorted(name for name, gated in found.items() if not gated)
    assert missing == [], (
        "these customer-facing queries do not call discoverable_vendor(), so "
        f"they return suspended and deleted stores: {missing}"
    )

    # And the list itself has not drifted out of the codebase.
    absent = sorted(CUSTOMER_FACING - set(found))
    assert absent == [], f"CUSTOMER_FACING names functions that no longer exist: {absent}"


def test_product_search_joins_the_vendor_unconditionally():
    """It used to join only when sorting by distance.

    A search with no coordinates therefore had no vendor row to filter on and
    happily returned products belonging to deleted stores.
    """
    source = (BACKEND / "services" / "query_service.py").read_text()
    node = _functions(BACKEND / "services" / "query_service.py")["search_service"]

    joins = [
        sub for sub in ast.walk(node)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "join"
    ]
    assert joins, "search_service must join Vendor so account state can be applied"

    # The join must not sit inside the `if user_lat is not None` branch.
    conditional_joins = [
        sub for branch in ast.walk(node) if isinstance(branch, ast.If)
        for sub in ast.walk(branch)
        if isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Attribute)
        and sub.func.attr == "join"
    ]
    assert conditional_joins == [], (
        "the Vendor join is inside a conditional, so a search without "
        "coordinates skips the account-state filter"
    )
    assert "discoverable_vendor()" in source


def test_the_predicate_excludes_suspended_and_deleted_only():
    """Compiled and inspected rather than asserted by eye.

    The exact SQL matters: `is_active IS true` and a `verification_status NOT
    IN` list. An `!= 'deleted'` would silently drop every row where the status
    is NULL, which is most of them on a platform where nothing has been
    verified yet.
    """
    compiled = str(
        select(Vendor.id).where(discoverable_vendor()).compile(
            compile_kwargs={"literal_binds": True}
        )
    )
    assert "is_active" in compiled
    assert "verification_status" in compiled
    assert "NOT IN" in compiled.upper()
    assert "deleted" in compiled


def test_verification_status_is_not_used_to_gate_trading():
    """Every vendor on the platform is `pending`.

    Filtering discovery to `verified` would empty the customer app entirely.
    Whether unverified stores may trade is a business decision, and this test
    exists so that decision is made deliberately rather than arriving as a
    side effect of a bug fix.
    """
    assert "verified" not in UNDISCOVERABLE_STATUSES
    assert "pending" not in UNDISCOVERABLE_STATUSES


def test_a_direct_link_to_a_suspended_store_does_not_bypass_the_listings():
    """`get_vendor_by_id_service` backs the product and store detail pages.

    Without the predicate, suspension would only hide a store from customers
    who were not already looking for it — a bookmark, or a shared product link,
    would still open it.
    """
    node = _functions(BACKEND / "services" / "vendor_service.py")["get_vendor_by_id_service"]
    assert any(
        isinstance(sub, ast.Call)
        and isinstance(sub.func, ast.Name)
        and sub.func.id == "discoverable_vendor"
        for sub in ast.walk(node)
    )


def test_verification_gating_is_off_by_default_and_switchable():
    """The switch exists; the decision is the operator's.

    Every vendor is `pending`, so turning this on empties the customer app. It is
    therefore off unless explicitly enabled, and read **per call** rather than
    frozen at import — so it can be turned off again as fast as it was turned on.

    It used to be the `REQUIRE_VENDOR_VERIFICATION` environment variable, which
    meant reverting it needed a Render edit and a restart while the customer app
    showed an empty directory. It is a `Platform_Settings` row now, switched from
    the console and revertible in seconds.
    """
    from services import platform_config_service as config

    def compiled() -> str:
        return str(
            select(Vendor.id).where(discoverable_vendor()).compile(
                compile_kwargs={"literal_binds": True}
            )
        )

    assert config.DEFAULTS["require_vendor_verification"] is False
    assert "'verified'" not in compiled()

    with config.temporarily({"require_vendor_verification": True}):
        assert "'verified'" in compiled()

    assert "'verified'" not in compiled()


def test_the_gating_switch_is_no_longer_read_from_the_environment():
    """A leftover `os.getenv("REQUIRE_VENDOR_VERIFICATION")` anywhere would be a
    second switch — and the two would disagree the moment somebody used the
    console one."""
    offenders = []
    for directory in ("services", "routes", "dependencies"):
        for path in (BACKEND / directory).rglob("*.py"):
            if "REQUIRE_VENDOR_VERIFICATION" in path.read_text(errors="ignore"):
                offenders.append(f"{directory}/{path.name}")

    assert offenders == [], f"the gating switch is a platform setting now: {offenders}"


def test_rejecting_a_vendor_does_not_take_them_offline():
    """"We haven't confirmed your paperwork" and "you may not trade" are
    different statements. Conflating them would take a working business offline
    for a missing document — so verification writes `verification_status` and
    suspension writes `is_active`, and neither touches the other."""
    import ast

    source = (BACKEND / "routes" / "admin_people_routes.py").read_text()
    tree = ast.parse(source)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "review_vendor_verification"
    )
    assigned = {
        target.attr
        for node in ast.walk(func)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Attribute)
    }
    assert "verification_status" in assigned
    assert "is_active" not in assigned, "verification must not suspend the store"
    assert "suspended_at" not in assigned
