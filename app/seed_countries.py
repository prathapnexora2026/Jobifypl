"""Seed the countries table on first boot (only if empty).

The app's phone/country picker reads the enabled countries from GET /countries,
so this list is what users can register with. Admin can enable/disable/add more
from the admin panel afterwards — no app rebuild needed.
"""
from app.database import SessionLocal
from app.models import Country

# (name, dial_code, flag, iso2, enabled)
# Everything enabled for now except Russia (Infobip cannot deliver SMS there).
COUNTRIES = [
    ("Poland", "+48", "\U0001F1F5\U0001F1F1", "PL", True),
    ("India", "+91", "\U0001F1EE\U0001F1F3", "IN", True),
    ("Ukraine", "+380", "\U0001F1FA\U0001F1E6", "UA", True),
    ("Sri Lanka", "+94", "\U0001F1F1\U0001F1F0", "LK", True),
    ("Nepal", "+977", "\U0001F1F3\U0001F1F5", "NP", True),
    ("Bangladesh", "+880", "\U0001F1E7\U0001F1E9", "BD", True),
    ("Philippines", "+63", "\U0001F1F5\U0001F1ED", "PH", True),
    ("Indonesia", "+62", "\U0001F1EE\U0001F1E9", "ID", True),
    ("Germany", "+49", "\U0001F1E9\U0001F1EA", "DE", True),
    ("United Kingdom", "+44", "\U0001F1EC\U0001F1E7", "GB", True),
    ("Netherlands", "+31", "\U0001F1F3\U0001F1F1", "NL", True),
    ("Belgium", "+32", "\U0001F1E7\U0001F1EA", "BE", True),
    ("France", "+33", "\U0001F1EB\U0001F1F7", "FR", True),
    ("Spain", "+34", "\U0001F1EA\U0001F1F8", "ES", True),
    ("Italy", "+39", "\U0001F1EE\U0001F1F9", "IT", True),
    ("Portugal", "+351", "\U0001F1F5\U0001F1F9", "PT", True),
    ("Austria", "+43", "\U0001F1E6\U0001F1F9", "AT", True),
    ("Switzerland", "+41", "\U0001F1E8\U0001F1ED", "CH", True),
    ("Ireland", "+353", "\U0001F1EE\U0001F1EA", "IE", True),
    ("Sweden", "+46", "\U0001F1F8\U0001F1EA", "SE", True),
    ("Denmark", "+45", "\U0001F1E9\U0001F1F0", "DK", True),
    ("Finland", "+358", "\U0001F1EB\U0001F1EE", "FI", True),
    ("Norway", "+47", "\U0001F1F3\U0001F1F4", "NO", True),
    ("Greece", "+30", "\U0001F1EC\U0001F1F7", "GR", True),
    ("Czech Republic", "+420", "\U0001F1E8\U0001F1FF", "CZ", True),
    ("Slovakia", "+421", "\U0001F1F8\U0001F1F0", "SK", True),
    ("Slovenia", "+386", "\U0001F1F8\U0001F1EE", "SI", True),
    ("Croatia", "+385", "\U0001F1ED\U0001F1F7", "HR", True),
    ("Hungary", "+36", "\U0001F1ED\U0001F1FA", "HU", True),
    ("Romania", "+40", "\U0001F1F7\U0001F1F4", "RO", True),
    ("Bulgaria", "+359", "\U0001F1E7\U0001F1EC", "BG", True),
    ("Serbia", "+381", "\U0001F1F7\U0001F1F8", "RS", True),
    ("Albania", "+355", "\U0001F1E6\U0001F1F1", "AL", True),
    ("Lithuania", "+370", "\U0001F1F1\U0001F1F9", "LT", True),
    ("Latvia", "+371", "\U0001F1F1\U0001F1FB", "LV", True),
    ("Estonia", "+372", "\U0001F1EA\U0001F1EA", "EE", True),
    ("Malta", "+356", "\U0001F1F2\U0001F1F9", "MT", True),
    ("Turkey", "+90", "\U0001F1F9\U0001F1F7", "TR", True),
    ("Russia", "+7", "\U0001F1F7\U0001F1FA", "RU", False),
]


def seed_default_countries():
    db = SessionLocal()
    try:
        if db.query(Country).first():
            return  # already seeded
        for i, (name, dial, flag, iso2, enabled) in enumerate(COUNTRIES):
            db.add(Country(name=name, dial_code=dial, flag=flag, iso2=iso2,
                           enabled=enabled, sort_order=i))
        db.commit()
        print(f"[seed] {len(COUNTRIES)} countries inserted")
    finally:
        db.close()
