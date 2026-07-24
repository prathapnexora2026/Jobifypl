"""Recruiter endpoints — profile/onboarding, 5-step post-a-job, dashboard,
manage jobs, view applicants, packages (wallet-based), payment history.

All routes require a recruiter JWT.
"""
import datetime as dt
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User, Role, RecruiterProfile, Job, JobApplication, CandidateProfile,
    CandidateDocument, Wallet, WalletTransaction, SubscriptionPlan,
    UserSubscription, Notification, CustomOption,
)

# Human labels for the document types a candidate can upload (recruiter CV view).
DOC_LABELS = {
    "resume": "Resume / CV", "passport": "Passport", "trc_card": "TRC Card",
    "pesel": "PESEL", "driving_license": "Driving License",
    "student_card": "Student Card", "other": "Other Document",
}
from app.security import get_current_user

router = APIRouter(prefix="/recruiter", tags=["recruiter"])

# Uploads live on the persistent disk in production (see app/paths.py).
from app.paths import UPLOADS_DIR as UPLOAD_DIR


def require_recruiter(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.recruiter:
        raise HTTPException(403, "Recruiters only")
    return user


def _wallet(db, uid):
    w = db.query(Wallet).filter(Wallet.user_id == uid).first()
    if not w:
        w = Wallet(user_id=uid, balance=0.0, currency="PLN")
        db.add(w); db.commit(); db.refresh(w)
    return w


# ---------- Profile / onboarding / edit ----------
class RecProfileIn(BaseModel):
    company_name: str | None = None
    contact_position: str | None = None
    hiring_authority: str | None = None
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    company_email: str | None = None
    actively_hiring: bool | None = None


def _profile_dict(p: RecruiterProfile, user: User):
    return {
        "company_name": p.company_name, "contact_position": p.contact_position,
        "hiring_authority": p.hiring_authority, "first_name": p.first_name,
        "middle_name": p.middle_name, "last_name": p.last_name,
        "company_email": p.company_email, "profile_pic": p.profile_pic,
        "cover_pic": p.cover_pic, "actively_hiring": p.actively_hiring,
        "profile_views": p.profile_views, "verified": p.verified,
        "can_post_jobs": p.can_post_jobs, "onboarding_completed": p.onboarding_completed,
        "phone": user.phone, "email": user.email,
    }


@router.get("/profile")
def get_profile(user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    p = user.recruiter_profile
    if not p:
        p = RecruiterProfile(user_id=user.id)
        db.add(p); db.commit(); db.refresh(p)
    return {"status": "success", "profile": _profile_dict(p, user)}


@router.post("/profile")
def save_profile(body: RecProfileIn, user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    p = user.recruiter_profile or RecruiterProfile(user_id=user.id)
    for f, v in body.model_dump(exclude_unset=True).items():
        setattr(p, f, v)
    # Once they have a name/company they can post (production waits for admin verify).
    if p.company_name or (p.first_name and p.last_name):
        p.onboarding_completed = True
        p.can_post_jobs = True
        p.verified = True
    db.add(p)
    if body.company_name:
        user.full_name = body.company_name
    elif body.first_name or body.last_name:
        user.full_name = f"{p.first_name or ''} {p.last_name or ''}".strip()
    if body.company_email:
        user.email = body.company_email
    db.commit()
    return {"status": "success", "can_post_jobs": p.can_post_jobs, "profile": _profile_dict(p, user)}


@router.post("/photo")
def upload_photo(kind: str = "profile", file: UploadFile = File(...),
                 user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    safe = f"rec_{kind}_{user.id}_{uuid.uuid4().hex}{ext}"
    with (UPLOAD_DIR / safe).open("wb") as out:
        shutil.copyfileobj(file.file, out)
    p = user.recruiter_profile or RecruiterProfile(user_id=user.id)
    if kind == "cover":
        p.cover_pic = f"/uploads/{safe}"
    else:
        p.profile_pic = f"/uploads/{safe}"
    db.add(p); db.commit()
    return {"status": "success", "url": f"/uploads/{safe}"}


# ---------- Post a Job (5-step wizard submits one payload) ----------
class JobIn(BaseModel):
    # Step 1 — Job Details
    category: str
    position: str | None = None
    shift_timing: str | None = None
    job_type: str | None = None
    work_type: str | None = None
    languages_required: str | None = None
    location: str | None = None
    street: str | None = None
    joining: str | None = "Immediate Joining"
    need_work_permit: bool | None = False
    accommodation: str | None = None
    charges_fee: bool | None = False
    # Step 2 — Candidate Requirements
    nationalities: str | None = None
    age_from: int | None = None
    age_to: int | None = None
    gender_pref: str | None = None
    accepts_to: str | None = None
    # Step 3 — Description
    description: str | None = None
    # Step 4 — Hiring Authority
    hiring_authority: str | None = None
    contact_first_name: str | None = None
    contact_middle_name: str | None = None
    contact_last_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    # salary / openings
    min_salary: int | None = None
    max_salary: int | None = None
    openings: int | None = 1


class JobEditIn(JobIn):
    """Same shape as JobIn but every field optional — edits send only what changed.
    (JobIn requires `category`; an edit that doesn't re-send it must not 422.)"""
    category: str | None = None


def _active_sub(db, uid):
    """The recruiter's current active, non-expired subscription (or None)."""
    now = dt.datetime.utcnow()
    return (db.query(UserSubscription)
            .filter(UserSubscription.user_id == uid, UserSubscription.status == "active")
            .filter((UserSubscription.end_date == None) | (UserSubscription.end_date >= now))
            .order_by(UserSubscription.start_date.desc()).first())


@router.post("/jobs")
def post_job(body: JobIn, user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    p = user.recruiter_profile
    if not p or not p.can_post_jobs:
        raise HTTPException(403, "Complete your profile before posting jobs")
    # POSTING QUOTA: recruiter must have an active plan with remaining postings.
    sub = _active_sub(db, user.id)
    if not sub:
        raise HTTPException(402, "No active plan. Choose a plan to post jobs.")
    if (sub.posts_used or 0) >= (sub.posts_total or 0):
        raise HTTPException(402, "Your plan's job-post limit is used up. Upgrade to post more.")

    # Remember contact details on the global profile so we don't re-ask next time.
    # Only fill blanks — never overwrite what the recruiter already saved.
    if body.contact_email and not p.company_email:
        p.company_email = body.contact_email
    if body.contact_email and not user.email:
        user.email = body.contact_email
    if body.contact_first_name and not p.first_name:
        p.first_name = body.contact_first_name
    if body.contact_last_name and not p.last_name:
        p.last_name = body.contact_last_name
    if body.hiring_authority and not p.hiring_authority:
        p.hiring_authority = body.hiring_authority

    company = p.company_name or f"{p.first_name or ''} {p.last_name or ''}".strip() or "Self-Hiring"
    if body.hiring_authority == "Self-Hiring":
        company = "Self-Hiring"
    job = Job(
        recruiter_id=user.id, title=body.category, company_name=company,
        position=body.position, description=body.description, category=body.category,
        location=body.location, job_type=body.job_type, work_type=body.work_type,
        gender_pref=body.gender_pref, shift_timing=body.shift_timing,
        age_from=body.age_from, age_to=body.age_to, min_salary=body.min_salary,
        max_salary=body.max_salary, currency="PLN", openings=body.openings or 1,
        languages_required=body.languages_required, street=body.street,
        joining=body.joining, need_work_permit=bool(body.need_work_permit),
        accommodation=body.accommodation, charges_fee=bool(body.charges_fee),
        nationalities=body.nationalities, accepts_to=body.accepts_to,
        hiring_authority=body.hiring_authority,
        contact_first_name=body.contact_first_name, contact_middle_name=body.contact_middle_name,
        contact_last_name=body.contact_last_name, contact_phone=body.contact_phone,
        contact_email=body.contact_email, status="open",
    )
    db.add(job); db.flush()
    # consume one posting from the plan quota
    sub.posts_used = (sub.posts_used or 0) + 1
    # notify all candidates that a new job was posted (they can tap to view/apply)
    cand_ids = [r[0] for r in db.query(User.id).filter(User.role == Role.candidate).all()]
    title = body.position or body.category or "New job"
    for cid in cand_ids:
        db.add(Notification(user_id=cid, title="New job posted",
                            company=company, body=f"{title} in {body.location or 'Poland'} — tap to view.",
                            job_id=job.id))
    db.commit(); db.refresh(job)
    remaining = (sub.posts_total or 0) - (sub.posts_used or 0)
    return {"status": "success", "job_id": job.id, "title": job.title, "posts_remaining": remaining}


@router.get("/jobs")
def my_jobs(user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(Job.recruiter_id == user.id).order_by(Job.created_at.desc()).all()
    out = []
    for j in jobs:
        applied = db.query(JobApplication).filter(
            JobApplication.job_id == j.id, JobApplication.applied == True).count()
        interested = db.query(JobApplication).filter(
            JobApplication.job_id == j.id, JobApplication.interested == True).count()
        out.append({"id": j.id, "title": j.title, "location": j.location or "N/A",
                    "gender_pref": j.gender_pref, "joining": j.joining, "status": j.status,
                    "job_type": j.job_type, "work_type": j.work_type, "category": j.category,
                    "views": j.views or 0,
                    # full fields so the Edit wizard can prefill every step
                    "position": j.position, "shift_timing": j.shift_timing,
                    "languages_required": j.languages_required, "street": j.street,
                    "need_work_permit": j.need_work_permit, "accommodation": j.accommodation,
                    "charges_fee": j.charges_fee, "nationalities": j.nationalities,
                    "age_from": j.age_from, "age_to": j.age_to, "accepts_to": j.accepts_to,
                    "description": j.description, "hiring_authority": j.hiring_authority,
                    "contact_first_name": j.contact_first_name, "contact_middle_name": j.contact_middle_name,
                    "contact_last_name": j.contact_last_name, "contact_phone": j.contact_phone,
                    "contact_email": j.contact_email,
                    "created_at": f"{j.created_at.month}/{j.created_at.day}/{j.created_at.year}" if j.created_at else "",
                    "applied_count": applied, "interested_count": interested})
    return {"status": "success", "jobs": out}


# ---------- Edit a posted job ----------
@router.put("/jobs/{job_id}")
def edit_my_job(job_id: int, body: JobEditIn, user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.recruiter_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in {"need_work_permit", "charges_fee"}:
            value = bool(value)
        setattr(job, field, value)
    if body.category:
        job.title = body.category
    db.commit()
    return {"status": "success", "job_id": job.id, "title": job.title}


@router.delete("/jobs/{job_id}")
def delete_job(job_id: int, user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.recruiter_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    db.query(JobApplication).filter(JobApplication.job_id == job_id).delete()
    db.delete(job); db.commit()
    return {"status": "success"}


# ---------- Dashboard ----------
@router.get("/dashboard")
def dashboard(user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    p = user.recruiter_profile or RecruiterProfile(user_id=user.id)
    my_jobs_q = db.query(Job).filter(Job.recruiter_id == user.id).all()
    jobs_posted = len(my_jobs_q)
    job_ids = [j.id for j in my_jobs_q]
    total_views = sum((j.views or 0) for j in my_jobs_q)   # real views across all this recruiter's jobs
    interested = 0
    if job_ids:
        interested = db.query(JobApplication).filter(
            JobApplication.job_id.in_(job_ids), JobApplication.interested == True).count()
    # unread message count (conversations where this recruiter is a party)
    from app.models import Conversation, Message
    convs = db.query(Conversation).filter(
        (Conversation.candidate_id == user.id) | (Conversation.recruiter_id == user.id)).all()
    messages = 0
    for c in convs:
        messages += db.query(Message).filter(
            Message.conversation_id == c.id, Message.sender_id != user.id, Message.is_read == False).count()
    sub = _active_sub(db, user.id)
    package = None
    if sub:
        pl = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first()
        package = {"name": pl.name if pl else "Plan", "price": pl.price if pl else 0,
                   "currency": pl.currency if pl else "PLN",
                   "postings": sub.posts_total or 0, "used": sub.posts_used or 0,
                   "remaining": max(0, (sub.posts_total or 0) - (sub.posts_used or 0)),
                   "expires": sub.end_date.strftime("%d %b, %Y") if sub.end_date else "N/A"}
    return {"status": "success",
            "welcome_name": user.full_name or "Recruiter",
            "actively_hiring": p.actively_hiring,
            "profile_views": total_views, "jobs_posted": jobs_posted,
            "interested_candidates": interested, "messages": messages,
            "package": package}


# ---------- Applicants ----------
@router.get("/jobs/{job_id}/applicants")
def applicants(job_id: int, user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.recruiter_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    rows = (
        db.query(JobApplication, User, CandidateProfile)
        .join(User, User.id == JobApplication.candidate_id)
        .outerjoin(CandidateProfile, CandidateProfile.user_id == User.id)
        .filter(JobApplication.job_id == job_id, JobApplication.applied == True)
        .all()
    )
    # Recruiter is now viewing these applicants → mark "recruiter_seen" (so the
    # candidate's tracker shows 'Recruiter seen' truthfully). Don't downgrade
    # anyone already at 'recruiter_contacted'.
    db.query(JobApplication).filter(
        JobApplication.job_id == job_id,
        JobApplication.applied == True,
        JobApplication.track_status == "application_sent",
    ).update({"track_status": "recruiter_seen"})
    db.commit()

    def _docs_for(cid: int):
        docs = db.query(CandidateDocument).filter(CandidateDocument.user_id == cid).all()
        out = [{"id": d.id, "type": d.doc_type,
                "label": DOC_LABELS.get(d.doc_type, d.doc_type.replace("_", " ").title()),
                "name": d.original_name or DOC_LABELS.get(d.doc_type, d.doc_type),
                "file": d.file_path} for d in docs]
        # resume first so the recruiter sees it at the top of the CV view
        out.sort(key=lambda x: 0 if x["type"] == "resume" else 1)
        return out

    applicants = []
    for a, u, cp in rows:
        docs = _docs_for(u.id)
        resume = next((d for d in docs if d["type"] == "resume"), None)
        applicants.append({
            "application_id": a.id, "status": a.status, "track_status": a.track_status,
            "candidate_id": u.id, "phone": u.phone,
            "name": f"{(cp.first_name if cp else '') or ''} {(cp.last_name if cp else '') or ''}".strip() or (u.full_name or "Candidate"),
            "photo": (cp.profile_photo if cp else None),
            "dob": cp.dob if cp else None,
            "gender": cp.gender if cp else None,
            "nationality": cp.nationality if cp else None,
            "qualification": cp.qualification if cp else None,
            "is_student": bool(cp.is_student) if cp else False,
            "languages": cp.languages if cp else None,
            "email": (cp.email if cp and cp.email else u.email),
            "documents": docs,                 # names + files (view links)
            "resume": resume,                  # the mandatory resume, if uploaded
        })
    return {"status": "success", "job_title": job.title, "applicants": applicants}


@router.put("/applications/{application_id}/status")
def update_application_status(application_id: int, status: str,
                              user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    valid = {"applied", "shortlisted", "interview", "rejected", "hired"}
    if status not in valid:
        raise HTTPException(400, f"status must be one of {sorted(valid)}")
    row = (db.query(JobApplication).join(Job, Job.id == JobApplication.job_id)
           .filter(JobApplication.id == application_id, Job.recruiter_id == user.id).first())
    if not row:
        raise HTTPException(404, "Application not found")
    row.status = status
    if status in ("shortlisted", "interview", "hired"):
        row.track_status = "recruiter_contacted"
    # notify candidate
    db.add(Notification(user_id=row.candidate_id, title="Application update",
                        body=f"A recruiter marked your application as {status}."))
    db.commit()
    return {"status": "success"}


@router.post("/applications/{application_id}/contact")
def mark_contacted(application_id: int, user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    row = (db.query(JobApplication).join(Job, Job.id == JobApplication.job_id)
           .filter(JobApplication.id == application_id, Job.recruiter_id == user.id).first())
    if not row:
        raise HTTPException(404, "Application not found")
    row.track_status = "recruiter_contacted"
    db.add(Notification(user_id=row.candidate_id, title="Recruiter contacted you",
                        body="A recruiter has contacted you about your application."))
    db.commit()
    return {"status": "success"}


# ---------- Packages (recruiter plans, wallet-based) ----------
@router.get("/packages")
def packages(user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    rows = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.is_active == True, SubscriptionPlan.for_role == "recruiter"
    ).order_by(SubscriptionPlan.price).all()
    current = (db.query(UserSubscription, SubscriptionPlan)
               .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.plan_id)
               .filter(UserSubscription.user_id == user.id, UserSubscription.status == "active")
               .order_by(UserSubscription.start_date.desc()).first())
    current_name = current[1].name if current else None
    current_expires = current[0].end_date.strftime("%Y-%m-%d %H:%M:%S") if current and current[0].end_date else None
    return {"status": "success", "current_plan": current_name, "current_expires": current_expires,
            "wallet": _wallet(db, user.id).balance,
            "packages": [
                {"id": p.id, "name": p.name, "price": p.price, "currency": p.currency,
                 "postings": p.postings, "duration_days": p.duration_days,
                 "features": (p.features or "").split("\n") if p.features else []}
                for p in rows
            ]}


class BuyIn(BaseModel):
    plan_id: int


@router.post("/packages/buy")
def buy_package(body: BuyIn, user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == body.plan_id, SubscriptionPlan.for_role == "recruiter").first()
    if not plan:
        raise HTTPException(404, "Package not found")
    w = _wallet(db, user.id)
    if w.balance < plan.price:
        raise HTTPException(400, f"Insufficient wallet balance. Need {plan.price} PLN, top up first.")
    w.balance -= plan.price
    w.total_spent += plan.price
    db.add(WalletTransaction(user_id=user.id, amount=plan.price, type="debit",
                            reason=f"{plan.name} Plan ({plan.duration_days} Days)"))
    # deactivate old, activate new
    db.query(UserSubscription).filter(
        UserSubscription.user_id == user.id, UserSubscription.status == "active"
    ).update({"status": "expired"})
    start = dt.datetime.utcnow()
    db.add(UserSubscription(user_id=user.id, plan_id=plan.id, start_date=start,
                           end_date=start + dt.timedelta(days=plan.duration_days or 30), status="active",
                           posts_total=plan.postings or 0, posts_used=0))
    p = user.recruiter_profile
    if p:
        p.can_post_jobs = True
    db.commit()
    return {"status": "success", "msg": f"{plan.name} activated", "balance": w.balance,
            "plan_name": plan.name, "posts_total": plan.postings or 0, "posts_used": 0}


@router.get("/quota")
def quota(user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Current plan + how many job posts are total / used / remaining (for the dashboard popup)."""
    sub = _active_sub(db, user.id)
    if not sub:
        return {"status": "success", "has_plan": False, "plan_name": None,
                "posts_total": 0, "posts_used": 0, "posts_remaining": 0, "expires": None}
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == sub.plan_id).first()
    total = sub.posts_total or 0
    used = sub.posts_used or 0
    return {"status": "success", "has_plan": True,
            "plan_name": plan.name if plan else "Plan",
            "posts_total": total, "posts_used": used,
            "posts_remaining": max(0, total - used),
            "expires": sub.end_date.strftime("%d %b %Y") if sub.end_date else None}


@router.get("/payments")
def payment_history(user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    rows = db.query(WalletTransaction).filter(
        WalletTransaction.user_id == user.id, WalletTransaction.type == "debit"
    ).order_by(WalletTransaction.created_at.desc()).all()
    return {"status": "success", "payments": [
        {"date": t.created_at.strftime("%b %d, %Y"), "description": t.reason,
         "amount": f"{t.amount:.2f}", "status": "active"} for t in rows
    ]}


# ======================= RECRUITER PAYMENTS (PayU) =======================
# Card details are entered on PayU's secure hosted page; we only ever act on a
# signature-verified webhook (see app/routers/payu_router.py). Wallet balance is
# credited / a package is activated only AFTER PayU confirms the money.
from app.config import settings as _settings
from app.services import payu as _payu
from app.models import Payment as _Payment


def activate_recruiter_package(db: Session, user_id: int, plan: SubscriptionPlan):
    """Activate a recruiter package (shared by wallet + PayU paths). Deactivates
    any current plan, starts the new one with its posting quota, enables posting,
    and notifies the recruiter. Does NOT touch wallet balance (caller decides)."""
    db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id, UserSubscription.status == "active"
    ).update({"status": "expired"})
    start = dt.datetime.utcnow()
    end = start + dt.timedelta(days=plan.duration_days or 30)
    db.add(UserSubscription(user_id=user_id, plan_id=plan.id, start_date=start, end_date=end,
                            status="active", posts_total=plan.postings or 0, posts_used=0))
    prof = db.query(RecruiterProfile).filter(RecruiterProfile.user_id == user_id).first()
    if prof:
        prof.can_post_jobs = True
    db.add(Notification(user_id=user_id, title="Plan activated",
                        body=f"{plan.name} is active. You can post {plan.postings or 0} job(s) until {end.date().isoformat()}."))


class RecTopupIn(BaseModel):
    amount: float


@router.post("/wallet/topup-checkout")
def rec_topup_checkout(body: RecTopupIn, user: User = Depends(require_recruiter),
                       db: Session = Depends(get_db)):
    """Start a real PayU top-up for a recruiter. Returns a redirect URL; wallet
    is credited later by the verified webhook. Falls back to instant credit in
    test mode (PAYU_ENABLED=false)."""
    if body.amount <= 0:
        raise HTTPException(400, "Invalid amount")
    if not _settings.PAYU_ENABLED:
        w = _wallet(db, user.id)
        w.balance += body.amount
        db.add(WalletTransaction(user_id=user.id, amount=body.amount, type="credit",
                                reason="Wallet top-up (test mode)"))
        db.commit()
        return {"status": "success", "paid": True, "balance": w.balance}
    ext = _payu.new_ext_order_id("recwallet", user.id)
    pay = _Payment(user_id=user.id, ext_order_id=ext, amount=body.amount, currency="PLN",
                   purpose="wallet_topup", status="pending")
    db.add(pay); db.commit()
    try:
        res = _payu.create_order(
            ext_order_id=ext, amount_pln=body.amount,
            description=f"JobifyPL recruiter wallet top-up ({body.amount:.2f} PLN)",
            buyer_email=user.email or "", buyer_phone=user.phone or "")
    except Exception as e:
        pay.status = "failed"; db.commit()
        raise HTTPException(502, f"Payment gateway error: {e}")
    pay.payu_order_id = res.get("payu_order_id"); db.commit()
    return {"status": "success", "paid": False, "redirect_url": res["redirect_uri"], "ext_order_id": ext}


@router.post("/packages/checkout")
def rec_package_checkout(body: BuyIn, user: User = Depends(require_recruiter),
                         db: Session = Depends(get_db)):
    """Buy a recruiter package by paying DIRECTLY via PayU. Package activates
    after the verified webhook. Falls back to instant activate in test mode."""
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == body.plan_id, SubscriptionPlan.for_role == "recruiter").first()
    if not plan:
        raise HTTPException(404, "Package not found")
    if not _settings.PAYU_ENABLED:
        w = _wallet(db, user.id)
        w.total_spent += plan.price
        db.add(WalletTransaction(user_id=user.id, amount=plan.price, type="debit",
                                reason=f"{plan.name} Plan (test)"))
        activate_recruiter_package(db, user.id, plan)
        db.commit()
        return {"status": "success", "paid": True, "plan_name": plan.name,
                "posts_total": plan.postings or 0}
    ext = _payu.new_ext_order_id("recplan", user.id)
    pay = _Payment(user_id=user.id, ext_order_id=ext, amount=plan.price,
                   currency=plan.currency or "PLN", purpose="rec_plan", plan_id=plan.id,
                   status="pending")
    db.add(pay); db.commit()
    try:
        res = _payu.create_order(
            ext_order_id=ext, amount_pln=plan.price,
            description=f"JobifyPL recruiter package: {plan.name}",
            buyer_email=user.email or "", buyer_phone=user.phone or "")
    except Exception as e:
        pay.status = "failed"; db.commit()
        raise HTTPException(502, f"Payment gateway error: {e}")
    pay.payu_order_id = res.get("payu_order_id"); db.commit()
    return {"status": "success", "paid": False, "redirect_url": res["redirect_uri"], "ext_order_id": ext}


@router.get("/payment-status/{ext_order_id}")
def rec_payment_status(ext_order_id: str, user: User = Depends(require_recruiter),
                       db: Session = Depends(get_db)):
    pay = db.query(_Payment).filter(
        _Payment.ext_order_id == ext_order_id, _Payment.user_id == user.id).first()
    if not pay:
        raise HTTPException(404, "Payment not found")
    return {"status": "success", "payment_status": pay.status, "fulfilled": pay.fulfilled}


# ---------- Custom dropdown options (languages, cities) shared across recruiters ----------
_ALLOWED_OPTION_FIELDS = {"language", "city"}


@router.get("/options/{field}")
def get_custom_options(field: str, user: User = Depends(require_recruiter),
                       db: Session = Depends(get_db)):
    """Return the recruiter-added values for a field (merged with the fixed list
    on the frontend). field ∈ {language, city}."""
    if field not in _ALLOWED_OPTION_FIELDS:
        raise HTTPException(400, "Unsupported field")
    rows = db.query(CustomOption).filter(CustomOption.field == field)\
        .order_by(CustomOption.value).all()
    return {"status": "success", "options": [r.value for r in rows]}


class AddOptionIn(BaseModel):
    value: str


@router.post("/options/{field}")
def add_custom_option(field: str, body: AddOptionIn,
                      user: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    """Add a new value to a field's shared option list (once), so every recruiter
    sees it afterwards. Case-insensitive de-dupe."""
    if field not in _ALLOWED_OPTION_FIELDS:
        raise HTTPException(400, "Unsupported field")
    val = (body.value or "").strip()
    if not val:
        raise HTTPException(400, "Value required")
    if len(val) > 120:
        raise HTTPException(400, "Value too long")
    exists = db.query(CustomOption).filter(
        CustomOption.field == field,
        func.lower(CustomOption.value) == val.lower()).first()
    if not exists:
        db.add(CustomOption(field=field, value=val, created_by=user.id))
        db.commit()
    return {"status": "success", "value": val}
