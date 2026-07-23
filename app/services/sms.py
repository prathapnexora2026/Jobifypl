"""SMS sending — provider-agnostic.

In dev mode (SMS_DEV_MODE=true) the OTP is printed to the server log, so the
whole auth flow works with no keys. Set SMS_DEV_MODE=false and fill the Twilio
keys to send real SMS. Swapping to another provider = editing only this file.
"""
import httpx

from app.config import settings


def send_sms(to_phone: str, message: str) -> bool:
    """Send an SMS. Returns True on success."""
    if settings.SMS_DEV_MODE or not settings.TWILIO_ACCOUNT_SID:
        # Dev mode — no real SMS. Print so we can read the code from the log.
        print(f"\n[SMS DEV MODE] To {to_phone}: {message}\n")
        return True

    # Twilio REST API (no SDK needed — a simple POST).
    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    )
    data = {
        "From": settings.TWILIO_FROM_NUMBER,
        "To": to_phone,
        "Body": message,
    }
    try:
        resp = httpx.post(
            url,
            data=data,
            auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            return True
        # Log Twilio's actual reason (code + message) so failures are debuggable.
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
