# Production Compose deployment

`compose.production.yaml` is a self-contained application edge for a single
host. PostgreSQL and Redis remain external managed dependencies; Caddy,
Prometheus, the API, workers, scheduler, and Flutter frontend run in Compose.

## Required host preparation

1. Point the `APP_DOMAIN` and `API_DOMAIN` DNS records at the host.
2. Permit inbound TCP `80` and TCP/UDP `443`. Do not publish the API,
   frontend, Redis, PostgreSQL, or Prometheus ports publicly.
3. Copy `.env.production.example` to an untracked file outside the repository,
   replace every placeholder, and set mode `0600`.
4. Keep `PUBLIC_API_BASE_URL`, `API_DOMAIN`, `ALLOWED_HOSTS`, `APP_DOMAIN`, and
   `CORS_ORIGINS` consistent. The production preflight rejects mismatches.

Run from the repository root:

```bash
cd backend
uv run check-production-config --env-file /secure/path/marko-production.env --mode static
cd ..
docker compose \
  --env-file /secure/path/marko-production.env \
  -f deploy/compose.production.yaml \
  config --quiet
docker compose \
  --env-file /secure/path/marko-production.env \
  -f deploy/compose.production.yaml \
  up -d --build
```

## Edge and proxy boundary

Caddy obtains and renews public certificates automatically and routes the two
public hosts:

- `APP_DOMAIN` to `frontend:80`;
- `API_DOMAIN` to `api:8000`.

The API and frontend use Compose `expose`, not host port publication. For this
topology `TRUSTED_PROXY_IPS=*` is intentional: the API is reachable only from
private Docker networks and all public traffic crosses Caddy. Do not reuse that
setting if an operator publishes the API container directly.

## Scheduler and monitoring

The scheduler healthcheck verifies all three conditions: the supervisor PID is
alive, its Celery Beat child is alive, and Redis still contains the same fresh
lease token. Lease loss stops the fenced Beat child before the supervisor tries
to reacquire ownership.

Prometheus scrapes the private
`/api/v1/operations/metrics/prometheus` endpoint. Caddy returns `404` for that
path, so it is not part of the public API. The Prometheus UI binds to loopback
only at `127.0.0.1:${PROMETHEUS_PORT:-9090}`; use an SSH tunnel for operator
access.

**The scrape target requires a credential.** It refuses anonymous requests, so
without the steps below Prometheus receives `401` and every operational alert
evaluates against no data — the target reports `up=0` while the stack looks
healthy. Generate one secret and give it to both sides:

```bash
# 1. Generate the shared service credential (32+ characters).
token=$(openssl rand -hex 32)

# 2. Give it to the API through the environment file.
printf 'OPERATIONAL_METRICS_TOKEN=%s\n' "$token" >>/path/to/your/.env.production

# 3. Give the same value to Prometheus as a file, without a trailing newline.
mkdir -p deploy/secrets
printf '%s' "$token" >deploy/secrets/metrics_token
chmod 600 deploy/secrets/metrics_token
```

`deploy/secrets/` is untracked. With `OPERATIONAL_METRICS_TOKEN` unset the
endpoint stays closed and keeps demanding a user token, which is the safe
default rather than an open metrics port. Verify after deployment:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:8000/api/v1/operations/metrics/prometheus            # 401
curl -s -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $token" \
  http://127.0.0.1:8000/api/v1/operations/metrics/prometheus            # 200
```

## Schema revision and readiness

`/api/v1/health/ready` compares the Alembic head shipped in the image with the
revision recorded in the database and answers `503 SCHEMA_REVISION_MISMATCH`
when they differ. A container built before a migration therefore fails its
healthcheck instead of serving traffic against a schema its code does not
describe. `/api/v1/health/schema-revision` reports both values for diagnosis:

```bash
curl -s http://127.0.0.1:8000/api/v1/health/schema-revision
# {"code_head":"20260729_0026","database_revision":"20260729_0026","in_sync":true}
```

A mismatch means the image and the volume disagree. Rebuild the affected
services so `migrate` runs the shipped graph:
`docker compose up -d --build migrate api worker store-sync-worker
pricing-worker scheduler`. Take a database backup before an upgrade
(`scripts/backup_postgres.sh`).

### Rollback boundary at `20260729_0025`

Revision `20260729_0025` adds reviewed `identity_status` and
`identity_reason` values. Once any row is no longer the untouched
`UNRESOLVED`/`NULL` state, its downgrade is intentionally blocked with
`IRREVERSIBLE_MIGRATION_20260729_0025`; dropping the columns would erase an
operator decision. Do not bypass that guard.

To roll back across this boundary, stop all application writers and restore the
verified custom-format backup made immediately before the upgrade into a new,
explicitly named database. Validate the archive first with
`pg_restore --list`, point a staging API image at the restored database, and
confirm its Alembic revision and row counts before switching traffic. A schema
downgrade remains available only while all identity rows are still untouched.

### Rollback boundary at `20260730_0029`

Revision `20260730_0029` adds catalog-import request fingerprints. Once any
import has a fingerprint, its downgrade is intentionally blocked with
`IRREVERSIBLE_MIGRATION_20260730_0029`; erasing the values would silently
re-enable duplicate imports. Do not bypass that guard.

To cross this boundary, use the verified custom-format backup made immediately
before `0029` and follow the same stop-writers, restore-to-a-new-database,
staging verification, and row-count comparison procedure above. A schema-only
downgrade remains available while every request fingerprint is still `NULL`.

`prometheus-alerts.yml` is loaded by the service, including scheduler lease,
queue, failure, evidence, and retry-amplification alerts. Route alert
notifications through the infrastructure's Alertmanager or managed monitoring
receiver before go-live.

Caddy certificates/configuration and Prometheus time-series data live in named
volumes. Back up and restore requirements for those volumes and the external
PostgreSQL service remain an operational go-live gate.
