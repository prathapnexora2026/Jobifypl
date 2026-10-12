"""Seed the editable site settings on first boot (only the keys that are missing).

These power the website footer (contact + social links) and the app-store
buttons, so the admin can edit them from the panel without a code change.
"""
from app.database import SessionLocal
from app.models import SiteSetting

DEFAULTS = {
    "contact_website": "www.jobifypl.pl",
    "contact_email": "jobifysupport@jobifypl.pl",
    "contact_phone": "+48 452 552 438",
    "contact_address": "Poznań, Poland",
    "social_instagram": "https://www.instagram.com/jobifypl?utm_source=qr&igsh=azI0aWd1cDZzcDAz",
    "social_facebook": "https://www.facebook.com/share/1EF9mSUEym/",
    "social_youtube": "https://youtube.com/@jobifypl?si=yWOn5di_m7g-56IJ",
    "social_tiktok": "https://www.tiktok.com/@jobifypl?_r=1&_t=ZS-93fb35KAHcD",
    "app_store_url": "https://apps.apple.com/app/id6807830282",
    "play_store_url": "https://play.google.com/store/apps/details?id=pl.jobifypl.app",
}


def seed_default_site_settings():
    db = SessionLocal()
    try:
        existing = {s.key for s in db.query(SiteSetting).all()}
        added = 0
        for k, v in DEFAULTS.items():
            if k not in existing:
                db.add(SiteSetting(key=k, value=v)); added += 1
        if added:
            db.commit()
            print(f"[seed] {added} site settings inserted")
    finally:
        db.close()
