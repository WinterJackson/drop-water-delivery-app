"""A store does not set how far its orders travel.

The platform's position is stated in `platform_config_service` and enforced by
`test_delivery_radius_and_fee_are_platform_settings_not_vendor_fields` — but
that test only checked that no *settings row* exists letting a vendor set it. It
could not see the other half: `Vendor.delivery_radius`, a writable column
exposed on the vendor profile PATCH, with a stepper in the vendor app wired
straight to it.

What made it hard to spot is that the column decided nothing. Dispatch,
discovery and checkout all read `retail_max_distance_km` /
`wholesale_max_distance_km`; nothing on any of those paths has ever read the
vendor column. So the control did not widen a catchment, and testing it by
placing an order would show it working correctly — because the radius that
applied was the platform's, whatever the store had set.

It was not inert, though. Two screens rendered it:

* the vendor's own map drew the circle from it, so a store that set 15 km was
  looking at a picture of a delivery zone it did not have; and
* the customer's product page derived the delivery estimate from it — and from
  the radius, not the distance, so *every* customer of that store was quoted
  the time to the edge of the catchment. Setting it to 15 km told the flat
  upstairs to expect "45 min – 1.5 hrs".

So the one thing a vendor could actually achieve with the control was to make
their own store look slower to everybody browsing it.

The radius is now reported by `GET /storefront` beside the other figures the
server owns, and is writable nowhere.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent

#: The column, and the request field that used to carry it.
COLUMN = "delivery_radius"


def test_the_vendor_profile_request_does_not_accept_a_radius():
    """The request model is the outer door."""
    source = (BACKEND / "routes" / "vendor_management_routes.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "VendorProfileUpdateRequest":
            fields = [
                target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                for target in [statement.target]
                if isinstance(target, ast.Name)
            ]
            assert COLUMN not in fields, (
                "VendorProfileUpdateRequest accepts delivery_radius again — a "
                "store setting its own service radius"
            )
            return

    pytest.fail("VendorProfileUpdateRequest is gone; this guard needs rewriting")


def test_the_profile_service_does_not_apply_a_radius():
    """And the inner one.

    A field absent from the request model but present in `updatable_fields` is
    still writable by anything calling the service directly, which is how a
    removed API field comes back without anybody adding it.
    """
    source = (BACKEND / "services" / "vendor_management_service.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == "updatable_fields" for t in node.targets
        ):
            continue
        assert isinstance(node.value, ast.List)
        names = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]
        assert COLUMN not in names, (
            "update_vendor_profile applies delivery_radius again"
        )
        return

    pytest.fail("updatable_fields is gone; this guard needs rewriting")


def test_the_storefront_reports_the_platform_radius():
    """The replacement has to exist, or the vendor's map has nothing to draw
    and the next person puts the column back."""
    source = (BACKEND / "routes" / "vendor_management_routes.py").read_text()
    assert "delivery_radius_km" in source, (
        "GET /storefront no longer reports the radius the platform enforces"
    )
    assert "DispatchPolicy.max_distance_km" in source, (
        "the reported radius is no longer read through the configured accessor"
    )


def test_no_app_reads_the_vendor_column():
    """All three apps. The customer app was the one quoting an estimate from
    it, but any of them could start."""
    offenders = []
    for app in ("drop-customer-app", "drop-rider-app", "drop-vendor-app"):
        base = ROOT / app
        for directory in ("app", "components", "hooks", "types", "utils", "lib"):
            if not (base / directory).is_dir():
                continue
            for path in (base / directory).rglob("*.ts*"):
                if "node_modules" in path.parts or path.suffix not in (".ts", ".tsx"):
                    continue
                for number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                    stripped = line.strip()
                    # The comments explaining the removal name the column; this
                    # is the codebase's usual rule that documenting a fix must
                    # not be what fails the test.
                    if stripped.startswith(("*", "//", "/*")):
                        continue
                    # `delivery_radius_km` from the storefront limits is the
                    # supported figure, and is a different name on purpose.
                    if "delivery_radius_km" in stripped:
                        continue
                    if COLUMN in stripped:
                        offenders.append(f"{path.relative_to(ROOT)}:{number} {stripped[:70]}")

    assert not offenders, (
        "an app reads Vendor.delivery_radius — it is not the store's "
        "catchment and never was:\n  " + "\n  ".join(offenders)
    )


def test_the_radius_still_comes_from_the_settings_rows():
    """What the vendor column is not, and this is."""
    from services import platform_config_service as config

    for key in ("retail_max_distance_km", "wholesale_max_distance_km"):
        assert key in config.SPEC_BY_KEY


def test_the_column_is_gone_from_the_model_and_the_schemas():
    """Dropped in `c7d2e94a6f18`.

    Left in place it was a nullable float on `Vendors` that nothing wrote and
    nothing read, whose only remaining function was to be mistaken for the
    catchment by the next person — which is exactly what had already happened
    twice, on the vendor's map and the customer's product page.
    """
    for rel in (
        "models/vendor_model.py",
        "schemas/vendor_schemas.py",
        "schemas/product_schemas.py",
    ):
        source = (BACKEND / rel).read_text()
        for number, line in enumerate(source.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert COLUMN not in stripped, (
                f"{rel}:{number} still declares {COLUMN}; the column was dropped"
            )


def test_the_migration_drops_the_column_and_can_put_it_back():
    migration = (
        BACKEND / "alembic" / "versions" / "c7d2e94a6f18_retail_radius_two_point_five.py"
    ).read_text()

    upgrade = migration[migration.index("def upgrade") : migration.index("def downgrade")]
    downgrade = migration[migration.index("def downgrade") :]

    assert 'drop_column("Vendors", "delivery_radius")' in upgrade
    assert "add_column" in downgrade and COLUMN in downgrade


def test_no_app_states_a_radius_of_its_own():
    """The figure is the server's, in every app.

    The rider app held it twice — a hardcoded 2 km circle on `OperationBase`
    and the sentence "you will receive requests from vendors within a 2KM
    radius" beside it. Both were a kilometre short the moment the setting moved,
    and a rider reading a promise the platform does not keep has no way to tell
    it is the app that is wrong.
    """
    offenders = []
    for app in ("drop-customer-app", "drop-rider-app", "drop-vendor-app"):
        base = ROOT / app
        for directory in ("app", "components", "hooks"):
            if not (base / directory).is_dir():
                continue
            for path in (base / directory).rglob("*.ts*"):
                if "node_modules" in path.parts or path.suffix not in (".ts", ".tsx"):
                    continue
                for number, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith(("*", "//", "/*")):
                        continue
                    if re.search(r"\b\d+(\.\d+)?\s*KM radius", stripped, re.I):
                        offenders.append(f"{path.relative_to(ROOT)}:{number} {stripped[:70]}")

    assert not offenders, (
        "an app states a service radius of its own — it comes from the server:"
        "\n  " + "\n  ".join(offenders)
    )
