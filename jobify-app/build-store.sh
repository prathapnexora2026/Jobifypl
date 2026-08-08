#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# One command to prepare the STORE build: bundles the frontend, switches
# Capacitor to bundled mode (no live server), and syncs the Android project.
# Your live/dev capacitor.config.json is restored automatically afterwards.
# Then just build the signed .aab (see the printed command / STORE-BUILD.md).
# ---------------------------------------------------------------------------
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

echo "[1/4] Bundling frontend into www/ ..."
sh build-www.sh

echo "[2/4] Switching Capacitor to bundled mode (removing live server.url) ..."
cp capacitor.config.json capacitor.config.json.bak
node -e '
const fs=require("fs");
const c=JSON.parse(fs.readFileSync("capacitor.config.json","utf8"));
c.server = { androidScheme: "https" };   // keep https origin, drop the live URL so it loads bundled www
fs.writeFileSync("capacitor.config.json", JSON.stringify(c,null,2));
'

echo "[3/4] Syncing Android project ..."
npx cap sync android

echo "[4/4] Restoring your live/dev config ..."
mv capacitor.config.json.bak capacitor.config.json

echo ""
echo "Done. The Android project is now BUNDLED. Build the signed bundle:"
echo "   cd android && ./gradlew bundleRelease        (Windows: .\\gradlew.bat bundleRelease)"
echo "Output: android/app/build/outputs/bundle/release/app-release.aab  -> upload to Play Console"
