# Marko

Marko helps prom.ua sellers keep their prices competitive. A seller connects a
store, Marko imports the catalog, then finds live competitor offers for each
product across public marketplaces and reports market prices for comparison.

**Production:** [markoprice.com](https://markoprice.com) · API at `api.markoprice.com`

## Architecture

Docker-first modular monolith:

```text
Flutter (web / Android)                     Celery worker ◄── Redis ◄─┐
   │ Firebase ID token                           │                    │
   ▼                                             ▼                    │
FastAPI ──► PostgreSQL 17                  prom.ua scraper      FastAPI (API)
   │                                                                  ▲
   ├──► competitor price search: avto.pro + prom.ua + Google (Serper) │
   │        └─► LLM relevance filter (OpenAI, gpt-5-nano) ────────────┘
   └──► SSE streams for live search / sync progress
```

- **Firebase** is used only for authentication. Users, workspaces, stores,
  products, and sync runs live in PostgreSQL and are accessed only through
  FastAPI.
- **Celery** handles background store imports and catalog refreshes; results
  are streamed to the client via Server-Sent Events.
- **Competitor prices** are aggregated live from avto.pro, prom.ua search, and
  optionally Google (via Serper.dev), then filtered for relevance by an OpenAI
  model and cached in Redis.
- **Cloudflare Tunnel** exposes the production API without opening VPS ports.

## Repository layout

```text
.
├── backend/
│   ├── migrations/              Alembic migrations
│   ├── src/marko/
│   │   ├── api/                 FastAPI app, v1 routers, SSE
│   │   ├── core/                settings (pydantic-settings, .env)
│   │   ├── infrastructure/db/   SQLAlchemy models and sessions
│   │   ├── parsers/             prom.ua and avto.pro scrapers
│   │   ├── repositories/        database queries
│   │   ├── services/            imports, competitor prices, LLM filter, auth
│   │   └── worker/              Celery app and tasks
│   └── tests/
├── frontend/
│   └── lib/
│       ├── core/                routing, API client, Firebase auth, theme
│       └── features/
│           ├── auth/            sign-in, registration, Google OAuth, password reset
│           ├── dashboard/       workspace overview
│           └── products/        catalog, import, competitor price analytics
├── compose.yaml
├── Makefile
└── .env.example
```

## Quick start

Prerequisites: Docker Desktop with Compose v2 and a Firebase project
(see [Authentication](#authentication)).

```bash
cp .env.example .env      # fill in the Firebase and OpenAI values
docker compose --profile local up -d --build
```

| Service | Purpose | Address |
|---|---|---|
| `frontend` | Flutter web served by nginx (profiles `local`/`frontend`) | `http://localhost:8080` |
| `api` | FastAPI REST API | `http://localhost:8000` |
| `db` | PostgreSQL 17 (loopback only) | `localhost:5432` |
| `broker` | Redis (Celery broker/results + price cache) | `localhost:6379` |
| `worker` | Celery worker: imports, refreshes | internal |
| `scheduler` | Celery beat | internal |
| `migrate` | one-shot Alembic upgrade | internal |
| `tunnel` | cloudflared (production only, needs `CLOUDFLARE_TUNNEL_TOKEN`) | internal |

Verify:

```bash
curl http://localhost:8000/api/v1/health/ready
```

Or use the Makefile: `make up`, `make down`, `make logs`, `make test`,
`make analyze`, `make migrate`.

## Configuration

All configuration comes from `.env` (see `.env.example` for the annotated
template). The important variables:

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development` or `production` |
| `POSTGRES_*`, `REDIS_PORT`, `API_PORT`, `WEB_PORT` | service credentials and host ports |
| `CORS_ORIGINS` | comma-separated allowed web origins |
| `API_BASE_URL` | public API URL, **baked into the web bundle at build time** |
| `FIREBASE_PROJECT_ID` | Firebase project (backend token verification + client) |
| `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_MESSAGING_SENDER_ID`, `FIREBASE_WEB_APP_ID` | Firebase web app config (public client identifiers) |
| `GOOGLE_CLIENT_ID` | Google OAuth web client ID |
| `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `COMPETITOR_FILTER_MODEL` | LLM relevance filter (default model `gpt-5-nano`; base URL supports OpenAI-compatible proxies) |
| `COMPETITOR_AVAILABILITY_GATE_ENABLED` | sandbox gate: keep unavailable offers visible but outside market statistics; default `false` |
| `SERPER_API_KEY` | optional Serper.dev key; empty disables the Google search source |
| `CLOUDFLARE_TUNNEL_TOKEN` | production tunnel token |

Frontend values (`API_BASE_URL`, `FIREBASE_*`, `GOOGLE_CLIENT_ID`) are
compile-time Dart defines — rebuild the `frontend` image after changing them:

```bash
docker compose --profile frontend up -d --build frontend
```

## Authentication

The client signs in with Firebase Authentication (email/password with
verification and password reset, or Google Sign-In) and sends the Firebase ID
token on every request:

```http
Authorization: Bearer FIREBASE_ID_TOKEN
```

FastAPI verifies the RS256 signature against Google's public keys, the
`aud`/`iss` claims against `FIREBASE_PROJECT_ID`, token timestamps, and a
verified email. On the first valid request it creates a local user and default
workspace; no Firebase Admin SDK or service-account key is needed — the backend
only requires `FIREBASE_PROJECT_ID`.

Firebase setup in short:

1. Create a Firebase project, enable **Email/Password** and **Google** sign-in
   methods.
2. Register a web app and copy its config into `.env`.
3. Add `localhost` and the production domain to
   **Authentication → Settings → Authorized domains**.
4. For Android: add an app with package `com.marko.marko_client`, register the
   signing SHA-1/SHA-256 fingerprints, and place the downloaded
   `google-services.json` at `frontend/android/app/google-services.json`.

The Firebase web config values are public client identifiers, not secrets.
Never put an OAuth client secret or a service-account JSON into the frontend or
`.env`.

## API overview

All routes are under `/api/v1`. Interactive docs: `http://localhost:8000/docs`.

```text
GET    /health/live | /health/ready
GET    /auth/me                                  authenticated profile

POST   /stores                                   register a prom.ua store, start async import (202 + sync run)
POST   /stores/import-file                       synchronous prom.ua XLSX catalog import
GET    /stores · /stores/{id} · /stores/{id}/products
DELETE /stores/{id}
POST   /stores/{id}/refresh                      re-sync the store catalog

GET    /products                                 paginated catalog: search, price range, sorting
PATCH  /products/{id}                            edit a listing
POST   /products/{id}/refresh                    re-scrape one listing
DELETE /products/{id}
POST   /products/bulk/delete · /products/bulk/refresh
GET    /products/{id}/competitor-prices          competitor price report for a listing
GET    /products/{id}/competitor-prices/stream   the same, streamed via SSE

GET    /competitors/search                       ad-hoc competitor price search (OEM/brand)
GET    /competitors/search/stream                the same, streamed via SSE

GET    /jobs/active · /jobs/{sync_run_id}        sync run status
POST   /jobs/{sync_run_id}/cancel
```

## Development

### Backend

Runs in Docker only — no local Python environment required.

```bash
make test                 # pytest in the backend-test container
make migrate              # apply Alembic migrations manually
docker compose logs --no-color --tail=100 api worker
```

Destructive local reset (deletes DB and Redis volumes):

```bash
docker compose down -v && docker compose --profile local up -d --build
```

### Frontend

Requires Flutter stable. Run against the dockerized backend:

```bash
docker compose up -d db broker migrate api worker scheduler
cd frontend
flutter pub get
flutter run -d chrome --web-port=8080 \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=FIREBASE_API_KEY=... \
  --dart-define=FIREBASE_AUTH_DOMAIN=... \
  --dart-define=FIREBASE_PROJECT_ID=... \
  --dart-define=FIREBASE_MESSAGING_SENDER_ID=... \
  --dart-define=FIREBASE_WEB_APP_ID=... \
  --dart-define=GOOGLE_CLIENT_ID=...
```

Values match `.env`; Flutter does not read `.env` at runtime. Checks:

```bash
dart format lib test && flutter analyze && flutter test
```

Android: emulators default to `http://10.0.2.2:8000` when `API_BASE_URL` is
omitted; physical devices need a LAN-reachable `API_BASE_URL`.

## Deployment

Production runs the same compose file on a VPS with a production `.env`
(`ENVIRONMENT=production`, real `CORS_ORIGINS`, public `API_BASE_URL`,
`CLOUDFLARE_TUNNEL_TOKEN`). The `tunnel` service publishes the API through
Cloudflare Zero Trust, so no inbound ports are exposed; PostgreSQL and Redis
bind to loopback only. Container logs are capped (20 MB × 3 files per service).

## Troubleshooting

- **401 after a successful Firebase login** — `FIREBASE_PROJECT_ID` must be
  identical in `.env`, the web build args, and `google-services.json`; rebuild
  `api` and `frontend` after changing `.env`; the account's email must be
  verified.
- **Google popup fails on web** — check Firebase authorized domains, that
  Google sign-in is enabled, and (while the OAuth app is in testing) that the
  account is added as a test user.
- **Android `ApiException: 10` / `DEVELOPER_ERROR`** — SHA-1/SHA-256
  fingerprints missing in Firebase, or a stale `google-services.json`.
- **Web app behaves stale after config changes** — the nginx image contains a
  previously compiled bundle; rebuild `frontend` and hard-refresh the browser.
- **Competitor results look noisy** — set `OPENAI_API_KEY`; without it the LLM
  relevance filter is disabled and raw scraper matches pass through.
  `SERPER_API_KEY` is optional and only adds the Google source.
