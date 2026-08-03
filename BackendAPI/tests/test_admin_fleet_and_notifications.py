"""The fleet registry and notification reachability.

Two things worth pinning:

  1. `Deliverer_Vendors` is a dead table whose model used to declare
     relationships that do not exist, so importing it from the application
     raised `InvalidRequestError` on the first ORM query in the process and took
     every unrelated query down with it. It went unnoticed because the only
     importer was `alembic/env.py`, which never compiles an ORM query.
  2. The notifications screen names no recipient. It is readable by anyone with
     `analytics.read`, and "who was told what" is a support question.
"""
import ast
import pathlib

import pytest

from services import admin_fleet_service as fleet
from services import admin_notification_service as notify

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ADMIN = BACKEND.parent / "drop-admin"


# ── the dead table stays importable ───────────────────────────────────────


def test_the_dead_registry_model_declares_no_relationships():
    """`back_populates="vendors"` named a property that does not exist on
    Deliverer. Any module that imported this one broke every ORM query in the
    process, not merely its own."""
    source = (BACKEND / "models/deliverer_vendor_model.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "relationship":
            pytest.fail(
                "Deliverer_Vendors is dead and its relationships pointed at "
                "properties that do not exist. Re-adding one makes importing "
                "this module break unrelated queries."
            )


def test_importing_the_dead_model_does_not_break_the_mappers():
    """The regression itself: configure every mapper with this module loaded."""
    from sqlalchemy.orm import configure_mappers

    from models.deliverer_vendor_model import DelivererVendor  # noqa: F401

    configure_mappers()


def test_the_fleet_service_reads_the_live_registry_not_the_dead_one():
    """`VendorRiderRegistry` is what dispatch, the rider app and the vendor app
    use. Drawing the console from the other table would make it the only place on
    the platform where the two disagree."""
    source = (BACKEND / "services/admin_fleet_service.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        if node.name == "summary":
            continue  # reports the dead table's row count, deliberately
        body = ast.get_source_segment(source, node) or ""
        assert "DelivererVendor" not in body, (
            f"{node.name} reads the dead Deliverer_Vendors table"
        )


# ── notifications name nobody ─────────────────────────────────────────────


def test_the_notification_feed_carries_no_recipient_identity():
    source = (BACKEND / "services/admin_notification_service.py").read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "recent":
            body = ast.get_source_segment(source, node) or ""
            assert '"user_id"' not in body and "row.user_id" not in body, (
                "the feed is readable with analytics.read; who was told what "
                "belongs on their support ticket"
            )
            assert '"audience": row.user_type' in body, "the audience type is fine"
            return

    pytest.fail("recent() not found")


def test_the_message_body_is_truncated_in_the_feed():
    """A notification body can carry a delivery address or a phone number."""
    source = (BACKEND / "services/admin_notification_service.py").read_text()
    assert "[:120]" in source


def test_every_notification_read_scopes_on_user_type():
    """`Notification.user_id` holds ids from three tables and carries no foreign
    key, so `user_id` alone relies on UUID collisions not happening."""
    source = (BACKEND / "services/admin_notification_service.py").read_text()
    assert "user_type" in source
    assert set(notify.AUDIENCES) == {"customer", "rider", "vendor"}


# ── honest zeroes ─────────────────────────────────────────────────────────


def test_a_rate_over_nothing_is_none_rather_than_zero_percent():
    """"0% opened" and "nothing to open" are different statements, and one of
    them is an accusation about a channel that was never used."""
    source = (BACKEND / "services/admin_notification_service.py").read_text()
    assert 'if total else None' in source
    assert 'if accounts else None' in source

    fleet_source = (BACKEND / "services/admin_fleet_service.py").read_text()
    assert "STALE_REQUEST_DAYS" in fleet_source


def test_the_stale_request_threshold_is_days_not_minutes():
    """A store is allowed to take a day or two to answer. Flagging a request as
    ignored within an hour would make the queue meaningless."""
    assert fleet.STALE_REQUEST_DAYS >= 1


# ── the console keeps the same promises ───────────────────────────────────


def test_the_notifications_page_names_nobody():
    page = (ADMIN / "app/(dashboard)/platform/notifications/page.tsx").read_text()
    assert "user_id" not in page
    assert "No recipient is named" in page
