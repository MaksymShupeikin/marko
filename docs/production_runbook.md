# Marko production runbook

This runbook defines the deploy, recovery, rollback, and evidence checks for the
current raise/hold/lower recommendation service. It does not authorize Prom
marketplace collection.

## 1. Hard preflight

Production deployment must stop unless all of the following are true:

1. Strict preflight exits zero for the explicitly named production env file;
   inherited shell variables are not accepted as a substitute.
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

The committed `deploy/.env.production.example` is a template and must fail
preflight until every placeholder is replaced. Never copy a preflight JSON
artifact containing configuration values: the checker emits only field names,
reason codes, hashes, and statuses.

Static validation:

```bash
backend/.venv/bin/python scripts/check_production_config.py \
  --env-file deploy/.env.production \
  --mode static \
  --format json \
  --output-json .artifacts/production-preflight-static.json
```

Full validation requires reachable PostgreSQL/Redis/TLS endpoints and a real,
successful PROMPT 15.015 E2E evidence manifest. A skipped connectivity or E2E
layer is a failure, not a warning:

```bash
backend/.venv/bin/python scripts/check_production_config.py \
  --env-file deploy/.env.production \
  --mode full \
  --format json \
  --e2e-evidence docs/PROMPT_15_015_E2E_EVIDENCE_2026-07-18.yaml \
  --output-json .artifacts/production-preflight-full.json
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

The scheduler entrypoint owns a Redis `SET NX EX` lease and terminates if it
cannot acquire or renew it. A second scheduler must exit with code `75`; do not
work around that guard. Configure one stable lock key, a TTL longer than the
refresh interval, and a refresh interval shorter than the TTL. Do not expose
PostgreSQL or Redis publicly. TLS, secret injection, network policy, log
shipping, Prometheus collection, and alert delivery belong to the deployment
platform.

## 2.1. Disposable local E2E

The E2E runner uses a unique Compose project, random loopback ports, clean
PostgreSQL/Redis volumes, real Celery workers/scheduler/API/frontend/browser,
and persisted replay fixtures. It sets source access to `NOT_PERMITTED`, makes
zero live Prom requests, never applies a price, kills/restarts a pricing worker,
and removes only its own project resources.

```bash
backend/.venv/bin/python scripts/run_prompt_15_015_e2e.py --validate-harness
backend/.venv/bin/python scripts/run_prompt_15_015_e2e.py \
  --evidence-output docs/PROMPT_15_015_E2E_EVIDENCE_2026-07-18.yaml \
  --artifact-root .artifacts/prompt_15_015_e2e
```

Exit code `3` means Docker/Compose is unavailable and the generated manifest is
`BLOCKED_ENVIRONMENT`; it is never evidence of E2E success. Browser traces are
not retained because they can contain the synthetic Authorization header.
Secret canaries are removed and scanned before the manifest is finalized.

## 2.2. Comparability and robust-policy activation

The code is fail-closed by default. `UNKNOWN` comparability fields route to
manual review, conflicts reject the candidate, and legacy rows never become
verified through backfill. Automatic comparability or robust-v3.1 activation
requires all of the following:

1. an approved, representative versioned dataset;
2. approved domain policy and business release parameters;
3. an immutable activation artifact and its expected SHA-256;
4. the matching feature flag for that artifact;
5. a decision-diff with zero unsafe relaxations.

Do not enable `PRICING_V3_ROBUST_DISPERSION_ENABLED` or
`PRICING_COMPARABILITY_V1_AUTOMATIC_ENABLED` with an empty, missing, or
unverified activation artifact. A flag alone is `NO_GO` for persisted runs.

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

For revision `20260718_0011`, downgrade removes comparability evidence,
fingerprints, and robust diagnostic columns. Treat that downgrade as lossy:
export the affected recommendation/observation audit data first, test the exact
downgrade on a restored disposable database, and prefer a forward fix. Never
downgrade a live database merely to disable v3; leave activation flags off.

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

The existing Prom parser remains frozen. E2E fixture replay and typed evidence
adapters are boundary components; they do not authorize parser-internal changes
or public competitor collection.
