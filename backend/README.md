# Marko backend

FastAPI API, background workers, PostgreSQL persistence, prom.ua ingestion, and
product matching for the Marko price-monitoring application. Firebase
Authentication owns credentials and sessions. This service verifies Firebase ID
tokens through Google's public signing keys, provisions local users/workspaces,
and owns all business authorization and data.

Set `FIREBASE_PROJECT_ID` to the exact Firebase project ID. No Firebase Admin
service-account JSON, OAuth client secret, or API key is needed by FastAPI.

The backend is developed and tested through Docker; no host `.venv` is needed:

```bash
docker compose up -d --build db broker migrate api worker pricing-worker scheduler
docker compose --profile test run --rm --build backend-test
```

The production pricing path is:

```text
XLSX snapshot -> pricing run -> rate-limited collection queue
              -> frozen paired-OE dataset + both coefficient models
              -> selected run-level calibration -> calculation queue
              -> append-only recommendations and operator decisions
```

The Prom extraction parser is consumed as a black box. Scaling,
physical-attempt Redis pacing, separate HTTP/task retry budgets, raw HTML
evidence, replay, checkpoints, persistence, reconciliation, and metrics live
around it. See
[`../docs/scraper_scaling.md`](../docs/scraper_scaling.md).

Live public-marketplace requests are protected by a fail-closed source-access
gate. `NOT_PERMITTED`/`UNKNOWN` blocks dispatch and physical HTTP attempts while
leaving XLSX ingestion and stored evidence replay usable. Permitted verdicts
require an auditable reference.

The Metis-owned pure domain under `src/metis/pricing/` implements Decimal KEMP
normalization, simple-median and hierarchical-shrinkage calibration,
leave-one-category/leave-one-OE leakage protection, MAD/IQR fair price,
half-life confidence, stock modes and typed economic priority. See
[`../docs/kemp_pricing_engine.md`](../docs/kemp_pricing_engine.md).

Recommendation replay, workspace roles, tenant-scoped dead letters, controlled
retry, production settings validation, and recovery procedures are documented
in [`../docs/production_runbook.md`](../docs/production_runbook.md).

Host verification when `.venv` is present:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q
.venv/bin/alembic upgrade head --sql
.venv/bin/alembic downgrade 20260716_0009:base --sql
```
