"""Jobs endpoints — browse, view, apply, mark interested, track (candidate-facing)."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User, Role, Job, JobApplication, Notification, RecruiterProfile, UserSubscription,
)
from app.security import get_current_user, get_optional_user

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _candidate_has_active_plan(db, user_id) -> bool:
    """True if the candidate has a non-expired active subscription.
    Viewing jobs is free; APPLYING requires an active plan."""
    now = dt.datetime.utcnow()
    sub = (db.query(UserSubscription)
           .filter(UserSubscription.user_id == user_id,
                   UserSubscription.status == "active")
           .filter((UserSubscription.end_date == None) | (UserSubscription.end_date >= now))
           .first())
    return sub is not None


def _recruiter_photo(db, recruiter_id):
    rp = db.query(RecruiterProfile).filter(RecruiterProfile.user_id == recruiter_id).first()
    return rp.profile_pic if rp and rp.profile_pic else None


def _job_dict(j: Job, applied=False, interested=False, db=None):
    return {
        "id": j.id, "title": j.title, "company_name": j.company_name or "Self-Hiring",
        "position": j.position, "description": j.description, "category": j.category,
        "location": j.location or "N/A", "job_type": j.job_type, "work_type": j.work_type,
        "gender_pref": j.gender_pref, "shift_timing": j.shift_timing,
        "age_from": j.age_from, "age_to": j.age_to,
        "min_salary": j.min_salary, "max_salary": j.max_salary, "currency": j.currency,
        "openings": j.openings, "is_premium": j.is_premium, "status": j.status,
        "accommodation": j.accommodation, "accommodation_amount": j.accommodation_amount,
        "charges_fee": bool(j.charges_fee),
        "recruiter_id": j.recruiter_id,
        "recruiter_photo": _recruiter_photo(db, j.recruiter_id) if db is not None else None,
        "applied": applied, "interested": interested,
    }


def _my_app(db, user_id, job_id):
    return db.query(JobApplication).filter(
        JobApplication.job_id == job_id, JobApplication.candidate_id == user_id).first()


@router.get("")
def list_jobs(
    q: str | None = Query(None),
    location: str | None = None,
    job_type: str | None = None,
    work_type: str | None = None,
    gender: str | None = None,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_user),
):
    query = db.query(Job).filter(Job.status == "open")
    if q:
        like = f"%{q}%"
        query = query.filter((Job.title.ilike(like)) | (Job.company_name.ilike(like)) | (Job.position.ilike(like)))
    if location:
        query = query.filter(Job.location.ilike(f"%{location}%"))
    if job_type:
        query = query.filter(Job.job_type == job_type)
    if work_type:
        query = query.filter(Job.work_type == work_type)
    if gender:
        query = query.filter(Job.gender_pref == gender)
    jobs = query.order_by(Job.created_at.desc()).limit(100).all()
    # If a candidate is signed in, flag which jobs they've already applied to /
    # marked interested — so the app shows "Applied" instead of "Apply Now".
    applied_ids: set[int] = set()
    interested_ids: set[int] = set()
    if user is not None:
        rows = db.query(JobApplication).filter(JobApplication.candidate_id == user.id).all()
        applied_ids = {r.job_id for r in rows if r.applied}
        interested_ids = {r.job_id for r in rows if r.interested}
    return {"status": "success", "jobs": [
        _job_dict(j, applied=j.id in applied_ids, interested=j.id in interested_ids, db=db)
        for j in jobs
    ]}


@router.get("/{job_id}")
def job_detail(job_id: int, db: Session = Depends(get_db),
               user: User | None = Depends(get_optional_user)):
    j = db.query(Job).filter(Job.id == job_id).first()
    if not j:
        raise HTTPException(404, "Job not found")
    # count this as a view (candidate opened Job Details)
    j.views = (j.views or 0) + 1
    db.commit()
    applied = interested = False
    if user is not None:
        row = _my_app(db, user.id, job_id)
        if row:
            applied = bool(row.applied); interested = bool(row.interested)
    return {"status": "success", "job": _job_dict(j, applied=applied, interested=interested, db=db)}


@router.post("/{job_id}/apply")
def apply_job(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != Role.candidate:
        raise HTTPException(403, "Only candidates can apply")
    # PAYWALL: viewing is free, but applying needs an active plan (min 25 PLN).
    if not _candidate_has_active_plan(db, user.id):
        raise HTTPException(402, "Buy a plan to apply for jobs.")
    job = db.query(Job).filter(Job.id == job_id, Job.status == "open").first()
    if not job:
        raise HTTPException(404, "Job not found or closed")
    row = _my_app(db, user.id, job_id)
    if row and row.applied:
        raise HTTPException(400, "You already applied to this job")
    if not row:
        row = JobApplication(job_id=job_id, candidate_id=user.id)
        db.add(row)
    row.applied = True
    row.track_status = "application_sent"
    row.status = "applied"
    # notify recruiter
    db.add(Notification(user_id=job.recruiter_id, title="New applicant",
                        company=job.title, body=f"A candidate applied to {job.title}"))
    db.commit()
    return {"status": "success", "msg": "Applied successfully"}


@router.post("/{job_id}/interested")
def toggle_interested(job_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != Role.candidate:
        raise HTTPException(403, "Candidates only")
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    row = _my_app(db, user.id, job_id)
    if not row:
        row = JobApplication(job_id=job_id, candidate_id=user.id, applied=False)
        db.add(row)
    row.interested = not row.interested
    db.commit()
    return {"status": "success", "interested": row.interested}


@router.get("/me/applications")
def my_applications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != Role.candidate:
        raise HTTPException(403, "Candidates only")
    rows = (
        db.query(JobApplication, Job)
        .join(Job, Job.id == JobApplication.job_id)
        .filter(JobApplication.candidate_id == user.id, JobApplication.applied == True)
        .order_by(JobApplication.applied_at.desc()).all()
    )
    return {"status": "success", "applications": [
        {"application_id": a.id, "status": a.status, "track_status": a.track_status,
         "job_id": j.id, "recruiter_id": j.recruiter_id,
         "title": j.title, "position": j.position,
         "recruiter_photo": _recruiter_photo(db, j.recruiter_id),
         "company_name": j.company_name or "Self-Hiring",
         "location": j.location, "job_type": j.job_type, "gender_pref": j.gender_pref,
         "work_type": j.work_type}
        for a, j in rows
    ]}


@router.get("/me/counts")
def my_counts(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    applied = db.query(JobApplication).filter(
        JobApplication.candidate_id == user.id, JobApplication.applied == True).count()
    interested = db.query(JobApplication).filter(
        JobApplication.candidate_id == user.id, JobApplication.interested == True).count()
    contacted = db.query(JobApplication).filter(
        JobApplication.candidate_id == user.id,
        JobApplication.track_status == "recruiter_contacted").count()
    return {"status": "success", "applied": applied, "interested": interested, "contacted": contacted}
