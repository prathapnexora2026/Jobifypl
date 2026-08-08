"""Google Cloud Translation (v2 REST) with a DB cache.

Robust + quota-friendly:
  • Every result is cached (hash of target-lang + text), so the same string is
    never translated twice — this keeps us well inside the free tier.
  • Graceful: if the API key isn't set, the target isn't supported, or the call
    fails, we return the ORIGINAL text (the app never breaks).

The API key lives only on the server (settings.GOOGLE_TRANSLATE_API_KEY) — it is
never sent to the app.
"""
import hashlib

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models import TranslationCache

_ENDPOINT = "https://translation.googleapis.com/language/translate/v2"
_SUPPORTED = {"en", "pl", "uk"}
_MAX_CHARS = 20000   # safety cap per request


def _hash(text: str, target: str) -> str:
    return hashlib.sha256(f"{target}::{text}".encode("utf-8")).hexdigest()


def translate(db: Session, text: str, target: str) -> dict:
    """Translate `text` into `target` ('en' | 'pl' | 'uk').
    Returns {"text", "source", "translated": bool}. Never raises."""
    text = (text or "").strip()
    target = (target or "en").lower()[:2]
    if not text or target not in _SUPPORTED:
        return {"text": text, "source": "", "translated": False}
    if len(text) > _MAX_CHARS:
        text = text[:_MAX_CHARS]
    if not settings.GOOGLE_TRANSLATE_API_KEY:
        return {"text": text, "source": "", "translated": False}

    h = _hash(text, target)
    cached = db.query(TranslationCache).filter(TranslationCache.hash == h).first()
    if cached:
        return {"text": cached.translated, "source": cached.source_lang or "",
                "translated": bool(cached.source_lang and cached.source_lang != target)}

    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(_ENDPOINT,
                       params={"key": settings.GOOGLE_TRANSLATE_API_KEY},
                       json={"q": text, "target": target, "format": "text"})
            r.raise_for_status()
            tr = r.json()["data"]["translations"][0]
            translated = tr.get("translatedText", text)
            source = (tr.get("detectedSourceLanguage") or "")[:2]
    except Exception as e:
        print(f"[translate] failed: {e}")
        return {"text": text, "source": "", "translated": False}

    try:
        db.add(TranslationCache(hash=h, target_lang=target, source_lang=source, translated=translated))
        db.commit()
    except Exception:
        db.rollback()
    return {"text": translated, "source": source, "translated": bool(source and source != target)}


def translate_many(db: Session, texts: list, target: str) -> list:
    """Translate many strings into `target` at once. Cached strings are served
    from the DB; all remaining unique strings are translated in ONE API call.
    Returns a list of {"text","source","translated"} in the same order. Never raises."""
    target = (target or "en").lower()[:2]
    out = [{"text": (t or ""), "source": "", "translated": False} for t in texts]
    if not texts or target not in _SUPPORTED:
        return out
    to_fetch = []  # (index, text, hash)
    for i, t in enumerate(texts):
        t = (t or "").strip()
        if not t:
            continue
        if len(t) > _MAX_CHARS:
            t = t[:_MAX_CHARS]
        h = _hash(t, target)
        c = db.query(TranslationCache).filter(TranslationCache.hash == h).first()
        if c:
            out[i] = {"text": c.translated, "source": c.source_lang or "",
                      "translated": bool(c.source_lang and c.source_lang != target)}
        else:
            to_fetch.append((i, t, h))
    if to_fetch and settings.GOOGLE_TRANSLATE_API_KEY:
        try:
            with httpx.Client(timeout=25) as cl:
                r = cl.post(_ENDPOINT, params={"key": settings.GOOGLE_TRANSLATE_API_KEY},
                            json={"q": [t for _, t, _ in to_fetch], "target": target, "format": "text"})
                r.raise_for_status()
                trs = r.json()["data"]["translations"]
            for (i, t, h), tr in zip(to_fetch, trs):
                translated = tr.get("translatedText", t)
                source = (tr.get("detectedSourceLanguage") or "")[:2]
                out[i] = {"text": translated, "source": source,
                          "translated": bool(source and source != target)}
                try:
                    db.add(TranslationCache(hash=h, target_lang=target, source_lang=source, translated=translated))
                except Exception:
                    pass
            try:
                db.commit()
            except Exception:
                db.rollback()
        except Exception as e:
            print(f"[translate] batch failed: {e}")
    return out
