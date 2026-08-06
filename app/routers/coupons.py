"""Coupons — admin create/list/track, plus user-facing validation and a redeem
helper used by the plan-purchase and wallet-top-up flows.

Code format: JPL + 3 random digits (e.g. JPL482). Two coupon types:
  • percent — reduces the amount charged by N% (plans and wallet top-ups)
  • credit  — adds N PLN of free wallet credit (wallet)
"""
import datetime as dt
import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Coupon, CouponRedemption, User
from app.security import require_admin, get_current_user


def _role_str(user: User) -> str:
    return user.role.value if hasattr(user.role, "value") else str(user.role)


def generate_code(db: Session) -> str:
    """JPL + 3 random (non-sequential) digits, guaranteed unique in the DB."""
    for _ in range(60):
        code = "JPL" + f"{random.randint(0, 999):03d}"
        if not db.query(Coupon).filter(Coupon.code == code).first():
            return code
    for _ in range(60):                      # fallback to 4 digits if 3-digit space is exhausted
        code = "JPL" + f"{random.randint(0, 9999):04d}"
        if not db.query(Coupon).filter(Coupon.code == code).first():
            return code
    raise HTTPException(500, "Could not generate a unique coupon code")


# ============================ ADMIN ============================
admin_router = APIRouter(prefix="/admin/coupons", tags=["admin-coupons"])


class CouponIn(BaseModel):
    label: str = ""
    discount_type: str = "percent"     # percent | credit
    discount_value: float = 0          # 50 => 50% ; or 25 => 25 PLN free credit
    applies_to: str = "both"           # plan | wallet | both
    for_role: str = "both"             # candidate | recruiter | both
    max_uses: int | None = None        # total redemption cap (None = unlimited)
    once_per_user: bool = True
    expires_at: str | None = None      # ISO date (optional)
    code: str | None = None            # optional custom code; else auto-generated


def _coupon_dict(db: Session, c: Coupon) -> dict:
    reds = db.query(CouponRedemption).filter(CouponRedemption.coupon_id == c.id).all()
    return {
        "id": c.id, "code": c.code, "label": c.label or "",
        "discount_type": c.discount_type, "discount_value": c.discount_value,
        "applies_to": c.applies_to, "for_role": c.for_role,
        "max_uses": c.max_uses, "used_count": c.used_count or 0,
        "once_per_user": bool(c.once_per_user), "active": bool(c.active),
        "expires_at": c.expires_at.isoformat() if c.expires_at else None,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "candidate_uses": sum(1 for r in reds if r.role == "candidate"),
        "recruiter_uses": sum(1 for r in reds if r.role == "recruiter"),
        "total_uses": len(reds),
        "total_discount": round(sum((r.discount_amount or 0) for r in reds), 2),
    }


@admin_router.post("")
def create_coupon(body: CouponIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.discount_type not in ("percent", "credit"):
        raise HTTPException(400, "discount_type must be 'percent' or 'credit'")
    if body.applies_to not in ("plan", "wallet", "both"):
        raise HTTPException(400, "applies_to must be plan, wallet or both")
    if body.for_role not in ("candidate", "recruiter", "both"):
        raise HTTPException(400, "for_role must be candidate, recruiter or both")
    if body.discount_value <= 0:
        raise HTTPException(400, "discount_value must be greater than 0")
    if body.discount_type == "percent" and body.discount_value > 100:
        raise HTTPException(400, "percent discount cannot exceed 100")
    code = (body.code or "").strip().upper() or generate_code(db)
    if db.query(Coupon).filter(Coupon.code == code).first():
        raise HTTPException(400, "That coupon code already exists")
    exp = None
    if body.expires_at:
        try:
            exp = dt.datetime.fromisoformat(body.expires_at)
        except Exception:
            raise HTTPException(400, "Invalid expires_at date")
    c = Coupon(code=code, label=(body.label or "").strip(), discount_type=body.discount_type,
               discount_value=body.discount_value, applies_to=body.applies_to,
               for_role=body.for_role, max_uses=body.max_uses,
               once_per_user=bool(body.once_per_user), active=True, expires_at=exp)
    db.add(c); db.commit(); db.refresh(c)
    return {"status": "success", "coupon": _coupon_dict(db, c)}


@admin_router.get("")
def list_coupons(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    rows = db.query(Coupon).order_by(Coupon.created_at.desc()).all()
    return {"status": "success", "coupons": [_coupon_dict(db, c) for c in rows]}


@admin_router.put("/{cid}/toggle")
def toggle_coupon(cid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    c = db.query(Coupon).filter(Coupon.id == cid).first()
    if not c:
        raise HTTPException(404, "Coupon not found")
    c.active = not c.active
    db.commit()
    return {"status": "success", "active": c.active}


@admin_router.delete("/{cid}")
def delete_coupon(cid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    c = db.query(Coupon).filter(Coupon.id == cid).first()
    if c:
        db.query(CouponRedemption).filter(CouponRedemption.coupon_id == cid).delete()
        db.delete(c); db.commit()
    return {"status": "success"}


@admin_router.get("/{cid}/redemptions")
def coupon_redemptions(cid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    reds = (db.query(CouponRedemption, User)
            .outerjoin(User, User.id == CouponRedemption.user_id)
            .filter(CouponRedemption.coupon_id == cid)
            .order_by(CouponRedemption.created_at.desc()).all())
    out = [{"user": (u.full_name or u.phone) if u else "—", "role": r.role,
            "context": r.context, "discount": round(r.discount_amount or 0, 2),
            "at": r.created_at.isoformat() if r.created_at else None}
           for r, u in reds]
    return {"status": "success", "redemptions": out}


# ==================== USER-FACING VALIDATION + REDEEM ====================
user_router = APIRouter(prefix="/coupons", tags=["coupons"])


def validate_coupon(db: Session, code: str, user: User, context: str, amount: float):
    """Validate a coupon for this user + context ('plan' or 'wallet') and a base
    amount. Returns (coupon, discount, new_charge). Raises HTTPException if invalid.
      • percent -> new_charge = amount - discount (they pay less)
      • credit  -> discount = free credit added; new_charge = amount (unchanged)."""
    code = (code or "").strip().upper()
    c = db.query(Coupon).filter(Coupon.code == code).first()
    if not c or not c.active:
        raise HTTPException(400, "Invalid or inactive coupon code")
    if c.expires_at and c.expires_at < dt.datetime.utcnow():
        raise HTTPException(400, "This coupon has expired")
    role = _role_str(user)
    if c.for_role != "both" and c.for_role != role:
        raise HTTPException(400, "This coupon is not valid for your account type")
    if c.applies_to != "both" and c.applies_to != context:
        raise HTTPException(400, f"This coupon can't be used on a {context} purchase")
    if c.max_uses is not None and (c.used_count or 0) >= c.max_uses:
        raise HTTPException(400, "This coupon has reached its usage limit")
    if c.once_per_user and db.query(CouponRedemption).filter(
            CouponRedemption.coupon_id == c.id, CouponRedemption.user_id == user.id).first():
        raise HTTPException(400, "You have already used this coupon")

    amount = float(amount or 0)
    if c.discount_type == "credit":
        discount = float(c.discount_value or 0)          # free credit
        new_charge = amount
    else:  # percent
        pct = max(0.0, min(100.0, float(c.discount_value or 0)))
        discount = round(amount * pct / 100.0, 2)
        new_charge = round(max(0.0, amount - discount), 2)
    return c, discount, new_charge


def redeem_coupon(db: Session, coupon: Coupon, user: User, context: str, discount_amount: float):
    """Record a redemption and bump used_count. Call inside the purchase txn
    (the caller commits)."""
    db.add(CouponRedemption(coupon_id=coupon.id, user_id=user.id, role=_role_str(user),
                            context=context, discount_amount=round(float(discount_amount or 0), 2)))
    coupon.used_count = (coupon.used_count or 0) + 1


class ValidateIn(BaseModel):
    code: str
    context: str = "plan"       # plan | wallet
    amount: float = 0


@user_router.post("/validate")
def validate(body: ValidateIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Preview a coupon before checkout (no redemption happens here)."""
    ctx = body.context if body.context in ("plan", "wallet") else "plan"
    c, discount, new_charge = validate_coupon(db, body.code, user, ctx, body.amount)
    return {"status": "success", "code": c.code, "label": c.label or "",
            "discount_type": c.discount_type, "discount_value": c.discount_value,
            "discount": discount, "new_charge": new_charge}
