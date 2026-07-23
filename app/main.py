"""JobifyPL — FastAPI application entry point.

Local run:  cd jobify && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
On Render:  uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine
from app import models  # noqa: F401 - ensure models are registered
from app.routers import auth, candidate, jobs, recruiter, wallet, misc, admin

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
app.include_router(admin.router)

# Serve uploaded files (dev). Production will use object storage instead.
UPLOADS = Path(__file__).resolve().parent.parent / "uploads"
UPLOADS.mkdir(exist_ok=True)
app.mount("/uploads", StaticFiles(directory=UPLOADS), name="uploads")

@app.get("/health")
def health():
    return {"status": "ok"}


# Serve the frontend directory (index.html, recruiter.html, assets).
# Mounted LAST so API routes above always take precedence; html=True makes
# "/" resolve to index.html.
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
