"""JobifyPL — FastAPI application entry point.

Local run:  cd jobify && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
On Render:  uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
from pathlib import Path

import html

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app import models  # noqa: F401 - ensure models are registered
from app.routers import auth, candidate, jobs, recruiter, wallet, misc, admin, payu_router, coupons

# Create tables (dev convenience; production uses Alembic migrations later).
Base.metadata.create_all(bind=engine)

# Apply tiny column migrations that create_all can't (e.g. new columns on
# existing tables). Safe + idempotent — see app/migrate.py.
from app.migrate import run_migrations
run_migrations()

# Seed the default subscription plans on first boot (only if the table is empty),
# so the admin and users see the standard plans immediately on a fresh database.
from app.seed_plans import seed_default_plans
seed_default_plans()

app = FastAPI(title="JobifyPL API")

# CORS — allow the website + Capacitor app origins (learned this the hard way!).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # tighten to real origins before production
    allow_methods=["*"],
    allow_headers=["*"],
)


# Never let the browser cache the HTML app shells — otherwise users keep seeing
# a stale page after we ship a fix (the "hard refresh needed" problem).
@app.middleware("http")
async def no_cache_html(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith(".html") or path == "/" or "." not in path.rsplit("/", 1)[-1]:
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response

# Routers
app.include_router(auth.router)
app.include_router(candidate.router)
app.include_router(jobs.router)
app.include_router(recruiter.router)
app.include_router(wallet.router)
app.include_router(wallet.plans_router)
app.include_router(misc.notif_router)
app.include_router(misc.chat_router)
app.include_router(misc.contact_router)
app.include_router(misc.testotp_router)   # test-only OTP viewer (auto-disabled when SMS goes live)
app.include_router(admin.router)
app.include_router(coupons.admin_router)  # admin: create/list/track coupons
app.include_router(coupons.user_router)   # user: validate a coupon at checkout
app.include_router(payu_router.router)    # PayU notify webhook + return page

# Serve uploaded files. On Render these live on the persistent disk (DATA_DIR)
# so they survive deploys — see app/paths.py.
from app.paths import UPLOADS_DIR, DOWNLOADS_DIR
app.mount("/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")

@app.get("/health")
def health():
    return {"status": "ok"}


# APK download for testers. Serves the latest Android build as a file download
# so testers can install it directly from the site (no Play Store needed yet).
#
# The APK ships WITH the code (committed to the repo's downloads/ folder), so it
# is served from there — not the persistent disk. We still fall back to the disk
# copy (/data/downloads) in case an APK is uploaded there manually.
REPO_DOWNLOADS = Path(__file__).resolve().parent.parent / "downloads"
APK_CANDIDATES = [REPO_DOWNLOADS / "JobifyPL.apk", DOWNLOADS_DIR / "JobifyPL.apk"]


@app.get("/download/app")
def download_apk():
    for apk in APK_CANDIDATES:
        if apk.exists():
            return FileResponse(
                apk,
                media_type="application/vnd.android.package-archive",
                filename="JobifyPL.apk",
            )
    raise HTTPException(status_code=404, detail="APK not available yet")


# ---- Shared job link landing page ----------------------------------------
# A candidate shares https://jobifypl.pl/job/<id>. Opening that link should:
#   • show a rich preview (OG tags) in WhatsApp / social,
#   • open the installed app straight to the job (Android intent:// with the
#     pl.jobifypl.app:// deep link the app already handles), and
#   • if the app isn't installed, fall back to the download page.
# Registered BEFORE the "/" static mount so it takes precedence.
@app.get("/job/{job_id}", response_class=HTMLResponse)
def job_share_landing(job_id: int, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    title = html.escape((job.title if job else "Job on JobifyPL") or "Job on JobifyPL")
    company = html.escape((job.company_name if job and job.company_name else "JobifyPL"))
    location = html.escape((job.location if job and job.location else "") or "")
    jtype = html.escape((job.job_type if job and job.job_type else "Job") or "Job")
    desc = html.escape(
        f"{job.title} at {job.company_name or 'JobifyPL'}"
        + (f" · {job.location}" if job and job.location else "")
        if job else "View this job on JobifyPL"
    )
    page = _JOB_LANDING_HTML
    for k, v in {
        "__JOBID__": str(job_id), "__TITLE__": title, "__COMPANY__": company,
        "__LOC__": location, "__JTYPE__": jtype, "__DESC__": desc,
    }.items():
        page = page.replace(k, v)
    return HTMLResponse(page)


_JOB_LANDING_HTML = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__ · JobifyPL</title>
<meta property="og:type" content="website">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__DESC__">
<meta property="og:url" content="https://jobifypl.pl/job/__JOBID__">
<meta property="og:image" content="https://jobifypl.pl/assets/logo/jobifyPLlogo.png">
<meta name="twitter:card" content="summary">
<style>
*{box-sizing:border-box} body{margin:0;font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;
background:linear-gradient(160deg,#12305a,#1b4b8f);min-height:100vh;display:flex;align-items:center;
justify-content:center;padding:24px;color:#12305a}
.card{background:#fff;border-radius:22px;max-width:400px;width:100%;padding:28px 24px;
box-shadow:0 20px 60px rgba(0,0,0,.3);text-align:center}
.logo{height:44px;margin-bottom:16px}
.tag{display:inline-block;background:#EEF2F8;color:#1b4b8f;font-size:12px;font-weight:700;
padding:5px 12px;border-radius:20px;margin-bottom:12px}
h1{font-size:22px;margin:6px 0 4px;line-height:1.25}
.co{color:#475569;font-size:14px;margin-bottom:2px;font-weight:600}
.loc{color:#94A3B8;font-size:13px;margin-bottom:20px}
.btn{display:block;width:100%;padding:15px;border-radius:14px;font-size:16px;font-weight:800;
border:none;cursor:pointer;text-decoration:none;margin-top:12px}
.btn.primary{background:#F5A800;color:#241c00}
.btn.ghost{background:#EEF2F8;color:#1b4b8f}
.hint{color:#94A3B8;font-size:12px;margin-top:18px;line-height:1.5}
</style></head><body>
<div class="card">
  <img class="logo" src="https://jobifypl.pl/assets/logo/jobifyPLlogo.png" alt="JobifyPL" onerror="this.style.display='none'">
  <div class="tag">__JTYPE__</div>
  <h1>__TITLE__</h1>
  <div class="co">__COMPANY__</div>
  <div class="loc">__LOC__</div>
  <a class="btn primary" id="openApp" href="#">Open in App</a>
  <a class="btn ghost" href="https://jobifypl.pl/">Download the App</a>
  <div class="hint">Tap <b>Open in App</b> to view this job in JobifyPL. Don't have the app yet? Tap <b>Download the App</b> to get started.</div>
</div>
<script>
(function(){
  var JOBID=__JOBID__, FALLBACK="https://jobifypl.pl/";
  var isAndroid=/Android/i.test(navigator.userAgent);
  var deep=isAndroid
    ? "intent://job/"+JOBID+"#Intent;scheme=pl.jobifypl.app;package=pl.jobifypl.app;S.browser_fallback_url="+encodeURIComponent(FALLBACK)+";end"
    : "pl.jobifypl.app://job/"+JOBID;
  document.getElementById("openApp").href=deep;
  // On Android, try to open the app automatically (installed -> app; not -> fallback).
  if(isAndroid){ setTimeout(function(){ try{ window.location.href=deep; }catch(e){} }, 400); }
})();
</script>
</body></html>"""


# Serve the frontend directory (index.html, recruiter.html, assets).
# Mounted LAST so API routes above always take precedence; html=True makes
# "/" resolve to index.html.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
