"""Shared chat engine — works between ANY two users (admin, recruiter, candidate).

The Conversation table has two participant columns (candidate_id, recruiter_id).
We treat them generically as "party A / party B" so the same table serves
admin<->recruiter, admin<->candidate and candidate<->recruiter conversations.
Every message also creates a Notification for the recipient.
"""
from sqlalchemy.orm import Session

from app.models import User, Role, Conversation, Message, Notification


def display_name(user: User) -> str:
    """Best human name for a user, by role."""
    if user is None:
        return "User"
    if user.role == Role.admin:
        return "Admin (JobifyPL)"
    if user.role == Role.candidate and user.candidate_profile:
        cp = user.candidate_profile
        n = f"{cp.first_name or ''} {cp.last_name or ''}".strip()
        return n or (user.full_name or "Candidate")
    if user.role == Role.recruiter and user.recruiter_profile:
        rp = user.recruiter_profile
        n = f"{rp.first_name or ''} {rp.last_name or ''}".strip()
        return n or rp.company_name or (user.full_name or "Recruiter")
    return user.full_name or user.phone or "User"


def display_photo(user: User):
    """Real uploaded avatar for a user (or None → caller shows a default avatar).
    Never returns a random/stock image."""
    if user is None:
        return None
    if user.role == Role.recruiter and user.recruiter_profile:
        return user.recruiter_profile.profile_pic or None
    if user.role == Role.candidate and user.candidate_profile:
        return user.candidate_profile.profile_photo or None
    if user.role == Role.admin:
        return getattr(user, "photo", None) or None
    return None


def get_or_create_conversation(db: Session, a_id: int, b_id: int, job_id=None) -> Conversation:
    """Find the conversation between users a and b, or create it. Order-independent."""
    conv = (
        db.query(Conversation)
        .filter(
            ((Conversation.candidate_id == a_id) & (Conversation.recruiter_id == b_id))
            | ((Conversation.candidate_id == b_id) & (Conversation.recruiter_id == a_id))
        )
        .first()
    )
    if conv:
        return conv
    conv = Conversation(candidate_id=a_id, recruiter_id=b_id, job_id=job_id)
    db.add(conv)
    db.flush()
    return conv


def get_or_create_admin_conversation(db: Session, admin_id: int, user_id: int) -> Conversation:
    """Admin↔user support thread, kept separate from role-to-role chats via is_admin.
    admin goes in candidate_id, the other user in recruiter_id (arbitrary slots)."""
    conv = (
        db.query(Conversation)
        .filter(Conversation.is_admin == True)
        .filter(
            ((Conversation.candidate_id == admin_id) & (Conversation.recruiter_id == user_id))
            | ((Conversation.candidate_id == user_id) & (Conversation.recruiter_id == admin_id))
        )
        .first()
    )
    if conv:
        return conv
    conv = Conversation(candidate_id=admin_id, recruiter_id=user_id, is_admin=True)
    db.add(conv)
    db.flush()
    return conv


def other_party_id(conv: Conversation, user_id: int) -> int:
    return conv.recruiter_id if conv.candidate_id == user_id else conv.candidate_id


def post_message(db: Session, conv: Conversation, sender: User, body: str) -> Message:
    """Add a message and notify the recipient. Returns the Message."""
    msg = Message(conversation_id=conv.id, sender_id=sender.id, body=body)
    db.add(msg)

    recipient_id = other_party_id(conv, sender.id)
    db.add(Notification(
        user_id=recipient_id,
        title=f"New message from {display_name(sender)}",
        company="JobifyPL",
        body=body[:140],
    ))
    db.commit()
    db.refresh(msg)
    return msg
