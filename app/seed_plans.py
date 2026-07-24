"""Seed the default subscription plans on first boot.

Runs automatically from main.py at startup. It ONLY inserts plans when the
table is empty, so it never duplicates or overwrites plans the admin has
edited/added from the panel. Safe to run on every deploy.

These are the original JobifyPL plans (candidate + recruiter) so the admin and
users see them immediately on the live site — the admin can still add, edit or
delete plans afterwards from the admin panel.
"""
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models import SubscriptionPlan


def seed_default_plans():
    db: Session = SessionLocal()
    try:
        if db.query(SubscriptionPlan).count() > 0:
            return  # already has plans — do nothing

        rec_valid = "30 DAYS PACK VALIDITY\nUNLIMITED APPLICATIONS\nCHAT SUPPORT\nADVERTISE VALIDITY 25 DAYS"
        rec_valid45 = "45 DAYS PACK VALIDITY\nUNLIMITED APPLICATIONS\nCHAT SUPPORT\nADVERTISE VALIDITY 25 DAYS"
        db.add_all([
            # --- Candidate plans ---
            SubscriptionPlan(name="1 Month Plan", price=25, currency="PLN", duration_days=30,
                             feature1="Unlimited Job Views", feature2="Valid for 30 Days",
                             for_role="candidate"),
            SubscriptionPlan(name="2 Months Plan", price=45, currency="PLN", duration_days=60,
                             feature1="Unlimited Job Views", feature2="Valid for 60 Days",
                             for_role="candidate"),
            SubscriptionPlan(name="6 Months Plan", price=120, currency="PLN", duration_days=180,
                             feature1="Unlimited Job Views", feature2="Valid for 180 Days",
                             recommended=True, for_role="candidate"),
            # --- Recruiter packages ---
            SubscriptionPlan(name="Basic", price=399, currency="PLN", duration_days=30, postings=2,
                             for_role="recruiter", features="2 POSTINGS\n" + rec_valid),
            SubscriptionPlan(name="Gold", price=599, currency="PLN", duration_days=30, postings=5,
                             for_role="recruiter", features="5 POSTINGS\n" + rec_valid),
            SubscriptionPlan(name="Platinum", price=1999, currency="PLN", duration_days=45, postings=10,
                             for_role="recruiter", recommended=True,
                             features="10 POSTINGS\n" + rec_valid45),
            SubscriptionPlan(name="Diamond", price=2099, currency="PLN", duration_days=45, postings=20,
                             for_role="recruiter", features="20 POSTINGS\n" + rec_valid45),
        ])
        db.commit()
        print("[seed] default subscription plans inserted (candidate + recruiter)")
    except Exception as e:
        db.rollback()
        print(f"[seed] plan seeding skipped: {e}")
    finally:
        db.close()
