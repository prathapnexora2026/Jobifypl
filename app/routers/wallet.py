"""Wallet & subscription plans — candidate-facing (PLN)."""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    User, Wallet, WalletTransaction, SubscriptionPlan, UserSubscription
)
from app.security import get_current_user

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _get_wallet(db, user_id):
    w = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not w:
        w = Wallet(user_id=user_id, balance=0.0, currency="PLN")
        db.add(w); db.commit(); db.refresh(w)
    return w


@router.get("")
def get_wallet(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w = _get_wallet(db, user.id)
    return {"status": "success", "balance": w.balance, "currency": w.currency,
            "total_spent": w.total_spent}


@router.get("/transactions")
def transactions(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(WalletTransaction).filter(
        WalletTransaction.user_id == user.id).order_by(WalletTransaction.created_at.desc()).all()
    return {"status": "success", "transactions": [
        {"amount": t.amount, "type": t.type, "reason": t.reason,
         "created_at": t.created_at.isoformat()} for t in rows
    ]}


class TopupIn(BaseModel):
    amount: float


@router.post("/topup")
def topup(body: TopupIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Placeholder top-up. Real money will flow through PayU (added when merchant keys arrive)."""
    if body.amount <= 0:
        raise HTTPException(400, "Invalid amount")
    w = _get_wallet(db, user.id)
    w.balance += body.amount
    db.add(WalletTransaction(user_id=user.id, amount=body.amount, type="credit", reason="Wallet top-up"))
    db.commit()
    return {"status": "success", "balance": w.balance}


# ----- Plans -----
plans_router = APIRouter(prefix="/plans", tags=["plans"])


@plans_router.get("")
def list_plans(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.is_active == True,
        SubscriptionPlan.for_role == user.role.value).all()
    return {"status": "success", "plans": [
        {"id": p.id, "name": p.name, "price": p.price, "currency": p.currency,
         "duration_days": p.duration_days, "feature1": p.feature1,
         "feature2": p.feature2, "recommended": p.recommended} for p in rows
    ]}


@plans_router.get("/current")
def current_plan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = (db.query(UserSubscription, SubscriptionPlan)
           .join(SubscriptionPlan, SubscriptionPlan.id == UserSubscription.plan_id)
           .filter(UserSubscription.user_id == user.id, UserSubscription.status == "active")
           .order_by(UserSubscription.start_date.desc()).first())
    if not sub:
        return {"status": "success", "plan": None}
    s, p = sub
    return {"status": "success", "plan": {"name": p.name, "end_date": s.end_date.isoformat() if s.end_date else None}}


class PurchaseIn(BaseModel):
    plan_id: int


@plans_router.post("/purchase")
def purchase(body: PurchaseIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == body.plan_id, SubscriptionPlan.is_active == True).first()
    if not plan:
        raise HTTPException(404, "Plan not found")
    w = _get_wallet(db, user.id)
    if w.balance < plan.price:
        raise HTTPException(400, "Insufficient wallet balance. Please top up.")
    w.balance -= plan.price
    w.total_spent += plan.price
    db.add(WalletTransaction(user_id=user.id, amount=plan.price, type="debit",
                            reason=f"Subscription: {plan.name}"))
    start = dt.datetime.utcnow()
    end = start + dt.timedelta(days=plan.duration_days)
    db.add(UserSubscription(user_id=user.id, plan_id=plan.id, start_date=start, end_date=end, status="active"))
    db.commit()
    return {"status": "success", "msg": f"{plan.name} activated", "balance": w.balance}
