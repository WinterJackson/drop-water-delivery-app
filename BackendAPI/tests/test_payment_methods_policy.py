"""A saved payment method is a Safaricom line, and there are at most two.

`payment_methods` is a JSONB column on `Users` that `update_user` wrote straight
from the request body. Anything at all could be stored: fifty entries, arbitrary
keys, three rows claiming to be the default, or a number no STK push can reach.
The screen validated for the person typing, which is worth doing and is not the
rule — the rule has to hold where the write happens.

Two constraints:

* **Safaricom only.** M-Pesa is Safaricom's. A push to an Airtel or Telkom line
  never arrives, so saving one is not a payment method, it is a failure deferred
  to the moment the customer is trying to pay.
* **Two at most.** The list exists so somebody can switch between the line they
  carry and the one the household pays from, not to become an address book.

Both limits apply only to what a payload *adds*. Validating the whole list
outright would trap anyone who already holds a third number or a non-Safaricom
one: every save they attempted, including the save that removed the offending
row, would be refused for containing it.
"""
from __future__ import annotations

import pathlib
import re

import pytest
from fastapi import HTTPException

from routes.auth_routes import MAX_PAYMENT_METHODS, _validate_payment_methods
from utils.phone import SAFARICOM_PREFIX_RANGES, is_safaricom, to_e164

ROOT = pathlib.Path(__file__).resolve().parents[2]

SAFARICOM = ["0110123456", "0712345678", "0729123456", "0748123456", "0759123456", "0799123456"]
NOT_SAFARICOM = ["0730111222", "0750123456", "0762123456", "0789123456", "0770123456", "0100123456"]


@pytest.mark.parametrize("number", SAFARICOM)
def test_safaricom_lines_are_accepted(number):
    assert is_safaricom(number)


@pytest.mark.parametrize("number", NOT_SAFARICOM)
def test_other_networks_are_refused(number):
    """Airtel and Telkom cannot receive an M-Pesa prompt."""
    assert not is_safaricom(number)


def test_the_gaps_inside_the_74x_block_are_real():
    """744 and 747 are not Safaricom.

    A contiguous 740-749 range would swallow them, which is why the table is a
    list of ranges rather than one.
    """
    assert not is_safaricom("0744123456")
    assert not is_safaricom("0747123456")


def test_a_new_non_safaricom_number_is_refused():
    with pytest.raises(HTTPException) as raised:
        _validate_payment_methods([{"phone": "0730111222"}], [])
    assert raised.value.status_code == 422
    assert "Safaricom" in raised.value.detail


def test_a_non_safaricom_number_already_stored_can_still_be_removed():
    """Otherwise the rule traps whoever it was introduced after.

    Anyone holding an Airtel number saved before this existed would have every
    save refused — including the one that deletes it.
    """
    existing = [{"phone": "+254730111222", "isDefault": True}]
    kept = _validate_payment_methods([{"phone": "0730111222"}], existing)
    assert kept[0]["phone"] == "+254730111222"
    # and removing it entirely is fine
    assert _validate_payment_methods([], existing) == []


def test_the_cap_refuses_a_third_number():
    two = [{"phone": "0712345678"}, {"phone": "0790111222"}]
    assert len(_validate_payment_methods(two, [])) == 2
    with pytest.raises(HTTPException) as raised:
        _validate_payment_methods(two + [{"phone": "0722333444"}], [])
    assert raised.value.status_code == 422
    assert str(MAX_PAYMENT_METHODS) in raised.value.detail


def test_someone_over_the_cap_can_still_delete_down():
    """The cap applies to growth, not to every save."""
    existing = [{"phone": f"+2547123456{n}0"} for n in range(3)]
    submitted = [{"phone": m["phone"]} for m in existing]
    assert len(_validate_payment_methods(submitted, existing)) == 3
    assert len(_validate_payment_methods(submitted[:2], existing)) == 2


def test_one_number_written_two_ways_is_one_number():
    """`0712345678` and `+254712345678` are the same line.

    Compared as raw strings they are two, and the same number could be saved
    twice — filling the cap with one line.
    """
    saved = _validate_payment_methods(
        [{"phone": "0712345678"}, {"phone": "+254712345678"}], []
    )
    assert len(saved) == 1
    assert saved[0]["phone"] == "+254712345678"


def test_exactly_one_default_survives():
    """Checkout picks the default. Zero or two of them has no answer."""
    none_marked = _validate_payment_methods(
        [{"phone": "0712345678"}, {"phone": "0790111222"}], []
    )
    assert sum(m["isDefault"] for m in none_marked) == 1

    both_marked = _validate_payment_methods(
        [{"phone": "0712345678", "isDefault": True}, {"phone": "0790111222", "isDefault": True}], []
    )
    assert sum(m["isDefault"] for m in both_marked) == 1


def test_entries_are_normalised_and_shaped():
    saved = _validate_payment_methods([{"phone": "0712 345 678", "junk": "ignored"}], [])
    assert saved == [{"type": "mpesa", "phone": "+254712345678", "isDefault": True}]


def test_a_method_with_no_number_is_refused():
    with pytest.raises(HTTPException):
        _validate_payment_methods([{"isDefault": True}], [])
    with pytest.raises(HTTPException):
        _validate_payment_methods(["0712345678"], [])


def test_the_app_and_the_server_agree_on_both_rules():
    """Two copies of a rule are two rules unless something checks.

    The client copy exists so the person typing is told before they submit; this
    asserts it still describes the same policy.
    """
    ts = (ROOT / "drop-customer-app" / "utils" / "phone.ts").read_text()

    cap = re.search(r"MAX_PAYMENT_METHODS\s*=\s*(\d+)", ts)
    assert cap, "the app declares no MAX_PAYMENT_METHODS"
    assert int(cap.group(1)) == MAX_PAYMENT_METHODS, (
        f"the app caps payment methods at {cap.group(1)} and the server at "
        f"{MAX_PAYMENT_METHODS}; one of them is wrong."
    )

    ranges = re.findall(r"\[\s*(\d+)\s*,\s*(\d+)\s*\]", ts)
    app_ranges = {(int(a), int(b)) for a, b in ranges}
    assert app_ranges == set(SAFARICOM_PREFIX_RANGES), (
        "the app's Safaricom prefix table has drifted from the server's:\n"
        f"  app only:    {sorted(app_ranges - set(SAFARICOM_PREFIX_RANGES))}\n"
        f"  server only: {sorted(set(SAFARICOM_PREFIX_RANGES) - app_ranges)}"
    )


def test_the_write_path_actually_calls_the_validator():
    """The premise everything above rests on."""
    source = (ROOT / "BackendAPI" / "routes" / "auth_routes.py").read_text()
    assert re.search(
        r"db_user\.payment_methods\s*=\s*_validate_payment_methods\(", source
    ), (
        "update_user no longer validates payment_methods before storing them, so "
        "the column is back to holding whatever the request body said."
    )
