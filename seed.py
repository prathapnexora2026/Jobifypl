"""Seed demo data: subscription plans + sample jobs (matching the app screenshots)."""
import sys
sys.path.insert(0, ".")

from app.database import SessionLocal, Base, engine
from app.models import User, Role, Job, SubscriptionPlan, RecruiterProfile

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# --- Plans (as seen in Plans & Subscription screen, in PLN) ---
if db.query(SubscriptionPlan).count() == 0:
    db.add_all([
        SubscriptionPlan(name="1 Month Plan", price=25, currency="PLN", duration_days=30,
                         feature1="Unlimited Job Views", feature2="Valid for 30 Days", for_role="candidate"),
        SubscriptionPlan(name="2 Months Plan", price=45, currency="PLN", duration_days=60,
                         feature1="Unlimited Job Views", feature2="Valid for 60 Days", for_role="candidate"),
        SubscriptionPlan(name="6 Months Plan", price=120, currency="PLN", duration_days=180,
                         feature1="Unlimited Job Views", feature2="Valid for 180 Days",
                         recommended=True, for_role="candidate"),
    ])
    # Recruiter packages — exact prices/features from screenshots
    rec_feats_basic = "2 POSTINGS\n30 DAYS PACK VALIDITY\nUNLIMITED APPLICATIONS\nCHAT SUPPORT\nADVERTISE VALIDITY 25 DAYS"
    db.add_all([
        SubscriptionPlan(name="Basic", price=399, currency="PLN", duration_days=30, postings=2,
                         for_role="recruiter", features=rec_feats_basic),
        SubscriptionPlan(name="Gold", price=599, currency="PLN", duration_days=30, postings=5,
                         for_role="recruiter",
                         features="5 POSTINGS\n30 DAYS PACK VALIDITY\nUNLIMITED APPLICATIONS\nCHAT SUPPORT\nADVERTISE VALIDITY 25 DAYS"),
        SubscriptionPlan(name="Platinum", price=1999, currency="PLN", duration_days=45, postings=10,
                         for_role="recruiter", recommended=True,
                         features="10 POSTINGS\n45 DAYS PACK VALIDITY\nUNLIMITED APPLICATIONS\nCHAT SUPPORT\nADVERTISE VALIDITY 25 DAYS"),
        SubscriptionPlan(name="Diamond", price=2099, currency="PLN", duration_days=45, postings=20,
                         for_role="recruiter",
                         features="20 POSTINGS\n45 DAYS PACK VALIDITY\nUNLIMITED APPLICATIONS\nCHAT SUPPORT\nADVERTISE VALIDITY 25 DAYS"),
    ])
    print("seeded plans (candidate + recruiter)")

# --- A recruiter to own the sample jobs ---
rec = db.query(User).filter(User.role == Role.recruiter).first()
if not rec:
    rec = User(phone="+48700000001", role=Role.recruiter, full_name="Nexora Tech")
    db.add(rec); db.flush()
    db.add(RecruiterProfile(user_id=rec.id, company_name="Nexora Tech", can_post_jobs=True, verified=True))

# --- Sample jobs (matching screenshots) ---
if db.query(Job).count() == 0:
    jobs = [
        dict(title="TUTOR JOB", company_name="hgy", position="Tutor", category="Education",
             location="Białystok", job_type="Full Time", work_type="Regular Job",
             gender_pref="Female", shift_timing="8 hours", age_from=18, age_to=45,
             min_salary=4000, max_salary=6000, description="Teaching opportunity."),
        dict(title="SORTING & PACKING JOB", company_name="zdfbnxn", position="Sorter", category="Warehouse",
             location="Gdynia", job_type="Full Time", work_type="Regular Job",
             gender_pref="Male", shift_timing="6 hours", age_from=18, age_to=40,
             min_salary=4200, max_salary=5000, description="Warehouse sorting and packing."),
        dict(title="DRIVING JOB", company_name="Self-Hiring", position="drivercdfme kjf", category="Transport",
             location="Białystok", job_type="Part Time", work_type="Regular Job",
             gender_pref="Male", shift_timing="6 hours", age_from=0, age_to=3,
             min_salary=3800, max_salary=4800, description="dcakjwniuef"),
        dict(title="DATA ENTRY OPERATOR JOB", company_name="data entry", position="Data Entry", category="IT",
             location="Świdnica", job_type="Part Time", work_type="Regular Job",
             gender_pref="Male", shift_timing="5 hours", age_from=18, age_to=50,
             min_salary=3500, max_salary=4200, description="Data entry work."),
    ]
    for j in jobs:
        db.add(Job(recruiter_id=rec.id, currency="PLN", openings=2, status="open", **j))
    print("seeded jobs")

db.commit()
print("plans:", db.query(SubscriptionPlan).count(), "| jobs:", db.query(Job).count())
