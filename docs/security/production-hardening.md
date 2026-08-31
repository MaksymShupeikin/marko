# Marko production hardening and release runbook

Status: the controls described here are implemented on branch
`sandbox/security-hardening`. This document does not assert that the branch has
been deployed. Production is considered fixed only after the final live audit
passes from outside the origin.

## Release safety contract

1. Take a database backup and verify that the backup is non-empty and readable.
2. Record the currently deployed Git commit, backend image digest and Cloudflare
   Pages deployment ID. These are the rollback targets.
3. Deploy to a staging/preview hostname first. Run backend tests, frontend tests,
   the local container smoke tests and `scripts/security_audit.py` against the
   preview.
4. Do not change Firebase providers, App Check enforcement, HSTS subdomain scope,
   DNS and the application release in one operation. Each has a separate
   rollback boundary.
5. Deploy the API before the frontend. The hardened API is backward-compatible
   with build 9, while the new frontend expects the same API paths.
6. Keep the previous API image and Pages deployment available until authenticated
   acceptance has covered login, import, competitor search/streaming, store sync,
   product refresh/delete and billing.

Never paste production secrets into chat, source control, command history or CI
logs. Configure them through the ignored VPS `.env` and the deployment platform's
encrypted secret store.

## Backend deployment

Required production configuration:

```dotenv
ENVIRONMENT=production
DEBUG=false
CORS_ORIGINS=https://markoprice.com
TRUSTED_HOSTS=api.markoprice.com,localhost,127.0.0.1,api
API_DOCS_ENABLED=false
HSTS_MAX_AGE_SECONDS=31536000
RATE_LIMITS_ENABLED=true
UPLOAD_MAX_BYTES=26214400
UPLOAD_MAX_UNCOMPRESSED_BYTES=209715200
UPLOAD_MAX_ROWS=100000
FIREBASE_PROJECT_ID=marko-4941e
```

The database password, tunnel token and service API keys must be real secret
values; the default `marko:marko` database credential is rejected in production.
Container bases and infrastructure services are pinned by digest so a later
registry change cannot silently alter a release. Refresh those digests in a
monthly maintenance PR only after rebuilding, scanning and rerunning acceptance;
pinning is not a substitute for updates.

The repository builds thin hardened PostgreSQL/Redis images and a scratch
wrapper around Cloudflare's statically linked `cloudflared` binary. Do not swap
the wrapper back to the full upstream image without rescanning it. The remaining
Go advisories in the pinned vendor binary are tracked in the dated verification
ledger and require a tested upstream rebuild.

Pre-release checks:

```bash
docker compose config -q
docker compose --profile test run --rm --build backend-test
docker build --target production -t marko-api:security-candidate backend
```

Deploy in this order: database and broker health, migration as a one-shot job,
API health, workers/scheduler, then the tunnel. The public firewall must not
expose PostgreSQL, Redis or port 8000. Compose binds their host ports to
`127.0.0.1`; the Cloudflare Tunnel is the only public path to the API.

After deployment, verify all of the following before advancing the frontend:

- `/api/v1/health/live` returns 200;
- `/docs`, `/redoc`, `/openapi.json` return 404;
- `/api/v1/products` without a token returns 401;
- an invalid `Host` is rejected;
- the application sends HSTS, CSP, `X-Frame-Options`, `Permissions-Policy`,
  `no-store` and a unique request ID;
- the response has no Uvicorn `Server` header;
- an owner/admin can mutate data, while a member is read-only;
- import limits, job cancellation and rate limiting do not reject ordinary
  traffic.

Rollback the API image if authenticated acceptance fails. Database rollback is a
separate decision: do not restore a backup merely to roll back stateless code.

## Frontend and SEO deployment

Build and verify the exact artifact that will be uploaded:

```bash
make test-frontend
make analyze
make deploy-frontend
```

`make deploy-frontend` builds with CSP mode and local web resources, fingerprints
`main.dart.js`, verifies metadata/headers/404 files and then calls Wrangler. It
requires an already authenticated local Wrangler session. Do not add an API
token to the Makefile.

The Pages artifact contains:

- security headers in `_headers`;
- a real `robots.txt`, `sitemap.xml` and `404.html`;
- a static, indexable `/about/` product landing page;
- canonical, description, Open Graph and Twitter metadata;
- explicit SPA routes only (`/`, `/login`, `/reset-password`) rather than a
  catch-all rewrite;
- a content-hashed main bundle with one-year immutable caching;
- locally bundled primary fonts, so CSP failure cannot erase UI text.

Cloudflare Pages applies `_headers` to static responses. After deployment, inspect
the actual CDN response; the existence of `_headers` in the repository is not
production evidence. A Pages project with a top-level `404.html` returns a real
404 only when no catch-all rewrite or Function intercepts the request.

The two inline-script hashes in CSP are generated by the currently locked
FlutterFire web bootstrap. Every Firebase/FlutterFire upgrade must repeat the
clean-browser console test and update the hashes only from inspected generated
code. Do not replace them with general `script-src 'unsafe-inline'` or
`'unsafe-eval'`.

## Cloudflare controls

Apply and record screenshots/exports of these settings:

- SSL/TLS mode: Full (strict); minimum TLS 1.2; TLS 1.3 enabled;
- Always Use HTTPS enabled; Automatic HTTPS Rewrites enabled only after checking
  for mixed-content regressions;
- DNS records proxied where appropriate; origin IP not published by another DNS
  record;
- Cloudflare Tunnel ingress contains only `api.markoprice.com -> api:8000` and a
  terminal catch-all `http_status:404` rule;
- managed WAF rules enabled in log/simulate mode first, then blocking after the
  false-positive review;
- edge rate limits for login/identity traffic, imports, refreshes, bulk actions,
  sync and competitor streaming; do not load-test production to prove them;
- alerts for WAF spikes, 5xx rate, tunnel health, API latency, Redis/PostgreSQL
  health and abnormal Firebase Authentication traffic;
- cache rules do not cache HTML, authenticated API responses, reset links or
  Server-Sent Events. Only fingerprinted static assets may be immutable.

Application rate limiting is a second layer and intentionally fails open if
Redis is unavailable so that a Redis incident does not take down all customer
operations. Cloudflare edge limits therefore remain required for volumetric
protection.

## HSTS rollout

The candidate sends `max-age=31536000` on the apex and API hosts, but deliberately
does not yet send `includeSubDomains` or `preload`. Those two directives affect
hosts outside this application and can cause a long outage if an old, internal
or third-party subdomain lacks valid HTTPS.

Before adding them:

1. Export the full Cloudflare DNS inventory, including delegated subdomains.
2. Check certificate-transparency records and organization documentation for
   forgotten hosts.
3. Confirm every HTTP service under `*.markoprice.com` redirects to HTTPS and
   every HTTPS service has a renewable valid certificate.
4. Run at least one complete certificate-renewal cycle without incidents.
5. Add `includeSubDomains` first. Submit to the browser preload list only as a
   separately approved, last step after the preload eligibility test passes.

Removing the header does not immediately remove HSTS state already cached by
browsers. This is why `includeSubDomains; preload` is not part of the first
damage-minimizing release.

## Final external acceptance

Run:

```bash
python3 scripts/security_audit.py
```

Then perform a clean-browser authenticated acceptance pass using a non-production
test workspace. Capture the deployed commit/digests, audit output, UTC timestamp
and screenshots. The release is accepted only when both automated external
checks and authenticated business flows pass.

The release reduces known attack surface; it cannot guarantee that the product
"cannot be hacked." Maintain monthly dependency/image scans, quarterly access
reviews, backup-restore drills, alert response ownership and an incident
runbook.
