# Store sync dispatch repair — validated result

Ремонт выполнен: `SyncRun.id` получает UUID до сборки outbox-события, HTTPS-адреса `*.prom.ua` безопасно приводятся к каноническому seller URL, схема price observations выровнена с SQLAlchemy, а два реальных магазина прошли весь локальный PostgreSQL/Redis/Celery store-sync путь.

Фактический результат: Pilot-avto — 725 товаров, PROFParts — 675, всего 1400. Оба `SyncRun` завершились со статусами `completed` / `succeeded`; UUID совпадает в `SyncRun.id`, `aggregate_id`, `event_key` и `task_args`.

## Структурированный результат текущего этапа

STAGE_RESULT:
- stage:
  - id: STORE_SYNC_DISPATCH_REPAIR_IMPLEMENTATION_2026_07_19
  - title: STORE SYNC DISPATCH REPAIR IMPLEMENTATION
  - type: IMPLEMENTATION
  - scope owner: Marko
- status: PASS
- completed scope:
  - [SCOPE-SYNC-RUN-IDENTITY] SyncRun is flushed before its UUID is consumed by the transactional outbox.
    - artifacts: backend/src/marko/repositories/stores.py, backend/tests/test_store_sync_identity.py, backend/tests/test_store_registration_postgres.py
    - evidence: opt-in PostgreSQL integration test passed
  - [SCOPE-PROM-SELLER-URL-RESOLUTION] Canonical prom.ua seller URLs and public HTTPS seller subdomains are safely admitted and resolved with bounded redirects, timeout, response size, and Prom-only redirect validation.
    - artifacts: backend/src/marko/services/seller_url_resolver.py, backend/src/marko/api/schemas/stores.py, frontend/lib/features/stores/stores_controller.dart
    - evidence: backend/tests/test_seller_url_resolver.py, frontend/test/stores_controller_test.dart, live Pilot-avto and PROFParts resolver check
  - [SCOPE-PRICE-OBSERVATION-SCHEMA] Missing price-observation currency evidence columns were added fail-closed and SQLAlchemy metadata now matches the migrated PostgreSQL schema.
    - artifacts: backend/migrations/versions/20260719_0015_price_observation_currency_evidence.py, backend/src/marko/services/catalog_import.py, backend/src/marko/infrastructure/db/models.py
    - evidence: alembic check reported no new upgrade operations, live price observations preserved raw currency
  - [SCOPE-LIVE-TWO-STORE-SYNC] Pilot-avto and PROFParts completed through PostgreSQL, Redis, the transactional outbox, and store-sync execution with 725 and 675 persisted products respectively.
    - artifacts: https://pilot-avto.prom.ua/ua/, https://profiparts-cs3325174.prom.ua/
    - evidence: completed SyncRun rows 06fe6ed9-a1dc-4455-a23d-2284a3b55aa1 and 3e2f695c-acb2-4734-8bae-8bec76eb94e4, Docker Compose runtime query
- strongest verified result:
  - claim: [CLM-LIVE-STORE-SYNC-SUCCEEDED] Two real Prom subdomain storefronts resolved to canonical seller identities and reached completed, succeeded sync runs with 1400 total persisted listings, raw currency evidence, full evidence coverage, and exact outbox UUID identity.
  - evidence level: E3
  - evidence: PostgreSQL runtime query for both completed SyncRun rows, docker compose ps, backend/tests/test_store_registration_postgres.py
  - reproduction status: reproducible
  - limitations: Validation is local rather than production., The final authenticated UI screen awaits user sign-in.
- weakest critical area:
  - area: [AREA-AUTHENTICATED-UI-VISUAL] Authenticated browser presentation after sync
  - score/evidence floor: 50.0 / E2
  - reason: Frontend validation and build passed, but the current browser session is signed out.
  - impact: The user must sign in once to visually confirm the already-persisted stores and products.
  - required resolution: Sign in through the open Marko login page and refresh the Stores screen.
- evidence quality:
  - highest level: E3
  - critical floor: E2
  - material claim coverage: 1.00
  - reproducible claim coverage: 1.00
  - freshness status: verified
  - representative scope: representative
  - limitations: No production load or recovery claim is made., Flutter analyze required an ASCII-path copy because the analysis server crashes on the checkout path encoding.
- production implication:
  - state: DEVELOPMENT_ONLY
  - production ready: false
  - evidence level: E3
  - passed hard gates: SYNC_RUN_UUID_BEFORE_OUTBOX, PROM_SUBDOMAIN_RESOLUTION, POSTGRES_STORE_REGISTRATION, TWO_STORE_LIVE_PERSISTENCE, SCHEMA_METADATA_ALIGNMENT
  - failed hard gates: NONE_VERIFIED
  - blocked hard gates: PROJECT_WIDE_PRODUCTION_READINESS_NOT_ASSESSED
  - statement: The requested local repair is complete and operational; this stage does not assert project-wide production readiness.

## Блокеры

BLOCKERS:
- P0:
  - NONE_VERIFIED
- P1:
  - NONE_VERIFIED
- business decisions:
  - NONE_VERIFIED
- source/access:
  - NONE_VERIFIED
- data:
  - NONE_VERIFIED
- environment/reproducibility:
  - NONE_VERIFIED
- unknowns:
  - NONE_VERIFIED

## Следующая часть

NEXT_STAGE:
- id: AUTHENTICATED_UI_VISUAL_CONFIRMATION
- title: AUTHENTICATED UI VISUAL CONFIRMATION
- why it is next:
  - The stores and products already exist; only the signed-in presentation remains to be viewed.
- required inputs:
  - [INPUT-USER-FIREBASE-SESSION] Open local Marko login page where the user can establish the user-controlled Firebase session.; source=in-app browser; required_state=login page available for user sign-in; available=true; evidence=in-app browser login screen
- expected artifacts:
  - [ART-AUTHENTICATED-STORES-SCREEN] report: должен быть создан; purpose=Confirm both stores and their product counts in the authenticated UI.; required_fields=Pilot-avto, PROFParts, product_count
- acceptance criteria:
  - [AC-UI-01] predicate=The authenticated Stores screen shows both synchronized competitors with non-zero product counts.; evidence=Browser state after user sign-in; threshold=two visible stores and no sync error banner
- stop condition:
  - gate key: STOP_GATE_AUTHENTICATED_UI_VISUAL_CONFIRMATION
  - allowed states: PASS, FAIL, BLOCKED, NO_GO
  - automatic transition: false
- client decisions required:
  - NONE_VERIFIED

STOP_GATE_STORE_SYNC_DISPATCH_REPAIR_IMPLEMENTATION_2026_07_19 = PASS

MACHINE_READABLE_SUMMARY:
```yaml
schema: {name: metis_marko_machine_readable_stage_summary, version: 1.1.0, generated_at: "2026-07-19T13:05:00+02:00", report_id: REPORT-STORE-SYNC-DISPATCH-REPAIR-2026-07-19, audit_id: VALIDATION-STORE-SYNC-DISPATCH-REPAIR-2026-07-19}
stage:
  id: STORE_SYNC_DISPATCH_REPAIR_IMPLEMENTATION_2026_07_19
  title: STORE SYNC DISPATCH REPAIR IMPLEMENTATION
  status: PASS
  status_reason: SyncRun identity, public Prom URL resolution, price-observation schema, and two-store live persistence all passed.
  acceptance_criteria_passed: true
  audit_complete: true
  production_ready: false
  secondary_findings:
    - type: PASS
      finding_id: FINDING-AUTHENTICATED-UI-VISUAL-OPTIONAL
      finding: Backend persistence and frontend automated checks pass; authenticated UI visual confirmation remains an optional user-controlled follow-up.
      evidence_refs: [frontend/test/stores_controller_test.dart, in-app browser login screen]
  evidence_refs: [backend/tests/test_store_registration_postgres.py, backend/tests/test_seller_url_resolver.py, "645 passed, 1 skipped", "Pilot-avto 725 products", "PROFParts 675 products"]
repository:
  audit_root: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия"
  audit_root_realpath: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия"
  topology: UNKNOWN
  git_commit: null
  dirty_before_audit: null
  identity_verified: false
  runtime_import_identity: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src"
  components:
    metis: {root: backend/src/metis, realpath: null, repository_top_level: null, git_commit: null, branch: null, detached_head: null, dirty_before_audit: null, identity_verified: false, runtime_import_path: null, evidence_refs: []}
    marko: {root: backend/src/marko, realpath: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko", repository_top_level: null, git_commit: null, branch: null, detached_head: null, dirty_before_audit: null, identity_verified: false, runtime_import_path: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko", evidence_refs: [backend/src/marko]}
  duplicate_copies: []
  unresolved_identity_conflicts: [NO_GIT_METADATA]
metis:
  weighted_readiness: null
  readiness_interval: {lower: null, upper: null}
  readiness_scale: "0_100"
  score_basis: CONSERVATIVE_LOWER_BOUND
  critical_floor: null
  evidence_level: null
  evidence_level_semantics: CRITICAL_EVIDENCE_FLOOR
  highest_evidence_level: null
  unknown_weight: null
  critical_unknown_count: null
  engineering_weights_approved: false
  production_eligible: false
  production_gate: {status: NOT_EVALUATED, passed_gates: [], failed_gates: [], blocked_gates: [], unknown_gates: [PROJECT_READINESS_NOT_ASSESSED]}
  dimension_weights: {implementation: 0.20, verification: 0.15, integration: 0.15, auditability: 0.15, operations: 0.15, security: 0.10, documentation: 0.10}
  capabilities: []
  critical_capability_ids: []
  strongest_domains: []
  missing_critical_domains: []
  evidence_refs: []
  maturity_class: UNKNOWN
marko:
  weighted_readiness: null
  readiness_interval: {lower: null, upper: null}
  readiness_scale: "0_100"
  score_basis: CONSERVATIVE_LOWER_BOUND
  critical_floor: null
  evidence_level: null
  evidence_level_semantics: CRITICAL_EVIDENCE_FLOOR
  highest_evidence_level: null
  unknown_weight: null
  critical_unknown_count: null
  engineering_weights_approved: false
  production_eligible: false
  production_gate: {status: NOT_EVALUATED, passed_gates: [LOCAL_STORE_SYNC_REPAIR], failed_gates: [], blocked_gates: [], unknown_gates: [PROJECT_READINESS_NOT_ASSESSED]}
  dimension_weights: {implementation: 0.20, verification: 0.15, integration: 0.15, auditability: 0.15, operations: 0.15, security: 0.10, documentation: 0.10}
  capabilities: []
  critical_capability_ids: []
  strongest_domains: []
  missing_critical_domains: []
  evidence_refs: [backend/src/marko/services/seller_url_resolver.py, backend/src/marko/repositories/stores.py, backend/migrations/versions/20260719_0015_price_observation_currency_evidence.py]
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
    batch_ready: PARTIAL
    parallel_safe: VERIFIED
    timeout_bounded: VERIFIED
    retry_safe: VERIFIED
    idempotent: VERIFIED
    queue_integrated: PARTIAL
    dead_letter_integrated: UNKNOWN
    raw_storage_integrated: VERIFIED
    structured_storage_integrated: VERIFIED
    metis_evidence_integrated: UNKNOWN
    replayable: VERIFIED
    observable: VERIFIED
    load_tested: NOT_VERIFIED
    production_proven: NOT_VERIFIED
    capacity: {measured: false, unique_urls: null, arrival_rate_urls_per_second: null, worker_service_rate_urls_per_second: null, active_workers: null, average_attempts_per_unique_url: null, effective_worker_service_rate: null, total_capacity_urls_per_second: null, utilization_rho: null, queue_backlog: null, queue_stability: NOT_MEASURED, estimated_drain_seconds: null, success_rate: null, retry_amplification: null, latency_p50_seconds: null, latency_p95_seconds: null, latency_p99_seconds: null, raw_storage_bytes: null, structured_storage_bytes: null, memory_peak_bytes: null, cpu_average_percent: null}
    evidence_refs: ["Pilot-avto completed 725", "PROFParts completed 675", "evidence coverage 1.000000"]
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
  last_verified_node: STORE_SYNC_PERSISTENCE_SUCCEEDED
  first_unverified_node: AUTHENTICATED_UI_VISUAL_CONFIRMATION
  first_broken_transition: null
  production_eligible: false
  production_gate: {status: NOT_EVALUATED, passed_gates: [LOCAL_STORE_SYNC_E2E], failed_gates: [], blocked_gates: [], unknown_gates: [PROJECT_READINESS_NOT_ASSESSED]}
  recommendation_contract: {explainable: UNKNOWN, auditable: UNKNOWN, reproducible: UNKNOWN, insufficient_data_abstention: UNKNOWN, manual_review_routing: UNKNOWN}
  evidence_refs: ["two completed SyncRun rows", "1400 total persisted products", "outbox identity equality"]
gaps: {p0: [], p1: [], p2: [], p3: [], priority_partition_valid: true, duplicate_gap_ids: [], critical_dependency_chain: []}
business_decisions_required: []
source_access_states: []
engineering_assumptions: []
future_hypotheses: []
unknowns:
  - {unknown_id: UNKNOWN-METIS-READINESS, field_path: "metis.*", question: "What is current Metis readiness?", reason_unknown: This store-sync repair did not assess complete Metis readiness., impact: No Metis readiness score is claimed., resolver_type: PROJECT_STATE_AUDIT, required_input: Representative project audit, owner: engineering, blocks: [METIS_PRODUCTION_GATE], target_stage: PROJECT_READINESS_ASSESSMENT}
  - {unknown_id: UNKNOWN-MARKO-READINESS, field_path: "marko.*", question: "What is current Marko readiness?", reason_unknown: This store-sync repair did not assess complete Marko readiness., impact: No Marko readiness score is claimed., resolver_type: PROJECT_STATE_AUDIT, required_input: Representative project audit, owner: engineering, blocks: [MARKO_PRODUCTION_GATE], target_stage: PROJECT_READINESS_ASSESSMENT}
  - {unknown_id: UNKNOWN-REPOSITORY-SNAPSHOT, field_path: "repository.*", question: "Which canonical commit owns this workspace?", reason_unknown: No Git metadata is present., impact: The implementation is path-bound., resolver_type: REPOSITORY_OWNER_INPUT, required_input: Canonical repository identity, owner: repository maintainer, blocks: [AUDITED_RELEASE], target_stage: RELEASE_PROVENANCE}
  - {unknown_id: UNKNOWN-PROJECT-READINESS, field_path: "combined_system.*", question: "Is the complete project production-ready?", reason_unknown: This stage repaired and validated local store onboarding only., impact: No production-readiness claim is made., resolver_type: PROJECT_STATE_AUDIT, required_input: Representative production evidence, owner: engineering, blocks: [PROJECT_PRODUCTION_GATE], target_stage: PROJECT_READINESS_ASSESSMENT}
  - {unknown_id: UNKNOWN-AUTHENTICATED-UI-VISUAL, field_path: "combined_system.first_unverified_node", question: "Do both stores render correctly after Firebase sign-in?", reason_unknown: The current in-app browser session is signed out., impact: Visual confirmation awaits one user-controlled login., resolver_type: USER_AUTHENTICATION, required_input: Authenticated Firebase browser session, owner: user, blocks: [AUTHENTICATED_UI_VISUAL_CONFIRMATION], target_stage: AUTHENTICATED_UI_VISUAL_CONFIRMATION}
  - {unknown_id: UNKNOWN-SCRAPER-CAPACITY, field_path: "marko.existing_scraper.capacity", question: "What are representative throughput and latency percentiles?", reason_unknown: This repair test was not a controlled load test., impact: No capacity or production SLO claim is made., resolver_type: LOAD_TEST, required_input: Representative workload and measurement window, owner: engineering, blocks: [SCRAPER_CAPACITY_CLAIM], target_stage: SCRAPER_PHASE_9_INTEGRATION_AND_LOAD_VALIDATION}
  - {unknown_id: UNKNOWN-METIS-EVIDENCE-INTEGRATION, field_path: "marko.existing_scraper.metis_evidence_integrated", question: "Is the complete downstream Metis recommendation trace verified for these stores?", reason_unknown: This stage ended at successful store persistence., impact: Downstream recommendation readiness remains unassessed., resolver_type: END_TO_END_REVALIDATION, required_input: Pricing and recommendation run over imported products, owner: engineering, blocks: [COMPLETE_MARKO_METIS_TRACE], target_stage: PROJECT_READINESS_ASSESSMENT}
next_stage:
  id: AUTHENTICATED_UI_VISUAL_CONFIRMATION
  title: AUTHENTICATED UI VISUAL CONFIRMATION
  objective: After user sign-in, confirm both synchronized stores and product counts on the Stores screen.
  why_it_is_next: Backend, database, outbox, worker, and frontend build are already verified; only user-controlled visual access remains.
  required_inputs: [Authenticated Firebase browser session]
  expected_outputs: [Authenticated Stores screen evidence must be created.]
  acceptance_criteria: [Both stores are visible with non-zero product counts and no sync error banner.]
  stop_condition: STOP_GATE_AUTHENTICATED_UI_VISUAL_CONFIRMATION with no automatic continuation
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
  warnings: [PROJECT_READINESS_NOT_ASSESSED, REPOSITORY_SNAPSHOT_NOT_GIT_BOUND, AUTHENTICATED_UI_VISUAL_CONFIRMATION_PENDING, "EMPTY_CATEGORY_VERIFIED:business_decisions_required", "EMPTY_CATEGORY_VERIFIED:source_access_states", "EMPTY_CATEGORY_VERIFIED:marko.reuse_partition", "EMPTY_CATEGORY_VERIFIED:gaps"]
termination:
  stop_gate_key: STOP_GATE_STORE_SYNC_DISPATCH_REPAIR_IMPLEMENTATION_2026_07_19
  stop_gate_value: PASS
  stage_status_matches_stop_gate: true
  next_stage_started: false
  execution_stopped: true
  no_content_after_summary: true
```
