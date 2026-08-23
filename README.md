# Marko

Marko helps prom.ua sellers keep their prices competitive. A user connects one
or more stores, Marko imports their catalog, finds similar competitor listings,
and stores price observations for comparison and future repricing rules.

The repository is a Docker-first modular monolith:

```text
Flutter ── Firebase ID token ──► FastAPI ──► PostgreSQL
   │                                │
   ├── Firebase Authentication      ├──► Redis ──► Celery worker ──► prom.ua
   └── web / Android / desktop      │
                                    └──► avto.pro (live competitor prices)
```

Firebase is used only for authentication. Marko's users, workspaces, stores,
products, matches, jobs, and price history remain in the project's PostgreSQL
database and are accessed only through FastAPI.

## Repository layout

```text
.
├── backend/
│   ├── migrations/                 Alembic database migrations
│   ├── src/marko/
│   │   ├── api/                    FastAPI routes and schemas
│   │   ├── core/                   application configuration
│   │   ├── infrastructure/db/      SQLAlchemy models and sessions
│   │   ├── parsers/                prom.ua and avto.pro parsers
│   │   ├── repositories/           database queries
│   │   ├── services/               import, matching, and authentication logic
│   │   └── worker/                 Celery tasks and scheduler
│   └── tests/
├── frontend/
│   ├── lib/main.dart               app entry point and MaterialApp
│   ├── lib/core/                   routing, API client, Firebase auth, theme & design tokens
│   └── lib/features/
│       ├── auth/                   sign-in, registration, Google OAuth, session
│       └── products/               catalog grid, search, filters, XLSX/Prom import, avto.pro analytics
├── docs/
├── compose.yaml
└── .env.example
```

## Authentication design

The client signs in with Firebase Authentication and obtains a Firebase ID
token. Every protected FastAPI request sends it as:

```http
Authorization: Bearer FIREBASE_ID_TOKEN
```

FastAPI verifies all of the following before trusting the request:

- RS256 signature against Google's Firebase public keys;
- `aud` equal to `FIREBASE_PROJECT_ID`;
- `iss` equal to `https://securetoken.google.com/FIREBASE_PROJECT_ID`;
- token timestamps and a non-empty Firebase UID in `sub`;
- a valid, verified email.

On the first valid request, FastAPI creates a local user and a default workspace.
Later requests look up that user by `users.firebase_uid`. No Google access token,
password, Firebase API key, OAuth secret, or service-account key is stored in
PostgreSQL.

The login screen supports:

- email/password with Firebase email verification;
- Google on web through `FirebaseAuth.signInWithPopup`;
- Google on Android through the official `google_sign_in` plugin, followed by a
  Firebase credential exchange;
- no Apple Sign-In.

## Prerequisites

For the complete Docker web stack, install only:

- Docker Desktop with Docker Compose v2;
- a browser;
- a Firebase/Google account for authentication setup.

For local Flutter development, also install Flutter stable. Android development
requires the Android SDK and a device/emulator with Google Play services. You do
not need a Python virtual environment, a local PostgreSQL installation, Redis,
Node.js, or backend Python dependencies.

## Product and behaviour specs

Before changing behaviour, read the specs — they are the source of truth for
what the product should do, and the code is expected to match them:

- [`docs/product-vision.md`](docs/product-vision.md) — what Marko is for and
  what the main scenario looks like;
- [`docs/ui-behavior.md`](docs/ui-behavior.md) — what every screen and button
  does, and its loading / success / empty / error states;
- [`docs/parser-spec.md`](docs/parser-spec.md) — contracts and acceptance
  criteria for the prom.ua, XLSX and avto.pro parsers;
- [`docs/known-gaps.md`](docs/known-gaps.md) — the live list of gaps between
  the specs and the code;
- [`CLAUDE.md`](CLAUDE.md) — working rules for agents on this repository.

## Firebase and Google Authentication

Use one Firebase project for web and Android. This is important: users then keep
the same Firebase UID regardless of which client they use.

### 1. Create the Firebase project

1. Open [Firebase Console](https://console.firebase.google.com/) and create a
   project, for example `marko-dev`.
2. Open **Project settings → General** and copy the exact **Project ID**. It is
   not the display name and not the numeric project number.
3. Open **Build → Authentication → Get started**.
4. In **Authentication → Sign-in method**, enable:
   - **Email/Password** if the email form should remain available;
   - **Google** and select a project support email.
5. Do not enable Apple. No Apple service ID, key, callback, or client secret is
   used by this repository.

If you want Google-only accounts, disable Email/Password in Firebase and remove
the email form later. Google is the only social provider implemented in code.

### 2. Configure the web application

1. In **Project settings → General → Your apps**, click the web icon `</>`.
2. Register a web app such as `marko-web`. Firebase Hosting is optional.
3. Firebase shows a configuration object similar to:

   ```javascript
   const firebaseConfig = {
     apiKey: "AIza...",
     authDomain: "marko-dev.firebaseapp.com",
     projectId: "marko-dev",
     storageBucket: "marko-dev.firebasestorage.app",
     messagingSenderId: "123456789012",
     appId: "1:123456789012:web:abcdef"
   };
   ```

4. Copy the repository environment template:

   ```bash
   cp .env.example .env
   ```

5. Map the Firebase values into `.env`:

   ```dotenv
   FIREBASE_API_KEY=AIza_REPLACE_ME
   FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com
   FIREBASE_PROJECT_ID=YOUR_PROJECT_ID
   FIREBASE_MESSAGING_SENDER_ID=123456789012
   FIREBASE_WEB_APP_ID=1:123456789012:web:replace_me
   ```

`FIREBASE_API_KEY` and the other web config values are public client identifiers,
not admin secrets. They are compiled into the web application by design. Still,
restrict the API key in Google Cloud to the APIs and web origins you actually use.
Never put an OAuth client secret or Firebase Admin service-account JSON into
Flutter or this `.env` file.

### 3. Configure authorized web domains

1. Open **Firebase Console → Authentication → Settings → Authorized domains**.
2. Keep `localhost` for local development.
3. Add each production hostname, for example `app.example.com`.
4. If a custom Firebase auth domain is used, set that same value in
   `FIREBASE_AUTH_DOMAIN`.

For local Docker, the browser opens `http://localhost:8080`; Firebase treats the
host as `localhost`, so the port does not need a separate allowlist entry.

### 4. Check Google Cloud OAuth configuration for web

Firebase creates or reuses Google OAuth credentials in the Google Cloud project
behind the Firebase project.

1. Open [Google Auth Platform](https://console.cloud.google.com/auth/overview)
   and select the same project.
2. Configure **Branding** with the app name, support email, and developer contact.
3. Configure **Audience**. While the app is in testing, add every Google account
   that should be able to sign in as a test user. Publish the app when ready.
4. The basic `openid`, `email`, and `profile` scopes are sufficient. Marko does
   not request access to Gmail, Drive, Contacts, or another Google API.
5. Under **Clients**, locate the web client used by Firebase Google Sign-In. Its
   redirect URI must include:

   ```text
   https://YOUR_PROJECT_ID.firebaseapp.com/__/auth/handler
   ```

6. If you use a custom auth domain, add the corresponding Firebase handler URI
   shown by Firebase. Add production JavaScript origins when the client page
   requires them.

The web OAuth client secret stays in Google/Firebase configuration. Marko does
not need it because Firebase completes the OAuth exchange and Flutter sends only
the resulting Firebase ID token to FastAPI.

### 5. Configure Android

The Android package name currently used by the project is:

```text
com.marko.marko_client
```

If that identifier is changed in `frontend/android/app/build.gradle.kts`, create
a matching Android app in Firebase and Google Cloud.

1. In **Firebase Console → Project settings → General → Your apps**, add an
   Android app with package name `com.marko.marko_client`.
2. Add the SHA-1 and SHA-256 certificate fingerprints for every signing key used
   by the app. For the standard local debug key, one option is:

   ```bash
   keytool -list -v \
     -alias androiddebugkey \
     -keystore ~/.android/debug.keystore \
     -storepass android \
     -keypass android
   ```

   Alternatively run `./gradlew signingReport` from `frontend/android/`.
3. After enabling Google sign-in and adding SHA fingerprints, download a fresh
   `google-services.json`.
4. Put it at exactly:

   ```text
   frontend/android/app/google-services.json
   ```

5. In **Google Cloud Console → Google Auth Platform → Clients**, confirm that an
   Android OAuth client exists with the same package name and SHA-1. Firebase
   usually creates it automatically.
6. If Google login reports a client configuration error, download
   `google-services.json` again. The refreshed file should contain both the
   Android client and the web/server OAuth client used to obtain an ID token.

The Google services Gradle plugin is already enabled in this repository. Do not
paste a web client secret into Dart. Android reads its client configuration from
`google-services.json`.

### 6. Backend Firebase configuration

FastAPI uses only:

```dotenv
FIREBASE_PROJECT_ID=YOUR_PROJECT_ID
```

It downloads Google's public signing keys and validates Firebase JWT claims.
There is no Firebase Admin SDK initialization and no service-account file to
mount. The project ID must exactly match the one compiled into the web app and
the project referenced by Android's `google-services.json`.

## Windows strategy

The official Flutter `google_sign_in` package supports Android, iOS, macOS, and
web, but not Windows. `firebase_auth` currently marks Windows support as beta;
email/password works there, while the underlying Firebase C++ federated provider
flow is not implemented for Windows.

The recommended Marko setup is therefore:

1. deploy the Flutter web build;
2. let Windows users open it in Chrome or Edge;
3. optionally install it as a PWA from the browser;
4. use the normal Firebase Google popup.

This keeps the official SDK path, the same Firebase UID, and one backend token
verification method. The native Windows executable hides the Google button and
keeps email/password available.

If a native Windows Google button becomes a hard requirement later, implement a
system-browser OAuth Authorization Code + PKCE flow and exchange the Google
credential with Firebase Authentication. That requires a separate desktop OAuth
client, loopback/deep-link handling, and careful token validation. A third-party
all-platform sign-in package also exists, but it should not be introduced into
the authentication boundary without a security and maintenance review.

## Start the complete web stack

After creating `.env` and configuring Firebase:

```bash
docker compose up -d --build
```

This starts:

| Service | Purpose | Default address |
|---|---|---|
| `frontend` | compiled Flutter web app served by nginx | `http://localhost:8080` |
| `api` | FastAPI REST API | `http://localhost:8000` |
| `db` | PostgreSQL 17 | `localhost:5432` |
| `broker` | Redis for Celery | `localhost:6379` |
| `worker` | background imports and matching | internal |
| `scheduler` | periodic Celery jobs | internal |
| `migrate` | one-shot Alembic upgrade | internal |

Check status and logs:

```bash
docker compose ps --all
docker compose logs --no-color --tail=100 api frontend worker
curl http://localhost:8000/api/v1/health/live
curl http://localhost:8000/api/v1/health/ready
```

When a Firebase value changes, rebuild the frontend because Dart defines are
compile-time values:

```bash
docker compose up -d --build frontend api
```

Open `http://localhost:8080`, sign in, and then inspect the protected profile:

```text
GET /api/v1/auth/me
```

The browser sends the Firebase token automatically. Calling the protected API
without a token correctly returns `401 Unauthorized`.

## Run Flutter web outside Docker

Start the backend services first:

```bash
docker compose up -d db broker migrate api worker scheduler
```

Then run Flutter:

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

The same values can be copied from `.env`; Flutter itself does not load `.env`
files at runtime.

## Run Android

Do this only after placing `google-services.json` in `frontend/android/app/`.

For an Android emulator, omit `API_BASE_URL`; the client automatically uses
`http://10.0.2.2:8000`:

```bash
cd frontend
flutter run -d YOUR_ANDROID_DEVICE
```

For a physical device, use a LAN-reachable backend address:

```bash
flutter run -d YOUR_ANDROID_DEVICE \
  --dart-define=API_BASE_URL=http://192.168.1.20:8000
```

The computer firewall must allow the API port, and both devices must be able to
reach each other. Production clients must use HTTPS.

## Environment variables

| Variable | Default | Used by |
|---|---:|---|
| `POSTGRES_DB` | `marko` | PostgreSQL/backend |
| `POSTGRES_USER` | `marko` | PostgreSQL/backend |
| `POSTGRES_PASSWORD` | `marko` | PostgreSQL/backend |
| `POSTGRES_PORT` | `5432` | host port mapping |
| `REDIS_PORT` | `6379` | host port mapping |
| `API_PORT` | `8000` | FastAPI host port |
| `WEB_PORT` | `8080` | Flutter web host port |
| `FIREBASE_PROJECT_ID` | required | backend and Flutter |
| `FIREBASE_API_KEY` | required for web | Flutter web |
| `FIREBASE_AUTH_DOMAIN` | required for web | Flutter web |
| `FIREBASE_MESSAGING_SENDER_ID` | required for web | Flutter web |
| `FIREBASE_WEB_APP_ID` | required for web | Flutter web |

Inside Docker, PostgreSQL and Redis URLs are assembled by `compose.yaml`. CORS
allows the configured local web origin. Set production database passwords,
origins, API URL, and TLS termination before deployment.

## API overview

The main endpoints are:

```text
GET  /api/v1/health/live
GET  /api/v1/health/ready
GET  /api/v1/auth/me
GET  /api/v1/products
POST /api/v1/stores
POST /api/v1/stores/import-file
GET  /api/v1/competitors/avtopro
GET  /api/v1/jobs/{job_id}
```

- `GET /api/v1/products` returns the paginated catalog with query search, price range, and sorting.
- `POST /api/v1/stores/import-file` synchronously imports a Prom.ua XLSX catalog export.
- `POST /api/v1/stores` registers a Prom shop URL, queues a background scraping task in Celery, and returns a job ID to poll.
- `GET /api/v1/competitors/avtopro` performs live market price lookups on avto.pro by OEM and brand.

## Database and migrations

Alembic runs automatically through the one-shot `migrate` service. To apply
migrations manually:

```bash
docker compose run --rm migrate
```

Migration `20260713_0004_firebase_auth.py` replaces the former external auth
subject with `users.firebase_uid`. It does not delete local users, workspaces,
stores, or products. Existing local users are linked to Firebase on their first
request with the same verified email.

For a disposable local reset only:

```bash
docker compose down -v
docker compose up -d --build
```

The `-v` flag deletes PostgreSQL and Redis volumes, so do not use it against data
you need to keep.

## Tests and checks

Backend tests run in Docker:

```bash
docker compose --profile test run --rm --build backend-test
```

Flutter checks run from `frontend/`:

```bash
dart format lib test
flutter analyze
flutter test
```

Build only the web target when disk space is limited:

```bash
flutter build web --release \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=FIREBASE_API_KEY=AIza_REPLACE_ME \
  --dart-define=FIREBASE_AUTH_DOMAIN=YOUR_PROJECT_ID.firebaseapp.com \
  --dart-define=FIREBASE_PROJECT_ID=YOUR_PROJECT_ID \
  --dart-define=FIREBASE_MESSAGING_SENDER_ID=123456789012 \
  --dart-define=FIREBASE_WEB_APP_ID=1:123456789012:web:replace_me
```

Android and iOS builds are not required to validate routine Dart changes.

## Troubleshooting

### FastAPI returns 401 after a successful Firebase login

1. Confirm that `FIREBASE_PROJECT_ID` is the exact same project in `.env`, the
   Firebase web config, and `google-services.json`.
2. Rebuild both `api` and `frontend` after changing `.env`.
3. Confirm that the user's email is verified. Google accounts are normally
   verified; password accounts must click the verification email first.
4. Ensure the client sends a Firebase ID token, not a Google OAuth access token
   or a raw Google ID token.
5. Check API logs:

   ```bash
   docker compose logs --no-color --tail=100 api
   ```

### Google popup fails on web

1. Add `localhost` and the production domain to Firebase Authentication's
   authorized domains.
2. Make sure Google is enabled under Authentication sign-in methods.
3. Add the login Google account as a test user in Google Auth Platform while the
   OAuth app is in testing.
4. Confirm the Firebase OAuth handler URI in the Google web client.
5. Allow popups for the site and inspect the browser console for the Firebase
   error code.

### Android reports `ApiException: 10`, `DEVELOPER_ERROR`, or a client error

1. Add the correct debug/release SHA-1 and SHA-256 to the Firebase Android app.
2. Confirm the package is exactly `com.marko.marko_client`.
3. Download a new `google-services.json` after changing fingerprints or enabling
   Google sign-in.
4. Confirm an Android OAuth client with the matching package/SHA exists in the
   same Google Cloud project.
5. Use a device or emulator with Google Play services.

### `/api/v1/auth/register` or `/api/v1/auth/oauth/google/start` returns 404

Those routes intentionally no longer exist. Registration and Google OAuth are
handled by the Firebase client SDK. FastAPI exposes only `/api/v1/auth/me` for
the authenticated local profile.

### The web container still calls old authentication routes

The running nginx container contains a previously compiled Flutter bundle.
Rebuild it:

```bash
docker compose up -d --build frontend
```

Then hard-refresh the browser or clear the site's cached application data.

### Native Windows has no Google button

This is intentional. Use the web/PWA build for Google sign-in on Windows, or use
email/password in the native Windows build. See [Windows strategy](#windows-strategy).
