# JobifyPL — Project Handoff (continue on Mac for the iOS / App Store build)

> **How to use this on the Mac:** install VS Code + Claude Code, `git clone` this repo,
> open this file, and tell Claude *"read HANDOFF-iOS.md — continue the iOS work."*
> That gives full context to pick up exactly where we left off.

## Status (2026-08-28)
- ✅ **Android: LIVE on Google Play.** Package `pl.jobifypl.app`, org account NEXORA TECH SOLUTIONS SP Z O O, current version **1.0.1 (versionCode 3, targetSdk 36)**.
- ⏳ **iOS: not started.** Apple Developer account is being created by the Poland client (individual/org) — need the login credentials + account fully active before building.
- **Backend:** FastAPI on Render, live at **https://jobifypl.pl** (Postgres + persistent disk). Payments via **PayU**.

## Repo layout
- `app/` — FastAPI backend (Render)
- `frontend/` — the web app: `app.html` (candidate), `recruiter.html`, `admin.html`, `autotr.js` (whole-app translation), `crop.js`, legal pages, `delete-account.html`. Served live at jobifypl.pl **and** bundled into the mobile app.
- `jobify-app/` — Capacitor mobile project. `android/` is built & shipped; **`ios/` must be added on the Mac**.

## Key facts & credentials
- **App ID / bundle id:** `pl.jobifypl.app` (must match on iOS too).
- **Android signing keystore:** `jobify-app/android/app/jobifypl-upload.jks` + `jobify-app/android/keystore.properties` (alias `jobifypl`). ⚠️ These are **gitignored (NOT in the repo)** — they live only on the Windows machine. **Copy both files securely to the Mac** (USB/encrypted transfer) if you want to build Android updates from the Mac. Losing the keystore = can't update the Android app.
- **App-store reviewer login** (built into the app): candidate `+48555010101`, recruiter `+48555020202`, fixed code `424242` (no real SMS). Defined in `app/config.py` (`REVIEWER_PHONES`/`REVIEWER_OTP`) + `app/routers/auth.py`. Reuse the same for Apple's reviewer in App Store Connect "Sign-in information".
- **Google Play:** managed publishing OFF; auto-publishes after review.
- **GitHub repo:** prathapnexora2026/Jobifypl.

## Features shipped (in both web + mobile)
Whole-app auto-translation (EN/PL/UK, `autotr.js` + Google Translate API — key in Render env `GOOGLE_TRANSLATE_API_KEY`), account deletion (`POST /account/delete` + web page /delete-account.html), report + block (`/report`, `/block`), offline "No internet" screen, no long-press text-copy, image cropper, coupons, PayU wallet/plans.

## Android build (for future updates — reference)
- **JDK:** use JBR 21 (Android Studio's JDK). On Windows it was `D:\Android\jbr`. On Mac use Android Studio's bundled JDK. (JDK 23 crashed; JDK 11 too old.)
- Gradle 8.14.3, AGP 8.13, `compileSdkVersion 36`, `targetSdkVersion 36`, heap `-Xmx3072m` in `gradle.properties`.
- Build: `cd jobify-app && sh build-store.sh && cd android && ./gradlew bundleRelease` → `.aab`. Bump `versionCode` each release (currently 3).

---

## iOS PLAN — do these on the Mac

### Phase 0 — prerequisites
- ✅ Xcode installed (open once, accept license).
- Apple Developer Program active (client creating it — get credentials).
- Node.js + CocoaPods: `sudo gem install cocoapods`

### Phase 1 — get the project
```bash
git clone https://github.com/prathapnexora2026/Jobifypl.git
cd Jobifypl/jobify-app
npm install
```

### Phase 2 — add iOS
```bash
sh build-www.sh          # bundle frontend/ into www/
npx cap add ios
npx cap sync ios
npx cap open ios         # opens the project in Xcode
```
For a STORE build, use bundled mode (remove `server.url` from capacitor.config.json before sync — same idea as build-store.sh does for Android; we'll make a build-store-ios step).

### Phase 3 — configure in Xcode
- Signing & Capabilities → select the Team (the Apple Developer account).
- Bundle Identifier = `pl.jobifypl.app`.
- Add **Info.plist usage strings** (uploads use camera/photos):
  - `NSCameraUsageDescription` = "JobifyPL uses the camera so you can take a photo for your profile or documents."
  - `NSPhotoLibraryUsageDescription` = "JobifyPL needs photo access so you can upload your profile picture and documents."
- Add app icons (1024×1024 App Store icon + set) and launch screen.

### Phase 4 — build & upload
- Xcode → Product → Archive → Distribute App → App Store Connect → Upload → appears in **TestFlight**.

### Phase 5 — App Store Connect (appstoreconnect.apple.com)
- Create the app (same bundle id), fill listing (name, subtitle, description — reuse the Play text, no country), iPhone screenshots (6.7" + 6.1"), **App Privacy** labels (name, email, phone, docs, photos, messages — same as Play Data Safety), reviewer sign-in info (the reviewer login above), age rating, then **Submit for review**.

### ⚠️ iOS PENDING DECISION — payments
Apple usually **forces its own In-App Purchase** (15–30%) for in-app digital purchases and **may reject PayU** for the plans (Android allowed PayU; iOS is stricter). Decide before submitting:
- (a) Add **Apple IAP (StoreKit)** for iOS, or
- (b) **Hide in-app plan purchase on iOS** (users manage plans on the website), or
- (c) Submit with PayU and risk rejection.
Resolve this before Phase 5. Get the app onto TestFlight first (payments don't block testing).

## Also pending (optional)
- **Edge-to-edge polish (Android 1.0.2):** top bars/bottom nav don't reserve status/nav-bar space; add `viewport-fit=cover` + `env(safe-area-inset-*)`. Recommended (Play flagged it) but optional.
