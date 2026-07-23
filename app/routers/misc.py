"""Notifications, Chat, and Contact endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User, Notification, Conversation, Message, ContactMessage
)
from app.security import get_current_user

# ---------------- Notifications ----------------
notif_router = APIRouter(prefix="/notifications", tags=["notifications"])


@notif_router.get("")
def list_notifications(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Notification).filter(Notification.user_id == user.id)\
        .order_by(Notification.created_at.desc()).limit(50).all()
    return {"status": "success", "notifications": [
        {"id": n.id, "title": n.title, "company": n.company, "body": n.body,
         "job_id": getattr(n, "job_id", None), "is_read": n.is_read,
         "created_at": n.created_at.isoformat() if n.created_at else ""} for n in rows
    ]}


@notif_router.post("/{nid}/read")
def mark_read(nid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    n = db.query(Notification).filter(Notification.id == nid, Notification.user_id == user.id).first()
    if n:
        n.is_read = True; db.commit()
    return {"status": "success"}


# ---------------- Chat (works for admin / recruiter / candidate) ----------------
from app.services.chat import (
    get_or_create_conversation, other_party_id, post_message, display_name, display_photo
)

chat_router = APIRouter(prefix="/chat", tags=["chat"])


@chat_router.get("/conversations")
def conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Conversation).filter(
        (Conversation.candidate_id == user.id) | (Conversation.recruiter_id == user.id)
    ).all()
    out = []
    for c in rows:
        other = db.query(User).filter(User.id == other_party_id(c, user.id)).first()
        last = db.query(Message).filter(Message.conversation_id == c.id)\
            .order_by(Message.created_at.desc()).first()
        unread = db.query(Message).filter(
            Message.conversation_id == c.id,
            Message.sender_id != user.id,
            Message.is_read == False,
        ).count()
        # null-safe timestamp: prefer last message time, fall back to conversation
        ts = None
        if last is not None and last.created_at is not None:
            ts = last.created_at
        elif c.created_at is not None:
            ts = c.created_at
        out.append({
            "conversation_id": c.id,
            "other_id": other.id if other else None,
            "name": display_name(other),
            "photo": display_photo(other),
            "role": other.role.value if other else "",
            "last_message": last.body if last else "",
            "time": ts.isoformat() if ts else "",
            "unread": unread,
        })
    # newest activity first
    out.sort(key=lambda x: x["time"], reverse=True)
    return {"status": "success", "conversations": out}


@chat_router.get("/{conversation_id}/messages")
def messages(conversation_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not c or user.id not in (c.candidate_id, c.recruiter_id):
        raise HTTPException(404, "Conversation not found")
    # mark incoming as read
    db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.sender_id != user.id,
        Message.is_read == False,
    ).update({"is_read": True})
    db.commit()
    rows = db.query(Message).filter(Message.conversation_id == conversation_id)\
        .order_by(Message.created_at).all()
    other = db.query(User).filter(User.id == other_party_id(c, user.id)).first()
    return {
        "status": "success",
        "other_name": display_name(other),
        "other_photo": display_photo(other),
        "messages": [
            {"id": m.id, "body": m.body, "mine": m.sender_id == user.id,
             "read": bool(m.is_read),  # for my sent messages: has the other person read it?
             "time": m.created_at.isoformat() if m.created_at else ""} for m in rows
        ],
    }


class StartChatIn(BaseModel):
    other_user_id: int


@chat_router.post("/start")
def start_conversation(body: StartChatIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Open (or reuse) a conversation with another user. Used by 'Message X' buttons."""
    other = db.query(User).filter(User.id == body.other_user_id).first()
    if not other or other.id == user.id:
        raise HTTPException(404, "User not found")
    conv = get_or_create_conversation(db, user.id, other.id)
    db.commit()
    return {"status": "success", "conversation_id": conv.id, "name": display_name(other)}


@chat_router.post("/support")
def start_support(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Open (or reuse) a conversation with JobifyPL admin/support. Lets recruiters
    and candidates message the admin. Finds the admin by the configured phone."""
    from app.config import settings
    from app.models import Role
    admin = db.query(User).filter(User.role == Role.admin).first()
    if not admin:
        # fall back to the configured admin phone (create the admin user if missing)
        phones = settings.admin_phone_list
        if phones:
            admin = db.query(User).filter(User.phone == phones[0]).first()
            if not admin:
                admin = User(phone=phones[0], role=Role.admin, full_name="JobifyPL Admin")
                db.add(admin); db.flush()
            elif admin.role != Role.admin:
                # don't hijack a user currently acting as another role in dev; only
                # treat as admin for the purpose of routing this support message
                pass
    if not admin or admin.id == user.id:
        raise HTTPException(404, "Support is unavailable right now")
    conv = get_or_create_conversation(db, user.id, admin.id)
    db.commit()
    return {"status": "success", "conversation_id": conv.id, "name": "Admin (JobifyPL)"}


class SendMsgIn(BaseModel):
    conversation_id: int
    body: str


@chat_router.post("/send")
def send_message(body: SendMsgIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.query(Conversation).filter(Conversation.id == body.conversation_id).first()
    if not c or user.id not in (c.candidate_id, c.recruiter_id):
        raise HTTPException(404, "Conversation not found")
    if not (body.body or "").strip():
        raise HTTPException(400, "Empty message")
    post_message(db, c, user, body.body.strip())
    return {"status": "success"}


# ---------------- Contact ----------------
contact_router = APIRouter(prefix="/contact", tags=["contact"])


class ContactIn(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    message: str


@contact_router.post("")
def send_contact(body: ContactIn, db: Session = Depends(get_db)):
    db.add(ContactMessage(name=body.name, email=body.email, phone=body.phone, message=body.message))
    db.commit()
    return {"status": "success", "msg": "Message sent. We'll get back to you."}
