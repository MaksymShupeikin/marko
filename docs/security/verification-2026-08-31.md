# Security candidate verification — 2026-08-31

- UTC evidence timestamp: `2026-08-31T14:29:48Z`
- Base commit: `c579df7c1e3fc5f1ccad7b9cb876ae23303f769e`
- Branch: `sandbox/security-hardening`

This ledger distinguishes candidate evidence from production evidence. Passing
localhost/container checks does not mean that `markoprice.com` has been changed.

## Candidate results

| Check | Result | Evidence |
|---|---:|---|
| Backend tests | PASS | 195 tests passed |
| Flutter analyzer | PASS | No issues found |
| Flutter tests | PASS | 58 tests passed |
| Web artifact verifier | PASS | Fingerprinted bundle and required static/security files verified during Docker build |
| Local external-style audit | PASS | 22/22 checks against final frontend/API containers |
| Clean-browser login render | PASS | Login surface rendered; no warning/error console entries for port 18084 |
| Full Compose smoke | PASS | Migration completed; API healthy; Celery worker and beat running from read-only non-root containers |
| Python dependency audit | PASS | `pip-audit`: no known vulnerabilities |
| Flutter lockfile audit | PASS | OSV Scanner: 154 packages, no issues found |
| Backend runtime image audit | PASS | OSV Scanner: no issues found |
| Frontend runtime image audit | PASS | OSV Scanner: no issues found |
| Hardened PostgreSQL image audit | PASS | Alpine upgraded and unused vulnerable `gosu` removed; OSV Scanner: no issues found |
| Hardened Redis image audit | PASS | Alpine upgraded; OSV Scanner: no issues found |
| Hardened Cloudflared wrapper | PARTIAL | Unused vulnerable OS libraries removed; 13 upstream Go advisories remain in the exact 2026.8.3 binary |
| CORS/auth/Host runtime checks | PASS | allowed origin 200; foreign origin 400; unauthenticated data 401; invalid Host 400 |
| API docs closure | PASS locally | `/docs`, `/redoc`, `/openapi.json` return 404 in production mode |
| Static 404/SEO | PASS locally | unknown path 404; text robots/sitemap; static `/about/` H1 page |

Candidate image digests:

- backend: `marko-backend-security@sha256:eddf6799148d232597b226826645a5e74c6df49364d5f99d85ca9fc74eb097b6`
- frontend: `marko-frontend-security@sha256:2150e833b0cbe6a8ed98992a5e127571406cde40d3b04e33370562ffaf890919`
- PostgreSQL: `marko-postgres@sha256:a3066c37a39d9f0c2d9e7f3de4b2fb19b2217a0b0dc6926266f5204d829ef656`
- Redis: `marko-redis@sha256:0af9dac8f2d7ca8d813e1f1e598b74fb4df2a55fb15da0ef01d2dbaf5c217768`
- cloudflared scratch wrapper: `marko-cloudflared@sha256:a757e3036fa756ac95d1d7c42026c2875aa83cb76f70ae93ffd3de4125edc557`

The final main bundle is `main.ae5cbe6ed9863d13.dart.js`: 3,546,384
uncompressed bytes, about 799 KB at Brotli quality 11. The fingerprint makes
one-year immutable browser caching safe for repeat visits. The static landing
page avoids loading Flutter/CanvasKit for indexable product information.

The official `cloudflared:2026.8.3` image initially exposed 35 scanner
findings, including vulnerable Debian/OpenSSL libraries not used by its
statically linked binary. The scratch wrapper removes those libraries and
reduces the result to 13 Go advisories with no OSV severity classification.
Twelve require a vendor binary built with newer Go/dependencies; the remaining
`x/crypto/openpgp` advisory has no fixed module version. A local rebuild with Go
1.26.6 and the fixed module versions was rejected because two upstream tests
failed, including post-quantum curve negotiation. Shipping an unvalidated
security fork would create more risk than retaining the exact vendor binary.
Keep the wrapper non-root/read-only, pinned, outbound-only and replace it as
soon as Cloudflare publishes a passing rebuilt release.

## Secret scan

Gitleaks scanned 110 commits. Findings consisted of:

- six Google/Firebase browser API-key findings in public web/mobile
  configuration and documentation; these keys are public identifiers, but their
  API restrictions still require console verification;
- 15 generic findings whose redacted contexts are test fixture tokens,
  idempotency/reference identifiers and documentation file references, not
  deployable server credentials.

The current directory scan likewise reported only Google/Firebase browser-key
patterns, including generated build caches. No OpenAI, tunnel, database,
service-account private key or server token finding was reported. This does not
replace provider-side credential inventory and rotation.

## Current live result (not yet deployed)

`python3 scripts/security_audit.py` against the public domains passed **9/24**
checks. The live site still lacks HSTS/CSP/frame/permissions headers, still
serves placeholder/SPA responses for robots, sitemap, landing and missing URLs,
still exposes all three API documentation routes, and still uses the
unfingerprinted bundle.

Existing live positives remain: HTTPS redirects, CORS allow/reject behavior,
public liveness and unauthenticated API rejection.

## Access blockers

- Wrangler reports no authenticated account, so the Pages artifact cannot be
  uploaded from this machine.
- Firebase CLI reports no authorized account, so authorized domains, provider
  settings, enumeration protection, key restrictions, App Check and rules
  cannot be inspected or changed.
- The repository contains no VPS target/SSH deployment context, so the backend
  candidate cannot be installed or its production database backed up from this
  workspace.
- Authenticated business flows remain unverified because no browser login was
  completed. Do not release without testing import, competitor search/stream,
  store sync, product update/refresh/delete, job cancellation and billing.

HSTS `includeSubDomains` and preload are intentionally excluded from the first
candidate. They require the full DNS/subdomain inventory and a separately
observed HTTPS/certificate-renewal period; enabling them blindly would violate
the no-damage release requirement.
