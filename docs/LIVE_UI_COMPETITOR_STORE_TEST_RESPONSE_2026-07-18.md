Потестил. Сайт загружается, авторизованная сессия работает, страницы «Рекомендации», «Каталог», «Магазины» и «Обзор» открываются. Но главный flow подключения конкурента сейчас не работает.

Для живой проверки взял два Prom-магазина: [Pilot-avto](https://pilot-avto.prom.ua/ua/) и [ПРОФПАРТС](https://profiparts-cs3325174.prom.ua/). Сам парсер живой: с первой страницы каждого магазина он извлёк по 29 товаров с ID, названием, ценой, брендом, SKU и URL.

Найдено два дефекта:

1. Обычная публичная ссылка `https://pilot-avto.prom.ua/ua/` отклоняется формой. Она принимает только канонический URL вида `prom.ua/ua/c<ID>-<slug>.html`, хотя текст UI просит «публичную ссылку на магазин».
2. Канонический URL проходит валидацию, но `POST /api/v1/stores` возвращает `500`. Точная причина: `stores_repo.create_sync_run()` добавляет `SyncRun` в SQLAlchemy session, но не делает `flush`; следом `_get_or_create_sync_run()` использует `sync_run.id`, который ещё `None`. PostgreSQL отклоняет outbox-строку: `aggregate_id violates not-null constraint`.

После ошибки транзакция откатилась корректно: после обновления списка подключённых магазинов осталось 0, то есть полусозданных данных нет. Фокусные unit-тесты зелёны: `15 passed`, но реальную PostgreSQL-транзакцию регистрации магазина они не покрывают.

Код не изменял: запрос был на тестирование. Полный воспроизводимый отчёт сохранён в этом файле.

## Структурированный результат текущего этапа

STAGE_RESULT:
- stage:
  - id: LIVE_UI_COMPETITOR_STORE_TEST_2026_07_18
  - title: LIVE UI COMPETITOR STORE TEST
  - type: VALIDATION
  - scope owner: Marko
- status: FAIL
- completed scope:
  - [SCOPE-LIVE-UI-NAVIGATION] The authenticated local Marko UI loaded and the Recommendations, Stores, Overview, and Catalog pages rendered their current empty states without navigation failure.
    - artifacts: frontend/lib/features/stores/stores_page.dart, frontend/lib/features/dashboard/dashboard_page.dart, frontend/lib/features/catalog/catalog_page.dart
    - evidence: Computer Use Safari session against http://localhost:8080
  - [SCOPE-COMPETITOR-DISCOVERY] Two current public Prom competitors were identified and canonical seller identities were recovered from live Prom search data.
    - artifacts: https://prom.ua/ua/c2257594-pilot-avto-avtozapchasti.html, https://prom.ua/ua/c3325174-profparts.html
    - evidence: https://pilot-avto.prom.ua/ua/, https://profiparts-cs3325174.prom.ua/
  - [SCOPE-PARSER-BLACK-BOX] The existing PromGateway parsed 29 first-page products from each competitor; the first Pilot-avto page contained 7 explicitly available products and the first PROFParts page contained 29.
    - artifacts: backend/src/marko/parsers/prom/gateway.py, backend/src/marko/parsers/prom/parser.py
    - evidence: docker compose exec api PromGateway one-page runtime check
  - [SCOPE-UI-FAILURE-ROOT-CAUSE] The canonical Pilot-avto URL passed frontend validation, POST /api/v1/stores reached FastAPI, and the request failed with an outbox aggregate_id NOT NULL violation because sync_run.id was still None.
    - artifacts: frontend/lib/features/stores/stores_controller.dart, backend/src/marko/services/stores.py, backend/src/marko/repositories/stores.py, backend/src/marko/services/scraper_outbox.py
    - evidence: docker compose logs api db at 2026-07-18T17:40:54Z
- strongest verified result:
  - claim: [CLM-LIVE-PROM-PARSER-WORKS] Live Prom HTML retrieval and the frozen parser boundary work for both tested competitor stores and return structured products with IDs, names, prices, currency, brand, SKU, and product URLs.
  - evidence level: E3
  - evidence: backend/src/marko/parsers/prom/gateway.py, docker compose exec api PromGateway one-page runtime check
  - reproduction status: reproducible
  - limitations: Only the first catalog page of each store was sampled., The queued batch and persistence path was not reachable because store registration failed.
- weakest critical area:
  - area: [AREA-STORE-SYNC-DISPATCH] Store registration to outbox dispatch transition
  - score/evidence floor: 0.0 / E3
  - reason: stores_repo.create_sync_run adds but does not flush SyncRun, while _get_or_create_sync_run immediately reads sync_run.id to build the outbox event.
  - impact: Every new store connection can return HTTP 500 before the catalog job is queued, so the main competitor onboarding flow is unusable.
  - required resolution: Assign or flush the SyncRun UUID before enqueue_dispatch, add a real PostgreSQL integration test for POST /api/v1/stores, rebuild, and repeat the browser flow.
- evidence quality:
  - highest level: E3
  - critical floor: E2
  - material claim coverage: 1.00
  - reproducible claim coverage: 1.00
  - freshness status: verified
  - representative scope: partial
  - limitations: Two competitors and one browser were tested., XLSX import was not exercised because no test catalog file was supplied in this request., Existing focused unit tests pass but do not execute the real store-registration transaction.
- production implication:
  - state: DEVELOPMENT_ONLY
  - production ready: false
  - evidence level: E3
  - passed hard gates: LOCAL_UI_LOADS, AUTHENTICATED_NAVIGATION, LIVE_PROM_FIRST_PAGE_PARSE
  - failed hard gates: LIVE_STORE_CONNECTION_DISPATCH
  - blocked hard gates: POST_SYNC_PRODUCT_AND_RECOMMENDATION_FLOW
  - statement: The requested live test is complete and found a deterministic P0 defect; the current build cannot onboard a competitor store through the UI.

## Блокеры

BLOCKERS:
- P0:
  - [BLK-P0-SYNC-RUN-ID-NONE] The store registration transaction constructs the outbox event with aggregate_id and task_args derived from sync_run.id before SQLAlchemy has assigned the default UUID.; owner=backend engineering; resolution=POST /api/v1/stores returns 202 with non-null store_id and sync_run_id, creates a valid outbox row, and the worker consumes the job in a real PostgreSQL integration and browser test.
- P1:
  - [BLK-P1-PROM-SUBDOMAIN-URL-REJECTED] The Stores form rejects normal public seller links such as https://pilot-avto.prom.ua/ua/ even though the UI asks for a public Prom store link.; owner=frontend and backend engineering; resolution=Public Prom seller subdomains are resolved to canonical company URLs or the UI explicitly explains and accepts only canonical marketplace seller URLs.
- business decisions:
  - NONE_VERIFIED
- source/access:
  - NONE_VERIFIED
- data:
  - NONE_VERIFIED
- environment/reproducibility:
  - BLK-P0-SYNC-RUN-ID-NONE, BLK-P1-PROM-SUBDOMAIN-URL-REJECTED
- unknowns:
  - NONE_VERIFIED

## Следующая часть

NEXT_STAGE:
- id: STORE_SYNC_DISPATCH_REPAIR_AND_REVALIDATION
- title: STORE SYNC DISPATCH REPAIR AND REVALIDATION
- why it is next:
  - It repairs the first deterministic failure in the real competitor onboarding path.
  - It unlocks the product, comparison, and recommendation UI tests that could not be reached.
- required inputs:
  - [INPUT-REPRODUCIBLE-PILOT-URL] Canonical Pilot-avto Prom seller URL; source=live Prom search data; required_state=URL remains publicly reachable; available=true; evidence=https://prom.ua/ua/c2257594-pilot-avto-avtozapchasti.html
  - [INPUT-LOCAL-STACK] Healthy local PostgreSQL, Redis, API, frontend, and store-sync worker stack; source=current Docker Compose runtime; required_state=required services remain healthy; available=true; evidence=docker compose ps
- expected artifacts:
  - [ART-SYNC-RUN-ID-FIX] code: должен быть создан; purpose=Must ensure SyncRun has a stable UUID before outbox construction.; required_fields=non_null_sync_run_id, valid_outbox_aggregate_id, deterministic_task_args
  - [ART-STORE-REGISTRATION-INTEGRATION-TEST] test: должен быть создан; purpose=Must cover the real PostgreSQL transaction from authenticated POST through outbox publication.; required_fields=http_202, sync_run_id, outbox_row, worker_consumption
- acceptance criteria:
  - [AC-STORE-SYNC-01] predicate=A canonical Prom competitor URL connects through the browser without an error banner; evidence=Computer Use browser replay plus API logs; threshold=POST returns 202 and UI enters queued or running state
  - [AC-STORE-SYNC-02] predicate=The outbox row contains the same non-null SyncRun UUID in aggregate_id, event_key, and task_args; evidence=PostgreSQL integration assertion; threshold=exact identity equality
  - [AC-STORE-SYNC-03] predicate=The store-sync worker persists products from both tested competitors; evidence=completed sync jobs and store product counts; threshold=product_count greater than zero for each store
- stop condition:
  - gate key: STOP_GATE_STORE_SYNC_DISPATCH_REPAIR_AND_REVALIDATION
  - allowed states: PASS, FAIL, BLOCKED, NO_GO
  - automatic transition: false
- client decisions required:
  - NONE_VERIFIED

STOP_GATE_LIVE_UI_COMPETITOR_STORE_TEST_2026_07_18 = FAIL

MACHINE_READABLE_SUMMARY:

```yaml
schema:
  name: metis_marko_machine_readable_stage_summary
  version: 1.1.0
  generated_at: "2026-07-18T19:45:11+02:00"
  report_id: REPORT-LIVE-UI-COMPETITOR-STORE-TEST-2026-07-18
  audit_id: VALIDATION-LIVE-UI-COMPETITOR-STORE-TEST-2026-07-18
stage:
  id: LIVE_UI_COMPETITOR_STORE_TEST_2026_07_18
  title: LIVE UI COMPETITOR STORE TEST
  status: FAIL
  status_reason: The live browser test deterministically failed at store registration because the outbox event was built with a null SyncRun UUID.
  acceptance_criteria_passed: false
  audit_complete: true
  production_ready: false
  secondary_findings: []
  evidence_refs:
  - Computer Use Safari session against http://localhost:8080
  - docker compose logs api db at 2026-07-18T17:40:54Z
  - backend/src/marko/services/stores.py
  - backend/src/marko/repositories/stores.py
repository:
  audit_root: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
  audit_root_realpath: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия
  topology: UNKNOWN
  git_commit: null
  dirty_before_audit: null
  identity_verified: false
  runtime_import_identity: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src
  components:
    metis:
      root: backend/src/metis
      realpath: null
      repository_top_level: null
      git_commit: null
      branch: null
      detached_head: null
      dirty_before_audit: null
      identity_verified: false
      runtime_import_path: null
      evidence_refs: []
    marko:
      root: backend/src/marko
      realpath: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko
      repository_top_level: null
      git_commit: null
      branch: null
      detached_head: null
      dirty_before_audit: null
      identity_verified: false
      runtime_import_path: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko
      evidence_refs:
      - backend/src/marko
  duplicate_copies: []
  unresolved_identity_conflicts:
  - NO_GIT_METADATA
metis:
  weighted_readiness: null
  readiness_interval:
    lower: null
    upper: null
  readiness_scale: '0_100'
  score_basis: CONSERVATIVE_LOWER_BOUND
  critical_floor: null
  evidence_level: null
  evidence_level_semantics: CRITICAL_EVIDENCE_FLOOR
  highest_evidence_level: null
  unknown_weight: null
  critical_unknown_count: null
  engineering_weights_approved: false
  production_eligible: false
  production_gate:
    status: NOT_EVALUATED
    passed_gates: []
    failed_gates: []
    blocked_gates: []
    unknown_gates:
    - METIS_NOT_IN_SCOPE_OF_UI_TEST
  dimension_weights:
    implementation: 0.2
    verification: 0.15
    integration: 0.15
    auditability: 0.15
    operations: 0.15
    security: 0.1
    documentation: 0.1
  capabilities: []
  critical_capability_ids: []
  strongest_domains: []
  missing_critical_domains: []
  evidence_refs: []
  maturity_class: UNKNOWN
marko:
  weighted_readiness: null
  readiness_interval:
    lower: null
    upper: null
  readiness_scale: '0_100'
  score_basis: CONSERVATIVE_LOWER_BOUND
  critical_floor: null
  evidence_level: null
  evidence_level_semantics: CRITICAL_EVIDENCE_FLOOR
  highest_evidence_level: null
  unknown_weight: null
  critical_unknown_count: null
  engineering_weights_approved: false
  production_eligible: false
  production_gate:
    status: FAIL
    passed_gates:
    - LOCAL_UI_LOADS
    - AUTHENTICATED_NAVIGATION
    - LIVE_PROM_FIRST_PAGE_PARSE
    failed_gates:
    - LIVE_STORE_CONNECTION_DISPATCH
    blocked_gates:
    - POST_SYNC_PRODUCT_AND_RECOMMENDATION_FLOW
    unknown_gates: []
  dimension_weights:
    implementation: 0.2
    verification: 0.15
    integration: 0.15
    auditability: 0.15
    operations: 0.15
    security: 0.1
    documentation: 0.1
  capabilities: []
  critical_capability_ids: []
  strongest_domains: []
  missing_critical_domains: []
  evidence_refs:
  - frontend/lib/features/stores/stores_controller.dart
  - backend/src/marko/services/stores.py
  - backend/src/marko/services/scraper_outbox.py
  maturity_class: INTEGRATED_PRODUCT_SHELL
  existing_scraper:
    located: VERIFIED
    physical_path: backend/src/marko/parsers/prom
    entry_point: marko.parsers.prom.gateway.PromGateway
    entry_point_verified: VERIFIED
    input_contract_verified: VERIFIED
    output_contract_verified: VERIFIED
    runtime_reverified: VERIFIED
    single_request_verified: VERIFIED
    small_batch_verified: VERIFIED
    batch_ready: BLOCKED
    parallel_safe: UNKNOWN
    timeout_bounded: VERIFIED
    retry_safe: UNKNOWN
    idempotent: UNKNOWN
    queue_integrated: PARTIAL
    dead_letter_integrated: UNKNOWN
    raw_storage_integrated: UNKNOWN
    structured_storage_integrated: BLOCKED
    metis_evidence_integrated: UNKNOWN
    replayable: UNKNOWN
    observable: PARTIAL
    load_tested: NOT_VERIFIED
    production_proven: NOT_VERIFIED
    capacity:
      measured: false
      unique_urls: null
      arrival_rate_urls_per_second: null
      worker_service_rate_urls_per_second: null
      active_workers: null
      average_attempts_per_unique_url: null
      effective_worker_service_rate: null
      total_capacity_urls_per_second: null
      utilization_rho: null
      queue_backlog: null
      queue_stability: NOT_MEASURED
      estimated_drain_seconds: null
      success_rate: null
      retry_amplification: null
      latency_p50_seconds: null
      latency_p95_seconds: null
      latency_p99_seconds: null
      raw_storage_bytes: null
      structured_storage_bytes: null
      memory_peak_bytes: null
      cpu_average_percent: null
    evidence_refs:
    - backend/src/marko/parsers/prom/gateway.py
    - backend/src/marko/parsers/prom/parser.py
    - docker compose exec api PromGateway one-page runtime check
  reusable_as_is: []
  adapt_before_reuse: []
  reference_only: []
  do_not_port: []
  unknown_reuse_state: []
  evaluated_component_ids: []
  reuse_partition_valid: null
combined_system:
  maturity_class: PARTIAL_INTEGRATION
  end_to_end_flow_verified: PARTIAL
  end_to_end_evidence_level: E3
  trace_coverage: null
  verified_trace_coverage: null
  integrated_trace_coverage: null
  last_verified_node: LIVE_PROM_FIRST_PAGE_PARSE
  first_unverified_node: STORE_SYNC_WORKER_COMPLETION
  first_broken_transition: STORE_REGISTRATION_TO_OUTBOX_DISPATCH
  production_eligible: false
  production_gate:
    status: FAIL
    passed_gates:
    - UI_LOAD
    - AUTH_SESSION
    - PROM_PARSE
    failed_gates:
    - STORE_REGISTRATION_TO_OUTBOX_DISPATCH
    blocked_gates:
    - PRODUCT_PERSISTENCE
    - COMPARISON_AND_RECOMMENDATION_UI
    unknown_gates: []
  recommendation_contract:
    explainable: UNKNOWN
    auditable: UNKNOWN
    reproducible: UNKNOWN
    insufficient_data_abstention: UNKNOWN
    manual_review_routing: UNKNOWN
  evidence_refs:
  - Computer Use Safari session against http://localhost:8080
  - docker compose logs api db at 2026-07-18T17:40:54Z
gaps:
  p0:
  - gap_id: GAP-P0-SYNC-RUN-ID-NONE
    system: MARKO
    capability_id: STORE_SYNC_DISPATCH
    title: SyncRun UUID is unavailable during outbox construction
    description: The repository adds a new SyncRun without flushing it and the service immediately uses sync_run.id as the outbox aggregate identity and task argument.
    gap_type: INTEGRATION_GAP
    priority: P0
    severity: 5
    likelihood: 5
    detection_difficulty: 2
    dependency_centrality: 3
    rpn: 150
    normalized_rpn: 39.839572192513366
    affected_invariants:
    - every outbox event has a stable aggregate identity
    - store creation returns a durable queued job
    blocks:
    - LIVE_STORE_CONNECTION_DISPATCH
    - POST_SYNC_PRODUCT_AND_RECOMMENDATION_FLOW
    evidence_refs:
    - backend/src/marko/services/stores.py
    - backend/src/marko/repositories/stores.py
    - docker compose logs api db at 2026-07-18T17:40:54Z
    owner_type: backend engineering
    remediation_class: flush or explicitly assign SyncRun UUID before outbox construction plus real PostgreSQL integration coverage
    acceptance_evidence_required: E3
  p1:
  - gap_id: GAP-P1-PROM-SUBDOMAIN-URL-NORMALIZATION
    system: MARKO
    capability_id: SELLER_URL_NORMALIZATION
    title: Public Prom seller subdomains are rejected by the form
    description: The UI requests a public Prom store link but accepts only prom.ua and www.prom.ua hosts, rejecting the seller URLs users normally copy.
    gap_type: PARTIAL_IMPLEMENTATION
    priority: P1
    severity: 3
    likelihood: 4
    detection_difficulty: 3
    dependency_centrality: 2
    rpn: 72
    normalized_rpn: 18.98395721925134
    affected_invariants:
    - valid public seller identity can be onboarded
    blocks:
    - INTUITIVE_COMPETITOR_ONBOARDING
    evidence_refs:
    - frontend/lib/features/stores/stores_controller.dart
    - Computer Use Safari validation attempt
    owner_type: frontend and backend engineering
    remediation_class: canonical seller URL resolver and aligned validation copy
    acceptance_evidence_required: E3
  p2: []
  p3: []
  priority_partition_valid: true
  duplicate_gap_ids: []
  critical_dependency_chain:
  - GAP-P0-SYNC-RUN-ID-NONE
  - STORE_SYNC_WORKER_COMPLETION
  - POST_SYNC_PRODUCT_AND_RECOMMENDATION_FLOW
business_decisions_required: []
source_access_states: []
engineering_assumptions: []
future_hypotheses: []
unknowns:
- unknown_id: UNKNOWN-PROJECT-WIDE-READINESS
  field_path: metis.*
  question: What is the current project-wide production readiness outside the tested onboarding path?
  reason_unknown: The request was limited to live website and competitor-store testing.
  impact: This report makes no project-wide production readiness score.
  resolver_type: PROJECT_STATE_AUDIT
  required_input: Representative full-system production evidence
  owner: engineering
  blocks:
  - PROJECT_WIDE_PRODUCTION_CLAIM
  target_stage: PROJECT_READINESS_ASSESSMENT
- unknown_id: UNKNOWN-REPOSITORY-SNAPSHOT
  field_path: repository.*
  question: Which canonical Git commit owns this workspace?
  reason_unknown: The tested workspace is not a Git worktree.
  impact: The reproduced failure is path-bound rather than commit-bound.
  resolver_type: REPOSITORY_OWNER_INPUT
  required_input: Canonical repository identity
  owner: repository maintainer
  blocks:
  - AUDITED_RELEASE
  target_stage: RELEASE_PROVENANCE
- unknown_id: UNKNOWN-MARKO-READINESS-SCORE
  field_path: marko.*
  question: What is Marko's complete weighted readiness and critical evidence floor?
  reason_unknown: The live test assessed one onboarding path rather than every readiness capability.
  impact: Marko readiness values remain null even though the tested path has a confirmed failure.
  resolver_type: PROJECT_STATE_AUDIT
  required_input: Full capability inventory and evidence-scored readiness assessment
  owner: engineering
  blocks:
  - MARKO_WEIGHTED_READINESS_CLAIM
  target_stage: PROJECT_READINESS_ASSESSMENT
- unknown_id: UNKNOWN-COMBINED-TRACE-COVERAGE
  field_path: combined_system.*
  question: What fraction of the complete Marko to Metis trace is currently verified?
  reason_unknown: The live path stopped at store-registration dispatch before products or recommendations existed.
  impact: Trace coverage ratios remain null.
  resolver_type: END_TO_END_REVALIDATION
  required_input: Passing store sync, comparison, and recommendation trace evidence
  owner: engineering
  blocks:
  - COMPLETE_E2E_TRACE_CLAIM
  target_stage: STORE_SYNC_DISPATCH_REPAIR_AND_REVALIDATION
next_stage:
  id: STORE_SYNC_DISPATCH_REPAIR_AND_REVALIDATION
  title: STORE SYNC DISPATCH REPAIR AND REVALIDATION
  objective: Ensure SyncRun has a stable UUID before outbox creation, cover the transaction with real PostgreSQL integration tests, rebuild, and repeat the browser flow.
  why_it_is_next: It repairs the first deterministic break in competitor onboarding and unlocks all downstream UI checks.
  required_inputs:
  - Canonical Pilot-avto and PROFParts seller URLs
  - Healthy local Docker Compose stack
  - Current PostgreSQL schema and store-sync worker
  expected_outputs:
  - A SyncRun identity fix must be created.
  - A real PostgreSQL store-registration integration test must be created.
  - A passing browser revalidation report must be created.
  acceptance_criteria:
  - POST /api/v1/stores returns 202 with non-null store_id and sync_run_id.
  - The outbox aggregate_id and task_args contain the exact SyncRun UUID.
  - Each tested store completes a sync with product_count greater than zero.
  stop_condition: STOP_GATE_STORE_SYNC_DISPATCH_REPAIR_AND_REVALIDATION with no automatic continuation
  client_decisions_required: []
  started: false
  new_direct_instruction_required: true
validation:
  yaml_parse: true
  duplicate_key_check: true
  schema_validation: true
  required_field_validation: true
  enum_validation: true
  type_validation: true
  arithmetic_validation: true
  readiness_interval_validation: true
  evidence_ceiling_validation: true
  critical_floor_validation: true
  stop_gate_consistency: true
  production_gate_consistency: true
  reuse_partition_validation: true
  gap_partition_validation: true
  evidence_traceability: true
  reverse_trace_validation: true
  variation_validation: true
  hostile_review: true
  errors: []
  warnings:
  - PROJECT_WIDE_READINESS_NOT_ASSESSED
  - REPOSITORY_SNAPSHOT_NOT_GIT_BOUND
  - STORE_REGISTRATION_INTEGRATION_TEST_MISSING
  - EMPTY_CATEGORY_VERIFIED:business_decisions_required
  - EMPTY_CATEGORY_VERIFIED:source_access_states
  - EMPTY_CATEGORY_VERIFIED:marko.reuse_partition
termination:
  stop_gate_key: STOP_GATE_LIVE_UI_COMPETITOR_STORE_TEST_2026_07_18
  stop_gate_value: FAIL
  stage_status_matches_stop_gate: true
  next_stage_started: false
  execution_stopped: true
  no_content_after_summary: true
```
