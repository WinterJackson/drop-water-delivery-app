import asyncio
import base64
import os
import datetime
import hmac
import logging
from decimal import Decimal, ROUND_HALF_UP

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

async def initiate_stk_push(phone: str, amount: int):
    """Ask Safaricom to prompt `phone` for `amount`.

    Returns Safaricom's body on success, or `{"error": …}` — never raises. The
    checkout route reads the absence of a `CheckoutRequestID` as "nothing was
    charged", which is only safe if every failure that happens *before* the push
    comes back the same shape as one during it.
    """
    try:
        token = await get_access_token()
        payload = {
            "BusinessShortCode": os.getenv("MPESA_SHORTCODE"),
            "TransactionType": "CustomerPayBillOnline",
            "Amount": whole_shillings(amount, label="Order amount"),
            "PartyA": phone,
            "PartyB": os.getenv("MPESA_SHORTCODE"),
            "PhoneNumber": phone,
            "CallBackURL": os.getenv("MPESA_CALLBACK_URL"),
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

def is_safaricom_ip(client_ip: str) -> bool:
    """Returns True if IP is from Safaricom's known ranges, or if ENV=development"""
    env = os.getenv("ENV", "development")
    if env == "development":
        return True  # Skip in dev
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


async def check_payment(checkout_request_id: str, session: AsyncSession):
    try:
        access_token = await get_access_token()
    except MpesaError as e:
        # The client polls this while watching a spinner. "Still processing" is
        # the honest answer: we could not ask, so we do not know, and the
        # callback remains the authority either way.
        logger.error("M-PESA query could not authenticate: %s", e)
        return {"message": "The transaction is being processed", "code": "pending"}

    password, timestamp = generate_password()
    business_short_code = os.getenv("MPESA_SHORTCODE")
    
    query_headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + access_token
        }

    query_payload = {
        'BusinessShortCode': business_short_code,
        'Password': password,
        'Timestamp': timestamp,
        'CheckoutRequestID': checkout_request_id
    }
    
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{MPESA_BASE_URL}/mpesa/stkpushquery/v1/query",
                headers=query_headers,
                json=query_payload
            )
            logger.info("M-PESA QUERY Response: %s", response.text)
            response_data = response.json()
            
            if 'errorCode' in response_data and response_data['errorCode'] == '500.001.1001':
                return {"message": "The transaction is being processed", "code": "pending"}
            if 'ResultCode' not in response_data:
                logger.warning(f"M-PESA QUERY missing ResultCode: {response_data}")
                return {"message": "Still processing or missing ResultCode", "code": "pending"}
            
            result_code = str(response_data['ResultCode'])
            result_desc = response_data.get('ResultDesc', 'Unknown error')

            if result_code == '0':
                # ✅ SUCCESS — mark as paid
                message = await update_orders_payment_status_by_checkout_id(
                    session=session,
                    checkout_request_id=checkout_request_id,
                    new_status="paid"
                )
            else:
                # ❌ FAILURE — mark as failed with reason
                failure_reason = {
                    '1032': "Transaction cancelled by user",
                    '1037': "Timeout in completing transaction",
                    '1': "Insufficient balance",
                    '2001': "Wrong M-Pesa PIN entered",
                }.get(result_code, f"Payment failed: {result_desc}")

                await update_orders_payment_status_by_checkout_id(
                    session=session,
                    checkout_request_id=checkout_request_id,
                    new_status="failed"
                )
                message = {"message": failure_reason, "code": result_code}

            return message
    except httpx.HTTPError as e:
        logger.error("M-PESA Query HTTP Error: %s", str(e))
        return {"error": str(e)}


# ── M-Pesa B2C (Business to Customer) Disbursement ─────────────────────────
# Used for vendor/rider payouts. Sends money from business paybill to user's M-Pesa.
# Requires: MPESA_B2C_SHORTCODE, MPESA_B2C_INITIATOR, MPESA_B2C_PASSWORD,
#           MPESA_B2C_RESULT_URL, MPESA_B2C_TIMEOUT_URL

async def initiate_b2c_payout(phone: str, amount: float, payout_id: str) -> dict:
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
            "Occasion": f"payout_{payout_id}",
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
    amount: float,
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