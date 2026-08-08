"""Minimal SMTP email sender — used to forward Contact-Us messages to the team.

If SMTP isn't configured (SMTP_HOST/USER/PASS empty), send_email() is a safe
no-op that returns False, so the app never breaks when credentials aren't set.
Configure SMTP_* + CONTACT_EMAIL_TO in the environment (Render) to turn it on.
"""
import smtplib
import ssl
from email.message import EmailMessage

from app.config import settings


def send_email(to: str, subject: str, body: str, reply_to: str = "") -> bool:
    """Send a plain-text email via SMTP. Returns True on success; False if SMTP
    isn't configured or sending failed (never raises)."""
    if not (settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASS and to):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    msg["To"] = to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    try:
        port = settings.SMTP_PORT or 587
        ctx = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, port, context=ctx, timeout=20) as s:
                s.login(settings.SMTP_USER, settings.SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP(settings.SMTP_HOST, port, timeout=20) as s:
                s.starttls(context=ctx)
                s.login(settings.SMTP_USER, settings.SMTP_PASS)
                s.send_message(msg)
        return True
    except Exception as e:
        print(f"[email] send failed: {e}")
        return False
