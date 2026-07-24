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


@notif_router.delete("/{nid}")
def delete_notification(nid: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete one of the caller's notifications (candidate or recruiter)."""
    n = db.query(Notification).filter(Notification.id == nid, Notification.user_id == user.id).first()
    if n:
        db.delete(n); db.commit()
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
    uid = str(user.id)

    def _hidden_for_me(m):
        return uid in [x for x in (m.deleted_for or "").split(",") if x]

    out = []
    for c in rows:
        other = db.query(User).filter(User.id == other_party_id(c, user.id)).first()
        all_msgs = db.query(Message).filter(Message.conversation_id == c.id)\
            .order_by(Message.created_at.desc()).all()
        # messages still visible to THIS user (not deleted-for-me)
        visible = [m for m in all_msgs if not _hidden_for_me(m)]
        # If the user deleted the whole chat and nothing new arrived, hide the thread.
        if all_msgs and not visible:
            continue
        last = visible[0] if visible else None
        unread = sum(1 for m in visible
                     if m.sender_id != user.id and not m.is_read)
        last_body = ("This message was deleted" if (last and last.deleted_for_all)
                     else (last.body if last else ""))
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
            "last_message": last_body,
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

    def _visible(m):
        # Hidden entirely if THIS user deleted it just for themselves.
        deleted_for = (m.deleted_for or "")
        mine_deleted = str(user.id) in [x for x in deleted_for.split(",") if x]
        return not mine_deleted

    out = []
    for m in rows:
        if not _visible(m):
            continue
        if getattr(m, "deleted_for_all", False):
            out.append({"id": m.id, "body": "This message was deleted", "mine": m.sender_id == user.id,
                        "deleted": True, "read": bool(m.is_read),
                        "time": m.created_at.isoformat() if m.created_at else ""})
        else:
            out.append({"id": m.id, "body": m.body, "mine": m.sender_id == user.id,
                        "deleted": False, "read": bool(m.is_read),
                        "time": m.created_at.isoformat() if m.created_at else ""})
    return {
        "status": "success",
        "other_name": display_name(other),
        "other_photo": display_photo(other),
        "messages": out,
    }


class DeleteMsgIn(BaseModel):
    message_ids: list[int]
    scope: str = "me"   # "me" or "everyone"


@chat_router.post("/{conversation_id}/delete-messages")
def delete_messages(conversation_id: int, body: DeleteMsgIn,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Delete messages. scope='me' hides them for the caller only (any message);
    scope='everyone' marks them deleted for both — allowed ONLY on the caller's
    own sent messages (like WhatsApp)."""
    c = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not c or user.id not in (c.candidate_id, c.recruiter_id):
        raise HTTPException(404, "Conversation not found")
    msgs = db.query(Message).filter(
        Message.conversation_id == conversation_id,
        Message.id.in_(body.message_ids or [])).all()
    for m in msgs:
        if body.scope == "everyone":
            # only your own messages can be deleted for everyone
            if m.sender_id == user.id:
                m.deleted_for_all = True
        else:  # "me"
            ids = [x for x in (m.deleted_for or "").split(",") if x]
            if str(user.id) not in ids:
                ids.append(str(user.id))
            m.deleted_for = ",".join(ids)
    db.commit()
    return {"status": "success"}


@chat_router.post("/{conversation_id}/delete")
def delete_conversation(conversation_id: int, user: User = Depends(get_current_user),
                        db: Session = Depends(get_db)):
    """Delete a whole conversation FOR THE CALLER (like WhatsApp 'Delete chat').
    Every message is hidden for this user; the thread disappears from their list.
    If the other person messages again, a fresh thread shows for the caller."""
    c = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not c or user.id not in (c.candidate_id, c.recruiter_id):
        raise HTTPException(404, "Conversation not found")
    msgs = db.query(Message).filter(Message.conversation_id == conversation_id).all()
    for m in msgs:
        ids = [x for x in (m.deleted_for or "").split(",") if x]
        if str(user.id) not in ids:
            ids.append(str(user.id))
        m.deleted_for = ",".join(ids)
    db.commit()
    return {"status": "success"}


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


# ---------------- TEST-ONLY OTP viewer ----------------
# Lets a small group of testers read their own OTP on-screen while SMS is not yet
# live (SMS_DEV_MODE=True). It does NOT touch the real auth flow — it only READS the
# latest unconsumed code for a phone. Auto-disables the moment real SMS goes live
# (SMS_DEV_MODE=False), so it can never leak OTPs in production.
import datetime as dt
from app.config import settings
from app.models import OtpCode

testotp_router = APIRouter(prefix="/testotp", tags=["test-otp"])


class PeekOtpIn(BaseModel):
    phone: str


@testotp_router.post("/peek")
def peek_otp(body: PeekOtpIn, db: Session = Depends(get_db)):
    if not settings.SMS_DEV_MODE:
        raise HTTPException(403, "This test helper is disabled (real SMS is live).")
    phone = (body.phone or "").strip()
    if not phone.startswith("+") or len(phone) < 8:
        raise HTTPException(400, "Enter a valid phone number with country code, e.g. +48...")
    otp = (
        db.query(OtpCode)
        .filter(OtpCode.phone == phone, OtpCode.consumed == False)
        .order_by(OtpCode.id.desc())
        .first()
    )
    if not otp:
        raise HTTPException(404, "No pending OTP for this number. Request one in the app first.")
    if otp.expires_at < dt.datetime.utcnow():
        raise HTTPException(400, "That OTP expired — request a new one in the app.")
    return {"status": "success", "phone": phone, "code": otp.code}
