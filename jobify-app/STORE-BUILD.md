# JobifyPL — Play Store build runbook

Produces a **signed `.aab`** (Android App Bundle — required by Google Play) that
runs the UI **bundled inside the app** (store-safe). The API and images still come
from `https://jobifypl.pl`. Prerequisites: Node + Capacitor CLI, Android Studio /
Android SDK, and **Java 17+**.

---

## One-time setup

### 1. Create your upload keystore (do this ONCE, keep it forever & back it up)
Losing this key means you can never update the app again, so save it somewhere safe.
```sh
cd jobify-app/android/app
keytool -genkeypair -v -keystore jobifypl-upload.jks \
  -keyalg RSA -keysize 2048 -validity 10000 -alias jobifypl
```
It asks for a password and your org details (name, org = NEXORA TECH SOLUTIONS SP ZOO, country PL).

### 2. Point the build at the keystore
```sh
cd jobify-app/android
cp ../keystore.properties.example keystore.properties
# edit keystore.properties → fill in storePassword / keyPassword (and keyAlias if you changed it)
```
`keystore.properties`, `*.jks` and `google-services.json` are git-ignored — they never get committed.

---

## Every time you build a store release

```sh
cd jobify-app

# 1. Bundle the current frontend into www/ (store-safe, offline UI)
sh build-www.sh

# 2. Switch Capacitor to bundled mode: in capacitor.config.json, REMOVE the
#    entire "server" block (that's what makes it load the live site). Keep the rest.

# 3. Copy the web build into the Android project
npx cap sync android

# 4. Build the signed release bundle
cd android
./gradlew bundleRelease          # Windows: .\gradlew.bat bundleRelease
```
Output: `android/app/build/outputs/bundle/release/app-release.aab` → upload this to Play Console.

> To go **back to live/dev mode** for quick testing, restore the `"server"` block in
> `capacitor.config.json` (url `https://jobifypl.pl/app.html`) and rebuild.

---

## Bump the version for each release
In `android/app/build.gradle` raise **both** every time you upload a new build:
```
versionCode 2          // must increase by 1 each upload (integer)
versionName "1.1"      // shown to users
```

---

## Play Console checklist (first submission)
- [ ] App name, short + full description (PL + EN), category
- [ ] Icon 512×512, feature graphic 1024×500, ≥2 phone screenshots
- [ ] Privacy policy URL → https://jobifypl.pl/privacy.html
- [ ] **Data safety** form (what data you collect: name, phone, docs; how it's used)
- [ ] Content rating questionnaire
- [ ] Target audience & content (not for children)
- [ ] Closed testing track: add testers, run ~14 days before requesting production
      (org accounts may be lighter — confirm in Console after verification)

## Later (v1.1) — push notifications
Add `@capacitor/push-notifications` + a Firebase project + `google-services.json`
(drop it in `android/app/`; the build auto-detects it) + a backend FCM sender.
