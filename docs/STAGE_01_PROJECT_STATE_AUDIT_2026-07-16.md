# Stage 01 — Project State Audit: Marko / Metis

Дата аудита: 2026-07-16

Режим: analysis only; product implementation code не изменялся

Объекты аудита:

- `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha/metis`
- `/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия`
- существующие Prom extraction components в обеих кодовых базах

## 1. Прямой вывод

[FACT_FROM_REPO] Marko уже содержит рабочий вертикальный срез продукта: FastAPI,
PostgreSQL-модели и миграции, Celery/Redis orchestration, Firebase authentication,
workspace-scoped queries, XLSX catalog snapshots, black-box wrapper вокруг
существующего Prom parser, raw evidence journal, replay, tier classification,
KEMP-normalized pricing engine, immutable recommendations, operator decisions и
Flutter workflow.

[FACT_FROM_REPO] Metis содержит более раннее и более строго сформулированное
evidence/data ядро: string-preserving catalog import, SQLite data spine,
append-only market observations и classifications, raw-before-parse filesystem
captures, hash verification, offline replay, owned-seller registry, Stage-0
validator и официальный own-cabinet Prom API client. При этом runtime
matching/pricing engine, product API, UI, distributed jobs и production
deployment в Metis не реализованы.

[FACT_FROM_REPO] Текущие документы Marko считают `pricing` собственным
детерминированным ядром (`docs/architecture.md:17-28`) и одновременно называют
Marko «репозиторной реализацией Metis» (`docs/metis.md:22-28`). Это противоречит
целевому ownership-контракту, где Metis обязан владеть evidence и recommendation
kernel, а Marko является product shell/reference.

[FACT_FROM_REPO] Существенная часть будущих Stage 03, 04, 07, 08 и 09 уже
реализована в Marko до формального завершения Stage 02. Эту работу нельзя
игнорировать или переписывать с нуля; Stage 02 должен классифицировать её как
`reuse`, `move`, `adapt` или `retire`.

[SOURCE_ACCESS_BLOCKER] Систематический сбор competitor offers с публичных
Prom.ua страниц остаётся `NOT_PERMITTED` по текущему project gate. На
2026-07-16 повторная проверка официальных источников не обнаружила competitor
market-data endpoint в public API и не сняла ограничения, зафиксированные в
локальном gate. Инженерная оценка не является юридической консультацией.

[FACT_FROM_REPO] Локальные тестовые поверхности проходят, но live
PostgreSQL/Redis/Celery, failure injection, sustained load, backup/restore и
production deployment в этом аудите не были доказаны. Docker отсутствует в
текущем окружении.

[FACT_FROM_REPO] Итоговая зрелость:

```text
Metis = research/data/evidence kernel prototype
Marko = advanced pre-pilot product vertical slice
Combined target = NOT_READY for production
```

## 2. Universal Stage Output Contract

```yaml
stage_id: S01
status: REVIEW_REQUIRED
readiness_score: 0.94
repo_facts:
  - "Both codebases and the existing scraper boundaries were inspected."
  - "Marko has substantially more implemented runtime capability than Metis STATUS.md."
  - "Metis has the stronger explicit source gate and append-only evidence baseline."
  - "Marko and Metis currently duplicate or contradict pricing/evidence ownership."
engineering_assumptions:
  - "Existing Marko pricing/evidence code should be adapted under Metis ownership, not discarded."
  - "A clean product boundary can be introduced without changing parser internals."
business_decisions_required:
  - "Approve the Metis/Marko ownership and migration matrix."
  - "Approve source-access path, pricing scope, tenant roles, throughput SLO, retention, RPO/RTO."
source_access_or_policy_blockers:
  - "No permitted systematic Prom.ua competitor-offer source is recorded."
  - "The owner-risk scraper implementation does not change the permission verdict."
future_hypotheses:
  - "Marko pricing modules can become a Metis-owned Python package or service."
  - "Object storage may replace PostgreSQL raw blobs after measured retention sizing."
artifacts_created_or_required:
  - "This Stage 01 audit."
  - "Required next: Stage 02 C4 views, ownership matrix, ADRs, integration contracts, migration map."
tests_or_validation_required:
  - "Live Postgres/Redis/Celery integration and redelivery tests."
  - "Controlled scraper load series at multiple concurrency levels."
  - "Cross-tenant authorization tests."
  - "Full recommendation replay test without network."
  - "Backup restore and rollback drill."
production_risks:
  - "Source permission, duplicated ownership, missing DLQ, unproven load, tenant/RBAC gaps, no restore proof."
next_stage_input_contract:
  - "Evidence inventory and gap register from this document."
  - "Owner decisions listed in section 10."
  - "Explicit rule: do not redesign parser without a reproducible defect."
go_no_go: "GO to Stage 02 review/design; NO-GO for production claim or automatic publishing."
```

## 3. Stage 01 readiness calculation

[ENGINEERING_ASSUMPTION] `readiness_score` measures completeness of this audit,
not product production readiness.

Hard gates:

| Hard gate | Value | Evidence |
|---|---:|---|
| Repository roots and component boundaries located | 1 | [FACT_FROM_REPO] Both trees and parser paths were inspected. |
| Existing capabilities verified from code, not README alone | 1 | [FACT_FROM_REPO] API, ORM, workers, parser boundary, pricing, frontend and Metis data spine were read. |
| Validation evidence attached | 1 | [FACT_FROM_REPO] Python, Dart/Flutter, OpenAPI and migration checks are listed in section 13. |
| Blockers classified | 1 | [FACT_FROM_REPO] Source, ownership, runtime, tenant and operations blockers are separated below. |
| Next-stage input contract prepared | 1 | [FACT_FROM_REPO] Section 16 defines the Stage 02 inputs and stop conditions. |

Soft score:

| Dimension | Weight | Score | Contribution |
|---|---:|---:|---:|
| Repository topology and provenance | 0.15 | 0.80 | 0.1200 |
| Metis capability audit | 0.20 | 1.00 | 0.2000 |
| Marko capability audit | 0.25 | 1.00 | 0.2500 |
| Scraper boundary/scaling audit | 0.15 | 0.95 | 0.1425 |
| Executable validation evidence | 0.15 | 0.90 | 0.1350 |
| Blocker and next-input classification | 0.10 | 0.95 | 0.0950 |
| **Total** | **1.00** |  | **0.9425** |

[ENGINEERING_ASSUMPTION] Rounded Stage 01 readiness is `0.94`.

[FACT_FROM_REPO] Status remains `REVIEW_REQUIRED`, rather than `PASS`, until the
owner accepts or corrects the ownership facts and decision register. No missing
Stage 01 evidence forces `BLOCKED`.

## 4. Repository topology and reproducibility

[FACT_FROM_REPO] The active Git root is
`/Users/leonidpofa/VSCodeHruchevoPY/SaaS/metis_alpha`, branch `main`, last
visible commit `9ea24b0`.

[FACT_FROM_REPO] The Git working tree records the old root layout as deleted and
the new `metis/` and `marko/` trees as untracked. The separate
`/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия` tree has no
`.git` directory.

[FACT_FROM_REPO] Therefore the exact audited combined state is not reproducible
from the current commit alone.

[ENGINEERING_ASSUMPTION] Before an implementation stage changes ownership or
moves code, the split should be normalized into one explicitly chosen Git
topology and committed without losing unrelated local work.

## 5. A — Ready / partial / missing

### 5.1 Ready at code/test level

| Capability | Verdict | Evidence |
|---|---|---|
| Existing parser treated as black box | Ready | [FACT_FROM_REPO] Marko freezes parser internals behind `scraper_contract.py`; `docs/architecture.md:47-50` places scaling around it. |
| Scraper input/output boundary | Ready | [FACT_FROM_REPO] Strict Prom URL validation, canonical input hash, versioned deterministic output and typed errors exist in `scraper_contract.py:35-174`. |
| Retry and attempt taxonomy | Ready | [FACT_FROM_REPO] Logical requests and physical attempts are separate; retryable and terminal outcomes are persisted. |
| Queue worker separation | Ready | [FACT_FROM_REPO] Celery routes store sync, collection and pricing calculation to separate queues; late ack, worker-loss rejection and prefetch 1 are configured in `worker/celery_app.py:20-34`. |
| Scraper capacity mathematics | Ready as code | [FACT_FROM_REPO] Retry amplification, reconciliation, multi-bottleneck capacity, utilization, drain time and benchmark acceptance contracts exist. |
| Catalog snapshot import | Ready as code | [FACT_FROM_REPO] XLSX identifiers remain strings, leading zeroes are tested, duplicate SKU is explicit, row lineage/raw row and file limits exist. |
| Raw evidence and observations | Ready as code | [FACT_FROM_REPO] Content-addressed raw HTTP blobs, logical requests, attempts, raw captures, observations and append-only classifications exist. |
| Deterministic pricing function | Ready as code | [FACT_FROM_REPO] `recommend_price` has no HTTP/ORM/queue/global-state dependency and enforces abstention and direction invariants. |
| Recommendation journal | Ready as code | [FACT_FROM_REPO] Recommendation rows store context, calculation trace, evidence IDs, versions, reasons, excluded observations and calibration hash. |
| Operator review workflow | Ready as code | [FACT_FROM_REPO] Flutter displays recommendation, confidence, evidence, excluded cohort and data health; accept/reject/override and tier override paths exist. |
| Authentication token verification | Ready as code | [FACT_FROM_REPO] Firebase RS256 signature, key ID, issuer, audience, time and verified-email claims are checked. |

### 5.2 Partial

| Capability | Verdict | Gap |
|---|---|---|
| Metis evidence kernel | Partial | [FACT_FROM_REPO] Strong local append-only/replay spine exists, but it is SQLite/filesystem-based and not integrated with Marko runtime. |
| Official owned-store Prom API | Partial | [FACT_FROM_REPO] Read and gated write client exists in Metis, but no live token test, DB mapping, scheduler or product integration exists. |
| Matching/comparability | Partial | [FACT_FROM_REPO] Marko has hard exclusions, confidence and tier rules, but no accepted labelled evaluation set with precision/recall/error report. |
| Pricing engine | Partial | [FACT_FROM_REPO] Implementation is extensive, but policy decisions and real-data calibration/shadow validation are not approved. |
| Full recommendation replay | Partial | [FACT_FROM_REPO] Raw HTTP replay and deterministic calculation exist; an audited end-to-end command/test reconstructing an exact stored recommendation without network was not found. |
| Scraper production capacity | Partial | [FACT_FROM_REPO] Metrics and benchmark evaluator exist; no controlled live concurrency series proves a production worker count or `rho <= 0.70`. |
| Observability | Partial | [FACT_FROM_REPO] JSON and Prometheus metric endpoints exist, but no deployed collector, dashboard, alerts, traces or error tracking were found. |
| Tenant isolation | Partial | [FACT_FROM_REPO] Queries are workspace-scoped, but role enforcement, workspace selection and adversarial cross-tenant tests are absent. |
| Deployment | Partial | [FACT_FROM_REPO] Development Compose and Dockerfiles exist; production secrets, TLS/ingress, hardened process settings and environment separation do not. |

### 5.3 Missing or not demonstrated

| Capability | Verdict | Evidence |
|---|---|---|
| Dedicated DLQ and operator replay flow | Missing | [FACT_FROM_REPO] Terminal failure rows exist, but no separately routed dead-letter queue or DLQ replay command/API was found. |
| Accepted Metis/Marko ownership package | Missing | [FACT_FROM_REPO] Current Marko docs claim ownership that conflicts with the target prompt. |
| Permitted competitor source | Missing | [SOURCE_ACCESS_BLOCKER] No official competitor feed, written Prom authorization or sufficient client-provided lawful feed is recorded. |
| Production labelled matching set | Missing | [FACT_FROM_REPO] No repository artifact proves agreed precision/recall thresholds on representative real offers. |
| Shadow-mode/pilot report | Missing | [FACT_FROM_REPO] No operator agreement, false-positive, abstention or calibration report was found. |
| Cross-tenant security suite | Missing | [FACT_FROM_REPO] Test search found workspace-scoped unit/API use but no explicit cross-tenant denial matrix. |
| Backup restore proof | Missing | [FACT_FROM_REPO] No backup policy, restore script/report, RPO/RTO or restore drill artifact was found. |
| Rollback/incident runbook | Missing | [FACT_FROM_REPO] No production rollback checkpoint or incident runbook was found. |
| Clean committed split | Missing | [FACT_FROM_REPO] The current audited topology is not represented by a clean commit. |

## 6. B — Metis readiness map

[ENGINEERING_ASSUMPTION] Scores below estimate current capability coverage on
`0..1`; they are not probability of success and do not override hard gates.

| Metis capability | Weight | Score | Evidence-backed assessment |
|---|---:|---:|---|
| Data spine/foundation | 0.15 | 0.80 | [FACT_FROM_REPO] SQLite schema, append-only guards, current-classification view and tests exist. |
| Catalog/product identity | 0.12 | 0.70 | [FACT_FROM_REPO] String-preserving importer and OE/MPN separation exist; real duplicate-SKU policy remains unresolved. |
| Source access | 0.15 | 0.15 | [SOURCE_ACCESS_BLOCKER] Owned-cabinet path is possible, competitor evidence path is blocked. |
| Raw evidence/replay | 0.15 | 0.75 | [FACT_FROM_REPO] Raw-before-parse, SHA-256 and offline replay exist; distributed storage/retention is not productionized. |
| Matching/comparability | 0.12 | 0.20 | [FACT_FROM_REPO] Requirements and normalizers exist; production classifier/evaluation is listed as not implemented. |
| Pricing/recommendation runtime | 0.15 | 0.15 | [FACT_FROM_REPO] Schema/specs exist; Metis runtime engine is listed as not implemented. |
| API/jobs/UI | 0.10 | 0.05 | [FACT_FROM_REPO] Product runtime surfaces are absent. |
| Production operations | 0.06 | 0.05 | [FACT_FROM_REPO] Deployment and monitoring are listed as absent. |
| **Weighted capability score** | **1.00** |  | **0.39** |

[FACT_FROM_REPO] Metis is strongest in evidence invariants and project truth,
not in deployable product runtime.

## 7. C — Marko readiness map

[ENGINEERING_ASSUMPTION] The scraper score blends implemented code with missing
operational capacity proof; a code-only score would be higher and misleading.

| Marko capability | Weight | Score | Evidence-backed assessment |
|---|---:|---:|---|
| Product/backend shell | 0.10 | 0.80 | [FACT_FROM_REPO] FastAPI, PostgreSQL, migrations, Celery, Redis and modular boundaries exist. |
| Catalog/product identity | 0.10 | 0.85 | [FACT_FROM_REPO] Immutable import batch, row lineage, identifiers and explicit duplicate handling exist. |
| Scraper scaling | 0.15 | 0.65 | [FACT_FROM_REPO] Boundary, queues, retries, fencing, persistence and metrics exist; load proof and DLQ do not. |
| Evidence/lineage | 0.12 | 0.80 | [FACT_FROM_REPO] Raw blobs, requests, attempts, captures, observations and recommendation evidence references exist. |
| Matching/comparability | 0.10 | 0.55 | [FACT_FROM_REPO] Deterministic gates exist; representative labelled evaluation is absent. |
| Pricing/recommendations | 0.15 | 0.75 | [FACT_FROM_REPO] Robust deterministic engine and journal exist; real policy/calibration/pilot acceptance is absent. |
| API/jobs | 0.10 | 0.82 | [FACT_FROM_REPO] Catalog/pricing/job/review endpoints and async workers exist. |
| Frontend/operator workflow | 0.08 | 0.78 | [FACT_FROM_REPO] Evidence-first recommendation UI and operator actions exist; full status taxonomy/pilot UX is incomplete. |
| Auth/tenant security | 0.06 | 0.50 | [FACT_FROM_REPO] Strong token verification and workspace filters exist; RBAC/cross-tenant proof is missing. |
| Production operations | 0.04 | 0.30 | [FACT_FROM_REPO] Dev containers and basic probes exist; production hardening/restore/alerts are absent. |
| **Weighted capability score** | **1.00** |  | **0.71** |

[FACT_FROM_REPO] `0.71` means broad pre-pilot feature coverage, not production
readiness.

[FACT_FROM_REPO] Production hard gates contain zeros for source access, DLQ,
ownership split, tenant proof and restore. Therefore, under the prompt formula:

```text
ProductionReadiness = min(H_production) × weighted_capability
                    = 0 × weighted_capability
                    = 0
production_status   = BLOCKED / NOT_READY
```

## 8. Existing scraper scaling assessment

[FACT_FROM_REPO] No reproducible parser defect was found during Stage 01.
Parser internals should remain frozen.

| Required Stage 03 output | Current state | Assessment |
|---|---|---|
| Stable input contract | Implemented | [FACT_FROM_REPO] Canonical Prom product URL, normalized query, version and input hash. |
| Stable output contract | Implemented | [FACT_FROM_REPO] Versioned deterministic JSON payload, structured hash, sizes and completeness. |
| Batch/job/item/attempt states | Implemented across run/item/target/task/request/attempt models | [FACT_FROM_REPO] Units are separated rather than conflated. |
| Persistent queue | Implemented through Celery/Redis plus PostgreSQL state | [FACT_FROM_REPO] Broker messages are not the sole source of truth. |
| Worker model | Implemented | [FACT_FROM_REPO] Store sync, collection and calculation queues/workers exist. |
| Retry/backoff/jitter | Implemented | [FACT_FROM_REPO] HTTP and task retry budgets are bounded; deadlines and circuit state exist. |
| Idempotency/fencing | Implemented as code | [FACT_FROM_REPO] Input hashes, unique constraints, leases and execution fencing exist. |
| Dead-letter queue | Not implemented as a distinct queue | [FACT_FROM_REPO] DB terminal-failure journal is useful but does not satisfy the explicit DLQ contract. |
| Raw/structured storage | Implemented | [FACT_FROM_REPO] Compressed raw evidence and structured captures are persisted. |
| Metrics | Implemented as API/Prometheus exposition | [FACT_FROM_REPO] Required counts, latency, retry, queue, worker and resource metrics are represented. |
| Load-test protocol | Implemented as evaluator contract | [FACT_FROM_REPO] Acceptance model requires comparable concurrency levels, fingerprints and zero silent loss. |
| Load-test execution | Not demonstrated | [FACT_FROM_REPO] No production capacity series or selected concurrency artifact exists. |

[FACT_FROM_REPO] The implementation correctly avoids a common mathematical
error: terminal worker time already includes retry/redelivery cost, so retry
amplification is not divided into throughput a second time
(`scraper_scaling.py:1-13`, `214-313`, `363-392`).

[BUSINESS_DECISION_REQUIRED] A required throughput and latency SLO must be
defined before the benchmark evaluator can return a production worker count.
At minimum:

```text
N_batch
maximum batch completion time
arrival profile lambda(t)
minimum successful throughput
success-rate floor
L95 / L99 limits
maximum HTTP attempts per item
source and database utilization budgets
infrastructure budget
```

## 9. D — Critical production gaps

| Priority | Gap | Why it blocks |
|---|---|---|
| P0 | Permitted competitor evidence source | [SOURCE_ACCESS_BLOCKER] Without it, real competitor-backed pricing cannot be described as an authorized production capability. |
| P0 | Metis/Marko ownership conflict | [FACT_FROM_REPO] Two competing kernels violate Stage 02 and make migrations, versioning and audit ownership ambiguous. |
| P0 | No dedicated DLQ/replay workflow | [FACT_FROM_REPO] Retry exhaustion is persisted, but explicit Stage 03/production self-audit requirement 6 is not met. |
| P0 | No accepted matching evaluation | [FACT_FROM_REPO] Tests prove examples, not agreed production precision/recall on representative evidence. |
| P0 | No shadow/pilot validation | [FACT_FROM_REPO] Correctness, operator agreement, coverage and false-positive rates are unknown on permitted real data. |
| P0 | Tenant/RBAC proof absent | [FACT_FROM_REPO] Roles are stored but not enforced; cross-tenant denial tests do not exist. |
| P0 | Restore not demonstrated | [FACT_FROM_REPO] Stage 11 hard gate and final self-audit item 10 fail. |
| P0 | Scraper capacity not measured live | [FACT_FROM_REPO] Mathematical and telemetry code exists, but production `c`, `C`, `rho` and `T_drain` are unknown. |
| P1 | Recommendation status contract mismatch | [FACT_FROM_REPO] Marko actions are `RAISE/HOLD/LOWER/MANUAL_REVIEW/INSUFFICIENT_DATA`; `stale_data`, `conflict`, `blocked` are reason/context states, not first-class statuses. |
| P1 | Pricing scope divergence | [FACT_FROM_REPO] Marko supports downward clearance, while Metis still records upward-only approval as unresolved. |
| P1 | Official own-cabinet API not integrated | [FACT_FROM_REPO] Client exists only in Metis and has not been live-verified or mapped into the product data spine. |
| P1 | Production security hardening | [FACT_FROM_REPO] API docs remain public, TrustedHost/security headers/rate limits are absent, CORS methods/headers are wildcarded. |
| P1 | Readiness is incomplete | [FACT_FROM_REPO] `/ready` checks PostgreSQL only, not Redis/broker, worker availability or required external dependencies. |
| P1 | Observability is not deployed | [FACT_FROM_REPO] Metric exposition exists; collection, dashboards, alert rules, traces and on-call ownership do not. |
| P1 | Repository split is uncommitted | [FACT_FROM_REPO] The audited state cannot be rebuilt from the current commit. |
| P1 | Documentation drift | [FACT_FROM_REPO] Marko documents mix historical gaps, current implementation claims and a conflicting Metis ownership definition. |

## 10. E — Client/business decisions required

1. [BUSINESS_DECISION_REQUIRED] Approve the target ownership form:
   Metis Python package embedded in Marko, separately deployed Metis service, or
   a staged package-first/service-later strategy.
2. [BUSINESS_DECISION_REQUIRED] Approve the source path: official Prom
   authorization/feed, lawful client/third-party export, or a reduced product
   without systematic competitor collection.
3. [BUSINESS_DECISION_REQUIRED] Approve pricing scope: upward-only adviser or
   upward plus stale/dead-stock clearance.
4. [BUSINESS_DECISION_REQUIRED] Approve target stores and stable owned-seller
   identities, including which Prom cabinets receive official API tokens.
5. [BUSINESS_DECISION_REQUIRED] Approve pricing policy: minimum cohort,
   effective sample, freshness, confidence, coefficient validation, threshold,
   step cap, price tick/rounding and cost-floor behavior.
6. [BUSINESS_DECISION_REQUIRED] Approve operator roles and permissions:
   owner/admin/member capabilities, workspace switching, review, override,
   below-cost approval and audit access.
7. [BUSINESS_DECISION_REQUIRED] Approve scraper SLO and infrastructure budget:
   batch size, deadline, arrival profile, capacity, latency and error budget.
8. [BUSINESS_DECISION_REQUIRED] Approve raw evidence retention, deletion/legal
   hold, encryption, storage tier and maximum monthly storage budget.
9. [BUSINESS_DECISION_REQUIRED] Approve RPO, RTO, backup frequency, restore
   owner and rollback acceptance criteria.
10. [BUSINESS_DECISION_REQUIRED] Approve pilot success metrics: automatic-match
    precision, actionable coverage, abstention range, operator agreement and
    maximum P0/P1 correctness failures.

## 11. Security and tenant assessment

### Strong controls already present

- [FACT_FROM_REPO] Firebase JWT verification is algorithm-pinned to RS256 and
  validates key ID, signature, audience, issuer, expiration-related claims,
  authentication time and verified email.
- [FACT_FROM_REPO] Business routes depend on authenticated `CurrentUser`.
- [FACT_FROM_REPO] Stores, jobs, catalog, pricing runs, recommendations,
  evidence and metrics are queried with `workspace_id`.
- [FACT_FROM_REPO] XLSX upload parsing has compressed/decompressed size, row and
  column limits.
- [FACT_FROM_REPO] Scraper product input is restricted to canonical Prom hosts
  and product paths before network use.

### Controls not ready for production

- [FACT_FROM_REPO] `WorkspaceRole` is persisted, but no route-level permission
  enforcement was found.
- [FACT_FROM_REPO] Authentication selects the first workspace membership;
  explicit workspace selection and membership/role verification per selected
  workspace are absent.
- [FACT_FROM_REPO] No cross-tenant test matrix proves that IDs from workspace B
  are rejected for a user in workspace A.
- [FACT_FROM_REPO] `/docs` and `/redoc` are always enabled.
- [FACT_FROM_REPO] Trusted host validation and standard security-header
  middleware were not found.
- [FACT_FROM_REPO] CORS origins are configured, but credentials are enabled with
  wildcard methods and headers.
- [FACT_FROM_REPO] Application/API rate limiting and tenant/job quotas were not
  found.
- [FACT_FROM_REPO] The production image does not explicitly declare a non-root
  user, worker/process limits or graceful timeout policy.
- [FACT_FROM_REPO] No production secret manager, TLS/ingress policy, key
  rotation runbook or environment-separation artifact was found.
- [FACT_FROM_REPO] A bounded filename scan found only `.env.example` placeholders,
  but a dedicated repository secret scanner was not run; therefore “no secrets
  in repo” is not yet proven as a production gate.

## 12. Final production self-audit

| # | Required check | Verdict | Evidence |
|---:|---|---|---|
| 1 | Raw evidence lineage for every recommendation | PARTIAL/PASS_CODE | [FACT_FROM_REPO] Marko recommendations reference observation IDs and versioned traces; full live integrity was not exercised. |
| 2 | Replay recommendation without network | PARTIAL | [FACT_FROM_REPO] Raw replay and pure deterministic engine exist; exact end-to-end stored-recommendation replay was not demonstrated. |
| 3 | Abstention instead of invented price | PARTIAL/PASS_CODE | [FACT_FROM_REPO] Manual review and insufficient data suppress price; full requested status taxonomy is not first-class. |
| 4 | Scraper scaled as queue/worker/storage system | PARTIAL | [FACT_FROM_REPO] Architecture exists; load/capacity proof does not. |
| 5 | Idempotency for batch/item/attempt/job | PARTIAL/PASS_CODE | [FACT_FROM_REPO] Constraints, hashes and fencing exist; live redelivery/failure-injection proof is absent. |
| 6 | DLQ and retry taxonomy | FAIL | [FACT_FROM_REPO] Retry taxonomy exists; distinct DLQ/replay workflow does not. |
| 7 | Metis kernel separated from Marko shell | FAIL | [FACT_FROM_REPO] Current docs/code ownership is duplicated and contradictory. |
| 8 | Tenant isolation protected | FAIL | [FACT_FROM_REPO] Workspace filters exist, but RBAC and cross-tenant tests do not. |
| 9 | Operator audit log | PARTIAL/PASS_CODE | [FACT_FROM_REPO] Recommendation decisions and overrides are append-only records; permission model is incomplete. |
| 10 | Restore test and rollback | FAIL | [FACT_FROM_REPO] No demonstrated restore or rollback artifact exists. |

[FACT_FROM_REPO] Because at least one item fails:

```text
production_status = NOT_READY
```

## 13. Validation evidence

Executed from the audited working copies on 2026-07-16:

| Surface | Command | Result |
|---|---|---|
| Marko backend tests | `PYTHONPATH=src .venv/bin/python -m pytest -q` | [FACT_FROM_REPO] `234 passed in 3.36s` |
| Marko backend lint | `uv run --frozen --group dev ruff check src tests` | [FACT_FROM_REPO] `All checks passed` |
| Marko lock consistency | `uv lock --check` | [FACT_FROM_REPO] lock resolved without changes |
| Marko bytecode/OpenAPI | `compileall` plus `app.openapi()` | [FACT_FROM_REPO] success; 27 OpenAPI paths |
| Marko migrations upgrade | Alembic PostgreSQL offline `upgrade head --sql` | [FACT_FROM_REPO] revisions `0001` through `0009` generated successfully |
| Marko migrations downgrade | Alembic PostgreSQL offline `downgrade head:base --sql` | [FACT_FROM_REPO] reverse chain generated successfully |
| Metis tests | `PYTHONPATH=. .venv/bin/python -m pytest -q` | [FACT_FROM_REPO] `61 passed in 0.72s` |
| Metis lint | `PYTHONPATH=. .venv/bin/python -m ruff check metis tests` | [FACT_FROM_REPO] `All checks passed` |
| Flutter tests | `flutter test --no-pub` | [FACT_FROM_REPO] `19 tests passed` |
| Dart analysis | `dart analyze lib test` | [FACT_FROM_REPO] `No issues found` |
| Dart formatting | `dart format --output=none --set-exit-if-changed lib test` | [FACT_FROM_REPO] 41 files checked, 0 changed |

[FACT_FROM_REPO] Not executed:

- live Docker Compose stack;
- real PostgreSQL migrations against a server;
- Redis/Celery redelivery and worker-loss experiment;
- live scraper load series;
- real Prom competitor collection;
- production web build/deployment;
- backup restore or rollback drill.

[FACT_FROM_REPO] Docker, `psql`, `redis-server` and `celery` executables were not
available in the host environment; Flutter and Dart were available.

## 14. Source-access status

[SOURCE_ACCESS_BLOCKER] Local Metis records
`PERMISSIBILITY_VERDICT: NOT_PERMITTED`
(`fixtures/stage0/SOURCE_ACCESS.md:1-10`) and states that the official API is
appropriate only for the authenticated company's own cabinet
(`docs/06_integrations/prom_ua.md:34-40`, `61-74`).

[SOURCE_ACCESS_BLOCKER] Official sources rechecked on 2026-07-16:

- [Prom.ua User Agreement](https://prom.ua/ua/terms-of-use) — the current
  marketplace agreement still contains the automated/equivalent collection
  restriction used by the project gate.
- [Prom.ua robots.txt](https://prom.ua/robots.txt) — wildcard rules still
  disallow search and general query routes; robots rules do not themselves grant
  permission.
- [Prom.ua public API](https://public-api.docs.prom.ua/) — documented routes are
  own-cabinet domains; no competitor search/offers route was found.

[FACT_FROM_REPO] ADR-0004 records an owner accepted-risk implementation choice,
but explicitly says it does not grant platform permission
(`docs/decisions/ADR-0004-competitor-collection-decoupled-scraping-accepted-risk.md:20-38`,
`109-121`).

[ENGINEERING_ASSUMPTION] Architecture work, offline fixtures, replay,
own-cabinet integration and synthetic load tooling can continue without
performing new competitor collection. Production evidence collection remains a
separate source/authorization decision.

## 15. F — Maturity verdict

[FACT_FROM_REPO] Metis is closer to a **research/data/evidence kernel** than to
production SaaS.

[FACT_FROM_REPO] Marko is closer to an **advanced pre-pilot SaaS vertical
slice** than to a reference skeleton, but it is not production-ready.

[FACT_FROM_REPO] The combined project is not the sum of `0.39 + 0.71`.
Overlapping ownership, different storage/runtime assumptions and contradictory
policy documents create integration debt.

[ENGINEERING_ASSUMPTION] The shortest safe path is:

```text
accept Stage 01 facts
  -> Stage 02 ownership and integration contracts
  -> preserve existing parser
  -> move/adapt Marko evidence + pricing under Metis ownership
  -> close Stage 03 operational proof and DLQ
  -> validate matching/pricing on permitted evidence
  -> close tenant/security/restore gates
  -> shadow pilot
```

## 16. Stage 02 input contract

Required inputs:

1. [FACT_FROM_REPO] This inventory of implemented components and gaps.
2. [BUSINESS_DECISION_REQUIRED] Selected Metis deployment/packaging boundary.
3. [BUSINESS_DECISION_REQUIRED] Accepted pricing direction and policy owner.
4. [BUSINESS_DECISION_REQUIRED] Source-access strategy.
5. [BUSINESS_DECISION_REQUIRED] Tenant roles and workspace/store ownership
   semantics.
6. [BUSINESS_DECISION_REQUIRED] Throughput/latency/storage budgets.
7. [ENGINEERING_ASSUMPTION] Existing Marko modules must be assessed with a
   `reuse / move / adapt / retire` disposition.
8. [FACT_FROM_REPO] Parser internals remain unchanged unless Stage 02 records a
   reproducible defect with fixture, expected output and regression test.

Required Stage 02 outputs:

- C4 context, container and component views;
- domain ownership matrix;
- sync/async boundary map;
- versioned contracts between Marko and Metis;
- ADR package;
- data and code migration strategy;
- plan for resolving duplicate models/documents without losing implemented
  behavior;
- explicit list of Stage 03 code already present versus operational proof still
  required.

Stage 02 hard stop:

```text
NO implementation migration
until:
  duplicated ownership = resolved
  Metis invariants = mapped
  source boundary = separated from product runtime
  acceptance criteria = approved
```

## 17. Go / no-go

[FACT_FROM_REPO] `GO` to Stage 02 architecture and ownership review.

[FACT_FROM_REPO] `NO-GO` to a production claim, automatic repricing, customer
pilot on unapproved competitor evidence, or destructive code migration.

[BUSINESS_DECISION_REQUIRED] Owner review should either accept this audit or
return concrete corrections to repository facts and the decision register.
