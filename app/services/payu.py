"""PayU (Poland) REST integration.

Flow (the secure one):
  1. create_order() gets an OAuth token, POSTs an order to PayU, and returns a
     hosted-checkout `redirectUri`. The customer pays on PayU's own page.
  2. PayU calls our /payu/notify webhook server-to-server with the order status.
     verify_notify_signature() checks the OpenPayU-Signature header against our
     MD5 second key, so a faked "paid" call is rejected.
  3. Only after a *verified* COMPLETED status do we credit the wallet / activate
     the plan (done in the router, not here).

Docs: https://developers.payu.com/en/restapi.html

All secrets come from settings (env vars). Nothing is hard-coded or committed.
"""
import hashlib
import time

import httpx

from app.config import settings

# PayU amounts are integers in the smallest unit (grosze for PLN). 100.00 PLN -> 10000.
def to_minor_units(amount_pln: float) -> str:
    return str(int(round(float(amount_pln) * 100)))


def _oauth_token() -> str:
    """Client-credentials OAuth token, required on every API call."""
    url = f"{settings.PAYU_BASE}/pl/standard/user/oauth/authorize"
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.PAYU_CLIENT_ID,
        "client_secret": settings.PAYU_CLIENT_SECRET,
    }
    with httpx.Client(timeout=20) as c:
        r = c.post(url, data=data)
        r.raise_for_status()
        return r.json()["access_token"]


def create_order(*, ext_order_id: str, amount_pln: float, description: str,
                 buyer_email: str, buyer_phone: str = "",
                 customer_ip: str = "127.0.0.1") -> dict:
    """Create a PayU order and return {'redirect_uri', 'payu_order_id'}.

    `ext_order_id` is OUR reference (the Payment.ext_order_id) that PayU echoes
    back in the notify webhook so we can match the payment to the right user.
    """
    token = _oauth_token()
    url = f"{settings.PAYU_BASE}/api/v2_1/orders"
    body = {
        "notifyUrl": f"{settings.BASE_URL}/payu/notify",
        "continueUrl": f"{settings.BASE_URL}/payu/return?ext={ext_order_id}",
        "customerIp": customer_ip or "127.0.0.1",
        "merchantPosId": settings.PAYU_POS_ID,
        "description": description,
        "currencyCode": "PLN",
        "totalAmount": to_minor_units(amount_pln),
        "extOrderId": ext_order_id,
        "buyer": {
            "email": buyer_email or "buyer@jobify.pl",
            "phone": buyer_phone or "",
            "language": "pl",
        },
        "products": [{
            "name": description,
            "unitPrice": to_minor_units(amount_pln),
            "quantity": "1",
        }],
    }
    headers = {"Authorization": f"Bearer {token}"}
    # PayU replies 302 with the redirectUri; we must NOT auto-follow it.
    with httpx.Client(timeout=20, follow_redirects=False) as c:
        r = c.post(url, json=body, headers=headers)
        # 200/201/302 are all "created"; anything else is an error.
        if r.status_code not in (200, 201, 302):
            raise RuntimeError(f"PayU order failed: {r.status_code} {r.text}")
        data = r.json()
    return {
        "redirect_uri": data.get("redirectUri"),
        "payu_order_id": data.get("orderId"),
    }


def verify_notify_signature(raw_body: bytes, signature_header: str) -> bool:
    """Verify the OpenPayU-Signature header on a notify webhook.

    Header looks like: 'sender=...;signature=<hash>;algorithm=MD5;content=DOCUMENT'
    The expected hash = MD5( raw_json_body + second_key ).
    """
    if not signature_header:
        return False
    parts = {}
    for chunk in signature_header.split(";"):
        if "=" in chunk:
            k, v = chunk.split("=", 1)
            parts[k.strip()] = v.strip()
    incoming = parts.get("signature", "")
    algo = (parts.get("algorithm") or "MD5").upper()
    if not incoming:
        return False

    concatenated = raw_body + settings.PAYU_MD5_KEY.encode()
    if algo == "MD5":
        expected = hashlib.md5(concatenated).hexdigest()
    elif algo == "SHA-256":
        expected = hashlib.sha256(concatenated).hexdigest()
    elif algo == "SHA-1":
        expected = hashlib.sha1(concatenated).hexdigest()
    else:
        return False
    # constant-time compare
    return _safe_eq(expected.lower(), incoming.lower())


def _safe_eq(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    res = 0
    for x, y in zip(a, b):
        res |= ord(x) ^ ord(y)
    return res == 0


def new_ext_order_id(prefix: str, user_id: int) -> str:
    """A unique reference for one checkout attempt, e.g. 'wallet-12-1690000000'."""
    return f"{prefix}-{user_id}-{int(time.time())}"
