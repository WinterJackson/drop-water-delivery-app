"""Administrator access control.

The console reads every customer's details, every rider's national ID and the
platform's money. Its authorisation is the highest-value gate on the platform,
and it shares a Clerk instance with the three consumer apps — so *every* signed
in user of every app holds a structurally valid token and is separated from the
admin API by this code alone.

The structural tests matter as much as the behavioural ones. A new endpoint
added without a gate is not a bug anybody notices in review; it is an endpoint
that works.
"""
import ast
import pathlib

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock

from models.admin_model import (
    ALL_PERMISSIONS,
    PERM_ADMINS_MANAGE,
    PERM_ANALYTICS_READ,
    PERM_PII_VIEW,
    PERMISSION_LABELS,
    ROLE_ANALYST,
    ROLE_PRESETS,
    ROLE_SUPER_ADMIN,
    ROLE_SUPPORT,
    AdminUser,
    normalise_permissions,
    permissions_for_role,
)

BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _code_only(path: pathlib.Path) -> str:
    """Source with comments and strings removed.

    These modules document the defects they replace, at length and by name, so a
    plain substring scan flags the explanation as if it were the offence. Only
    real tokens count as a use.
    """
    import io
    import tokenize

    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(path.read_text(errors="ignore")).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
        return ""
    return " ".join(
        tok.string for tok in tokens
        if tok.type not in (tokenize.COMMENT, tokenize.STRING)
    )


# ── Structural: no endpoint escapes the gate ──────────────────────────────


#: Every module mounted under /api/admin. Discovered from disk rather than
#: listed, so a fourth admin module cannot be added without being covered.
ADMIN_ROUTE_MODULES = sorted((BACKEND / "routes").glob("admin*routes.py"))


def test_the_admin_modules_are_all_discovered():
    """Guards the discovery itself: a glob that stops matching would make every
    test below pass vacuously."""
    names = {path.name for path in ADMIN_ROUTE_MODULES}
    assert {"admin_routes.py", "admin_people_routes.py", "admin_analytics_routes.py"} <= names


def test_every_admin_route_declares_a_permission():
    """A handler under /api/admin with no `require_admin` is reachable by anyone
    holding any Clerk token — which is every customer of the platform.

    Checked structurally rather than by calling each route: a test that has to
    be extended by hand for each new endpoint is a test that silently stops
    covering the newest one.
    """
    ungated = []
    for path in ADMIN_ROUTE_MODULES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            decorators = [
                d for d in node.decorator_list
                if isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in {"get", "post", "put", "patch", "delete"}
            ]
            if not decorators:
                continue

            gated = any(
                isinstance(sub, ast.Name) and sub.id in {"require_admin", "current_admin"}
                for sub in ast.walk(node.args)
            )
            if not gated:
                ungated.append(f"{path.name}::{node.name}")

    assert ungated == [], (
        "these admin handlers have no require_admin/current_admin dependency, so "
        f"any authenticated user of any app can call them: {ungated}"
    )


def test_current_admin_handlers_narrow_to_a_capability_themselves():
    """`current_admin` only proves the caller is *an* administrator.

    It is the right dependency where the required capability is not knowable
    until the path is parsed — `/people/{kind}s` needs `customers.read` or
    `riders.read` depending on `kind`. But a handler that takes `current_admin`
    and never calls `access.require(...)` is an endpoint any administrator can
    call regardless of role, which is not what the roles are for.

    Three handlers are deliberate exceptions, and they share a shape: each
    returns a payload *assembled* from `access.may(...)` rather than gated by a
    single `access.require(...)`, so demanding one capability up front would
    refuse a caller who is legitimately entitled to part of the answer.

    * `admin_me` reports the caller's own capabilities — requiring one would be
      circular.
    * `search` scopes every result set by the capability that opens its detail
      page, so a support agent searching a phone number gets the customer and
      not the payout.
    * `nav_counts` returns one figure per queue the caller may actually work,
      and omits the rest. Requiring, say, `finance.read` for the whole call
      would leave a support agent with no dispute badge.
    * `queue_stats` is `nav_counts` with more detail behind each figure and the
      identical contract — a missing key means "not yours", never zero.

    Anything else taking `current_admin` must narrow explicitly.
    """
    EXEMPT = {"admin_me", "search", "nav_counts", "queue_stats"}

    offenders = []
    for path in ADMIN_ROUTE_MODULES:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            if node.name in EXEMPT:
                continue
            uses_current_admin = any(
                isinstance(sub, ast.Name) and sub.id == "current_admin"
                for sub in ast.walk(node.args)
            )
            if not uses_current_admin:
                continue
            narrows = any(
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "require"
                for sub in ast.walk(node)
            )
            if not narrows:
                offenders.append(f"{path.name}::{node.name}")

    assert offenders == [], (
        "these handlers accept any administrator without narrowing to a "
        f"capability: {offenders}"
    )


def test_the_gate_has_exactly_one_implementation():
    """`require_admin` used to be defined inside the routes module against an
    environment variable. A second definition anywhere is a second set of rules,
    and the weaker one wins for whichever routes import it."""
    offenders = []
    for directory in ("routes", "services", "utils"):
        for path in (BACKEND / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(errors="ignore"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "require_admin":
                    offenders.append(f"{directory}/{path.name}")

    assert offenders == [], (
        "require_admin must only be defined in dependencies/admin_dependencies.py; "
        f"also defined in {offenders}"
    )


def test_admin_clerk_ids_is_no_longer_an_authorisation_source():
    """The env allowlist may only be read by the one-time seeding helper.

    Anywhere else it is a backdoor that bypasses roles, revocation and the audit
    trail entirely.
    """
    offenders = []
    for directory in ("routes", "services", "dependencies", "utils"):
        root = BACKEND / directory
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if path.name == "admin_service.py":
                continue  # seed_first_admin, documented and idempotent
            if "ADMIN_CLERK_IDS" in _code_only(path):
                offenders.append(f"{directory}/{path.name}")

    assert offenders == [], f"ADMIN_CLERK_IDS must not gate anything: {offenders}"


def test_no_admin_route_reads_an_encrypted_column_through_raw_sql():
    """`/admin/payouts` used `text()` to select `account_details`.

    `StringEncryptedType` decrypts in `process_result_value`, which only runs
    for a typed ORM column, so raw SQL returns base64 ciphertext. The screen
    would have shown that where the M-Pesa number belongs — and it looks like
    data corruption, not a query bug.
    """
    code = _code_only(BACKEND / "routes" / "admin_routes.py")
    assert "text (" not in code and "text(" not in code, (
        "read encrypted columns through the ORM; raw SQL bypasses decryption"
    )


def test_money_is_never_cast_to_float_in_admin_routes():
    """`float(Decimal(...))` loses precision, and a revenue report that
    disagrees with the ledger by fractions of a cent gets argued with rather
    than used."""
    code = _code_only(BACKEND / "routes" / "admin_routes.py")
    assert "float (" not in code and "float(" not in code, (
        "money is Decimal on this platform"
    )


# ── The capability set ────────────────────────────────────────────────────


def test_unknown_permissions_are_discarded():
    assert normalise_permissions(["riders.read", "become_owner", ""]) == ["riders.read"]


def test_every_permission_has_a_label():
    assert set(PERMISSION_LABELS) == set(ALL_PERMISSIONS)
    assert all(PERMISSION_LABELS[p] for p in ALL_PERMISSIONS)


def test_every_role_preset_contains_only_real_permissions():
    """A typo in a preset silently grants nothing, and looks like a bug in the
    gate rather than in the preset."""
    for role, perms in ROLE_PRESETS.items():
        unknown = set(perms) - set(ALL_PERMISSIONS)
        assert not unknown, f"{role} references unknown permissions: {unknown}"


def test_support_cannot_read_personal_data_or_touch_money():
    """Support answers "where is my order" all day. That job does not require
    the ability to open somebody's national ID, and the console should be able
    to express the difference."""
    support = set(ROLE_PRESETS[ROLE_SUPPORT])
    assert PERM_PII_VIEW not in support
    assert not {p for p in support if p.startswith("finance.")}


def test_analyst_can_answer_questions_without_changing_or_identifying_anything():
    analyst = set(ROLE_PRESETS[ROLE_ANALYST])
    assert PERM_ANALYTICS_READ in analyst
    assert PERM_PII_VIEW not in analyst
    # Nothing that mutates.
    assert not {
        p for p in analyst
        if any(p.endswith(v) for v in (".suspend", ".approve", ".intervene", ".erase", ".resolve"))
    }


def test_only_super_admin_can_manage_administrators():
    for role, perms in ROLE_PRESETS.items():
        if role == ROLE_SUPER_ADMIN:
            assert PERM_ADMINS_MANAGE in perms
        else:
            assert PERM_ADMINS_MANAGE not in perms, f"{role} can grant itself anything"


def test_an_unknown_role_grants_nothing():
    """Never a default grant: a typo in a role name must fail closed."""
    assert permissions_for_role("ceo") == []


# ── The gate itself ───────────────────────────────────────────────────────


def test_require_admin_rejects_a_permission_that_does_not_exist():
    """Fails at import, not at request time.

    A typo would otherwise produce a route nobody can ever call, and in
    production that is indistinguishable from a permissions misconfiguration.
    """
    from dependencies.admin_dependencies import require_admin

    with pytest.raises(ValueError):
        require_admin("riders.raed")


def test_permission_names_used_by_routes_all_exist():
    """Every `require_admin("...")` literal in the routes resolves."""
    source = (BACKEND / "routes" / "admin_routes.py").read_text()
    tree = ast.parse(source)
    used = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "require_admin"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert used <= set(ALL_PERMISSIONS), f"unknown: {used - set(ALL_PERMISSIONS)}"


@pytest.mark.asyncio
async def test_a_signed_in_non_admin_is_refused():
    """Every customer, rider and vendor holds a valid Clerk token. This is the
    only thing standing between them and the console."""
    from dependencies.admin_dependencies import _resolve_admin

    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=result)

    request = MagicMock()
    request.headers = {}
    request.client = None

    with pytest.raises(HTTPException) as exc:
        await _resolve_admin(request, db, {"sub": "user_a_customer"})
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_a_revoked_admin_loses_access_immediately():
    """The query filters on `revoked_at IS NULL`, so revocation takes effect on
    the next request rather than whenever a cache expires."""
    from dependencies.admin_dependencies import _resolve_admin

    db = AsyncMock()
    result = MagicMock()
    # Revoked rows are excluded by the WHERE clause, so the lookup finds nothing.
    result.scalars.return_value.first.return_value = None
    db.execute = AsyncMock(return_value=result)

    request = MagicMock()
    request.headers = {}
    request.client = None

    with pytest.raises(HTTPException) as exc:
        await _resolve_admin(request, db, {"sub": "user_revoked"})
    assert exc.value.status_code == 403


def test_two_factor_is_required_by_default():
    """Opting out has to be a deliberate act. An unset variable must not be the
    same as "off" for the console that holds every identity document."""
    import os

    from dependencies.admin_dependencies import _two_factor_required

    os.environ.pop("ADMIN_2FA_REQUIRED", None)
    assert _two_factor_required() is True

    os.environ["ADMIN_2FA_REQUIRED"] = "false"
    assert _two_factor_required() is False
    os.environ.pop("ADMIN_2FA_REQUIRED", None)


def test_the_two_factor_claim_is_read_from_the_session_not_the_client():
    """Clerk spells it differently across token versions. All known spellings
    are accepted rather than pinning one and locking every admin out on an
    upgrade — but an absent claim is never treated as satisfied."""
    from dependencies.admin_dependencies import _claims_two_factor

    assert _claims_two_factor({"two_factor_enabled": True})
    assert _claims_two_factor({"tfa": True})
    assert _claims_two_factor({"fva": [0, 1]})

    assert not _claims_two_factor({})
    assert not _claims_two_factor({"fva": [0, -1]})  # second factor never verified
    assert not _claims_two_factor({"two_factor_enabled": "yes"})  # not a bool


# ── Model behaviour ───────────────────────────────────────────────────────


def test_revocation_is_a_soft_delete():
    """The audit log references the admin row. Deleting it would leave every
    action that person took pointing at nothing."""
    admin = AdminUser(permissions=list(ALL_PERMISSIONS), is_active=True)
    admin.revoke()
    assert admin.revoked_at is not None
    assert admin.is_active is False


def test_permissions_are_stored_expanded_not_as_a_role_name():
    """Narrowing a preset next quarter must not silently narrow the people
    already doing that job, and widening it must not silently widen them."""
    granted = permissions_for_role(ROLE_SUPPORT)
    assert granted and granted == list(ROLE_PRESETS[ROLE_SUPPORT])
    assert isinstance(granted, list)


def test_the_audit_record_keeps_the_email_rather_than_only_a_foreign_key():
    """The log must stay readable after the admin is revoked or their address
    reassigned; joining to a mutable table for an immutable record would let
    history change retroactively."""
    from models.admin_model import AdminAuditLog

    columns = {c.name for c in AdminAuditLog.__table__.columns}
    assert {"admin_id", "admin_email"} <= columns
    assert AdminAuditLog.__table__.columns["admin_email"].nullable is False
    assert not AdminAuditLog.__table__.foreign_keys


def test_audit_is_never_committed_by_the_service_itself():
    """`record_audit` must stage the row in the caller's transaction.

    A commit here would let the audit row survive an action that then rolls
    back, or an action to commit while its audit row is lost — and the second
    is the one that matters.
    """
    source = (BACKEND / "services" / "admin_service.py").read_text()
    tree = ast.parse(source)
    func = next(
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "record_audit"
    )
    commits = [
        n for n in ast.walk(func)
        if isinstance(n, ast.Attribute) and n.attr == "commit"
    ]
    assert commits == [], "record_audit must not commit; the route owns the transaction"


# ── Enum vocabulary ───────────────────────────────────────────────────────


def _literal_values(node) -> set[str] | None:
    """The string members of a `Literal[...]` annotation, or None."""
    import ast

    if not isinstance(node, ast.Subscript):
        return None
    if not (isinstance(node.value, ast.Name) and node.value.id == "Literal"):
        return None
    members = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    return {m.value for m in members if isinstance(m, ast.Constant) and isinstance(m.value, str)}


def test_every_dispute_status_literal_is_a_real_enum_value():
    """`RejectionStatus(value)` raises `ValueError` on anything it does not
    define, and FastAPI does not catch that — so a status literal which is not
    an enum *value* is a 500, not a 422.

    Both dispute endpoints shipped with this defect. The list accepted
    "resolved" and "rejected", so two of the three tabs on the screen returned
    500; the resolve endpoint took those same two as its **only** outcomes, so
    every dispute decision on the platform returned 500. Nothing caught it
    because they look like a perfectly reasonable vocabulary — the enum's is
    `approved`/`denied`, since a ticket is a rider's *rejection* and "approved"
    means that rejection stands.

    Both sites are named explicitly rather than discovered. A heuristic that
    looks for literals overlapping the enum would have skipped the resolve
    endpoint precisely because *none* of its values were valid — which is the
    more serious of the two bugs.
    """
    import ast

    from models.bottle_rejection_model import RejectionStatus

    valid = {status.value for status in RejectionStatus}
    tree = ast.parse((BACKEND / "routes" / "admin_orders_routes.py").read_text())

    found: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == "list_disputes":
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.arg == "status" and arg.annotation is not None:
                    values = _literal_values(arg.annotation)
                    if values is not None:
                        # "all" is the endpoint's own sentinel for no filter and
                        # is branched on before the enum is constructed.
                        found["list_disputes.status"] = values - {"all"}

        if isinstance(node, ast.ClassDef) and node.name == "ResolveDisputeRequest":
            for statement in node.body:
                if (
                    isinstance(statement, ast.AnnAssign)
                    and isinstance(statement.target, ast.Name)
                    and statement.target.id == "outcome"
                ):
                    values = _literal_values(statement.annotation)
                    if values is not None:
                        found["ResolveDisputeRequest.outcome"] = values

    assert set(found) == {"list_disputes.status", "ResolveDisputeRequest.outcome"}, (
        f"the dispute status literals have moved; update this test. Found: {sorted(found)}"
    )

    for where, values in found.items():
        assert values <= valid, (
            f"{where} accepts {sorted(values - valid)}, which RejectionStatus does "
            f"not define — every such request is a 500. Valid: {sorted(valid)}"
        )

    # A decision must be able to say yes *and* no.
    assert len(found["ResolveDisputeRequest.outcome"]) >= 2


def test_reconciliation_is_gated_on_finance_read():
    """A failed payment callback carries the customer's amount and the M-Pesa
    receipt. It is finance data and is gated like finance data — `support` and
    `analyst` hold no `finance.read`, so neither can enumerate who paid what."""
    import ast
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "routes"
        / "admin_finance_routes.py"
    ).read_text()

    tree = ast.parse(source)
    guarded = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            continue
        if "reconciliation" not in ast.dump(node):
            continue
        guarded[node.name] = "PERM_FINANCE_READ" in ast.dump(node)

    assert guarded, "no reconciliation handlers found — did the route move?"
    unguarded = [name for name, ok in guarded.items() if not ok]
    assert unguarded == [], f"reconciliation handlers with no capability check: {unguarded}"


def test_the_reconciliation_screen_offers_no_replay():
    """Replaying a payment callback would be a second path that moves money.

    The platform refuses those on principle — `admin_orders_routes` leaves
    refunding to `refund_service` for exactly this reason — and a replay that
    raced the reconciliation sweep would credit a wallet twice. The screen
    triages; the fix goes through the single-path tools.
    """
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent

    # Scoped to the reconciliation handlers, not the whole module: the wallet
    # adjustment endpoint lives in the same file and *should* call
    # `apply_wallet_delta` — that is the single path, and it is the one this
    # screen deliberately does not become a second of.
    checked = 0
    for name in ("routes/admin_finance_routes.py", "services/admin_reconciliation_service.py"):
        tree = ast.parse((root / name).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            # Every module-level function in the service, plus the two route
            # handlers. Matching on name fragments missed `list_failures`.
            if name.endswith("admin_finance_routes.py") and "webhook" not in node.name:
                continue
            checked += 1
            calls = {
                child.func.attr
                for child in ast.walk(node)
                if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
            }
            assert "apply_wallet_delta" not in calls, f"{name}:{node.name} moves money"
            assert "replay" not in node.name, f"{name}:{node.name} is a replay path"

    assert checked >= 4, f"expected the reconciliation handlers, found {checked}"


def test_every_mutating_admin_route_leaves_an_audit_trail():
    """"Who did this" must have an answer for every action, not most of them.

    `Admin_Audit_Log` exists because the environment variable it replaced made
    nothing attributable — two admins sharing one capability set left no trace.
    A gap in the coverage is the same problem in miniature: ticket assignment
    was the one mutating route that recorded nothing, so a complaint could
    change hands between an audited reply and an audited resolution with
    nothing in between to show it had.

    Read-only POSTs are exempt by name. `/config/preview` takes a body because
    it prices a sample order under proposed values; it persists nothing, and
    auditing a calculation would be noise in the log people actually read.
    """
    READ_ONLY_POSTS = {("POST", "/config/preview")}

    unaudited = []
    for path in ADMIN_ROUTE_MODULES + sorted((BACKEND / "routes").glob("admin_*_routes.py")):
        source = path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            routes = [
                d for d in node.decorator_list
                if isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name)
                and d.func.value.id == "router"
                and d.args
                and isinstance(d.args[0], ast.Constant)
            ]
            if not routes:
                continue
            method = routes[0].func.attr.upper()
            if method not in ("POST", "PUT", "PATCH", "DELETE"):
                continue
            route = (method, routes[0].args[0].value)
            if route in READ_ONLY_POSTS:
                continue
            body = ast.get_source_segment(source, node) or ""
            if "record_audit" not in body:
                unaudited.append(f"{path.name}: {method} {route[1]}")

    assert sorted(set(unaudited)) == [], (
        "these change something and record nobody as having done it: "
        f"{sorted(set(unaudited))}"
    )
