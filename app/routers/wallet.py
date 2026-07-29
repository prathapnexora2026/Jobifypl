"""Wallet & subscription plans (PLN).

Payments can flow two ways:
  * from wallet balance (instant, no gateway) — the original flow, and
  * via PayU real-money checkout — /wallet/topup-checkout and
    /plans/checkout create a PENDING Payment and return a PayU redirect URL.
    The wallet is only credited / the plan only activated after PayU's notify
    webhook confirms the money (see app/routers/payu_router.py).
"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    User, Wallet, WalletTransaction, SubscriptionPlan, UserSubscription,
    Payment, Notification,
)
from app.security import get_current_user
from app.services import payu

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _get_wallet(db, user_id):
    w = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not w:
        w = Wallet(user_id=user_id, balance=0.0, currency="PLN")
        db.add(w); db.commit(); db.refresh(w)
    return w


# ---------------------------------------------------------------------------
# Shared fulfilment helpers — called BOTH by the pay-from-wallet path and by
# the PayU notify webhook once a real payment is confirmed. Keeping them here
# (one place) means "what a successful payment does" can never drift apart.
# ---------------------------------------------------------------------------
def credit_wallet(db: Session, user_id: int, amount: float, reason: str,
                  method: str = "wallet", payu_ref: str = None):
    w = _get_wallet(db, user_id)
    w.balance += amount
    db.add(WalletTransaction(user_id=user_id, amount=amount, type="credit", reason=reason,
                            method=method, payu_ref=payu_ref))
    db.add(Notification(user_id=user_id, title="Wallet topped up",
                        body=f"{amount:.2f} PLN added to your wallet."))
    return w


def activate_plan(db: Session, user_id: int, plan: SubscriptionPlan, paid_reason: str):
    """Activate `plan` for a user and record the spend. Does NOT touch wallet
    balance (caller decides whether it was paid from wallet or via PayU)."""
    start = dt.datetime.utcnow()
    end = start + dt.timedelta(days=plan.duration_days or 0)
    db.add(UserSubscription(
        user_id=user_id, plan_id=plan.id, start_date=start, end_date=end,
        status="active", posts_total=plan.postings or 0, posts_used=0))
    db.add(Notification(user_id=user_id, title="Plan activated",
                        body=f"{plan.name} is now active until {end.date().isoformat()}."))


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
        {"id": t.id, "amount": t.amount, "type": t.type, "reason": t.reason,
         "ref": t.ref, "method": t.method, "payu_ref": t.payu_ref,
         "created_at": t.created_at.isoformat()} for t in rows
    ]}


class TopupIn(BaseModel):
    amount: float


@router.post("/topup")
def topup(body: TopupIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Instant wallet credit WITHOUT a gateway.

    Used only when PayU is disabled (PAYU_ENABLED=false) so testing is never
    blocked. When PayU is live, the frontend calls /wallet/topup-checkout
    instead and money really moves.
    """
    if body.amount <= 0:
        raise HTTPException(400, "Invalid amount")
    if settings.PAYU_ENABLED:
        raise HTTPException(400, "Use PayU checkout to add funds.")
    w = credit_wallet(db, user.id, body.amount, "Wallet top-up (test mode)")
    db.commit()
    return {"status": "success", "balance": w.balance}


@router.post("/topup-checkout")
def topup_checkout(body: TopupIn, request: Request,
                   user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Start a real PayU payment to add funds. Returns a redirect URL the app
    opens; wallet is credited later by the verified notify webhook."""
    if body.amount <= 0:
        raise HTTPException(400, "Invalid amount")
    if not settings.PAYU_ENABLED:
        # graceful fallback so the same button works before keys are set
        w = credit_wallet(db, user.id, body.amount, "Wallet top-up (test mode)")
        db.commit()
        return {"status": "success", "paid": True, "balance": w.balance}

    ext = payu.new_ext_order_id("wallet", user.id)
    pay = Payment(user_id=user.id, ext_order_id=ext, amount=body.amount,
                  currency="PLN", purpose="wallet_topup", status="pending")
    db.add(pay); db.commit()
    try:
        res = payu.create_order(
            ext_order_id=ext, amount_pln=body.amount,
            description=f"JobifyPL wallet top-up ({body.amount:.2f} PLN)",
            buyer_email=user.email or "", buyer_phone=user.phone or "",
            customer_ip=(request.client.host if request.client else "127.0.0.1"))
    except Exception as e:
        pay.status = "failed"; db.commit()
        raise HTTPException(502, f"Payment gateway error: {e}")
    pay.payu_order_id = res.get("payu_order_id"); db.commit()
    return {"status": "success", "paid": False, "redirect_url": res["redirect_uri"], "ext_order_id": ext}


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


@plans_router.get("/public")
def public_plans(db: Session = Depends(get_db)):
    """Public price list (NO login) for the website — required by the payment
    provider so prices are visible before purchase. Reflects live admin changes
    (reads the same SubscriptionPlan table), so it is never hard-coded.
    Returns plans grouped into candidate (job seeker) and recruiter (employer)."""
    rows = db.query(SubscriptionPlan).filter(SubscriptionPlan.is_active == True)\
             .order_by(SubscriptionPlan.price.asc()).all()

    def fmt(p):
        return {"id": p.id, "name": p.name, "price": p.price, "currency": p.currency or "PLN",
                "duration_days": p.duration_days, "postings": p.postings,
                "feature1": p.feature1, "feature2": p.feature2, "recommended": p.recommended}

    candidate = [fmt(p) for p in rows if (p.for_role or "").lower() == "candidate"]
    recruiter = [fmt(p) for p in rows if (p.for_role or "").lower() == "recruiter"]
    return {"status": "success", "candidate": candidate, "recruiter": recruiter}


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
    """Buy a plan using WALLET balance (option 1: pay from wallet)."""
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
    activate_plan(db, user.id, plan, "wallet")
    db.commit()
    return {"status": "success", "msg": f"{plan.name} activated", "balance": w.balance}


@plans_router.post("/checkout")
def plan_checkout(body: PurchaseIn, request: Request,
                  user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Buy a plan by paying DIRECTLY via PayU (option 2: pay direct).

    Returns a PayU redirect URL; the plan is activated later by the verified
    notify webhook. Falls back to instant activation if PayU is disabled."""
    plan = db.query(SubscriptionPlan).filter(
        SubscriptionPlan.id == body.plan_id, SubscriptionPlan.is_active == True).first()
    if not plan:
        raise HTTPException(404, "Plan not found")

    if not settings.PAYU_ENABLED:
        w = _get_wallet(db, user.id)
        w.total_spent += plan.price
        db.add(WalletTransaction(user_id=user.id, amount=plan.price, type="debit",
                                reason=f"Subscription (test): {plan.name}"))
        activate_plan(db, user.id, plan, "test")
        db.commit()
        return {"status": "success", "paid": True, "msg": f"{plan.name} activated"}

    ext = payu.new_ext_order_id("plan", user.id)
    pay = Payment(user_id=user.id, ext_order_id=ext, amount=plan.price,
                  currency=plan.currency or "PLN", purpose="plan", plan_id=plan.id,
                  status="pending")
    db.add(pay); db.commit()
    try:
        res = payu.create_order(
            ext_order_id=ext, amount_pln=plan.price,
            description=f"JobifyPL plan: {plan.name}",
            buyer_email=user.email or "", buyer_phone=user.phone or "",
            customer_ip=(request.client.host if request.client else "127.0.0.1"))
    except Exception as e:
        pay.status = "failed"; db.commit()
        raise HTTPException(502, f"Payment gateway error: {e}")
    pay.payu_order_id = res.get("payu_order_id"); db.commit()
    return {"status": "success", "paid": False, "redirect_url": res["redirect_uri"], "ext_order_id": ext}


@plans_router.get("/payment-status/{ext_order_id}")
def payment_status(ext_order_id: str, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """The app polls this after returning from PayU to know if it's done.

    We don't rely on the notify webhook alone (it can be delayed or blocked):
    if the payment is still pending, ask PayU directly. If PayU says the order
    is only WAITING_FOR_CONFIRMATION (manual-capture POS), capture it here, then
    fulfil — so the wallet is credited even if no webhook ever arrives.
    """
    pay = db.query(Payment).filter(
        Payment.ext_order_id == ext_order_id, Payment.user_id == user.id).first()
    if not pay:
        raise HTTPException(404, "Payment not found")

    if not pay.fulfilled and pay.status != "failed" and pay.payu_order_id and settings.PAYU_ENABLED:
        pu = payu.get_order_status(pay.payu_order_id)
        if pu == "WAITING_FOR_CONFIRMATION":
            payu.capture_order(pay.payu_order_id)
            pu = payu.get_order_status(pay.payu_order_id)
        if pu == "COMPLETED":
            _fulfil_payment(db, pay)
        elif pu in ("CANCELED", "REJECTED"):
            pay.status = "failed"; db.commit()

    return {"status": "success", "payment_status": pay.status, "fulfilled": pay.fulfilled}


def _fulfil_payment(db: Session, pay: Payment):
    """Credit wallet / activate plan for a confirmed payment, exactly once.
    Shared by the polling endpoint and the notify webhook.

    Guard against a poll + webhook fulfilling the same payment at once: flip
    `fulfilled` false->true with a single conditional UPDATE and only proceed if
    THIS call is the one that won the flip (rowcount == 1)."""
    if pay.fulfilled:
        return
    won = (db.query(Payment)
             .filter(Payment.id == pay.id, Payment.fulfilled == False)  # noqa: E712
             .update({Payment.fulfilled: True, Payment.status: "paid"},
                     synchronize_session=False))
    db.commit()
    if not won:
        return  # another request already fulfilled it
    db.refresh(pay)
    if pay.purpose == "wallet_topup":
        credit_wallet(db, pay.user_id, pay.amount, "Wallet top-up (PayU)",
                      method="payu", payu_ref=pay.payu_order_id)
    elif pay.purpose == "plan" and pay.plan_id:
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == pay.plan_id).first()
        if plan:
            wal = db.query(Wallet).filter(Wallet.user_id == pay.user_id).first()
            if wal:
                wal.total_spent += plan.price
            db.add(WalletTransaction(user_id=pay.user_id, amount=plan.price, type="debit",
                                    reason=f"Subscription: {plan.name}", method="payu",
                                    payu_ref=pay.payu_order_id))
            activate_plan(db, pay.user_id, plan, "payu")
    elif pay.purpose == "rec_plan" and pay.plan_id:
        plan = db.query(SubscriptionPlan).filter(SubscriptionPlan.id == pay.plan_id).first()
        if plan:
            wal = db.query(Wallet).filter(Wallet.user_id == pay.user_id).first()
            if wal:
                wal.total_spent += plan.price
            db.add(WalletTransaction(user_id=pay.user_id, amount=plan.price, type="debit",
                                    reason=f"{plan.name} Plan", method="payu",
                                    payu_ref=pay.payu_order_id))
            from app.routers.recruiter import activate_recruiter_package
            activate_recruiter_package(db, pay.user_id, plan)
    db.commit()
