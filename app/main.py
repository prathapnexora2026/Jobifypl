"""JobifyPL — FastAPI application entry point.

Local run:  cd jobify && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
On Render:  uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app import models  # noqa: F401 - ensure models are registered
from app.routers import auth, candidate, jobs, recruiter, wallet, misc, admin, payu_router

# Create tables (dev convenience; production uses Alembic migrations later).
Base.metadata.create_all(bind=engine)

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


# Serve the frontend directory (index.html, recruiter.html, assets).
# Mounted LAST so API routes above always take precedence; html=True makes
# "/" resolve to index.html.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
