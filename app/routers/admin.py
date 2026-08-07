"""Admin endpoints — power the admin dashboard.

Every endpoint requires the admin role (require_admin). Mirrors the reference
admin panel: dashboard stats, users, jobs, applications, plans, payments, logs.
"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from app.paths import UPLOADS_DIR
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User, Role, CandidateProfile, RecruiterProfile, CandidateDocument,
    Job, JobApplication, SubscriptionPlan, UserSubscription,
    WalletTransaction, ContactMessage, Wallet, Notification, CustomOption,
)
from app.security import require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


# ============================ DASHBOARD ============================
@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    total_candidates = db.query(User).filter(User.role == Role.candidate).count()
    total_recruiters = db.query(User).filter(User.role == Role.recruiter).count()
    total_jobs = db.query(Job).count()
    total_apps = db.query(JobApplication).count()

    # recent jobs
    recent_jobs = (
        db.query(Job).order_by(Job.created_at.desc()).limit(6).all()
    )
    jobs_out = [{
        "id": j.id, "category": j.category, "position": j.position,
        "gender_pref": j.gender_pref, "shift_timing": j.shift_timing,
        "job_type": j.job_type, "work_type": j.work_type,
        "created_at": j.created_at.isoformat() if j.created_at else None,
    } for j in recent_jobs]

    # recent applicants (join candidate profile for name/photo)
    recent = (
        db.query(JobApplication, CandidateProfile, Job)
        .join(CandidateProfile, CandidateProfile.user_id == JobApplication.candidate_id)
        .join(Job, Job.id == JobApplication.job_id)
        .order_by(JobApplication.applied_at.desc())
        .limit(6).all()
    )
    applicants_out = [{
        "first_name": cp.first_name, "middle_name": cp.middle_name,
        "last_name": cp.last_name, "profile_photo": cp.profile_photo,
        "applied_role": job.category, "applied_at": app.applied_at.isoformat() if app.applied_at else None,
    } for app, cp, job in recent]

    return {
        "status": "success",
        "stats": {
            "candidates": total_candidates, "recruiters": total_recruiters,
            "jobs": total_jobs, "applications": total_apps,
        },
        "recent_jobs": jobs_out,
        "recent_applicants": applicants_out,
    }


@router.get("/calendar")
def calendar_day(date: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Everything that happened on a given day (date = 'YYYY-MM-DD'):
    jobs posted, candidates registered, recruiters registered, payments made."""
    from datetime import datetime, timedelta
    try:
        day = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    # jobs posted that day
    jobs = (
        db.query(Job, RecruiterProfile)
        .outerjoin(RecruiterProfile, RecruiterProfile.user_id == Job.recruiter_id)
        .filter(Job.created_at >= start, Job.created_at < end)
        .order_by(Job.created_at.desc()).all()
    )
    jobs_out = [{
        "id": j.id, "position": j.position, "category": j.category,
        "location": j.location, "job_type": j.job_type, "work_type": j.work_type,
        "recruiter": (f"{rp.first_name or ''} {rp.last_name or ''}".strip() or (rp.company_name or "")) if rp else "",
    } for j, rp in jobs]

    # users registered that day (split by role)
    users = db.query(User).filter(User.created_at >= start, User.created_at < end).all()
    cands, recs = [], []
    for u in users:
        if u.role == Role.candidate:
            cp = u.candidate_profile
            cands.append({"id": u.id, "name": (f"{cp.first_name or ''} {cp.last_name or ''}".strip() if cp else "") or u.full_name or u.phone,
                          "photo": cp.profile_photo if cp else ""})
        elif u.role == Role.recruiter:
            rp = u.recruiter_profile
            recs.append({"id": u.id, "name": (f"{rp.first_name or ''} {rp.last_name or ''}".strip() if rp else "") or (rp.company_name if rp else "") or u.full_name or u.phone,
                         "company": rp.company_name if rp else "", "photo": rp.profile_pic if rp else ""})

    # payments that day (credits = money in)
    pays = (
        db.query(WalletTransaction, User)
        .outerjoin(User, User.id == WalletTransaction.user_id)
        .filter(WalletTransaction.created_at >= start, WalletTransaction.created_at < end)
        .order_by(WalletTransaction.created_at.desc()).all()
    )
    pays_out = [{
        "id": t.id, "amount": t.amount, "type": t.type, "reason": t.reason,
        "user": (u.full_name or u.phone) if u else "",
    } for t, u in pays]

    return {
        "status": "success", "date": date,
        "jobs": jobs_out, "candidates": cands, "recruiters": recs, "payments": pays_out,
        "counts": {"jobs": len(jobs_out), "candidates": len(cands),
                   "recruiters": len(recs), "payments": len(pays_out)},
    }


# ============================ USERS ============================
@router.get("/users")
def get_all_users(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    users = db.query(User).filter(User.role != Role.admin).all()
    out = []
    for u in users:
        row = {
            "id": u.id, "name": u.full_name or "", "email": u.email or "",
            "phone": u.phone, "type": u.role.value.capitalize(), "img": "",
            "role": "", "Sector": "",
        }
        if u.role == Role.candidate and u.candidate_profile:
            cp = u.candidate_profile
            row["name"] = f"{cp.first_name or ''} {cp.last_name or ''}".strip() or row["name"]
            row["img"] = cp.profile_photo or ""
            row["role"] = cp.qualification or ""
            row["email"] = cp.email or u.email or ""
        elif u.role == Role.recruiter and u.recruiter_profile:
            rp = u.recruiter_profile
            row["name"] = f"{rp.first_name or ''} {rp.last_name or ''}".strip() or (rp.company_name or row["name"])
            row["img"] = rp.profile_pic or ""
            row["role"] = rp.contact_position or ""
            row["Sector"] = rp.company_name or "company"
            row["email"] = rp.company_email or u.email or ""
        out.append(row)
    return {"status": "success", "users": out}


@router.get("/candidate/{user_id}")
def candidate_detail(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == user_id, User.role == Role.candidate).first()
    if not u:
        raise HTTPException(404, "Candidate not found")
    cp = u.candidate_profile
    docs = db.query(CandidateDocument).filter(CandidateDocument.user_id == user_id).all()
    app_rows = (
        db.query(JobApplication, Job)
        .join(Job, Job.id == JobApplication.job_id)
        .filter(JobApplication.candidate_id == user_id)
        .order_by(JobApplication.id.desc()).all()
    )
    applied_jobs = [{
        "category": j.category, "position": j.position, "job_type": j.job_type,
        "work_type": j.work_type,
        "applied_at": ja.applied_at.isoformat() if ja.applied_at else None,
        "status": ja.status,
    } for ja, j in app_rows]
    # current candidate subscription plan (if any)
    sub = (
        db.query(UserSubscription, SubscriptionPlan)
        .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.plan_id)
        .filter(UserSubscription.user_id == user_id, UserSubscription.status == "active")
        .order_by(UserSubscription.id.desc()).first()
    )
    plan_out = None
    if sub:
        us, plan = sub
        plan_out = {
            "name": plan.name, "price": plan.price, "currency": plan.currency,
            "features": plan.features, "duration_days": plan.duration_days,
            "start_date": us.start_date.isoformat() if us.start_date else None,
            "end_date": us.end_date.isoformat() if us.end_date else None,
        }
    cwal = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    return {
        "status": "success",
        "data": {
            "id": u.id, "phone": u.phone, "role": "Candidate",
            "first_name": cp.first_name if cp else "", "middle_name": cp.middle_name if cp else "",
            "last_name": cp.last_name if cp else "", "email": cp.email if cp else u.email,
            "dob": cp.dob if cp else "", "gender": cp.gender if cp else "",
            "nationality": cp.nationality if cp else "", "qualification": cp.qualification if cp else "",
            "is_student": cp.is_student if cp else False, "languages": cp.languages if cp else "",
            "profile_photo": cp.profile_photo if cp else "",
            "wallet_balance": cwal.balance if cwal else 0.0,
            "wallet_currency": cwal.currency if cwal else "PLN",
            "documents": [{"type": d.doc_type, "file": d.file_path, "name": d.original_name} for d in docs],
            "applications_count": len(applied_jobs),
            "applied_jobs": applied_jobs,
            "current_plan": plan_out,
        },
    }


@router.get("/recruiter/{user_id}")
def recruiter_detail(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == user_id, User.role == Role.recruiter).first()
    if not u:
        raise HTTPException(404, "Recruiter not found")
    rp = u.recruiter_profile
    jobs = db.query(Job).filter(Job.recruiter_id == user_id).all()
    sub = (
        db.query(UserSubscription, SubscriptionPlan)
        .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.plan_id)
        .filter(UserSubscription.user_id == user_id, UserSubscription.status == "active")
        .order_by(UserSubscription.id.desc()).first()
    )
    plan_out = None
    if sub:
        us, plan = sub
        plan_out = {
            "name": plan.name, "price": plan.price, "currency": plan.currency,
            "features": plan.features, "postings": plan.postings, "duration_days": plan.duration_days,
            "start_date": us.start_date.isoformat() if us.start_date else None,
            "end_date": us.end_date.isoformat() if us.end_date else None,
        }
    wal = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    return {
        "status": "success",
        "data": {
            "id": u.id, "phone": u.phone,
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "first_name": rp.first_name if rp else "", "last_name": rp.last_name if rp else "",
            "company_name": rp.company_name if rp else "", "contact_position": rp.contact_position if rp else "",
            "company_email": rp.company_email if rp else u.email, "profile_pic": rp.profile_pic if rp else "",
            "verified": rp.verified if rp else False, "hiring_authority": rp.hiring_authority if rp else "",
            "wallet_balance": wal.balance if wal else 0.0,
            "wallet_currency": wal.currency if wal else "PLN",
            "jobs": [{"id": j.id, "category": j.category, "position": j.position,
                      "job_type": j.job_type, "work_type": j.work_type, "status": j.status,
                      "created_at": j.created_at.isoformat() if j.created_at else None} for j in jobs],
            "current_plan": plan_out,
        },
    }


class AddWalletIn(BaseModel):
    amount: float


@router.post("/recruiter/{user_id}/add-wallet")
def admin_add_wallet(user_id: int, body: AddWalletIn,
                     db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """TEST-ONLY: manually credit a recruiter's wallet from the admin panel so
    they can try paid features without real money. Remove before public launch.

    (Removing = delete this endpoint + the "Add wallet amount" button in the
    admin frontend. Nothing else depends on it.)
    """
    u = db.query(User).filter(User.id == user_id, User.role == Role.recruiter).first()
    if not u:
        raise HTTPException(404, "Recruiter not found")
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    w = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not w:
        w = Wallet(user_id=user_id, balance=0.0, currency="PLN")
        db.add(w); db.flush()
    w.balance += body.amount
    db.add(WalletTransaction(user_id=user_id, amount=body.amount, type="credit",
                            reason="Admin credit", method="admin"))
    db.add(Notification(user_id=user_id, title="Wallet credited",
                        body=f"Admin added {body.amount:.2f} PLN to your wallet."))
    db.commit()
    return {"status": "success", "balance": w.balance}


@router.post("/candidate/{user_id}/add-wallet")
def admin_add_wallet_candidate(user_id: int, body: AddWalletIn,
                               db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Admin manually credits a CANDIDATE's wallet (no PayU — a real admin-issued
    credit). Same behaviour as the recruiter version. Removable before launch."""
    u = db.query(User).filter(User.id == user_id, User.role == Role.candidate).first()
    if not u:
        raise HTTPException(404, "Candidate not found")
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    w = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not w:
        w = Wallet(user_id=user_id, balance=0.0, currency="PLN")
        db.add(w); db.flush()
    w.balance += body.amount
    db.add(WalletTransaction(user_id=user_id, amount=body.amount, type="credit",
                            reason="Admin credit", method="admin"))
    db.add(Notification(user_id=user_id, title="Wallet credited",
                        body=f"Admin added {body.amount:.2f} PLN to your wallet."))
    db.commit()
    return {"status": "success", "balance": w.balance}


class GrantPlanIn(BaseModel):
    plan_id: int


@router.post("/user/{user_id}/grant-plan")
def admin_grant_plan(user_id: int, body: GrantPlanIn,
                     db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Admin manually activates a subscription plan for a user (e.g. they paid
    outside the app). Expires any current active plan, then activates the new one
    — no money moves. Works for candidates and recruiters."""
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == body.plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    # expire any current active subscription
    db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id, UserSubscription.status == "active"
    ).update({"status": "expired"})
    start = dt.datetime.utcnow()
    end = start + dt.timedelta(days=plan.duration_days or 30)
    db.add(UserSubscription(user_id=user_id, plan_id=plan.id, start_date=start, end_date=end,
                            status="active", posts_total=plan.postings or 0, posts_used=0))
    if u.role == Role.recruiter and u.recruiter_profile:
        u.recruiter_profile.can_post_jobs = True
    db.add(Notification(user_id=user_id, title="Plan activated",
                        body=f"An admin activated your {plan.name} plan."))
    db.commit()
    return {"status": "success", "plan_name": plan.name}


@router.post("/user/{user_id}/revoke-plan")
def admin_revoke_plan(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Admin expires the user's current active plan (removes access)."""
    n = db.query(UserSubscription).filter(
        UserSubscription.user_id == user_id, UserSubscription.status == "active"
    ).update({"status": "expired"})
    db.commit()
    return {"status": "success", "revoked": n}


@router.delete("/user/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.query(User).filter(User.id == user_id).first()
    if not u:
        raise HTTPException(404, "User not found")
    if u.role == Role.admin:
        raise HTTPException(400, "Cannot delete an admin")
    db.delete(u)
    db.commit()
    return {"status": "success", "msg": "User deleted"}


# ============================ JOBS ============================
@router.get("/jobs")
def admin_jobs(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (
        db.query(Job, RecruiterProfile)
        .outerjoin(RecruiterProfile, RecruiterProfile.user_id == Job.recruiter_id)
        .order_by(Job.created_at.desc()).all()
    )
    out = []
    for j, rp in rows:
        recruiter_name = ""
        if rp:
            recruiter_name = f"{rp.first_name or ''} {rp.last_name or ''}".strip() or (rp.company_name or "")
        out.append({
            "id": j.id, "status": j.status, "recruiter_name": recruiter_name,
            "category": j.category, "position": j.position, "shift_timing": j.shift_timing,
            "job_type": j.job_type, "work_type": j.work_type, "languages_required": j.languages_required,
            "location": j.location, "nationalities": j.nationalities,
            "age_from": j.age_from, "age_to": j.age_to, "gender_pref": j.gender_pref,
            "accepts_to": j.accepts_to, "description": j.description,
            "joining": j.joining, "need_work_permit": j.need_work_permit,
            "accommodation": j.accommodation, "charges_fee": j.charges_fee,
        })
    return {"status": "success", "jobs": out}


class JobEditIn(BaseModel):
    category: str | None = None
    position: str | None = None
    shift_timing: str | None = None
    job_type: str | None = None
    work_type: str | None = None
    languages_required: str | None = None
    location: str | None = None
    nationalities: str | None = None
    age_from: int | None = None
    age_to: int | None = None
    gender_pref: str | None = None
    accepts_to: str | None = None
    description: str | None = None
    joining: str | None = None
    need_work_permit: bool | None = None
    accommodation: str | None = None
    charges_fee: bool | None = None


@router.put("/job/{job_id}")
def edit_job(job_id: int, body: JobEditIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.commit()
    return {"status": "success", "msg": "Job updated"}


@router.post("/job/{job_id}/toggle-hold")
def toggle_hold(job_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    job.status = "hold" if job.status != "hold" else "open"
    db.commit()
    return {"status": "success", "new_status": job.status}


@router.delete("/job/{job_id}")
def delete_job(job_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    db.query(JobApplication).filter(JobApplication.job_id == job_id).delete()
    db.delete(job)
    db.commit()
    return {"status": "success", "msg": "Job deleted"}


# ============================ APPLICATIONS ============================
@router.get("/applications")
def admin_applications(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (
        db.query(JobApplication, CandidateProfile, Job, User)
        .join(User, User.id == JobApplication.candidate_id)
        .outerjoin(CandidateProfile, CandidateProfile.user_id == JobApplication.candidate_id)
        .join(Job, Job.id == JobApplication.job_id)
        .order_by(JobApplication.applied_at.desc()).all()
    )
    out = []
    for app, cp, job, user in rows:
        name = ""
        if cp:
            name = f"{cp.first_name or ''} {cp.last_name or ''}".strip()
        docs = db.query(CandidateDocument).filter(
            CandidateDocument.user_id == app.candidate_id).all()
        out.append({
            "id": app.id,
            "candidate_id": app.candidate_id,
            "name": name or user.full_name or "",
            "photo": cp.profile_photo if cp else "",
            "role": job.category, "job_type": job.job_type, "work_type": job.work_type,
            "applied_at": app.applied_at.isoformat() if app.applied_at else None,
            "contact": user.phone, "email": cp.email if cp else user.email,
            "documents": [{"type": d.doc_type, "file": d.file_path, "name": d.original_name} for d in docs],
        })
    return {"status": "success", "count": len(out), "applications": out}


# ============================ PLANS ============================
@router.get("/plans")
def admin_plans(role: str = "recruiter", db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    plans = db.query(SubscriptionPlan).filter(SubscriptionPlan.for_role == role).all()
    return {"status": "success", "plans": [{
        "id": p.id, "name": p.name, "price": p.price, "currency": p.currency,
        "duration_days": p.duration_days, "postings": p.postings,
        "features": p.features, "for_role": p.for_role, "recommended": p.recommended,
    } for p in plans]}


class PlanIn(BaseModel):
    name: str
    price: float
    currency: str = "PLN"
    duration_days: int
    features: str = ""
    postings: int = 0
    for_role: str = "recruiter"


@router.post("/plan")
def create_plan(body: PlanIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    plan = SubscriptionPlan(**body.model_dump())
    db.add(plan)
    db.commit()
    return {"status": "success", "msg": "Plan created", "id": plan.id}


@router.put("/plan/{plan_id}")
def edit_plan(plan_id: int, body: PlanIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    for field, value in body.model_dump().items():
        setattr(plan, field, value)
    db.commit()
    return {"status": "success", "msg": "Plan updated"}


@router.delete("/plan/{plan_id}")
def delete_plan(plan_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    db.delete(plan)
    db.commit()
    return {"status": "success", "msg": "Plan deleted"}


# ============================ PAYMENTS ============================
@router.get("/payments")
def admin_payments(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    # Payment history from wallet debits (subscription purchases etc.)
    rows = (
        db.query(WalletTransaction, User)
        .join(User, User.id == WalletTransaction.user_id)
        .order_by(WalletTransaction.created_at.desc()).limit(50).all()
    )
    history = [{
        "id": t.id, "name": u.full_name or u.phone, "reason": t.reason,
        "amount": t.amount, "type": t.type, "method": t.method,
        "date": t.created_at.isoformat() if t.created_at else None,
    } for t, u in rows]

    # Monthly totals for the chart. We separate:
    #   revenue = money users actually SPENT on plans (debits)  → real income
    #   topups  = REAL money added via PayU (method='payu' credits)
    # Admin test credits (method='admin') are EXCLUDED — they aren't real money.
    monthly = {}
    for t, _ in rows:
        if not t.created_at:
            continue
        key = t.created_at.strftime("%b")
        monthly.setdefault(key, {"credit": 0.0, "debit": 0.0})
        if t.type == "debit":
            monthly[key]["debit"] += (t.amount or 0)          # revenue (plans)
        elif t.type == "credit" and t.method == "payu":
            monthly[key]["credit"] += (t.amount or 0)         # real PayU top-ups only

    return {"status": "success", "history": history, "monthly": monthly}


# ============================ LOGS / CONTACTED INFO ============================
@router.get("/logs/contact")
def contact_logs(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = db.query(ContactMessage).order_by(ContactMessage.created_at.desc()).all()
    return {"status": "success", "logs": [{
        "id": c.id, "name": c.name, "email": c.email, "phone": c.phone,
        "message": c.message,
        "date": c.created_at.isoformat() if c.created_at else None,
    } for c in rows]}


# ============================ ADMIN PROFILE ============================
@router.get("/profile")
def admin_profile(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return {
        "status": "success",
        "data": {
            "id": admin.id, "full_name": admin.full_name or "",
            "email": admin.email or "", "phone": admin.phone,
            "photo": getattr(admin, "photo", None) or "",
        },
    }


@router.post("/profile/photo")
def admin_upload_photo(file: UploadFile = File(...),
                       db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """Upload/replace the admin's profile photo. Saved to the uploads disk."""
    import uuid, os
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
        raise HTTPException(400, "Image files only")
    safe = f"admin_{admin.id}_{uuid.uuid4().hex}{ext}"
    dest = UPLOADS_DIR / safe
    with dest.open("wb") as out:
        out.write(file.file.read())
    admin.photo = f"/uploads/{safe}"
    db.commit()
    return {"status": "success", "photo": admin.photo}


class AdminProfileIn(BaseModel):
    full_name: str | None = None
    email: str | None = None


@router.put("/profile")
def update_admin_profile(body: AdminProfileIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.full_name is not None:
        admin.full_name = body.full_name
    if body.email is not None:
        admin.email = body.email
    db.commit()
    return {"status": "success", "msg": "Profile updated"}


# ==================== CUSTOM OPTIONS (cities / languages) ====================
# Recruiters can add new cities/languages while posting; admin manages the full
# list here. Anything added shows for ALL recruiters.
_ADMIN_OPTION_FIELDS = {"language", "city"}


@router.get("/options/{field}")
def admin_list_options(field: str, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if field not in _ADMIN_OPTION_FIELDS:
        raise HTTPException(400, "Unsupported field")
    rows = (db.query(CustomOption, RecruiterProfile)
            .outerjoin(RecruiterProfile, RecruiterProfile.user_id == CustomOption.created_by)
            .filter(CustomOption.field == field)
            .order_by(CustomOption.created_at.desc()).all())
    out = []
    for opt, rp in rows:
        out.append({
            "id": opt.id, "value": opt.value,
            "added_by": (f"{rp.first_name or ''} {rp.last_name or ''}".strip() or rp.company_name)
                        if rp else "—",
            "created_at": opt.created_at.isoformat() if opt.created_at else None,
        })
    return {"status": "success", "options": out}


class AdminOptionIn(BaseModel):
    value: str


@router.post("/options/{field}")
def admin_add_option(field: str, body: AdminOptionIn,
                     db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if field not in _ADMIN_OPTION_FIELDS:
        raise HTTPException(400, "Unsupported field")
    val = (body.value or "").strip()
    if not val:
        raise HTTPException(400, "Value required")
    exists = db.query(CustomOption).filter(
        CustomOption.field == field, func.lower(CustomOption.value) == val.lower()).first()
    if exists:
        raise HTTPException(400, "Already exists")
    opt = CustomOption(field=field, value=val, created_by=admin.id)
    db.add(opt); db.commit()
    return {"status": "success", "id": opt.id, "value": val}


@router.put("/options/{opt_id}")
def admin_edit_option(opt_id: int, body: AdminOptionIn,
                      db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    opt = db.query(CustomOption).filter(CustomOption.id == opt_id).first()
    if not opt:
        raise HTTPException(404, "Option not found")
    val = (body.value or "").strip()
    if not val:
        raise HTTPException(400, "Value required")
    opt.value = val
    db.commit()
    return {"status": "success", "value": val}


@router.delete("/options/{opt_id}")
def admin_delete_option(opt_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    opt = db.query(CustomOption).filter(CustomOption.id == opt_id).first()
    if not opt:
        raise HTTPException(404, "Option not found")
    db.delete(opt); db.commit()
    return {"status": "success"}


# ============================ ADMIN MESSAGING ============================
# Admin↔user threads are kept SEPARATE from recruiter↔candidate chats (is_admin
# flag), so "Message Recruiter" from admin never opens a role-to-role chat —
# even when one test phone serves several roles.
from app.models import Conversation, Message
from app.services.chat import (
    get_or_create_admin_conversation, post_message, display_name, display_photo,
)


class AdminChatStartIn(BaseModel):
    other_user_id: int


@router.post("/chat/start")
def admin_chat_start(body: AdminChatStartIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    other = db.query(User).filter(User.id == body.other_user_id).first()
    if not other:
        raise HTTPException(404, "User not found")
    if other.id == admin.id:
        raise HTTPException(400, "Cannot start a conversation with yourself")
    conv = get_or_create_admin_conversation(db, admin.id, other.id)
    db.commit()
    return {"status": "success", "conversation_id": conv.id, "name": display_name(other)}


@router.get("/chat/conversations")
def admin_chat_conversations(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = (db.query(Conversation)
            .filter(Conversation.is_admin == True)
            .filter((Conversation.candidate_id == admin.id) | (Conversation.recruiter_id == admin.id))
            .all())
    out = []
    for c in rows:
        other_id = c.recruiter_id if c.candidate_id == admin.id else c.candidate_id
        other = db.query(User).filter(User.id == other_id).first()
        last = (db.query(Message).filter(Message.conversation_id == c.id)
                .order_by(Message.created_at.desc()).first())
        unread = db.query(Message).filter(
            Message.conversation_id == c.id, Message.sender_id != admin.id,
            Message.is_read == False).count()
        ts = (last.created_at if last and last.created_at else c.created_at)
        out.append({
            "conversation_id": c.id, "other_id": other_id,
            "name": display_name(other), "photo": display_photo(other),
            "role": other.role.value if other else "",
            "last_message": last.body if last else "",
            "time": ts.isoformat() if ts else "",
            "unread": unread,
        })
    out.sort(key=lambda x: x["time"], reverse=True)
    return {"status": "success", "conversations": out}


@router.get("/chat/{conversation_id}/messages")
def admin_chat_messages(conversation_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    c = db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.is_admin == True).first()
    if not c or admin.id not in (c.candidate_id, c.recruiter_id):
        raise HTTPException(404, "Conversation not found")
    db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.sender_id != admin.id, Message.is_read == False,
    ).update({"is_read": True})
    db.commit()
    rows = (db.query(Message).filter(Message.conversation_id == conversation_id)
            .order_by(Message.created_at).all())
    other_id = c.recruiter_id if c.candidate_id == admin.id else c.candidate_id
    other = db.query(User).filter(User.id == other_id).first()
    return {
        "status": "success", "other_name": display_name(other),
        "other_photo": display_photo(other),
        "messages": [{"id": m.id, "body": m.body, "mine": m.sender_id == admin.id,
                      "read": bool(m.is_read),
                      "time": m.created_at.isoformat() if m.created_at else ""} for m in rows],
    }


class AdminSendIn(BaseModel):
    conversation_id: int
    body: str


@router.post("/chat/send")
def admin_chat_send(body: AdminSendIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    c = db.query(Conversation).filter(Conversation.id == body.conversation_id, Conversation.is_admin == True).first()
    if not c or admin.id not in (c.candidate_id, c.recruiter_id):
        raise HTTPException(404, "Conversation not found")
    if not (body.body or "").strip():
        raise HTTPException(400, "Empty message")
    post_message(db, c, admin, body.body.strip())
    return {"status": "success"}
