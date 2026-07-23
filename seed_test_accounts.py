"""Seed two ready-to-use test accounts (recruiter + candidate) with documents
and one real job, so the full candidate->apply->message->recruiter loop can be
tested end to end. Idempotent: safe to run repeatedly (re-uses accounts by phone).

Run:  python seed_test_accounts.py
"""
import os
import shutil
import uuid

from app.database import SessionLocal, engine, Base
from app.models import (
    User, Role, CandidateProfile, RecruiterProfile, CandidateDocument,
    Wallet, Job,
)

UPLOADS = os.path.join(os.path.dirname(__file__), "uploads")

# real sample images already in uploads/ (candidate #2's originals) — reuse as sources
DOC_SOURCES = {
    "passport":        "2_passport_7e630f46b8fd4ed780517414fa32be6a.jpeg",
    "trc_card":        "2_trc_card_03905346adaf451c886cdbe47a5cf4d7.jpeg",
    "pesel":           "2_pesel_8051705c30bf4a53a2ef6a819c2e98cb.jpeg",
    "driving_license": "2_driving_license_a80c664ea27841cca03076a3a7cba5e5.jpeg",
}

REC_PHONE = "+48730100200"
CAND_PHONE = "+48730300400"


def get_or_create_user(db, phone, role, full_name):
    u = db.query(User).filter(User.phone == phone).first()
    if not u:
        u = User(phone=phone, role=role, full_name=full_name, phone_verified=True)
        db.add(u)
        db.flush()
        db.add(Wallet(user_id=u.id, balance=0.0, currency="PLN"))
    else:
        u.role = role
        u.full_name = full_name
    return u


def copy_doc(user_id, doc_type):
    src = os.path.join(UPLOADS, DOC_SOURCES[doc_type])
    if not os.path.exists(src):
        return None
    ext = os.path.splitext(src)[1]
    fname = f"{user_id}_{doc_type}_{uuid.uuid4().hex}{ext}"
    dst = os.path.join(UPLOADS, fname)
    shutil.copyfile(src, dst)
    return fname


def main():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # ---------- RECRUITER (ready to post) ----------
        rec = get_or_create_user(db, REC_PHONE, Role.recruiter, "Marek Nowak")
        rp = db.query(RecruiterProfile).filter(RecruiterProfile.user_id == rec.id).first()
        if not rp:
            rp = RecruiterProfile(user_id=rec.id)
            db.add(rp)
        rp.company_name = "GreenField Logistics Sp. z o.o."
        rp.contact_position = "HR Manager"
        rp.hiring_authority = "Company"
        rp.first_name = "Marek"
        rp.last_name = "Nowak"
        rp.company_email = "hr@greenfield-logistics.pl"
        rp.verified = True
        rp.can_post_jobs = True
        rp.onboarding_completed = True
        db.flush()

        # a real, ready job for this recruiter (so candidate can apply)
        existing_job = db.query(Job).filter(
            Job.recruiter_id == rec.id, Job.title == "Warehouse Operator (Test)"
        ).first()
        if not existing_job:
            db.add(Job(
                recruiter_id=rec.id,
                title="Warehouse Operator (Test)",
                company_name=rp.company_name,
                position="Warehouse Operator",
                description=("We are hiring warehouse operators for our logistics centre near "
                             "Warsaw. Duties include picking, packing and loading. Training "
                             "provided. Accommodation available. Immediate joining."),
                category="WAREHOUSE JOB",
                location="Warszawa",
                job_type="Regular Job",
                work_type="Full Time",
                gender_pref="Any",
                shift_timing="8 hours",
                age_from=18, age_to=45,
                min_salary=4500, max_salary=6000, currency="PLN",
                openings=5,
                status="open",
                languages_required="Basic English",
                joining="Immediate Joining",
                need_work_permit=False,
                accommodation="Free",
                charges_fee=False,
                nationalities="Nepal & Philippines",
                accepts_to="All are eligible",
                hiring_authority="Company",
                contact_first_name="Marek", contact_last_name="Nowak",
                contact_phone=REC_PHONE, contact_email=rp.company_email,
            ))

        # ---------- CANDIDATE (docs filled, ready to apply) ----------
        cand = get_or_create_user(db, CAND_PHONE, Role.candidate, "Anna Wiśniewska")
        cp = db.query(CandidateProfile).filter(CandidateProfile.user_id == cand.id).first()
        if not cp:
            cp = CandidateProfile(user_id=cand.id)
            db.add(cp)
        cp.first_name = "Anna"
        cp.last_name = "Wiśniewska"
        cp.dob = "1998-04-12"
        cp.gender = "Female"
        cp.nationality = "Poland"
        cp.qualification = "Bachelor's Degree"
        cp.is_student = False
        cp.languages = "Polish, English"
        cp.email = "anna.wisniewska@example.com"
        cp.status_label = "Active Looking"
        cp.onboarding_completed = True
        db.flush()

        # documents (skip-method style is for onboarding; here we attach real ones)
        have = {d.doc_type for d in db.query(CandidateDocument)
                .filter(CandidateDocument.user_id == cand.id).all()}
        for doc_type in ("passport", "pesel", "trc_card", "driving_license"):
            if doc_type in have:
                continue
            fname = copy_doc(cand.id, doc_type)
            if fname:
                db.add(CandidateDocument(
                    user_id=cand.id, doc_type=doc_type, file_path=fname,
                    original_name=f"{doc_type}.jpeg",
                ))

        db.commit()

        print("SEED OK")
        print(f"  RECRUITER  id={rec.id}  {rp.first_name} {rp.last_name}  ({rp.company_name})  phone={REC_PHONE}")
        print(f"  CANDIDATE  id={cand.id}  {cp.first_name} {cp.last_name}  phone={CAND_PHONE}")
        job = db.query(Job).filter(Job.recruiter_id == rec.id).order_by(Job.id.desc()).first()
        print(f"  JOB        id={job.id}  {job.position} @ {job.location}")
        ndocs = db.query(CandidateDocument).filter(CandidateDocument.user_id == cand.id).count()
        print(f"  DOCS       candidate has {ndocs} documents attached")
    finally:
        db.close()


if __name__ == "__main__":
    main()
