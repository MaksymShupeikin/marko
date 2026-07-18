# PROMPT 15.015 — implementation report

Date: 2026-07-18  
Checkout: `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`  
Git identity: `NOT_AVAILABLE` — neither this checkout nor its parent exposes `.git`
metadata, so no commit, branch, or reliable pre-existing dirty-path list can be claimed.

## Direct result

The implementation stage is `PASS`. Matching/comparability, robust v3.1, strict preflight,
clean migrations, API, replay, operator UI, observability, singleton scheduling, mutations,
and the isolated runtime are implemented and executable.

The mandatory Docker E2E completed on a real PostgreSQL 17 + Redis 8 + FastAPI + three Celery
workers + scheduler + served Flutter + Playwright stack. All E2E-F01…F10 and all ten browser
assertions passed. A separate full-mode production preflight then passed against disposable
PostgreSQL and TLS Redis dependencies plus the passing E2E bundle.

Production automatic activation remains disabled until representative labeled data and an
approved activation policy exist. That bounded product decision does not invalidate this
implementation-stage PASS; full production readiness remains `NOT_PROVEN` because E5
recovery/load/pilot evidence is outside this run.

## Baseline defects and after-fix behavior

| Reproduction | Before | After | Evidence |
|---|---|---|---|
| Missing OE/fitment/side/condition/quantity/provenance/currency | `RAISE`, price `920` | `INSUFFICIENT_DATA`, price `null` | `PROMPT_15_015_BASELINE_REPRO_2026-07-18.json`, `PROMPT_15_015_AFTER_REPRO_2026-07-18.json` |
| `[100,101,102,103,180,181,182,183]` under the old robust candidate | `RAISE`, price `92` | `MANUAL_REVIEW`, price `null`, explicit disagreement/multimodal reasons | same artifacts plus robust decision diff |
| `.env.production.example` | exit `0` despite placeholders | exit `2`, secret-safe reason codes, no values emitted | `PROMPT_15_015_PREFLIGHT_TEMPLATE_NEGATIVE_2026-07-18.json` |
| Real Docker E2E | not verified | `PASS`: 10/10 failure injections, 10/10 browser assertions, exact replay, scoped cleanup | `PROMPT_15_015_E2E_EVIDENCE_2026-07-18.yaml` |

The executable after-fix reproduction reports `expectation_met: true`, `network_requests: 0`,
and `secrets_included: false`.

## Implemented remediation

### Comparability and matching

- Added immutable `ComparisonEvidence` with four-state dimensions: `MATCH`, `CONFLICT`,
  `UNKNOWN`, and policy-approved `NOT_APPLICABLE`.
- Versioned and hashed the auto-parts comparability policy.
- Evaluated OE, manufacturer/brand, fitment, generation/year/engine/body, side/position,
  condition, package quantity, and raw currency before automatic pricing.
- Prevented exact SKU/model/OE retrieval and caller confidence from bypassing unknowns or
  conflicts.
- Required verified stable seller IDs for independence; seller display aliases cannot create
  additional evidence.
- Bound source provenance to immutable records and SHA-256; legacy rows remain
  `legacy-unknown-v0` and fail closed.
- Required both feature flag and exact activation-artifact hash before any persisted automatic
  comparability recommendation. Preview/QA can still evaluate typed evidence without granting
  production authority.
- Added a versioned synthetic/adversarial gold-set contract with train/calibration/test leakage
  controls and safety-first metrics. It passes its engineering gate with zero unsafe automatic
  cases while correctly returning production activation `BLOCKED_DATA`.

### Robust dispersion v3.1

- Preserved exact MAD, IQR, S_n, and Q_n estimators and added estimator-disagreement tracing.
- Added a deterministic log-price, balanced two-cluster diagnostic with explicit threshold,
  boundary, scale, permutation, and seller-dedup contracts.
- Added baseline non-relaxation: v3.1 cannot turn a v2 abstention into RAISE/HOLD/LOWER.
- Added explicit `ROBUST_ESTIMATOR_DISAGREEMENT`, `ROBUST_MULTIMODAL_COHORT`, partial
  degeneracy, unavailable-diagnostic, and non-relaxation reasons.
- Persisted the diagnostic and versioned robust-policy fingerprint; replay compares the entire
  decision fingerprint, not only the final price.
- Decision diff has `unsafe_relaxation_count: 0`; production activation remains
  `BLOCKED_DATA` because the available matrix is synthetic rather than representative.

### Persistence, API, replay, and operator UI

- Added migration `20260718_0011` for raw currency, evidence contract/policy, verified seller
  and source flags, eligibility, robust diagnostics, hard-gate trace, and decision fingerprint.
- Added database constraints so automatic rows require verified evidence and 64-character
  policy/fingerprint hashes. Backfill defaults are explicitly ineligible.
- Fixed API serialization of immutable `MappingProxyType` evidence instead of weakening the
  immutable contract.
- Added comprehensive canonical NFC/Decimal/datetime fingerprinting over context, evidence,
  provenance, policy, coefficients, robust diagnostics, build identity, rounding, and result.
- Replay reconstructs current immutable inputs and rejects evidence/policy/fingerprint drift.
- API rejects `accepted` for ineligible recommendations. The Flutter UI hides Accept, keeps
  Reject, and exposes a separately audited manual-price override.
- Added additive API/Flutter fields and verified the OpenAPI schema without exposing E2E routes
  outside E2E mode.

### E2E, workers, and operations

- Added an isolated Compose E2E override with unique project names, random loopback ports,
  clean volumes, migrations, PostgreSQL, Redis, three worker lanes, singleton scheduler, API,
  served Flutter frontend, and Playwright browser assertions.
- Added E2E-only constant-time bearer auth. Settings, production Compose, preflight, and tests
  forbid enabling it outside `ENVIRONMENT=e2e`.
- Added immutable compressed fixture replay. The E2E source verdict is `NOT_PERMITTED`; the
  runner makes zero live Prom requests and applies zero prices.
- Added E2E-F01…F10 probes for DB readiness failure, broker outage, worker loss/fencing,
  duplicate delivery, row rejection, missing evidence, frontend-before-API recovery, migration
  failure, scheduler singleton, and tamper detection.
- Added Redis lease ownership, compare-and-renew/release scripts, exit `75` for duplicate
  schedulers, and termination on lease loss.
- Cleanup is scoped to the unique Compose project; no global prune is present. Logs are captured
  before cleanup and scanned/redacted for canaries. Browser traces are intentionally not stored
  because they can contain the synthetic Authorization token.
- Corrected the production runbook, strict preflight commands, activation/rollback rules, worker
  health checks, and frontend health check.

The existing Prom parser internals were not edited. `parser_models.py` received only an additive
boundary contract. Source-access policy and local `.env` were not changed.

### Runtime defects found by the real E2E and fixed

- Replaced per-task `asyncio.run()` calls with one persistent worker-process async runner, so
  SQLAlchemy pools are no longer reused across closed event loops.
- Added missing ORM `currency_raw` / `currency_inferred` fields already present in migration
  `0011`, and fixed raw-manifest and decision-fingerprint hashing/serialization.
- Configured the same Celery visibility timeout across broker, result backend, and app so a
  killed late-ack task is actually redelivered and fenced.
- Made readiness return 503 for database network/DNS failures instead of leaking a 500.
- Made the Playwright harness activate Flutter semantics with a valid locale and locate both
  canvas accessibility labels and DOM controls.
- Made E2E network accounting count physical `ScrapeHttpAttempt` rows; deterministic replay
  logical requests are no longer falsely reported as live Prom traffic.

## Verification actually executed

| Check | Result |
|---|---|
| Full backend | `547 passed` |
| Ruff | PASS |
| Python compileall | PASS |
| Matching M-001…M-025 + properties | PASS |
| Comparability critical mutations | `7/7 KILLED`, survived `0` |
| Comparability gold set | 15/15 expected decisions, unsafe auto `0`, no split leakage |
| Robust R-001…R-020 and existing robust suites | PASS |
| Robust critical mutations | `11/11 KILLED`, survived `0` |
| Robust decision diff | unsafe relaxations `0` |
| Robust exact benchmark | completed through `n=500`; capacity guard, not latency SLO |
| Preflight P-001…P-025 plus valid/static/blocked-evidence tests | PASS |
| E2E harness static/pure fixture contract | PASS |
| E2E runtime | PASS; run `20260718T140556Z-1b2165b5`, E2E-F01…F10 `10/10` |
| Alembic heads | `20260718_0011 (head)` |
| Alembic offline upgrade SQL | PASS |
| Clean PostgreSQL migration | PASS inside the disposable PostgreSQL 17 E2E stack |
| Full production preflight | PASS; every P0…P7 check PASS, TLS Redis connectivity verified, secrets emitted `false` |
| OpenAPI additive schema | PASS, 31 paths / 45 schemas at probe time |
| Flutter format | PASS, 41 files / 0 changes |
| Flutter tests | PASS, 22 tests |
| Flutter analyze | PASS on an exact-hash ASCII mirror; native Unicode checkout path crashes the Dart analysis-server LSP parser with exit 255 |
| Flutter web release build | PASS; `build/web` produced |
| Section 15.1 manifest | PASS; `END_OF_RESPONSE_VALID` |
| Section 16 manifest | PASS; `MACHINE_READABLE_SUMMARY_VALID` |
| Combined final response | PASS; human footer, stop-gate, and machine summary cross-validation |

The ASCII analysis mirror is only a workaround for a Flutter 3.44.4 analysis-server LSP bug on
the checkout's Unicode path. It is not used as Docker E2E evidence; the real browser flow ran
from the actual checkout and passed.

## Hostile self-review

1. Five offers without hard evidence cannot create an automatic price: M-025 and the after-fix
   reproduction return null.
2. Exact model/SKU cannot bypass brand/fitment/condition conflicts: every M-001…M-013 case runs
   under fuzzy, SKU, and model retrieval.
3. `source_confidence=1` cannot replace provenance: M-014.
4. Blank seller IDs cannot become independent through names: M-016 and the direct seller gate.
5. Missing/empty/whitespace raw currency cannot become UAH: M-018 variations.
6. The balanced two-cluster cohort cannot become automatic through low Q_n: R-006.
7. v3.1 cannot relax baseline abstention and cannot persist with a flag alone: R-019 and exact
   activation-artifact verification.
8. Decision diff cannot PASS with unsafe relaxation: its exit gate is tied to count zero.
9. The production example cannot pass unchanged: recorded exit `2`.
10. Full preflight cannot pass with skipped connectivity/workflow or a blocked/incomplete E2E
    manifest.
11. Secret canaries are absent from JSON/human outputs and E2E artifacts; exception text is never
    emitted by the preflight CLI.
12. E2E PASS is backed by real containers and a real browser; only market acquisition uses the
    required immutable replay fixture, with zero physical Prom requests.
13. E2E auth cannot start in production and production Compose hardcodes it off.
14. Duplicate delivery was dispatched through real Redis/Celery and left one recommendation.
15. A real pricing worker was killed with `SIGKILL`; the task was redelivered with a newer fence
    and completed without a stale commit.
16. Replay fingerprints include policy, evidence, provenance, build/algorithm identity, and
    decision; tampering changes the hash.
17. Legacy backfill stays unknown/ineligible and cannot synthesize verified evidence.
18. Clean PostgreSQL migration, schema head, offline SQL, and full preflight database evidence pass.
19. API, OpenAPI, Flutter model/UI tests, format, analysis, and release build pass; ineligible
    operator actions remain visible through manual/reject paths.
20. No production claim exceeds the evidence level: implementation passes are separate from
    activation, E2E, recovery/load, and production-readiness gates.

## Material files

Core contracts and engine:

- `backend/src/metis/pricing/{types,comparability,gold_set,statistics,engine}.py`
- `backend/src/marko/services/{matching,market_collection,pricing_runs,decision_fingerprint,recommendation_replay}.py`
- `backend/src/marko/services/parser_models.py` — additive boundary only

Runtime, API, and database:

- `backend/src/marko/{core/config.py,services/auth.py,worker/beat_singleton.py}`
- `backend/src/marko/api/{dependencies.py,main.py,routers/e2e.py,routers/v1/pricing.py,schemas/pricing.py}`
- `backend/src/marko/e2e/` and its replay fixture
- `backend/src/marko/infrastructure/db/models.py`
- `backend/migrations/versions/20260718_0011_comparability_and_robust_gates.py`

Frontend and operations:

- `frontend/{Dockerfile,lib/core/environment.dart,lib/core/firebase_auth_client.dart,lib/main.dart}`
- `frontend/lib/features/pricing/{pricing_controller,pricing_models,recommendations_page}.dart`
- `frontend/test/pricing_api_test.dart`
- `compose.yaml`, `compose.e2e.yaml`, `deploy/compose.production.yaml`
- `deploy/.env.production.example`, `docs/production_runbook.md`, `e2e/browser/`

Harnesses and tests:

- `scripts/{check_production_config,reproduce_prompt_15_015_baseline,run_prompt_15_015_e2e}.py`
- `scripts/run_prompt_15_015_preflight_proof.py`
- `scripts/{validate_comparability_gold_set,run_comparability_mutation_probes}.py`
- `scripts/{validate_robust_dispersion_decision_diff,run_robust_dispersion_mutation_probes,benchmark_robust_dispersion}.py`
- Prompt-specific backend tests and fixtures under `backend/tests/`
- `docs/examples/{end_of_response,machine_readable_summary}_prompt_15_015.yaml`
- `docs/PROMPT_15_015_FINAL_RESPONSE_2026-07-18.md`

## Reproduction commands

```bash
cd "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия"

backend/.venv/bin/pytest -q backend/tests
/opt/anaconda3/bin/ruff check backend/src backend/tests scripts
backend/.venv/bin/python -m compileall -q backend/src backend/tests scripts

backend/.venv/bin/python scripts/reproduce_prompt_15_015_baseline.py \
  --expect after --output docs/PROMPT_15_015_AFTER_REPRO_2026-07-18.json
backend/.venv/bin/python scripts/validate_comparability_gold_set.py
backend/.venv/bin/python scripts/run_comparability_mutation_probes.py
backend/.venv/bin/python scripts/validate_robust_dispersion_decision_diff.py
backend/.venv/bin/python scripts/run_robust_dispersion_mutation_probes.py
backend/.venv/bin/python scripts/benchmark_robust_dispersion.py --repeats 5

cd backend
.venv/bin/alembic -c alembic.ini heads
.venv/bin/alembic -c alembic.ini upgrade head --sql
cd ../frontend
dart format --output=none --set-exit-if-changed lib test
flutter test --no-pub
flutter build web --release --no-pub \
  --dart-define=API_BASE_URL=http://localhost:8000 \
  --dart-define=FIREBASE_API_KEY=AIza_REPLACE_ME \
  --dart-define=FIREBASE_AUTH_DOMAIN=placeholder.firebaseapp.com \
  --dart-define=FIREBASE_PROJECT_ID=placeholder \
  --dart-define=FIREBASE_MESSAGING_SENDER_ID=123456789012 \
  --dart-define=FIREBASE_WEB_APP_ID=1:123456789012:web:replace_me \
  --dart-define=E2E_MODE=false --dart-define=E2E_AUTH_TOKEN=
cd ..

backend/.venv/bin/python scripts/run_prompt_15_015_e2e.py --validate-harness
backend/.venv/bin/python scripts/run_prompt_15_015_e2e.py \
  --evidence-output docs/PROMPT_15_015_E2E_EVIDENCE_2026-07-18.yaml
backend/.venv/bin/python scripts/run_prompt_15_015_preflight_proof.py \
  --e2e-evidence docs/PROMPT_15_015_E2E_EVIDENCE_2026-07-18.yaml \
  --output docs/PROMPT_15_015_PREFLIGHT_FULL_RUNTIME_2026-07-18.json
```

The last command now exits `0` on the configured Colima/Docker Compose runtime and writes the
passing evidence manifest cited above.

## Final gates

```yaml
remediation_execution: PASS
docker_e2e_gate: PASS
matching_implementation_gate: PASS
matching_production_activation: BLOCKED_DATA
robust_v3_implementation_gate: PASS
robust_v3_activation_gate: BLOCKED_DATA
production_preflight_gate: PASS
full_production_readiness: NOT_PROVEN
```

`STOP_GATE_PROMPT_15_015_IMPLEMENTATION = PASS`
