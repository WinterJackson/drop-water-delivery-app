"""What we send Safaricom, and what we accept back.

Three defects, each invisible from inside this codebase because the other end
never complains:

* **`Occasion` vs `Occassion`.** Safaricom's B2C parameter has two s's. Daraja
  discards a key it does not recognise, so the correctly-spelled version meant
  the payout id had never been attached to a single disbursement — the field
  that ties a line on an M-Pesa statement back to a payout row.
* **No `OriginatorConversationID`.** Their table marks it required and calls it
  the guard against double disbursement; `500.002.1001` is the refusal it
  produces. Sending nothing means the gateway cannot deduplicate, on the one
  money path where a repeat pays a rider twice rather than miscounting.
* **A production IP allow-list applied to sandbox callbacks.** The secret would
  match and the request would still be refused, silently, from both ends.
"""
from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx

from services import payment_service as ps

SANDBOX = "https://sandbox.safaricom.co.ke"
PRODUCTION = "https://api.safaricom.co.ke"


def _b2c_env(**overrides):
    env = {
        "MPESA_B2C_INITIATOR": "testapi",
        "MPESA_B2C_PASSWORD": "encrypted==",
        "MPESA_B2C_SHORTCODE": "600584",
        "MPESA_B2C_RESULT_URL": "https://example.test/api/payouts/mpesa/b2c_result?secret=s",
        "MPESA_B2C_TIMEOUT_URL": "https://example.test/api/payouts/mpesa/b2c_timeout?secret=s",
        "MPESA_BASE_URL": SANDBOX,
    }
    env.update(overrides)
    return env


async def _captured_b2c_payload(payout_id: str = "8b1f0c22-0000-4000-8000-000000000001") -> dict:
    """Run one disbursement against a mocked Daraja and return what we sent."""
    with respx.mock:
        route = respx.post(f"{SANDBOX}/mpesa/b2c/v3/paymentrequest").mock(
            return_value=httpx.Response(
                200, json={"ResponseCode": "0", "ConversationID": "AG_1", "OriginatorConversationID": "x"}
            )
        )
        with patch.dict(os.environ, _b2c_env(), clear=False), \
             patch.object(ps, "get_access_token", new=AsyncMock(return_value="tok")):
            result = await ps.initiate_b2c_payout(
                phone="254708374149", amount=10, payout_id=payout_id
            )

    assert result["success"] is True, result
    return json.loads(route.calls[0].request.content)


# ── The B2C request body ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_b2c_spells_occasion_the_way_safaricom_does():
    payload = await _captured_b2c_payload()

    assert "Occassion" in payload, (
        "Safaricom's B2C parameter is `Occassion`, with two s's. A key Daraja "
        "does not recognise is dropped in silence, so the correct English "
        f"spelling is the defect here. Sent: {sorted(payload)}"
    )
    assert "Occasion" not in payload, (
        "the single-s spelling is the one Daraja ignores — sending both is not "
        "a fix, it is the bug plus noise"
    )


@pytest.mark.asyncio
async def test_b2c_carries_the_payout_id_that_reconciles_it():
    payout_id = "8b1f0c22-0000-4000-8000-00000000abcd"
    payload = await _captured_b2c_payload(payout_id)

    assert payload["Occassion"] == f"payout_{payout_id}"


@pytest.mark.asyncio
async def test_b2c_sends_an_originator_conversation_id():
    """Safaricom's own idempotency key. Without it they cannot deduplicate."""
    payout_id = "8b1f0c22-0000-4000-8000-00000000beef"
    payload = await _captured_b2c_payload(payout_id)

    assert payload.get("OriginatorConversationID") == payout_id, (
        "the B2C double-disbursement guard is not being sent; a retried "
        "request is indistinguishable from a second payout"
    )


@pytest.mark.asyncio
async def test_the_originator_id_is_stable_for_one_payout():
    """It must be derived from the payout, not generated per call — a fresh id
    on a retry defeats the entire purpose of sending one."""
    payout_id = "8b1f0c22-0000-4000-8000-00000000cafe"

    first = await _captured_b2c_payload(payout_id)
    second = await _captured_b2c_payload(payout_id)

    assert first["OriginatorConversationID"] == second["OriginatorConversationID"]


@pytest.mark.asyncio
async def test_b2c_disburses_from_the_b2c_shortcode():
    """`PartyA` is the disbursement shortcode, not the collection one."""
    with patch.dict(os.environ, {"MPESA_SHORTCODE": "174379"}, clear=False):
        payload = await _captured_b2c_payload()

    assert payload["PartyA"] == "600584"


# ── The callback IP allow-list ────────────────────────────────────────────


def test_sandbox_callbacks_are_not_measured_against_production_addresses():
    """The list is production M-Pesa. Enforcing it against sandbox rejects
    every callback *after* a correct secret has already matched."""
    env = {"ENV": "production", "MPESA_BASE_URL": SANDBOX}
    with patch.dict(os.environ, env, clear=False):
        assert ps.is_sandbox_daraja() is True
        assert ps.is_safaricom_ip("41.90.64.10") is True


def test_production_callbacks_are_still_measured_against_them():
    env = {"ENV": "production", "MPESA_BASE_URL": PRODUCTION}
    with patch.dict(os.environ, env, clear=False):
        assert ps.is_sandbox_daraja() is False
        assert ps.is_safaricom_ip("41.90.64.10") is False
        assert ps.is_safaricom_ip("196.201.214.200") is True


def test_development_still_accepts_anything():
    with patch.dict(os.environ, {"ENV": "development", "MPESA_BASE_URL": PRODUCTION}, clear=False):
        assert ps.is_safaricom_ip("127.0.0.1") is True


def test_the_shared_secret_is_still_enforced_on_sandbox():
    """The IP check is defence in depth; relaxing it must not relax the guard.

    This is the assertion that makes the change above safe to have made.
    """
    class _Req:
        headers = {}
        client = None

    env = {"ENV": "production", "MPESA_BASE_URL": SANDBOX, "MPESA_CALLBACK_SECRET": "right"}
    with patch.dict(os.environ, env, clear=False):
        assert ps.reject_mpesa_callback(_Req(), "wrong", "test") is not None
        assert ps.reject_mpesa_callback(_Req(), None, "test") is not None
        assert ps.reject_mpesa_callback(_Req(), "right", "test") is None
