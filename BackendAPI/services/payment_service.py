import asyncio
import base64
import os
import datetime
import hmac
import logging
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit, urlunsplit

from utils.money import MoneyIn

import httpx
from dotenv import load_dotenv
from services.order_service import update_orders_payment_status_by_checkout_id
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv()

logger = logging.getLogger(__name__)

# F-008 FIX: M-Pesa base URL configurable via env (sandbox vs production)
MPESA_BASE_URL = os.getenv("MPESA_BASE_URL", "https://sandbox.safaricom.co.ke")

#: East Africa Time. Safaricom validates the STK `Timestamp` against its own
#: clock, and the password is the base64 of `shortcode + passkey + timestamp` —
#: so the two must be generated from the same instant *in EAT*. `datetime.now()`
#: is naive local time, which on Render (and in every container that does not set
#: TZ) is UTC: three hours behind, every request.
EAT = datetime.timezone(datetime.timedelta(hours=3))


class MpesaError(RuntimeError):
    """Safaricom could not be reached, or refused before a transaction existed.

    Distinct from a *declined* transaction, which arrives as a result code on a
    successful HTTP call. This is the case where no money can possibly have moved
    — the caller must surface it rather than proceed as though a push went out.
    """


# ── Access token ──────────────────────────────────────────────────────────
# Daraja tokens live an hour and Safaricom throttles the generate endpoint.
# Minting a fresh one per call meant two round trips for every payment, every
# status poll and every disbursement, and a throttled mint returned `None`
# silently — which then went out on the wire as the literal header
# `Authorization: Bearer None` and failed as an opaque Safaricom error.
_token_cache: dict[str, object] = {"value": None, "expires_at": 0.0}
_token_lock = asyncio.Lock()

#: Refreshed this far before the stated expiry, so a token cannot lapse
#: mid-flight on a request that has already been accepted.
_TOKEN_SKEW_SECONDS = 120


async def get_access_token(*, force_refresh: bool = False) -> str:
    """A valid Daraja OAuth token, cached until shortly before it expires.

    Raises `MpesaError` rather than returning `None`: a caller that cannot
    authenticate has not failed to *charge* anybody, and must say so.
    """
    loop = asyncio.get_event_loop()

    if not force_refresh:
        cached = _token_cache["value"]
        if cached and loop.time() < float(_token_cache["expires_at"]):
            return str(cached)

    async with _token_lock:
        # Another coroutine may have refreshed it while we waited for the lock.
        cached = _token_cache["value"]
        if not force_refresh and cached and loop.time() < float(_token_cache["expires_at"]):
            return str(cached)

        consumer_key = os.getenv("MPESA_CONSUMER_KEY")
        consumer_secret = os.getenv("MPESA_CONSUMER_SECRET")
        if not consumer_key or not consumer_secret:
            raise MpesaError("M-Pesa credentials are not configured.")

        encoded = base64.b64encode(f"{consumer_key}:{consumer_secret}".encode()).decode()
        url = f"{MPESA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials"

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.get(url, headers={"Authorization": f"Basic {encoded}"})
        except httpx.HTTPError as exc:
            raise MpesaError(f"Could not reach M-Pesa: {exc}") from exc

        if response.status_code != 200:
            # Never log the body — it echoes the credentials on some errors.
            raise MpesaError(f"M-Pesa rejected our credentials (HTTP {response.status_code}).")

        try:
            data = response.json()
        except ValueError as exc:
            raise MpesaError("M-Pesa returned an unreadable token response.") from exc

        token = data.get("access_token")
        if not token:
            raise MpesaError("M-Pesa returned no access token.")

        # `expires_in` is seconds, as a string on sandbox and an int on
        # production. Treat anything unparseable as the documented hour.
        try:
            ttl = int(float(data.get("expires_in", 3599)))
        except (TypeError, ValueError):
            ttl = 3599

        _token_cache["value"] = token
        _token_cache["expires_at"] = loop.time() + max(60, ttl - _TOKEN_SKEW_SECONDS)
        logger.info("M-PESA access token refreshed, valid for %ss.", ttl)
        return str(token)


def generate_password():
    shortcode = os.getenv("MPESA_SHORTCODE")
    passkey = os.getenv("MPESA_PASSKEY")
    timestamp = datetime.datetime.now(EAT).strftime('%Y%m%d%H%M%S')
    raw_password = f"{shortcode}{passkey}{timestamp}"
    password = base64.b64encode(raw_password.encode()).decode()
    return password, timestamp


def whole_shillings(amount, *, label: str) -> int:
    """The integer M-Pesa will actually move, or a refusal.

    Every Daraja amount field is whole shillings. `int(amount)` **truncates**,
    so a disbursement of 984.50 left the wallet debited for the full withdrawal
    and put 984 on the phone — the missing 50 cents recorded nowhere and
    explained to nobody. The withdrawal fee is a `Platform_Settings` row an
    administrator may set to 15.50 at any time, which is all it takes.

    Refusing is right rather than rounding: the caller has already decided what
    to debit, and a silent adjustment here would put the two out of step again.
    """
    value = Decimal(str(amount))
    if value != value.to_integral_value(rounding=ROUND_HALF_UP) or value <= 0:
        raise MpesaError(
            f"{label} must be a positive whole number of shillings, got {value}."
        )
    return int(value)

# ── Where a push comes back to ────────────────────────────────────────────
#
# An STK push names its own `CallBackURL` in the request body; there is no
# registration step and nothing in the Daraja portal decides this. That makes
# the URL a *per-caller* choice, and it had been a module-level constant.
#
# Both STK callers therefore shared one: `initiate_wallet_topup` pushed for a
# wallet top-up and named the **order** endpoint, which resolves a
# `CheckoutRequestID` against `Orders`. A top-up writes a `WalletTransaction`
# and no order, so the handler found nothing, returned 400 — which is a retry
# instruction to Safaricom, not an acknowledgement — and the customer's money
# left their phone against a transaction that stayed `pending` forever, with no
# sweep and no poll to notice. `handle_mpesa_topup_callback` was live, correct,
# and unreachable: nothing had ever told Safaricom its address.
#
# `callback_url` is keyword-only and **required** for that reason. A default of
# `MPESA_CALLBACK_URL` would restore the defect for the next caller, silently,
# and this is a path where the failure is somebody's money.

#: `/api/cart/mpesa/callback` — settles an `Order`.
ORDER_CALLBACK_PATH = "/api/cart/mpesa/callback"
#: `/api/wallet/mpesa-callback` — settles a `WalletTransaction`. Note the
#: hyphen; that is how the route is declared.
TOPUP_CALLBACK_PATH = "/api/wallet/mpesa-callback"


def _swap_callback_path(url: str, path: str) -> str:
    """`url` with its path replaced, keeping scheme, host **and query**.

    The query is what carries `?secret=…`, which `reject_mpesa_callback`
    compares in constant time — so it has to survive the swap or the derived
    endpoint would 403 every callback it received.
    """
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def order_callback_url() -> str:
    """Where an order payment is settled, or `""` if it is not configured.

    Both resolvers return `""` rather than raising, because `initiate_stk_push`
    refuses a falsy `callback_url` and reports it in the `{"error": …}` shape
    both call sites already read as "nothing was charged". That keeps the
    fail-closed behaviour on the paths that already handle it, instead of
    adding a new exception for two callers to remember to catch.
    """
    return os.getenv("MPESA_CALLBACK_URL") or ""


def topup_callback_url() -> str:
    """Where a wallet top-up is settled, or `""` if it cannot be determined.

    `MPESA_TOPUP_CALLBACK_URL` when set. Otherwise derived from the order URL
    by swapping the path, because the two endpoints are the same host behind
    the same secret — and requiring a second variable would mean this fix does
    nothing until somebody also remembered to set it, on a deploy that would
    still be collecting money it could not credit.
    """
    explicit = os.getenv("MPESA_TOPUP_CALLBACK_URL") or ""
    if explicit:
        return explicit

    base = os.getenv("MPESA_CALLBACK_URL") or ""
    if not base:
        return ""
    return _swap_callback_path(base, TOPUP_CALLBACK_PATH)


async def initiate_stk_push(phone: str, amount: int, *, callback_url: str):
    """Ask Safaricom to prompt `phone` for `amount`.

    `callback_url` says which endpoint settles the result and is required: see
    the note above `ORDER_CALLBACK_PATH`. Pass `order_callback_url()` or
    `topup_callback_url()` rather than reading an environment variable here —
    those raise `MpesaError`, which this catches and returns as an error dict.

    Returns Safaricom's body on success, or `{"error": …}` — never raises. The
    checkout route reads the absence of a `CheckoutRequestID` as "nothing was
    charged", which is only safe if every failure that happens *before* the push
    comes back the same shape as one during it.
    """
    try:
        if not callback_url:
            raise MpesaError("No callback URL was supplied for this STK push.")
        token = await get_access_token()
        payload = {
            "BusinessShortCode": os.getenv("MPESA_SHORTCODE"),
            "TransactionType": "CustomerPayBillOnline",
            "Amount": whole_shillings(amount, label="Order amount"),
            "PartyA": phone,
            "PartyB": os.getenv("MPESA_SHORTCODE"),
            "PhoneNumber": phone,
            "CallBackURL": callback_url,
            "AccountReference": os.getenv("PLATFORM_NAME", "Drop"),
            "TransactionDesc": "Payment",
        }
        password, timestamp = generate_password()
        payload["Password"], payload["Timestamp"] = password, timestamp
    except MpesaError as e:
        logger.error("M-PESA STK could not be prepared: %s", e)
        return {"error": str(e)}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{MPESA_BASE_URL}/mpesa/stkpush/v1/processrequest",
                headers=headers,
                json=payload
            )
            logger.info("M-PESA STK Response: %s", response.text)
            return response.json()
    except httpx.HTTPError as e:
        logger.error("M-PESA STK HTTP Error: %s", str(e))
        return {"error": str(e)}


# ── Safaricom Callback IP Whitelist (production) ──
SAFARICOM_IP_RANGES = [
    "196.201.214.",  # Safaricom M-Pesa production
    "196.201.213.",
    "196.201.212.",
    "41.215.78.",    # Safaricom alternate
]

def is_sandbox_daraja() -> bool:
    """Are we talking to the Daraja sandbox rather than production M-Pesa?

    Read from `MPESA_BASE_URL` — the same variable that decides where every
    request goes — so this cannot disagree with which Safaricom we are actually
    integrated against. It defaults to the sandbox host, matching the default
    in `MPESA_BASE_URL` itself.
    """
    return "sandbox" in (os.getenv("MPESA_BASE_URL") or MPESA_BASE_URL).lower()


def is_safaricom_ip(client_ip: str) -> bool:
    """Whether a callback came from an address M-Pesa actually uses.

    Defence in depth only — the shared secret is the guard. This cannot stand
    alone, because the app runs behind `ProxyHeadersMiddleware(trusted_hosts=
    ["*"])` and the apparent client IP therefore comes from a header any caller
    can set.

    Skipped in two cases, and the second one matters:

    * **Development**, as before.
    * **Sandbox**, whatever `ENV` says. `SAFARICOM_IP_RANGES` is a list of
      *production* M-Pesa addresses, so enforcing it against callbacks from the
      sandbox is incoherent: the check would reject every one, and it would do
      so *after* a correct secret had already matched. The failure is silent
      from both ends — Safaricom sees a 403 and retries, the order never leaves
      `pending`, and the only evidence is a log line — which is exactly the
      class of failure this module keeps being bitten by.

      Gating it on `MPESA_BASE_URL` rather than `ENV` is what lets a staging or
      pre-launch deployment run `ENV=production` — every fail-closed gate on,
      cron endpoints guarded, the callback secret actually enforced — while
      still pointed at the sandbox.
    """
    if os.getenv("ENV", "development").lower() == "development":
        return True

    if is_sandbox_daraja():
        # Warned, not silent: in production this pairing is a misconfiguration
        # (real money against a sandbox host), and it should be visible.
        logger.warning(
            "Skipping the Safaricom IP allow-list: MPESA_BASE_URL points at the "
            "sandbox, whose callbacks do not originate from production ranges. "
            "The shared secret is still enforced."
        )
        return True

    return any(client_ip.startswith(prefix) for prefix in SAFARICOM_IP_RANGES)


def callback_client_ip(request) -> str:
    """The caller's IP, preferring the proxy's forwarded header.

    Render terminates TLS at its edge, so `request.client.host` is the proxy
    unless `X-Forwarded-For` is read. Only the left-most entry is the original
    client. This is advisory: the header is attacker-controlled, which is why
    the shared secret below is the actual guard.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def reject_mpesa_callback(request, supplied_secret, label: str):
    """Guard for every M-Pesa callback. Returns a `JSONResponse` to return, or None.

    These endpoints mark orders paid, settle wallets and — on the B2C failure
    path — refund a debited balance, all without an authenticated user. Two
    layers apply, in this order:

    1. **Shared secret**, compared in constant time. This is the real guard.
    2. **Safaricom IP range**, as defence in depth. It cannot stand alone: the
       app runs behind `ProxyHeadersMiddleware(trusted_hosts=["*"])`, so the
       apparent client IP comes from a header any caller can set.

    Fails closed when `MPESA_CALLBACK_SECRET` is unset outside development. The
    five call sites previously each wrote `if SECRET and supplied != SECRET`,
    which silently disabled the check whenever the variable was missing —
    exactly the deployment where it was most needed.
    """
    from fastapi.responses import JSONResponse

    secret = os.getenv("MPESA_CALLBACK_SECRET")
    if not secret:
        if os.getenv("ENV", "development").lower() != "development":
            logger.error(
                "%s refused: MPESA_CALLBACK_SECRET is not configured.", label
            )
            return JSONResponse(
                status_code=503, content={"message": "Callback not configured"}
            )
        logger.warning(
            "%s accepted without a shared secret — development only.", label
        )
    elif not supplied_secret or not hmac.compare_digest(str(supplied_secret), secret):
        logger.warning("%s rejected: invalid or missing shared secret", label)
        return JSONResponse(status_code=403, content={"message": "Forbidden"})

    client_ip = callback_client_ip(request)
    if not is_safaricom_ip(client_ip):
        logger.warning("%s rejected from non-Safaricom IP: %s", label, client_ip)
        return JSONResponse(status_code=403, content={"message": "Forbidden"})

    return None


#: Safaricom spells this field `Occassion` on B2C — two s's — in both the v3
#: request body and the parameter table. It is theirs to spell, and a key Daraja
#: does not recognise is discarded without a word from either side, so the
#: correct English spelling is the bug. Named rather than inlined so the next
#: person sees it is deliberate and does not "fix" it back.
#:
#: The Reversal API is documented with the single-s `Occasion`, so the two are
#: genuinely inconsistent with each other and each call site uses the spelling
#: its own documentation gives.
B2C_OCCASION_KEY = "Occassion"

#: What Safaricom's own words mean, for the codes worth naming. Anything else
#: is reported with the description Daraja returned.
STK_FAILURE_REASONS = {
    '1032': "Transaction cancelled by user",
    '1037': "Timeout in completing transaction",
    '1': "Insufficient balance",
    '2001': "Wrong M-Pesa PIN entered",
}


async def query_stk_status(checkout_request_id: str) -> dict:
    """Ask Safaricom how one STK push ended. No side effects, no session.

    Returns `{"state": "success" | "failed" | "pending", "result_code": str |
    None, "result_desc": str, "reason": str | None}`. **`pending` means "we
    could not find out"** — Daraja not reachable, the token unavailable, the
    transaction still in flight — and is never a reason to move money either
    way. `reason` distinguishes those cases for a caller that reports them
    differently; a caller deciding whether to settle must treat them alike.

    Split out of `check_payment` so the top-up reconciliation asks the same
    question through the same code. Two implementations of "did this collection
    succeed?" is the shape of defect this platform keeps finding.

    Note what a query does **not** carry: no `MpesaReceiptNumber` and no
    `Amount`. `stkpushquery` answers only with a result code, so a caller
    settling from this has to already know what it asked for.
    """
    try:
        access_token = await get_access_token()
    except MpesaError as e:
        logger.error("M-PESA query could not authenticate: %s", e)
        return {"state": "pending", "result_code": None, "result_desc": str(e), "reason": "auth"}

    password, timestamp = generate_password()
    query_headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + access_token,
    }
    query_payload = {
        'BusinessShortCode': os.getenv("MPESA_SHORTCODE"),
        'Password': password,
        'Timestamp': timestamp,
        'CheckoutRequestID': checkout_request_id,
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{MPESA_BASE_URL}/mpesa/stkpushquery/v1/query",
                headers=query_headers,
                json=query_payload,
            )
            logger.info("M-PESA QUERY Response: %s", response.text)
            response_data = response.json()
    except httpx.HTTPError as e:
        logger.error("M-PESA Query HTTP Error: %s", str(e))
        return {"state": "pending", "result_code": None, "result_desc": str(e), "reason": "http_error"}
    except ValueError as e:
        logger.error("M-PESA Query returned an unreadable body: %s", e)
        return {"state": "pending", "result_code": None, "result_desc": "Unreadable response", "reason": "http_error"}

    if response_data.get('errorCode') == '500.001.1001':
        # Safaricom's "still being processed" — the prompt is on the handset.
        return {"state": "pending", "result_code": None, "result_desc": "Being processed", "reason": "processing"}
    if 'ResultCode' not in response_data:
        logger.warning("M-PESA QUERY missing ResultCode: %s", response_data)
        return {"state": "pending", "result_code": None, "result_desc": "No ResultCode", "reason": "no_result_code"}

    result_code = str(response_data['ResultCode'])
    result_desc = response_data.get('ResultDesc', 'Unknown error')
    return {
        "state": "success" if result_code == '0' else "failed",
        "result_code": result_code,
        "result_desc": result_desc,
        "reason": None,
    }


async def check_payment(checkout_request_id: str, session: AsyncSession):
    outcome = await query_stk_status(checkout_request_id)

    if outcome["state"] == "pending":
        # The client polls this while watching a spinner. "Still processing" is
        # the honest answer: we could not ask, so we do not know, and the
        # callback remains the authority either way.
        if outcome.get("reason") == "http_error":
            return {"error": outcome["result_desc"]}
        if outcome.get("reason") == "no_result_code":
            return {"message": "Still processing or missing ResultCode", "code": "pending"}
        return {"message": "The transaction is being processed", "code": "pending"}

    result_code = outcome["result_code"]
    result_desc = outcome["result_desc"]

    if outcome["state"] == "success":
        # ✅ SUCCESS — mark as paid
        return await update_orders_payment_status_by_checkout_id(
            session=session,
            checkout_request_id=checkout_request_id,
            new_status="paid",
        )

    # ❌ FAILURE — mark as failed with reason
    failure_reason = STK_FAILURE_REASONS.get(
        result_code, f"Payment failed: {result_desc}"
    )
    await update_orders_payment_status_by_checkout_id(
        session=session,
        checkout_request_id=checkout_request_id,
        new_status="failed",
    )
    return {"message": failure_reason, "code": result_code}


# ── M-Pesa B2C (Business to Customer) Disbursement ─────────────────────────
# Used for vendor/rider payouts. Sends money from business paybill to user's M-Pesa.
# Requires: MPESA_B2C_SHORTCODE, MPESA_B2C_INITIATOR, MPESA_B2C_PASSWORD,
#           MPESA_B2C_RESULT_URL, MPESA_B2C_TIMEOUT_URL

async def initiate_b2c_payout(phone: str, amount: MoneyIn, payout_id: str) -> dict:
    """
    Initiate M-Pesa B2C payment to disburse funds to a vendor/rider.
    
    Args:
        phone: Recipient phone number (format: 2547XXXXXXXX)
        amount: Amount in KSH to disburse
        payout_id: Internal payout record ID for tracking
    
    Returns:
        dict with ConversationID and OriginatorConversationID on success
    """
    try:
        token = await get_access_token()
        platform_name = os.getenv("PLATFORM_NAME", "Drop")
        payload = {
            # Safaricom's own double-disbursement guard, and it was not being
            # sent. Their parameter table marks it required and describes it as
            # "unique string generated by the merchant system for every B2C
            # request to avoid double disbursement"; `500.002.1001 Duplicate
            # OriginatorConversationID` is the refusal it produces. Omitting it
            # means the gateway *cannot* deduplicate — on the one money path
            # where a repeat does not miscount something but pays a rider
            # twice.
            #
            # `payout_id` is the natural key: one per payout row, already a
            # UUID, and the same value on a retry of the same disbursement.
            "OriginatorConversationID": str(payout_id),
            "InitiatorName": os.getenv("MPESA_B2C_INITIATOR", "testapi"),
            "SecurityCredential": os.getenv("MPESA_B2C_PASSWORD", ""),
            "CommandID": "BusinessPayment",
            # Whole shillings, or refuse. See `whole_shillings` — truncating here
            # is how a debited balance and a disbursed amount came to disagree.
            "Amount": whole_shillings(amount, label="Disbursement amount"),
            "PartyA": os.getenv("MPESA_B2C_SHORTCODE", os.getenv("MPESA_SHORTCODE")),
            "PartyB": phone,
            "Remarks": f"{platform_name} Payout {payout_id[:8]}",
            "QueueTimeOutURL": os.getenv("MPESA_B2C_TIMEOUT_URL", ""),
            "ResultURL": os.getenv("MPESA_B2C_RESULT_URL", ""),
            # `Occassion`, with Safaricom's double s. Their B2C v3 request body
            # and parameter table both spell it that way, and a parameter name
            # Daraja does not recognise is dropped in silence — so `Occasion`
            # meant the payout id had never once been attached to a
            # disbursement, which is the field that ties an M-Pesa statement
            # line back to a payout row. Same shape as a misspelt prop on a
            # native view: right value, wrong key, no complaint from either
            # side. See `B2C_OCCASION_KEY`.
            B2C_OCCASION_KEY: f"payout_{payout_id}",
        }
    except MpesaError as e:
        # The caller has already debited the balance and refunds on a falsy
        # `success`, so this must never propagate as an exception.
        logger.error("M-PESA B2C could not be prepared: %s", e)
        return {"success": False, "error": str(e)}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{MPESA_BASE_URL}/mpesa/b2c/v3/paymentrequest",
                headers=headers,
                json=payload,
            )
            data = response.json()
            logger.info("M-PESA B2C Response: %s", response.text)

            if data.get("ResponseCode") == "0":
                return {
                    "success": True,
                    "ConversationID": data.get("ConversationID"),
                    "OriginatorConversationID": data.get("OriginatorConversationID"),
                }
            else:
                error_msg = data.get("errorMessage", data.get("ResponseDescription", "B2C request failed"))
                logger.error("M-PESA B2C Error: %s", error_msg)
                return {"success": False, "error": error_msg}

    except httpx.HTTPError as e:
        logger.error("M-PESA B2C HTTP Error: %s", str(e))
        return {"success": False, "error": str(e)}


# ── M-Pesa Transaction Reversal ──────────────────────────────────────────────
# Used when a customer's paid order is cancelled. Reverses the original C2B payment.
# Requires: MPESA_REVERSAL_RESULT_URL, MPESA_REVERSAL_TIMEOUT_URL

async def initiate_mpesa_reversal(
    transaction_id: str,
    amount: MoneyIn,
    receiver_party: str | None = None,
) -> dict:
    """
    Initiate M-Pesa Reversal for a previously completed C2B transaction.
    
    Args:
        transaction_id: The original MpesaReceiptNumber (e.g., "QJI4ABCDEF")
        amount: Amount to reverse in KSH
        receiver_party: The shortcode that received the payment (defaults to env MPESA_SHORTCODE)
    
    Returns:
        dict with success status and ConversationID
    """
    shortcode = receiver_party or os.getenv("MPESA_SHORTCODE")

    try:
        token = await get_access_token()
        reversal_amount = whole_shillings(amount, label="Reversal amount")
    except MpesaError as e:
        logger.error("M-PESA reversal could not be prepared: %s", e)
        return {"success": False, "error": str(e)}

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "Initiator": os.getenv("MPESA_B2C_INITIATOR", "testapi"),
        "SecurityCredential": os.getenv("MPESA_B2C_PASSWORD", ""),
        "CommandID": "TransactionReversal",
        "TransactionID": transaction_id,
        "Amount": reversal_amount,
        "ReceiverParty": shortcode,
        "RecieverIdentifierType": "11",  # Shortcode identifier
        "Remarks": f"Drop refund for {transaction_id}",
        "QueueTimeOutURL": os.getenv("MPESA_REVERSAL_TIMEOUT_URL", os.getenv("MPESA_B2C_TIMEOUT_URL", "")),
        "ResultURL": os.getenv("MPESA_REVERSAL_RESULT_URL", os.getenv("MPESA_B2C_RESULT_URL", "")),
        "Occasion": f"refund_{transaction_id}",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{MPESA_BASE_URL}/mpesa/reversal/v1/request",
                headers=headers,
                json=payload,
            )
            data = response.json()
            logger.info("M-PESA Reversal Response: %s", response.text)

            if data.get("ResponseCode") == "0":
                return {
                    "success": True,
                    "ConversationID": data.get("ConversationID"),
                    "OriginatorConversationID": data.get("OriginatorConversationID"),
                }
            else:
                error_msg = data.get("errorMessage", data.get("ResponseDescription", "Reversal request failed"))
                logger.error("M-PESA Reversal Error: %s", error_msg)
                return {"success": False, "error": error_msg}

    except httpx.HTTPError as e:
        logger.error("M-PESA Reversal HTTP Error: %s", str(e))
        return {"success": False, "error": str(e)}