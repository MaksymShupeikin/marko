# Marko production runbook

This runbook defines the deploy, recovery, rollback, and evidence checks for the
current raise/hold/lower recommendation service. It does not authorize Prom
marketplace collection.

## 1. Hard preflight

Production deployment must stop unless all of the following are true:

1. `scripts/check_production_config.py` exits zero.
2. `alembic upgrade head` succeeds against the target PostgreSQL database.
3. `/api/v1/health/live` and `/api/v1/health/ready` return `200`.
4. `/api/v1/health/source-access` matches the approved source record.
5. A permitted verdict has an auditable reference. `NOT_PERMITTED` and
   `UNKNOWN` intentionally keep live HTTP collection blocked while XLSX,
   deterministic evaluation, stored evidence, and replay remain available.
6. Backend tests, Ruff, Python compile, Flutter tests, formatting, and release
   build pass in a clean CI runner.
7. A controlled benchmark satisfies the accepted success, latency, resource,
   source-headroom, database, queue, and `rho <= 0.70` thresholds.
8. A clean-database restore drill and at least one exact recommendation replay
   have passed.

Example preflight:

```bash
set -a
. deploy/.env.production
set +a
backend/.venv/bin/python scripts/check_production_config.py
```

## 2. Deployment

`deploy/compose.production.yaml` is a hardened single-host reference manifest.
It expects private managed PostgreSQL and Redis endpoints, binds HTTP ports to
loopback for an external TLS reverse proxy, runs the backend as UID/GID 10001,
uses a read-only filesystem, disables API docs, validates hosts/CORS, and
separates API, scheduler, general, store-sync, and pricing workers.

```bash
docker compose \
  --env-file deploy/.env.production \
  -f deploy/compose.production.yaml \
  config

docker compose \
  --env-file deploy/.env.production \
  -f deploy/compose.production.yaml \
  up --build -d
```

Only one scheduler instance may run. Do not expose PostgreSQL or Redis publicly.
TLS, secret injection, network policy, log shipping, Prometheus collection, and
alert delivery belong to the deployment platform.

## 3. Source-access incident

If source permission is absent, revoked, expired, or uncertain:

1. Set `PROM_MARKETPLACE_SOURCE_ACCESS_VERDICT=NOT_PERMITTED`.
2. Restart API and workers.
3. Confirm live run creation returns `409 SOURCE_ACCESS_BLOCKED`.
4. Confirm stored recommendation replay and XLSX catalog reads still work.
5. Record the new source decision before any later `PERMITTED_*` change.

An accepted business risk does not override this gate.

## 4. Dead letters and replay

Terminal store-sync and pricing-target failures are exposed as a durable,
workspace-scoped dead-letter registry:

```text
GET  /api/v1/operations/dead-letters
POST /api/v1/operations/dead-letters/{kind}/{id}/replay
```

Replay requires `owner` or `admin`. It creates a new workflow and never mutates
the terminal history. If source access is blocked, replay remains blocked with
the same explicit source error.

## 5. Backup

Use a PostgreSQL client version compatible with the managed server:

```bash
POSTGRES_DSN='postgresql://...' \
BACKUP_DIR=/secure/marko-backups \
scripts/backup_postgres.sh
```

The script creates a custom-format dump, validates its table of contents, uses
private file permissions, and writes a SHA-256 sidecar. Copy both files to
encrypted storage with retention and immutability configured by the operator.
Managed PITR remains the primary recovery mechanism; logical dumps are the
portable second line.

RPO, RTO, retention, encryption key ownership, and restore frequency require an
explicit business/operations decision.

## 6. Clean restore drill

Restore only into a newly created empty database:

```bash
TARGET_POSTGRES_DSN='postgresql://...' \
BACKUP_FILE=/secure/marko-backups/marko-YYYYMMDDTHHMMSSZ.dump \
ALLOW_EMPTY_DATABASE_RESTORE=YES \
scripts/restore_postgres.sh
```

Then point `DATABASE_URL` to the restored database, run:

```bash
cd backend
alembic -c alembic.ini current
cd ..
backend/.venv/bin/python scripts/verify_recommendation_replay.py \
  WORKSPACE_UUID RECOMMENDATION_UUID
```

The drill passes only when schema revision is correct, row-count probes succeed,
the selected replay reports `exact_match: true`, and elapsed time is recorded
against the approved RTO.

## 7. Rollback

1. Stop new job dispatch and leave workers draining bounded in-flight work.
2. Record current image digest and Alembic revision.
3. Deploy the previous known-good immutable image.
4. Prefer forward-compatible migrations. Run `alembic downgrade` only after the
   downgrade path has been tested against a restored copy and a fresh backup
   has completed.
5. Verify health, tenant-scoped reads, dead-letter visibility, and a
   recommendation replay.
6. Re-enable dispatch gradually and watch queue age, terminal failure rate,
   retry amplification, evidence coverage, CPU, and memory.

## 8. Capacity and parser incidents

Do not infer capacity from unit tests or one local request. Use
`scripts/evaluate_scraper_benchmark.py` with controlled runs at increasing
worker counts. Select the smallest worker count that passes every acceptance
condition and leaves `rho <= 0.70`.

On a parser-empty anomaly, 429 storm, upstream contract change, or rising
terminal failure rate:

1. Stop dispatch or open the circuit.
2. Preserve raw evidence and request traces.
3. Do not change parser internals until a reproducible boundary defect exists.
4. Compare replay against the frozen adapter version.
5. Route terminal items to the dead-letter view and resume only after a bounded
   canary passes.
