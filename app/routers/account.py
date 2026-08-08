"""Account & safety endpoints required by the Play Store / App Store:
  • self-service account deletion (GDPR-style: PII scrubbed, owned content removed)
  • report objectionable content/users (App Store 1.2 / Play UGC policy)
  • block / unblock a user (chat + content)
"""
import datetime as dt
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.paths import UPLOADS_DIR
from app.security import get_current_user
from app.models import (
    User, CandidateDocument, JobApplication, Job, Notification, Wallet,
    WalletTransaction, UserSubscription, Report, UserBlock,
)

router = APIRouter(tags=["account"])


# ------------------------------ account deletion ------------------------------
@router.post("/account/delete")
def delete_my_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete the signed-in user's account and personal data. We remove owned
    content (documents, applications, jobs, wallet, notifications) and scrub the
    user's PII, then deactivate — so login is blocked and no personal data remains,
    while financial records / others' chat history keep referential integrity."""
    uid = user.id

    # documents — remove the files too
    for d in db.query(CandidateDocument).filter(CandidateDocument.user_id == uid).all():
        try:
            if d.file_path:
                fp = UPLOADS_DIR / os.path.basename(d.file_path)
                if fp.exists():
                    fp.unlink()
        except Exception:
            pass
        db.delete(d)

    # candidate's applications
    db.query(JobApplication).filter(JobApplication.candidate_id == uid).delete(synchronize_session=False)

    # recruiter's jobs (and the applications to them)
    job_ids = [j.id for j in db.query(Job.id).filter(Job.recruiter_id == uid).all()]
    if job_ids:
        db.query(JobApplication).filter(JobApplication.job_id.in_(job_ids)).delete(synchronize_session=False)
        db.query(Job).filter(Job.recruiter_id == uid).delete(synchronize_session=False)

    # notifications, wallet, subscriptions, blocks
    db.query(Notification).filter(Notification.user_id == uid).delete(synchronize_session=False)
    db.query(WalletTransaction).filter(WalletTransaction.user_id == uid).delete(synchronize_session=False)
    db.query(Wallet).filter(Wallet.user_id == uid).delete(synchronize_session=False)
    db.query(UserSubscription).filter(UserSubscription.user_id == uid).delete(synchronize_session=False)
    db.query(UserBlock).filter(
        (UserBlock.blocker_id == uid) | (UserBlock.blocked_id == uid)
    ).delete(synchronize_session=False)

    # profile rows
    if user.candidate_profile:
        db.delete(user.candidate_profile)
    if user.recruiter_profile:
        db.delete(user.recruiter_profile)

    # anonymize + deactivate (keeps the row so messages/payments stay valid)
    user.is_active = False
    user.deleted_at = dt.datetime.utcnow()
    user.full_name = None
    user.email = None
    user.photo = None
    user.phone_verified = False
    user.phone = f"deleted_{uid}"        # frees the real number for a fresh signup; keeps uniqueness

    db.commit()
    return {"status": "success", "msg": "Your account and personal data have been deleted."}


# ------------------------------ report ------------------------------
class ReportIn(BaseModel):
    target_type: str                     # "user" | "job" | "message"
    target_id: int
    reason: str = "other"                # spam | harassment | scam | inappropriate | other
    details: str | None = None


@router.post("/report")
def create_report(body: ReportIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.target_type not in ("user", "job", "message"):
        raise HTTPException(400, "Invalid report target")
    db.add(Report(
        reporter_id=user.id, target_type=body.target_type, target_id=body.target_id,
        reason=(body.reason or "other")[:60], details=(body.details or None),
    ))
    db.commit()
    return {"status": "success", "msg": "Thanks — our team will review this within 24 hours."}


# ------------------------------ block / unblock ------------------------------
class BlockIn(BaseModel):
    user_id: int


@router.post("/block")
def block_user(body: BlockIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.user_id == user.id:
        raise HTTPException(400, "You can't block yourself")
    exists = db.query(UserBlock).filter(
        UserBlock.blocker_id == user.id, UserBlock.blocked_id == body.user_id
    ).first()
    if not exists:
        db.add(UserBlock(blocker_id=user.id, blocked_id=body.user_id))
        db.commit()
    return {"status": "success", "msg": "User blocked. They can no longer message you."}


@router.post("/unblock")
def unblock_user(body: BlockIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    db.query(UserBlock).filter(
        UserBlock.blocker_id == user.id, UserBlock.blocked_id == body.user_id
    ).delete(synchronize_session=False)
    db.commit()
    return {"status": "success", "msg": "User unblocked."}


@router.get("/blocks")
def my_blocks(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ids = [b.blocked_id for b in db.query(UserBlock.blocked_id).filter(UserBlock.blocker_id == user.id).all()]
    return {"status": "success", "blocked": ids}


def is_blocked_between(db: Session, a_id: int, b_id: int) -> bool:
    """True if either user has blocked the other (used to gate chat)."""
    return db.query(UserBlock.id).filter(
        ((UserBlock.blocker_id == a_id) & (UserBlock.blocked_id == b_id)) |
        ((UserBlock.blocker_id == b_id) & (UserBlock.blocked_id == a_id))
    ).first() is not None
