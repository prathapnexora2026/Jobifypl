#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# Bundle the JobifyPL frontend into the Capacitor www/ folder for the STORE build.
# The app runs its own UI locally (store-safe); only API + images come from the
# server. Run this before `npx cap sync android`. www/ is git-ignored (build output).
# ---------------------------------------------------------------------------
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/../frontend"
WWW="$HERE/www"

rm -rf "$WWW"
mkdir -p "$WWW"

# Pages the mobile app actually uses (NOT the marketing homepage or admin panel)
cp "$SRC/app.html" "$SRC/recruiter.html" "$WWW/"
cp "$SRC/autotr.js" "$SRC/crop.js" "$WWW/"
cp "$SRC/terms-candidate.html" "$SRC/terms-recruiter.html" "$SRC/terms.html" "$SRC/privacy.html" "$WWW/"

# Assets (logos, banners, avatars, category art…) so images load offline/instantly
cp -R "$SRC/assets" "$WWW/assets"

# Entry point → the candidate app (which shows the role picker)
cat > "$WWW/index.html" <<'HTML'
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta http-equiv="refresh" content="0; url=app.html">
<script>location.replace("app.html");</script>
<title>JobifyPL</title></head><body></body></html>
HTML

echo "www/ bundled:"
ls "$WWW"
