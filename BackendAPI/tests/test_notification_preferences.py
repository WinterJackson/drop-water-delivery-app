"""
The customer app's settings/NotificationPreferences screen has always written
these toggles to User.preferences, but until push_allowed() existed nothing on
the backend read them — every toggle was cosmetic. These tests pin the gate.
"""
from types import SimpleNamespace

import pytest

from services.notification_service import (
    DEFAULT_NOTIFICATION_PREFERENCES,
    push_allowed,
)


def _user(preferences):
    return SimpleNamespace(preferences=preferences, push_token="ExponentPushToken[x]")


def test_promotions_are_opt_in_by_default():
    """The DB default has promotions off; a promo push must not go out."""
    user = _user(dict(DEFAULT_NOTIFICATION_PREFERENCES))
    assert push_allowed(user, "promotion") is False
    assert push_allowed(user, "offer") is False


def test_promotions_deliver_once_enabled():
    user = _user({**DEFAULT_NOTIFICATION_PREFERENCES, "promotions": True})
    assert push_allowed(user, "promotion") is True


@pytest.mark.parametrize(
    "message_type",
    ["order_update", "order_assigned", "order_cancelled", "mismatch_resolved"],
)
def test_order_updates_toggle_governs_order_messages(message_type):
    on = _user({**DEFAULT_NOTIFICATION_PREFERENCES, "order_updates": True})
    off = _user({**DEFAULT_NOTIFICATION_PREFERENCES, "order_updates": False})
    assert push_allowed(on, message_type) is True
    assert push_allowed(off, message_type) is False


@pytest.mark.parametrize(
    "message_type", ["delivery_update", "delivery_assigned", "delivery_cancelled"]
)
def test_delivery_reminders_toggle_governs_delivery_messages(message_type):
    on = _user({**DEFAULT_NOTIFICATION_PREFERENCES, "delivery_reminders": True})
    off = _user({**DEFAULT_NOTIFICATION_PREFERENCES, "delivery_reminders": False})
    assert push_allowed(on, message_type) is True
    assert push_allowed(off, message_type) is False


@pytest.mark.parametrize("message_type", ["refund_update", "payout_update", "kyc_status"])
def test_transactional_messages_are_never_suppressed(message_type):
    """Money and account notices are not a preference. Silencing promotions
    must never silence 'your refund failed'."""
    silenced = _user({k: False for k in DEFAULT_NOTIFICATION_PREFERENCES})
    assert push_allowed(silenced, message_type) is True


def test_missing_or_malformed_preferences_fall_back_to_defaults():
    assert push_allowed(_user(None), "order_update") is True
    assert push_allowed(_user({}), "order_update") is True
    assert push_allowed(_user("not-a-dict"), "order_update") is True
    # …and the default for promotions is still off.
    assert push_allowed(_user({}), "promotion") is False


def test_absent_recipient_is_not_pushed():
    assert push_allowed(None, "order_update") is False
