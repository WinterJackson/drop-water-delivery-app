import base64
import os
import datetime
import hmac
import logging
import httpx
from dotenv import load_dotenv
from services.order_service import update_orders_payment_status_by_checkout_id
from sqlalchemy.ext.asyncio import AsyncSession

load_dotenv()

logger = logging.getLogger(__name__)

# F-008 FIX: M-Pesa base URL configurable via env (sandbox vs production)
MPESA_BASE_URL = os.getenv("MPESA_BASE_URL", "https://sandbox.safaricom.co.ke")


async def get_access_token():
    consumer_key = os.getenv("MPESA_CONSUMER_KEY")
    consumer_secret = os.getenv("MPESA_CONSUMER_SECRET")
    credentials = f"{consumer_key}:{consumer_secret}"
    encoded = base64.b64encode(credentials.encode()).decode()

    headers = {
        "Authorization": f"Basic {encoded}"
    }

    url = f"{MPESA_BASE_URL}/oauth/v1/generate?grant_type=client_credentials"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers)
        data = response.json()
        return data.get("access_token")

def generate_password():
    shortcode = os.getenv("MPESA_SHORTCODE")
    passkey = os.getenv("MPESA_PASSKEY")
    timestamp = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
    raw_password = shortcode + passkey + timestamp
    password = base64.b64encode(raw_password.encode()).decode()
    return password, timestamp

async def initiate_stk_push(phone: str, amount: int):
    token = await get_access_token()
    password, timestamp = generate_password()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    platform_name = os.getenv("PLATFORM_NAME", "Drop")
    payload = {
        "BusinessShortCode": os.getenv("MPESA_SHORTCODE"),
        "Password": password,
        "Timestamp": timestamp,
        "TransactionType": "CustomerPayBillOnline",
        "Amount": amount,
        "PartyA": phone,
        "PartyB": os.getenv("MPESA_SHORTCODE"),
        "PhoneNumber": phone,
        "CallBackURL": os.getenv("MPESA_CALLBACK_URL"),
        "AccountReference": platform_name,
        "TransactionDesc": "Payment"
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
    access_token = await get_access_token()
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
    token = await get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    platform_name = os.getenv("PLATFORM_NAME", "Drop")
    payload = {
        "InitiatorName": os.getenv("MPESA_B2C_INITIATOR", "testapi"),
        "SecurityCredential": os.getenv("MPESA_B2C_PASSWORD", ""),
        "CommandID": "BusinessPayment",
        "Amount": int(amount),
        "PartyA": os.getenv("MPESA_B2C_SHORTCODE", os.getenv("MPESA_SHORTCODE")),
        "PartyB": phone,
        "Remarks": f"{platform_name} Payout {payout_id[:8]}",
        "QueueTimeOutURL": os.getenv("MPESA_B2C_TIMEOUT_URL", ""),
        "ResultURL": os.getenv("MPESA_B2C_RESULT_URL", ""),
        "Occasion": f"payout_{payout_id}",
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
    token = await get_access_token()
    shortcode = receiver_party or os.getenv("MPESA_SHORTCODE")

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "Initiator": os.getenv("MPESA_B2C_INITIATOR", "testapi"),
        "SecurityCredential": os.getenv("MPESA_B2C_PASSWORD", ""),
        "CommandID": "TransactionReversal",
        "TransactionID": transaction_id,
        "Amount": int(amount),
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