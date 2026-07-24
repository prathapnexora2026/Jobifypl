"""Single source of truth for on-disk storage locations.

Locally these sit in the project folder. On Render we set DATA_DIR=/data (a
mounted Persistent Disk), so everything users upload — profile photos, CVs, the
APK — lives on the disk and SURVIVES every deploy / GitHub push. Nothing is
stored inside the code folder that Render wipes and rebuilds on each deploy.
"""
from pathlib import Path

from app.config import settings

# Root for all persisted data. If DATA_DIR is set (Render), use it; otherwise
# fall back to the project directory (one level above /app) for local dev.
if settings.DATA_DIR:
    DATA_ROOT = Path(settings.DATA_DIR)
else:
    DATA_ROOT = Path(__file__).resolve().parent.parent

UPLOADS_DIR = DATA_ROOT / "uploads"
DOWNLOADS_DIR = DATA_ROOT / "downloads"

# Make sure they exist on boot (harmless if already there).
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
