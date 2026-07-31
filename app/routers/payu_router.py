"""PayU webhook + return handling.

/payu/notify  — server-to-server call from PayU. We VERIFY the signature, then
                (and only then) mark the Payment paid and grant what was bought.
/payu/return  — where the browser lands after paying; just a friendly page that
                tells the app to re-check status. No trust is placed in it.
"""
from fastapi import APIRouter, Depends, Request, Header
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Payment
from app.services import payu

router = APIRouter(prefix="/payu", tags=["payu"])

# PayU statuses that mean the money is actually captured.
_PAID = {"COMPLETED"}
# Authorized but not yet collected (manual-capture POS). We must capture these.
_NEEDS_CAPTURE = {"WAITING_FOR_CONFIRMATION"}


@router.post("/notify")
async def payu_notify(request: Request,
                      openpayu_signature: str = Header(default="", alias="OpenPayU-Signature"),
                      db: Session = Depends(get_db)):
    """PayU calls this after every status change. Verify, then fulfil once."""
    raw = await request.body()

    # 1) Reject anything not genuinely signed by PayU with our secret key.
    if not payu.verify_notify_signature(raw, openpayu_signature):
        return JSONResponse({"error": "bad signature"}, status_code=400)

    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "bad json"}, status_code=400)

    order = payload.get("order") or {}
    ext_order_id = order.get("extOrderId")
    status = (order.get("status") or "").upper()
    if not ext_order_id:
        # Always 200 so PayU stops retrying a call we can't map.
        return {"status": "ignored"}

    pay = db.query(Payment).filter(Payment.ext_order_id == ext_order_id).first()
    if not pay:
        return {"status": "unknown-order"}

    # Authorized but not collected yet (manual-capture POS): capture it now so
    # it becomes COMPLETED. PayU then sends another notify with COMPLETED, and
    # we also fall through below in case this same call flips to paid.
    if status in _NEEDS_CAPTURE:
        if payu.capture_order(pay.payu_order_id):
            # Re-check the real status after capture.
            new_status = payu.get_order_status(pay.payu_order_id)
            if new_status in _PAID:
                status = new_status  # fall through to fulfilment below
            else:
                return {"status": "capturing"}
        else:
            return {"status": "capture-pending"}

    # Record the latest status.
    if status and status not in _PAID:
        if status in ("CANCELED", "REJECTED"):
            pay.status = "failed"
            db.commit()
        return {"status": "ok"}

    # 2) Money captured. Fulfil exactly once (idempotent — PayU may retry).
    if status in _PAID and not pay.fulfilled:
        from app.routers.wallet import _fulfil_payment
        _fulfil_payment(db, pay)

    return {"status": "ok"}


@router.get("/return", response_class=HTMLResponse)
def payu_return(ext: str = ""):
    """Landing page after PayU checkout.

    In the mobile APK, PayU is opened in the Capacitor in-app Browser, so here we
    just CLOSE that browser — Android returns to the still-logged-in app, which
    resumes the pending payment and credits the wallet. In a plain web browser
    (no Capacitor), we navigate back to the correct app page instead.
    ext prefixes: recwallet-/recplan- => recruiter; wallet-/plan- => candidate."""
    is_recruiter = ext.startswith("rec")
    back = "/recruiter.html" if is_recruiter else "/app.html"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Payment complete — JobifyPL</title>
<style>body{{font-family:system-ui,Arial;text-align:center;padding:60px 20px;color:#12305a}}
.b{{background:#F5A800;color:#241c00;border:none;border-radius:12px;padding:15px 26px;font-size:16px;font-weight:700;margin-top:16px}}
.sp{{width:36px;height:36px;border:3px solid #eee;border-top-color:#F5A800;border-radius:50%;margin:0 auto 18px;animation:s 1s linear infinite}}
@keyframes s{{to{{transform:rotate(360deg)}}}}</style>
</head><body>
<div class="sp"></div>
<h2>Payment received ✅</h2>
<p>You can now return to the JobifyPL app — your wallet/plan updates automatically.</p>
<button class="b" onclick="goBack()">Return to app</button>
<script>
var BACK={back!r};
function goBack(){{
  // 1) Try a deep link so Android brings the JobifyPL app to the foreground
  //    (closing this in-app tab). The app's browserFinished/resume listener then
  //    resumes the payment. 2) If that scheme isn't handled, fall back to
  //    navigating this tab back to the app page.
  try{{ window.location.href = "pl.jobifypl.app://payu-return"; }}catch(e){{}}
  setTimeout(function(){{ location.href = BACK; }}, 600);
}}
setTimeout(goBack, 800);
</script>
</body></html>"""
