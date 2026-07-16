# Marko Flutter client

This directory contains the Flutter client for web, Android, and desktop.
Firebase Authentication owns credentials and sessions; stores, products, jobs,
workspaces, and all business authorization go through Marko FastAPI.

The first screen supports verified email/password accounts and Google. Google
uses Firebase popup auth on web and the official `google_sign_in` plugin on
Android. Apple Sign-In is not part of the application.

## Structure

`lib/main.dart` contains the entry point and `MaterialApp`. Shared infrastructure
is in `lib/core/`; each feature keeps a flat set of model, API, controller, and
page files. There are no `lib/app/` or `lib/shared/` directories.

The pricing feature is action-first: separate raise, clearance, manual-review
and hold queues show the recommended action/economic effect before model
details. Expanded rows expose confidence, weakest factor, evidence health, raw
and KEMP-normalized competitor prices, multiplier/coefficient metadata and the
listing link. Stock/sales/cost context, tier corrections and decisions are
append-only API operations. Below-cost decisions require an explicit checkbox
confirmation and approved floor.

## Local web run

Configure Firebase first by following the root [setup guide](../README.md#firebase-and-google-authentication).
Then start the backend and run:

```bash
cd frontend
flutter pub get
flutter run -d chrome --web-port=8080 \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=FIREBASE_API_KEY=AIza_REPLACE_ME \
  --dart-define=FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com \
  --dart-define=FIREBASE_PROJECT_ID=YOUR_PROJECT_ID \
  --dart-define=FIREBASE_MESSAGING_SENDER_ID=123456789012 \
  --dart-define=FIREBASE_WEB_APP_ID=1:123456789012:web:replace_me
```

For Android, put `google-services.json` in `android/app/`; Firebase reads it at
startup. The Android emulator uses `http://10.0.2.2:8000` by default.

Native Windows supports Firebase email/password in beta. The official
`google_sign_in` plugin has no Windows implementation, so use the Marko web/PWA
build on Windows when Google-only sign-in is required.

## Verify changes

```bash
dart format lib test
flutter analyze
flutter test
flutter build web --release \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=FIREBASE_API_KEY=AIza_REPLACE_ME \
  --dart-define=FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com \
  --dart-define=FIREBASE_PROJECT_ID=YOUR_PROJECT_ID \
  --dart-define=FIREBASE_MESSAGING_SENDER_ID=123456789012 \
  --dart-define=FIREBASE_WEB_APP_ID=1:123456789012:web:replace_me
```
