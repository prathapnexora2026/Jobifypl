"""Database models for JobifyPL — aligned to the app screens.

One `users` table (role: candidate/recruiter/admin); role data in profile tables.
Everything the candidate screens show has a model here.
"""
import datetime as dt
import enum

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text, Float
)
from sqlalchemy.orm import relationship

from app.database import Base


def now():
    return dt.datetime.utcnow()


class Role(str, enum.Enum):
    candidate = "candidate"
    recruiter = "recruiter"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    role = Column(Enum(Role), nullable=False, index=True)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    email = Column(String(160), index=True, nullable=True)
    full_name = Column(String(160), nullable=True)
    phone_verified = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)
    last_login_at = Column(DateTime, nullable=True)

    candidate_profile = relationship("CandidateProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    recruiter_profile = relationship("RecruiterProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    profile_photo = Column(String(255))
    first_name = Column(String(80))
    middle_name = Column(String(80))
    last_name = Column(String(80))
    dob = Column(String(20))
    gender = Column(String(20))
    nationality = Column(String(80))
    qualification = Column(String(120))
    is_student = Column(Boolean, default=False)
    languages = Column(Text)          # comma-separated chips
    email = Column(String(160))
    status_label = Column(String(40), default="Active Looking")
    onboarding_completed = Column(Boolean, default=False)

    user = relationship("User", back_populates="candidate_profile")


class RecruiterProfile(Base):
    __tablename__ = "recruiter_profiles"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    company_name = Column(String(160))
    contact_position = Column(String(120))
    hiring_authority = Column(String(40))          # Agency / Company / Freelancer / Self-Hiring
    first_name = Column(String(80))
    middle_name = Column(String(80))
    last_name = Column(String(80))
    company_email = Column(String(160))            # no gmail/yahoo
    profile_pic = Column(String(255))
    cover_pic = Column(String(255))
    actively_hiring = Column(Boolean, default=True)
    profile_views = Column(Integer, default=0)
    verified = Column(Boolean, default=False)
    can_post_jobs = Column(Boolean, default=False)
    onboarding_completed = Column(Boolean, default=False)

    user = relationship("User", back_populates="recruiter_profile")


class CandidateDocument(Base):
    __tablename__ = "candidate_documents"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    doc_type = Column(String(40), nullable=False)   # trc_card, pesel, passport, driving_license, student_card, other
    file_path = Column(String(255), nullable=False)
    original_name = Column(String(200))
    uploaded_at = Column(DateTime, default=now)


class Job(Base):
    __tablename__ = "jobs"
    id = Column(Integer, primary_key=True, index=True)
    recruiter_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    title = Column(String(160), nullable=False)
    company_name = Column(String(160))       # or "Self-Hiring"
    position = Column(String(160))
    description = Column(Text)
    category = Column(String(80), index=True)
    location = Column(String(120), index=True)
    job_type = Column(String(40))            # Full Time / Part Time
    work_type = Column(String(40))           # Regular Job / etc
    gender_pref = Column(String(20))         # Male / Female / Any
    shift_timing = Column(String(60))        # "6 hours"
    age_from = Column(Integer)
    age_to = Column(Integer)
    min_salary = Column(Integer)
    max_salary = Column(Integer)
    currency = Column(String(8), default="PLN")
    openings = Column(Integer, default=1)
    is_premium = Column(Boolean, default=False)
    status = Column(String(20), default="open", index=True)
    views = Column(Integer, default=0)             # times a candidate opened Job Details
    created_at = Column(DateTime, default=now)
    # --- Post-a-Job wizard fields (from recruiter screenshots) ---
    languages_required = Column(String(160))       # e.g. "Basic English"
    street = Column(String(160))
    joining = Column(String(40), default="Immediate Joining")
    need_work_permit = Column(Boolean, default=False)
    accommodation = Column(String(30))             # Free / Paid
    charges_fee = Column(Boolean, default=False)
    nationalities = Column(String(200))            # "Nepal & Philippines"
    accepts_to = Column(String(60))                # Student Only / Polish TRC / Polish Citizens / All
    hiring_authority = Column(String(40))          # Agency / Company / Freelancer / Self-Hiring
    contact_first_name = Column(String(80))
    contact_middle_name = Column(String(80))
    contact_last_name = Column(String(80))
    contact_phone = Column(String(30))
    contact_email = Column(String(160))


class JobApplication(Base):
    __tablename__ = "job_applications"
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), index=True, nullable=False)
    candidate_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    interested = Column(Boolean, default=False)
    applied = Column(Boolean, default=True)
    # track journey: application_sent -> recruiter_seen -> recruiter_contacted
    track_status = Column(String(30), default="application_sent")
    status = Column(String(30), default="applied")  # applied/shortlisted/interview/rejected/hired
    applied_at = Column(DateTime, default=now)


class Wallet(Base):
    __tablename__ = "wallets"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    balance = Column(Float, default=0.0)
    currency = Column(String(8), default="PLN")
    total_spent = Column(Float, default=0.0)


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    amount = Column(Float)
    type = Column(String(10))   # credit / debit
    reason = Column(String(120))
    created_at = Column(DateTime, default=now)


class SubscriptionPlan(Base):
    __tablename__ = "subscription_plans"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(80))            # "1 Month Plan"
    price = Column(Float)
    currency = Column(String(8), default="PLN")
    duration_days = Column(Integer)
    feature1 = Column(String(160))
    feature2 = Column(String(160))
    features = Column(Text)              # newline-separated bullet list (recruiter plans)
    postings = Column(Integer, default=0)  # job posting quota for recruiter plans
    recommended = Column(Boolean, default=False)
    for_role = Column(String(20), default="candidate")
    is_active = Column(Boolean, default=True)


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    plan_id = Column(Integer, ForeignKey("subscription_plans.id"))
    start_date = Column(DateTime, default=now)
    end_date = Column(DateTime)
    status = Column(String(20), default="active")
    posts_total = Column(Integer, default=0)       # posting quota granted by this plan
    posts_used = Column(Integer, default=0)        # postings consumed so far


class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    title = Column(String(160))
    company = Column(String(120))
    body = Column(Text)
    job_id = Column(Integer, nullable=True)        # if set, tapping opens this job's details
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("users.id"), index=True)
    recruiter_id = Column(Integer, ForeignKey("users.id"), index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=True)
    # True → this is an ADMIN↔user support thread. Kept separate so it never
    # collides with a recruiter↔candidate chat (important when one test phone
    # serves several roles). candidate_id holds the admin, recruiter_id the user.
    is_admin = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=now)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    body = Column(Text)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)


class ContactMessage(Base):
    __tablename__ = "contact_messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    name = Column(String(120))
    email = Column(String(160))
    phone = Column(String(30))
    message = Column(Text)
    created_at = Column(DateTime, default=now)


class OtpCode(Base):
    __tablename__ = "otp_codes"
    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(20), index=True, nullable=False)
    code = Column(String(8), nullable=False)
    purpose = Column(String(20), default="login")
    expires_at = Column(DateTime, nullable=False)
    consumed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=now)
