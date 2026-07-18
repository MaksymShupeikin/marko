# METIS CONFORMAL CALIBRATION AND ABSTENTION LAYER

# STAGE 0 — REPOSITORY AND DATA REALITY AUDIT

## Audit metadata

```yaml
audit_id: metis-conformal-stage-0-2026-07-17
audit_date: 2026-07-17
stage_id: 0
stage_name: REPOSITORY_AND_DATA_REALITY_AUDIT
terminal_status: PASS
conformal_implementation_status: NOT_STARTED
production_activation_status: BLOCKED
project_root: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
prompt_sha256: 73421a7413deb26865abee42d60fff4f18f0339c856cb9d4251d74d04e6a4001
code_commit: NOT_AVAILABLE
code_commit_reason: checkout_has_no_git_metadata
audited_tree_fingerprint_sha256: ca4ec8a5eefd3d43461005c53b851e6cdf3b370a96bbb4187c98519b3e4ef8f0
runtime_code_changed: false
database_schema_changed: false
automatic_stage_transition: false
```

The scientific source named by the master prompt was verified as Angelopoulos
and Bates, *A Gentle Introduction to Conformal Prediction and
Distribution-Free Uncertainty Quantification*, arXiv:2107.07511, version 6.
No paper-derived formula is claimed as implemented by this stage.

## Epistemic labels used in this report

- `REPOSITORY_FACT` — confirmed by an active source file, migration, test, or
  command executed against this checkout.
- `PAPER_FACT` — attributed to the named primary paper; not used here to claim
  runtime behavior.
- `ENGINEERING_ASSUMPTION` — a candidate design direction requiring a later
  approved stage.
- `BUSINESS_DECISION` — must be selected by the product/statistical owner.
- `DATA_OR_SOURCE_BLOCKER` — required evidence, provenance, permission, or
  runtime environment is absent.
- `VALIDATED_RESULT` — confirmed by an executed check in this audit.

---

# A. Repository fact map

| Area | Repository reality | Evidence | Conformal implication |
| --- | --- | --- | --- |
| Physical layout | `REPOSITORY_FACT`: this is one checkout containing Python packages `metis` and `marko`, not two independently versioned repositories. | `backend/src/metis/`, `backend/src/marko/` | Artifact compatibility cannot currently point to separate Metis/Marko commits. |
| Kernel ownership | `REPOSITORY_FACT`: the canonical pricing kernel is `metis.pricing`; `marko.pricing` is a compatibility facade. | `backend/src/metis/pricing/__init__.py`; `backend/src/marko/pricing/__init__.py` | The conformal mathematical core belongs under the Metis package; transport and persistence belong under Marko. |
| Base estimator | `REPOSITORY_FACT`: `recommend_price` is a pure, deterministic function without HTTP, ORM, queue, or mutable global state. | `backend/src/metis/pricing/engine.py:48-55` | This is an appropriate black-box estimator boundary, but it is not a conformal estimator. |
| Base outputs | `REPOSITORY_FACT`: output includes point recommendation, market quartile bounds, composite data-quality confidence, evidence, exclusions, action, and versions. | `backend/src/metis/pricing/types.py:470-510` | Existing bounds and confidence must remain semantically separate from conformal interval and coverage status. |
| Existing “calibration” | `REPOSITORY_FACT`: `metis.pricing.calibration` fits simple/shrinkage cross-tier multipliers from paired OE observations. | `backend/src/metis/pricing/calibration.py:1-14,52-230` | This is coefficient calibration, not conformal calibration. Reusing names without qualification would be unsafe. |
| Existing coefficient interval | `REPOSITORY_FACT`: the interval is formed as `exp(center ± 1.96 * robust_standard_error)` and a heuristic confidence is computed. | `backend/src/metis/pricing/calibration.py:309-332` | It has no split-conformal coverage contract and cannot be promoted to one. |
| Exact order statistic primitive | `REPOSITORY_FACT`: a private exact 1-based order statistic exists and does not interpolate. | `backend/src/metis/pricing/statistics.py:70-75` | It is a candidate primitive only; finite-sample conformal rank and insufficient-sample semantics do not exist. |
| Robust dispersion | `REPOSITORY_FACT`: pricing-v2 uses legacy MAD; a v3 robust-dispersion candidate can use IQR/MAD/Sn/Qn and is activation-gated off by default. | `backend/src/metis/pricing/types.py:223-290`; `backend/src/marko/core/config.py` | A conformal artifact must pin the exact recommendation policy/version and not silently span v2/v3. |
| Evidence persistence | `REPOSITORY_FACT`: content-addressed raw captures, market observations, and versioned tier classifications exist. | `backend/src/marko/infrastructure/db/models.py:1116-1247` | There is reusable lineage material, but no dedicated conformal evidence snapshot identity. |
| Recommendation persistence | `REPOSITORY_FACT`: base recommendation, context snapshot, calculation trace, evidence IDs, policy/parser/classifier/coefficient versions, and money tick are persisted. | `backend/src/marko/infrastructure/db/models.py:1412-1504`; `backend/src/marko/services/market_collection.py:2115-2293` | This is the natural upstream record for a separate calibration result. Historical recommendation rows must not be rewritten. |
| Replay | `REPOSITORY_FACT`: network-free replay reconstructs the base recommendation and compares persisted outputs, including robust-dispersion v2 trace fields. | `backend/src/marko/services/recommendation_replay.py:58-151,201-324` | A later conformal replay can compose with this boundary, but conformal artifact/result replay does not yet exist. |
| Operator decisions | `REPOSITORY_FACT`: accepted/rejected/overridden decisions are append-only and persist the displayed recommendation snapshot. | `backend/src/marko/infrastructure/db/models.py:1506-1552`; `backend/src/marko/services/pricing_runs.py:1122-1198` | These are visibly post-recommendation labels and are feedback-contaminated for market-truth calibration. |
| API | `REPOSITORY_FACT`: 31 OpenAPI paths exist; pricing endpoints expose base recommendation, evidence, decisions, coefficient calibration, and replay. No conformal endpoint/schema exists. | `backend/src/marko/api/schemas/pricing.py`; `backend/src/marko/api/routers/v1/pricing.py` | Conformal fields require a separate nested contract; current fields cannot be relabeled. |
| UI | `REPOSITORY_FACT`: Flutter shows the existing scalar as “Качество данных” and a percentage/grade. | `frontend/lib/features/pricing/recommendations_page.dart:807-850` | The current label is safer than “probability,” but conformal coverage must be displayed in a separate component. |
| Auth/roles | `REPOSITORY_FACT`: Firebase bearer auth resolves a workspace; owner/admin are required for admin workflows. | `backend/src/marko/api/dependencies.py:23-76` | Activation/suspension roles are not modeled. |
| Tenant filters | `REPOSITORY_FACT`: recommendation/run/service reads bind `workspace_id`; unit tests inspect generated SQL for selected paths. | `backend/src/marko/services/pricing_runs.py:401-448,913-1120`; `backend/tests/test_tenant_authorization.py` | Useful baseline, but no conformal entities and no live cross-tenant integration test exist. |
| Workers | `REPOSITORY_FACT`: Celery separates collection and calculation queues with retry/idempotency controls. | `backend/src/marko/worker/tasks/pricing.py:30-169`; `backend/src/marko/worker/celery_app.py` | Candidate execution substrate exists; there is no conformal dataset/build/evaluation/shadow task. |
| Observability | `REPOSITORY_FACT`: pricing emits structured log events; scraper exposes Prometheus metrics and alerts. | `backend/src/metis/pricing/observability.py`; `backend/src/marko/services/scraper_metrics.py`; `deploy/prometheus-alerts.yml` | None of the required conformal coverage, width, drift, artifact, or abstention metrics exist. |
| Migrations | `REPOSITORY_FACT`: Alembic has one linear chain through `20260716_0009`; current pricing/evidence tables have append-only triggers. | `backend/migrations/versions/` | No target/example/manifest/artifact/evaluation/result tables or migrations exist. |
| Dependency stack | `REPOSITORY_FACT`: FastAPI 0.139.0, SQLAlchemy 2.0.51, Alembic 1.18.5, Celery 5.6.3, Pydantic 2.13.4, Python >=3.12. | `backend/pyproject.toml`; runtime version inspection | No NumPy/SciPy/scikit-learn/Hypothesis dependency is declared. M1/M2 can be implemented without them; M3/M4 need an explicit later dependency/model decision. |
| Source access | `REPOSITORY_FACT`: public Prom collection defaults to `NOT_PERMITTED` with empty reference and fails closed. | `backend/src/marko/services/source_access.py:16-76`; `.env.example`; `compose.yaml` | New real competitor outcomes cannot be assumed available. Persisted evidence and client-supplied data remain separate paths. |
| Version control | `REPOSITORY_FACT`: `git rev-parse` reports that the checkout is not a Git repository. | executed command | Required `code_commit` lineage is unavailable until a versioned checkout or immutable build identifier is provided. |
| Local data/runtime | `REPOSITORY_FACT`: no local `.env`, production `.env`, SQLite/CSV/Parquet dataset, Docker CLI, or `psql` is available in this audit environment. | executed commands | Dataset counts, live PostgreSQL constraints, real tenant isolation, and real outcome maturity cannot be measured now. |

### Audited code surface

```yaml
python_source_files: 74
backend_test_files: 28
alembic_revisions: 9
openapi_paths: 31
flutter_version: 3.44.4
dart_version: 3.12.2
```

---

# B. Existing recommendation flow

```text
immutable XLSX import batch
  -> CatalogItem rows scoped by workspace/import batch
  -> PricingRun + deduplicated ScrapeTarget + idempotent PricingRunItem
  -> source-access gate
  -> collection worker / persisted replay
  -> RawMarketCapture(content_sha256)
  -> MarketObservation
  -> append-only ObservationTierClassification
  -> run-level paired-OE coefficient dataset
  -> simple + shrinkage tier coefficient artifacts
  -> selected coefficient model
  -> metis.pricing.recommend_price(...)
  -> append-only PricingRecommendation + calculation_trace
  -> optional append-only RecommendationDecision
  -> network-free recommendation replay
```

`REPOSITORY_FACT`: the run status named `calibrating` currently means tier
coefficient calibration, not conformal calibration. A later implementation
must not silently overload that state.

`REPOSITORY_FACT`: the base recommendation is created and committed in the same
calculation service transaction. There is no post-persistence conformal
resolver or separate final-action record.

---

# C. Existing data lineage flow

| Lineage requirement | Current representation | Gap |
| --- | --- | --- |
| Catalog snapshot | `catalog_import_batches.id`, file content SHA-256, `catalog_snapshot_id` on recommendation | Adequate upstream identity; not a conformal dataset manifest. |
| Extraction identity | `ScrapeTarget.input_hash`, adapter version, content SHA-256 | Good input/content boundary. |
| Raw evidence | `RawMarketCapture` linked to run item and scrape target | No single `evidence_snapshot_id/hash` representing the full cohort used by one recommendation. |
| Structured evidence | `MarketObservation` linked to raw capture; evidence observation IDs on recommendation | Cohort identity is an ordered trace/list rather than a first-class immutable manifest. |
| Classification | Append-only classification rows with method version and override user | Replay chooses the latest classification at/before calculation time; usable but must be explicitly frozen for a calibration example. |
| Base estimator version | policy, parser, classifier, coefficient and replay contract versions | No immutable code/build commit; `pricing-v2` is a policy version, not the complete executable identity. |
| Point prediction | `recommended_price` and `fair_price` on `PricingRecommendation` | The target contract must specify which base value is `y_hat`; this cannot be inferred. |
| Outcome | `RecommendationDecision` only | Post-display operator decision is feedback-contaminated; no blind expert reference, future market reference, or matured commercial outcome entity exists. |
| Frozen dataset membership | tier-pair dataset hash only | No conformal example IDs, split assignment, inclusion policy, cutoff, or manifest. |
| Artifact identity | tier coefficient version/hash only | No conformal method/score/alpha/q-hat/applicability/validity artifact. |
| Runtime result | base recommendation only | No separate interval semantics, coverage status, abstention reasons, compatibility lineage, or final action. |

### Append-only reality

`REPOSITORY_FACT`: PostgreSQL triggers reject UPDATE/DELETE for raw captures,
market observations, tier classifications, pricing recommendations,
recommendation decisions, catalog overrides, tier calibration pairs, and tier
coefficients (`20260716_0005` and `20260716_0006`). This is a strong convention
for future conformal facts. The ORM alone does not enforce immutability; the
guarantee depends on migrations being applied to PostgreSQL.

---

# D. Existing status and enum map

## Recommendation and workflow statuses

```yaml
RecommendationAction:
  - RAISE
  - HOLD
  - LOWER
  - MANUAL_REVIEW
  - INSUFFICIENT_DATA

PricingRun.status:
  - queued
  - running
  - collecting
  - classifying
  - calibrating        # tier-coefficient calibration
  - calculating
  - completed
  - partial
  - failed
  - cancelled

PricingRunItem.status:
  - queued
  - collecting
  - collected
  - classified
  - calculating
  - calculated
  - manual_review      # also used when action is INSUFFICIENT_DATA
  - failed
  - cancelled

CoefficientModel:
  - simple_median
  - shrinkage

RobustScaleMethod:
  - legacy_mad
  - iqr
  - mad
  - sn
  - qn
```

## Missing conformal lifecycle

No first-class values exist for:

```yaml
calibration_mode_or_artifact_status:
  - disabled
  - shadow
  - candidate
  - active
  - suspended
  - retired

coverage_claim_status:
  - none
  - nominal_only
  - empirical_only
  - theoretically_eligible
  - validated_active
  - suspended_assumption_violation
```

## Current confidence fields

| Field | Actual semantics | Must not be presented as |
| --- | --- | --- |
| `PricingRecommendation.confidence` | Composite of coverage/evidence count, dispersion, freshness, match, tier, and source scores | probability that the price is correct; conformal coverage |
| `confidence_grade` | Thresholded grade of the same composite | statistical confidence level |
| `TierClassification.tier_confidence` | Rule/override classification score | target-label probability |
| `TierCoefficient.confidence` | Heuristic support/stability/quality minimum | conformal confidence |
| `lower_bound` / `upper_bound` | 25th and 75th percentiles of cleaned normalized market prices | target prediction interval |

The master prompt's `manual_review_required` maps conceptually to current
`MANUAL_REVIEW`, but historical enums must not be renamed without an explicit
compatibility/migration decision.

---

# E. Candidate integration points

The entries below are `ENGINEERING_ASSUMPTION`, not approved implementation
design.

| Layer | Candidate boundary | Constraint discovered by audit |
| --- | --- | --- |
| Metis math | A separate module/package next to `metis.pricing`, wrapping a frozen `PricingRecommendation` point output | Do not modify `recommend_price` or let calibration repair an upstream unsafe action. |
| Score contracts | New versioned absolute/log/normalized-log score interfaces | Do not reuse the tier-coefficient `calibration.py` semantics. |
| Persistence | New append-only target/example/manifest/artifact/evaluation/result entities following existing trigger convention | Must include workspace scope and a complete compatibility key. |
| Dataset building | Service over immutable recommendation/evidence/outcome records | Must not query a mutable “current valid rows” view as a dataset identity. |
| Runtime resolver | After base recommendation persistence, before exposing a conformal final decision in active mode | Base record must remain immutable; shadow mode must leave its action unchanged. |
| Worker | Separate dataset/evaluation/recalibration tasks and, if needed, a separate runtime result task | Existing `calibrating` state is already occupied by coefficient calibration. |
| Replay | Compose base replay with frozen conformal artifact + result replay | Must fail closed on code/artifact/target/version mismatch. |
| API | Add a separate `calibration` object and administrative lifecycle endpoints | Do not reuse `confidence`, `lower_bound`, `upper_bound`, or current `calibration_dataset_hash`. |
| UI | Add an uncertainty panel with target semantics, mode, claim status, width, evidence freshness, and reason-coded abstention | Keep the existing “Качество данных” score visually and semantically separate. |
| Metrics | Add dedicated low-cardinality conformal metrics and alerts | Existing metrics cover scraper operations, not statistical validity. |

---

# F. Conflicts with the proposed contract

| Conflict ID | Confirmed conflict | Severity | Required disposition before implementation |
| --- | --- | --- | --- |
| CF-001 | Exact `model_id` or `sku` equality returns match score `1.0` before brand/laterality checks. This contradicts the invariant that identifier equality alone does not prove commercial comparability. | CRITICAL for label/evidence eligibility | Strengthen upstream comparability contract or exclude affected rows from calibration until independently validated. |
| CF-002 | Product extraction has name/SKU/model/category ID/brand but no structured fitment, engine, side, condition, or package quantity contract. | CRITICAL | Define and persist these comparability dimensions or explicitly narrow the eligible population. |
| CF-003 | Existing `lower_bound/upper_bound` are market IQR bounds, not target prediction bounds. | HIGH | Add separately named conformal interval fields with explicit target semantics. |
| CF-004 | Existing `confidence` is a data-quality composite and is filterable in API/UI. | HIGH | Never populate it with nominal/empirical coverage; introduce `coverage_claim_status`. |
| CF-005 | `calibration`, `calibration_dataset_hash`, and run status `calibrating` already mean tier-coefficient calibration. | HIGH | Use explicit `conformal_*` or `uncertainty_*` names and document coexistence. |
| CF-006 | `RecommendationDecision` is created after the operator sees the recommendation. | CRITICAL | Permit it only as operator-alignment data unless an independent/blinded target protocol is created. |
| CF-007 | Recommendation lineage lacks an executable code commit/build identity because this checkout has no `.git`. | HIGH | Supply a Git-backed checkout or immutable build/source digest policy before artifact activation. |
| CF-008 | No dedicated evidence snapshot hash covers the exact recommendation cohort and classifications. | HIGH | Define deterministic snapshot canonicalization and hash before calibration examples are accepted. |
| CF-009 | Current item status collapses `INSUFFICIENT_DATA` into `manual_review` at workflow level. | MEDIUM | Preserve base action separately when deriving conformal final action and metrics. |
| CF-010 | No target, label maturity, split, drift, OOD, artifact lifecycle, or selective-abstention data model exists. | EXPECTED MISSING CAPABILITY | Implement only after Stage 1 target/statistical contract passes. |
| CF-011 | Default public competitor source access is `NOT_PERMITTED`. | EXTERNAL HARD GATE | Use only permitted client data/persisted evidence or obtain an auditable permission reference. |
| CF-012 | Live PostgreSQL, Redis, Celery, and deployment are unavailable in this host audit. | VALIDATION GAP | Repeat integration, tenancy, migration, concurrency, and rollback checks in the real stack. |

---

# G. Unknowns and blockers

## Confirmed unknowns

```yaml
primary_target: NOT_DECIDED
target_semantics: NOT_DECIDED
prediction_horizon: NOT_DECIDED
label_creation_policy: NOT_DECIDED
reviewer_blinding_policy: NOT_DECIDED
outcome_maturity_policy: NOT_DECIDED
alpha: NOT_DECIDED
evaluation_confidence_level: NOT_DECIDED
coverage_tolerance: NOT_DECIDED
minimum_evaluation_n: NOT_DECIDED
minimum_unique_group_count: NOT_DECIDED
maximum_useful_interval_width: NOT_DECIDED
acceptable_abstention_rate: NOT_DECIDED
runtime_mode: NOT_DECIDED
missing_calibrator_policy: NOT_DECIDED
artifact_staleness_window: NOT_DECIDED
segment_policy: NOT_DECIDED
cross_tenant_pooling: NOT_DECIDED_DEFAULT_DENY
activation_and_suspension_roles: NOT_DECIDED
operator_wording: NOT_DECIDED
rollback_policy: NOT_DECIDED
retention_policy: NOT_DECIDED
real_calibration_examples: NOT_AVAILABLE
real_independent_evaluation_dataset: NOT_AVAILABLE
```

## Blocker register

### BLK-CONF-001

- type: `BUSINESS_DECISION`
- description: no approved primary target definition exists.
- owner: product owner + statistical owner.
- evidence: no target contract/entity/file found in source, migrations, tests, or data.
- required resolution: approve a versioned target contract including semantics,
  independence, maturity, units, currency/VAT/shipping/quantity policies, and
  feedback-contamination policy.
- affected next stage: Stage 1 and every later stage.

### BLK-CONF-002

- type: `DATA_OR_SOURCE_BLOCKER`
- description: no independent target labels or matured evaluation outcomes are
  available in the checkout.
- owner: data owner + operations/review owner.
- evidence: no dataset files or outcome entities beyond post-display operator
  decisions.
- required resolution: create the approved label workflow and collect eligible,
  traceable outcomes.
- affected next stage: Stages 2, 3, 5, 9, 10.

### BLK-CONF-003

- type: `DATA_OR_SOURCE_BLOCKER`
- description: public Prom competitor collection is fail-closed as
  `NOT_PERMITTED` without an authorization reference.
- owner: source/data-rights owner.
- evidence: source access defaults and executed settings inspection.
- required resolution: approved feed/written authorization or a permitted
  client-supplied evidence path.
- affected next stage: real data collection and production evaluation.

### BLK-CONF-004

- type: `REPOSITORY_LINEAGE_BLOCKER`
- description: no Git commit is available for code lineage.
- owner: engineering/release owner.
- evidence: `git rev-parse` failed; no `.git` directory.
- required resolution: restore Git metadata or approve an immutable build/source
  fingerprint contract.
- affected next stage: artifact manifest, evaluation, activation, replay.

### BLK-CONF-005

- type: `UPSTREAM_DATA_QUALITY_BLOCKER`
- description: comparability does not implement every mandatory commercial gate
  and exact identifiers can bypass brand/laterality validation.
- owner: Metis domain owner.
- evidence: `backend/src/marko/services/matching.py:96-114` and parser field map.
- required resolution: repair/validate comparability or explicitly exclude the
  unsupported population before building calibration data.
- affected next stage: target validity, dataset builder, evaluation, activation.

### BLK-CONF-006

- type: `VALIDATION_ENVIRONMENT_BLOCKER`
- description: live PostgreSQL/Redis/Celery/deployment checks cannot run because
  Docker and `psql` are unavailable and no configured environment is present.
- owner: platform owner.
- evidence: executed environment checks.
- required resolution: run future migration, rollback, tenancy, concurrency, and
  recovery suites in the target stack.
- affected next stage: Stages 2, 7, 9, 10.

---

# STAGE RESULT

## 1. Stage

- stage_id: `0`
- stage_name: `REPOSITORY_AND_DATA_REALITY_AUDIT`
- terminal_status: `PASS`

Rationale: actual integration points, models, statuses, flows, dependencies,
tests, missing capabilities, conflicts, and blockers were identified from the
active checkout and executed checks. This PASS is an audit-completeness result,
not an implementation or production-readiness result.

## 2. Structured result

- Checked: repository layout, Metis/Marko ownership boundary, base pricing
  engine, coefficient calibration, evidence/classification lineage, money and
  status fields, migrations, API, auth/tenancy filters, workers, replay,
  observability, frontend semantics, dependencies, source gate, and tests.
- Created: this Stage 0 audit report.
- Changed: documentation only.
- Not changed: Python/Dart runtime code, API schemas, ORM models, migrations,
  deployment, configuration, database records, or calibration artifacts.
- Repository facts: recorded in sections A–F.
- Remaining assumptions: candidate integration points in section E only.

## 3. Mathematical result

```yaml
target:
  value: NOT_AVAILABLE
  reason: primary_target_not_approved
alpha:
  value: NOT_AVAILABLE
  reason: business_statistical_decision_missing
score:
  value: NOT_AVAILABLE
  reason: target_and_selection_contract_missing
n_fit:
  value: NOT_AVAILABLE
  reason: no_conformal_dataset
n_select:
  value: NOT_AVAILABLE
  reason: no_conformal_dataset
n_cal:
  value: NOT_AVAILABLE
  reason: no_conformal_dataset
n_eval:
  value: NOT_AVAILABLE
  reason: no_independent_evaluation_dataset
empirical_coverage:
  value: NOT_AVAILABLE
  reason: no_calibrator_or_evaluation_outcomes
wilson_lower_bound:
  value: NOT_AVAILABLE
  reason: no_empirical_coverage_count
interval_width:
  value: NOT_AVAILABLE
  reason: no_conformal_interval
abstention_rate:
  value: NOT_AVAILABLE
  reason: no_conformal_abstention_policy_or_shadow_run
coverage_claim_status: none
```

## 4. Evidence

### Files inspected

- `backend/src/metis/pricing/{types,engine,statistics,calibration,tiering,observability}.py`
- `backend/src/marko/infrastructure/db/models.py`
- `backend/src/marko/services/{market_collection,pricing_runs,recommendation_replay,matching,source_access,scraper_metrics}.py`
- `backend/src/marko/api/{dependencies,schemas/pricing,routers/v1/pricing}.py`
- `backend/src/marko/worker/celery_app.py`
- `backend/src/marko/worker/tasks/pricing.py`
- all nine Alembic revisions and migration configuration/history.
- backend test inventory, tenant/security/replay/pricing tests.
- Flutter pricing models, API, recommendation UI, and test inventory.
- backend/frontend dependency manifests, Compose files, alerts, and runbook.

### Files changed

- `docs/METIS_CONFORMAL_STAGE_0_AUDIT_2026-07-17.md`

### Tests and checks executed

```yaml
backend_pytest:
  command: PYTHONPATH=src .venv/bin/python -m pytest -q
  result: PASS
  tests: 323
  duration_seconds: 1.89
ruff:
  command: /opt/anaconda3/bin/ruff check backend/src backend/tests scripts
  result: PASS
python_compileall:
  command: python -m compileall -q backend/src backend/tests
  result: PASS
alembic_upgrade_static_sql:
  command: alembic upgrade head --sql
  result: PASS
  head: 20260716_0009
alembic_downgrade_static_sql:
  command: alembic downgrade 20260716_0009:base --sql
  result: PASS
flutter_test:
  command: flutter test
  result: PASS
  tests: 21
flutter_analyze:
  command: flutter analyze --no-pub
  result: TOOL_FAILURE
  detail: Dart_analysis_server_FormatException_while_parsing_truncated_LSP_JSON
  code_diagnostics_produced: false
```

### Dataset manifests

- conformal dataset manifests: none.
- existing tier coefficient dataset hashes: supported by code, but no live
  database records were available to enumerate.

### Artifact hashes

- master prompt SHA-256:
  `73421a7413deb26865abee42d60fff4f18f0339c856cb9d4251d74d04e6a4001`
- audited source/config/test tree fingerprint:
  `ca4ec8a5eefd3d43461005c53b851e6cdf3b370a96bbb4187c98519b3e4ef8f0`
- conformal artifact hashes: none.

### Reports

- this file.

## 5. Validation and variation

- happy path: base engine/API/replay/unit suite passes; schema imports and static
  migration SQL generation pass.
- boundary cases: existing tests cover low sample counts, unsafe statuses,
  versioned robust dispersion, source access, retries, replay drift, and selected
  tenant filters.
- adversarial cases: existing pricing matrix includes data-health, below-cost,
  outlier, duplicate, and conflicting-tier cases. It does not cover conformal
  leakage, target contamination, distribution shift, OOD, or artifact mismatch.
- variation matrix: the master prompt's conformal variation matrix has not been
  executed because no conformal implementation or approved target exists.
- reproducibility: the active source tree is fingerprinted and all backend tests
  are deterministic in this run; conformal replay is not available.
- unresolved failures: Flutter analyzer tool process fails before emitting code
  diagnostics; live infrastructure tests are unavailable.

## 6. Blockers

See `BLK-CONF-001` through `BLK-CONF-006` in section G. The first blocker alone
prevents Stage 1 from passing and prevents production implementation from
starting under the master contract.

## 7. Defects

### DEF-CONF-001

- severity: `CRITICAL`
- reproducibility: deterministic source path in `match_offer`.
- expected: exact identifiers remain subject to commercial comparability gates.
- actual: exact model/SKU equality returns score `1.0` before brand/laterality
  checks.
- proposed correction: handled in a separately authorized upstream
  comparability remediation; until then exclude these examples from calibration.

### DEF-CONF-002

- severity: `HIGH_SEMANTIC_COLLISION`
- reproducibility: deterministic engine/API schema inspection.
- expected: target interval and coverage have dedicated names and semantics.
- actual: generic `lower_bound`, `upper_bound`, `confidence`, and `calibration`
  names already represent unrelated concepts.
- proposed correction: additive, explicitly conformal contracts; no historical
  field reinterpretation.

### DEF-CONF-003

- severity: `MEDIUM_TOOLING`
- reproducibility: repeated twice with Flutter 3.44.4 / Dart 3.12.2.
- expected: `flutter analyze --no-pub` emits diagnostics and exits normally.
- actual: analysis server exits 255 with `FormatException: Unexpected end of
  input` while parsing its LSP initialization JSON.
- proposed correction: reproduce from a path/toolchain environment accepted by
  the analysis server or update/fix the local Flutter toolchain; no source defect
  was identified by this failed command.

## 8. Claims that are NOT allowed

Current evidence does not permit claiming that:

- a conformal calibration or abstention layer is implemented;
- any target has nominal, theoretical, empirical, conditional, or accepted-set
  coverage;
- current `lower_bound/upper_bound` are prediction intervals;
- current `confidence` is a probability or coverage value;
- operator-approved prices are market truth or independent labels;
- synthetic or unit-test cases demonstrate production performance;
- the current repository has an independent fit/select/calibration/evaluation
  split;
- tenant isolation is integration-validated for future conformal entities;
- migrations were executed forward/backward on a live PostgreSQL instance;
- a permitted real competitor source or matured outcome dataset exists;
- Stage 0 PASS means conformal implementation, activation, or system-wide
  production readiness.

## 9. Next permitted part

- next_stage: `1 — TARGET_AND_STATISTICAL_DESIGN_CONTRACT`
- prerequisites:
  - a new direct user authorization issued after this Stage 0 result;
  - explicit client decisions D1–D20 from the master prompt;
  - at minimum, an approved primary target choice before Stage 1 can pass;
  - agreement that post-display operator decisions are alignment data only,
    unless an independent/blinded protocol proves otherwise.
- direct user authorization required: `true`

No runtime implementation, migration, dataset builder, conformal core, or
abstention policy is permitted before the Stage 1 stop-gate passes.

## 10. Stop confirmation

The agent stopped after the Stage 0 stop-gate. Stage 1 was not started. No
implementation code, migrations, schemas, database state, API behavior, or UI
behavior were changed.
