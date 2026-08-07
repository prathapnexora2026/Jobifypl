"""Candidate endpoints — profile, onboarding, documents (KYC), CV builder.

All routes require a candidate JWT (Authorization: Bearer <token>).
"""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Role, CandidateProfile, CandidateDocument
from app.security import get_current_user

router = APIRouter(prefix="/candidate", tags=["candidate"])

# Where uploaded files go. On Render this is the persistent disk (see app/paths.py).
from app.paths import UPLOADS_DIR as UPLOAD_DIR

ALLOWED_DOC_TYPES = {
    "resume", "passport", "trc_card", "pesel", "driving_license",
    "student_card", "profile_photo", "other",
}


def require_candidate(user: User = Depends(get_current_user)) -> User:
    if user.role != Role.candidate:
        raise HTTPException(403, "Candidates only")
    return user


# ---------- Profile ----------
class ProfileIn(BaseModel):
    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    dob: str | None = None
    gender: str | None = None
    nationality: str | None = None
    qualification: str | None = None
    is_student: bool | None = None
    languages: str | None = None       # comma-separated chips
    email: str | None = None


@router.get("/profile")
def get_profile(user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    p = user.candidate_profile
    if not p:
        p = CandidateProfile(user_id=user.id)
        db.add(p); db.commit(); db.refresh(p)
    return {
        "status": "success",
        "profile": {
            "first_name": p.first_name, "middle_name": p.middle_name,
            "last_name": p.last_name, "dob": p.dob, "gender": p.gender,
            "nationality": p.nationality, "qualification": p.qualification,
            "is_student": p.is_student, "languages": p.languages,
            "email": p.email or user.email, "profile_photo": p.profile_photo,
            "status_label": p.status_label,
            "onboarding_completed": p.onboarding_completed,
            "docs_step_done": bool(getattr(p, "docs_step_done", False)),
            "phone": user.phone,
        },
    }


@router.post("/onboarding/docs-done")
def mark_docs_done(user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    """Mark the documents onboarding step as finished (submitted or skipped), so a
    candidate who quit mid-upload resumes there — not stuck — on next open."""
    p = user.candidate_profile or CandidateProfile(user_id=user.id)
    p.docs_step_done = True
    db.add(p); db.commit()
    return {"status": "success"}


@router.post("/profile")
def save_profile(
    body: ProfileIn,
    user: User = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    p = user.candidate_profile or CandidateProfile(user_id=user.id)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(p, field, val)
    if p.first_name and p.last_name and p.nationality:
        p.onboarding_completed = True
    db.add(p)
    if body.email:
        user.email = body.email
    if body.first_name or body.last_name:
        user.full_name = f"{p.first_name or ''} {p.last_name or ''}".strip()
    db.commit()
    return {"status": "success", "onboarding_completed": p.onboarding_completed}


# ---------- Profile photo ----------
@router.post("/photo")
def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    safe = f"photo_{user.id}_{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / safe
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    p = user.candidate_profile or CandidateProfile(user_id=user.id)
    p.profile_photo = f"/uploads/{safe}"
    db.add(p); db.commit()
    return {"status": "success", "profile_photo": p.profile_photo}


# ---------- Documents (KYC) ----------
@router.post("/documents")
def upload_document(
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    if doc_type not in ALLOWED_DOC_TYPES:
        raise HTTPException(400, f"Invalid doc_type. Allowed: {sorted(ALLOWED_DOC_TYPES)}")

    ext = Path(file.filename or "").suffix.lower()
    safe_name = f"{user.id}_{doc_type}_{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / safe_name
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    doc = CandidateDocument(
        user_id=user.id, doc_type=doc_type,
        file_path=f"/uploads/{safe_name}", original_name=file.filename,
    )
    db.add(doc); db.commit(); db.refresh(doc)
    return {"status": "success", "document": {"id": doc.id, "doc_type": doc_type, "file_path": doc.file_path}}


@router.get("/documents")
def list_documents(user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    docs = db.query(CandidateDocument).filter(CandidateDocument.user_id == user.id).all()
    return {
        "status": "success",
        "documents": [
            {"id": d.id, "doc_type": d.doc_type, "file_path": d.file_path,
             "original_name": d.original_name}
            for d in docs
        ],
    }


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: int, user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    doc = db.query(CandidateDocument).filter(
        CandidateDocument.id == doc_id, CandidateDocument.user_id == user.id
    ).first()
    if not doc:
        raise HTTPException(404, "Document not found")
    db.delete(doc); db.commit()
    return {"status": "success"}
