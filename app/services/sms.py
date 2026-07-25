"""SMS sending — provider-agnostic (Infobip by default, Twilio optional).

In dev mode (SMS_DEV_MODE=true) the OTP is printed to the server log, so the
auth flow works with no keys. For real SMS set SMS_DEV_MODE=false and configure
a provider:
  * Infobip (default): INFOBIP_BASE_URL + INFOBIP_API_KEY (+ INFOBIP_SENDER)
      → sends worldwide (190+ countries). Infobip routes per-country and falls
        back from the alphanumeric sender to a number where required (e.g. USA).
  * Twilio: TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_FROM_NUMBER.
"""
import httpx

from app.config import settings


def send_sms(to_phone: str, message: str) -> bool:
    """Send an SMS. Returns True on success."""
    if settings.SMS_DEV_MODE:
        # Dev mode — no real SMS. Print so we can read the code from the log.
        print(f"\n[SMS DEV MODE] To {to_phone}: {message}\n")
        return True

    provider = (settings.SMS_PROVIDER or "infobip").lower()
    if provider == "twilio":
        return _send_twilio(to_phone, message)
    return _send_infobip(to_phone, message)


def _send_infobip(to_phone: str, message: str) -> bool:
    base = (settings.INFOBIP_BASE_URL or "").replace("https://", "").replace("http://", "").strip("/")
    if not base or not settings.INFOBIP_API_KEY:
        print("[SMS ERROR] Infobip not configured (INFOBIP_BASE_URL / INFOBIP_API_KEY missing)")
        return False
    url = f"https://{base}/sms/2/text/advanced"
    headers = {
        "Authorization": f"App {settings.INFOBIP_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "messages": [{
            "from": settings.INFOBIP_SENDER or "JobifyPL",
            "destinations": [{"to": to_phone}],
            "text": message,
        }]
    }
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=20)
        if resp.status_code in (200, 201):
            # Infobip returns a per-message status; PENDING/DELIVERED/ACCEPTED = queued OK.
            try:
                data = resp.json()
                st = data["messages"][0]["status"]
                grp = (st.get("groupName") or "").upper()
                if grp in ("PENDING", "DELIVERED", "ACCEPTED"):
                    return True
                print(f"[SMS ERROR] Infobip status={st} to={to_phone}")
                return False
            except Exception:
                return True   # 2xx with unexpected body — assume queued
        print(f"[SMS ERROR] Infobip {resp.status_code}: {resp.text[:300]} to={to_phone}")
        return False
    except Exception as e:
        print(f"[SMS ERROR] Infobip {type(e).__name__}: {e}")
        return False


def _send_twilio(to_phone: str, message: str) -> bool:
    if not settings.TWILIO_ACCOUNT_SID:
        print("[SMS ERROR] Twilio not configured")
        return False
    url = (f"https://api.twilio.com/2010-04-01/Accounts/"
           f"{settings.TWILIO_ACCOUNT_SID}/Messages.json")
    data = {"From": settings.TWILIO_FROM_NUMBER, "To": to_phone, "Body": message}
    try:
        resp = httpx.post(url, data=data,
                          auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                          timeout=15)
        if resp.status_code in (200, 201):
            return True
        try:
            err = resp.json()
            print(f"[SMS ERROR] Twilio {resp.status_code} code={err.get('code')} "
                  f"msg={err.get('message')} to={to_phone}")
        except Exception:
            print(f"[SMS ERROR] Twilio {resp.status_code}: {resp.text[:300]} to={to_phone}")
        return False
    except Exception as e:
        print(f"[SMS ERROR] {type(e).__name__}: {e}")
        return False
