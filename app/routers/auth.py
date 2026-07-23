"""Auth endpoints — SMS-OTP registration & login for candidate/recruiter.

Flow:
  1. POST /auth/send-otp    { phone, role }         -> sends OTP via SMS
  2. POST /auth/verify-otp  { phone, code, ... }    -> verifies, creates/loads user, returns JWT
"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, Role, CandidateProfile, RecruiterProfile, OtpCode, Wallet
from app.security import generate_otp, create_access_token, get_current_user
from app.services.sms import send_sms

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- request bodies ----------
class SendOtpIn(BaseModel):
    phone: str = Field(..., examples=["+48512345678"])
    role: Role = Role.candidate


class VerifyOtpIn(BaseModel):
    phone: str
    code: str
    role: Role = Role.candidate
    full_name: str | None = None


# ---------- endpoints ----------
@router.post("/send-otp")
def send_otp(body: SendOtpIn, db: Session = Depends(get_db)):
    phone = body.phone.strip()
    if not phone.startswith("+") or len(phone) < 8:
        raise HTTPException(400, "Enter a valid phone number with country code, e.g. +48...")

    code = generate_otp()
    otp = OtpCode(
        phone=phone,
        code=code,
        purpose="login",
        expires_at=dt.datetime.utcnow() + dt.timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
    )
    db.add(otp)
    db.commit()

    ok = send_sms(phone, f"Your JobifyPL verification code is {code}")
    if not ok:
        raise HTTPException(502, "Could not send SMS. Please try again.")

    return {"status": "success", "msg": "OTP sent"}


@router.post("/verify-otp")
def verify_otp(body: VerifyOtpIn, db: Session = Depends(get_db)):
    phone = body.phone.strip()

    otp = (
        db.query(OtpCode)
        .filter(OtpCode.phone == phone, OtpCode.consumed == False)
        .order_by(OtpCode.id.desc())
        .first()
    )
    if not otp:
        raise HTTPException(400, "No OTP requested for this number")
    if otp.expires_at < dt.datetime.utcnow():
        raise HTTPException(400, "OTP expired, please request a new one")
    if otp.code != body.code.strip():
        raise HTTPException(400, "Incorrect OTP")

    otp.consumed = True

    # Admin phones (from config) resolve to the admin role, regardless of which
    # role button was tapped on the login screen — UNLESS the dev override is on,
    # in which case an admin phone may act as candidate/recruiter/admin for testing.
    is_admin_phone = phone in settings.admin_phone_list
    dev_override = settings.DEV_ROLE_OVERRIDE and is_admin_phone
    if dev_override:
        effective_role = body.role                       # honour the picked role
    else:
        effective_role = Role.admin if is_admin_phone else body.role

    # Find existing user or create a new one (auto-register on first verify).
    user = db.query(User).filter(User.phone == phone).first()
    new_user = user is None
    if new_user:
        user = User(phone=phone, role=effective_role, full_name=body.full_name)
        db.add(user)
        db.flush()  # get user.id
        db.add(Wallet(user_id=user.id, balance=0.0, currency="PLN"))
    elif dev_override and user.role != effective_role:
        # dev override: switch this test user to the role they picked
        user.role = effective_role
    elif is_admin_phone and not dev_override and user.role != Role.admin:
        # Existing user whose number is now an admin phone → upgrade to admin.
        user.role = Role.admin

    # ensure the profile matching the effective role exists (idempotent)
    if effective_role == Role.candidate and not user.candidate_profile:
        db.add(CandidateProfile(user_id=user.id))
    elif effective_role == Role.recruiter and not user.recruiter_profile:
        db.add(RecruiterProfile(user_id=user.id))
    # NOTE: recruiters must complete onboarding (which sets can_post_jobs) before
    # posting — we no longer auto-enable it on dev-override login, so the real
    # onboarding + "complete your profile" flow works for testing too.

    user.phone_verified = True
    user.last_login_at = dt.datetime.utcnow()
    db.commit()
    db.refresh(user)

    token = create_access_token(user.id, user.role.value)

    onboarding_completed = False
    if user.role == Role.candidate and user.candidate_profile:
        onboarding_completed = user.candidate_profile.onboarding_completed
    elif user.role == Role.recruiter and user.recruiter_profile:
        onboarding_completed = user.recruiter_profile.onboarding_completed

    return {
        "status": "success",
        "token": token,
        "new_user": new_user,
        "role": user.role.value,
        "onboarding_completed": onboarding_completed,
    }


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {
        "status": "success",
        "id": user.id,
        "phone": user.phone,
        "role": user.role.value,
        "full_name": user.full_name,
    }
