# PROMPT 15.016 — SERVER_SIDE_ENCRYPTED cost implementation

Серверное шифрование себестоимости реализовано и проверено. Значение хранится только как AES-256-GCM ciphertext; API и интерфейс не возвращают исходную сумму. Ручное решение ниже себестоимости требует отдельного подтверждения, но себестоимость не становится рыночным ценовым floor.

Проверено: 590 backend-тестов, 25 Flutter-тестов, статический анализ, migration head 20260718_0013 и реальный rollback-only PostgreSQL round-trip без сохранённых synthetic records и без вывода ключа.

Локальный runtime остаётся fail-closed в режиме UNDECIDED, потому что реальный ключ намеренно не генерировался и не записывался в repository. Для production activation нужен отдельный secret-provisioning и recovery drill; это не отменяет PASS текущего implementation stage.

## Структурированный результат текущего этапа

STAGE_RESULT:
- stage:
  - id: PROMPT_15_016_COST_ENCRYPTION_IMPLEMENTATION
  - title: YURI_V1_SERVER_SIDE_ENCRYPTED_COST_IMPLEMENTATION
  - type: IMPLEMENTATION
  - scope owner: Cross-cutting
- status: PASS
- completed scope:
  - [SCOPE-COST-AUTHENTICATED-ENCRYPTION] Unit cost is persisted only as AES-256-GCM ciphertext with a fresh nonce, row and tenant bound associated data, external versioned keys and append-only SET or CLEAR records.
    - artifacts: backend/src/marko/core/cost_encryption.py, backend/src/marko/services/catalog_costs.py, backend/migrations/versions/20260718_0013_encrypted_catalog_cost.py
    - evidence: backend/tests/test_cost_encryption.py, docs/PROMPT_15_016_COST_PRIVACY_ADR_2026-07-18.md
  - [SCOPE-COST-SAFE-API-UI] Manual set, replace, clear and below-cost confirmation are implemented without returning raw cost in catalog, recommendation, decision, replay or validation-error responses.
    - artifacts: backend/src/marko/api/schemas/pricing.py, backend/src/marko/services/pricing_runs.py, frontend/lib/features/pricing/catalog_context_dialog.dart, frontend/lib/features/pricing/recommendation_decision_dialog.dart
    - evidence: frontend/test/pricing_encrypted_cost_dialog_test.dart, backend/tests/test_cost_encryption.py
  - [SCOPE-COST-LOCAL-VERIFICATION] Backend, frontend, static, migration and local PostgreSQL rollback-only encrypted-cost proofs pass; no synthetic cost row or key material remains in evidence.
    - artifacts: scripts/prove_encrypted_cost_runtime.py, docs/PROMPT_15_016_IMPLEMENTATION_REPORT_2026-07-18.md
    - evidence: command:590 backend tests passed, command:25 Flutter tests passed, command:RUNTIME_ENCRYPTED_COST_TRANSACTION_PASS, command:database head 20260718_0013
- strongest verified result:
  - claim: [CLM-COST-POSTGRES-AUTHENTICATED-ROUNDTRIP] The real local PostgreSQL schema accepted an encrypted synthetic cost, application services authenticated and decrypted it, the latest-value query resolved it, and rollback left zero synthetic records.
  - evidence level: E4
  - evidence: scripts/prove_encrypted_cost_runtime.py, backend/migrations/versions/20260718_0013_encrypted_catalog_cost.py, command:RUNTIME_ENCRYPTED_COST_TRANSACTION_PASS
  - reproduction status: reproducible
  - limitations: The proof used an ephemeral synthetic key and value in a rolled-back local transaction., A real deployment key and protected recovery drill were intentionally not fabricated.
- weakest critical area:
  - area: [AREA-COST-KEY-OPERATIONS] External production key provisioning and recovery
  - score/evidence floor: 50.0 / E2
  - reason: Code-level rotation and old-key reads are tested, but no real production secret or protected backup and restore drill exists.
  - impact: The encrypted feature implementation passes, while production activation remains blocked.
  - required resolution: Provision a real key through an approved secret boundary and complete rotation plus backup and restore validation without exposing key material.
- evidence quality:
  - highest level: E4
  - critical floor: E2
  - material claim coverage: 1.00
  - reproducible claim coverage: 1.00
  - freshness status: verified
  - representative scope: non_representative
  - limitations: No real Yuri cost value was used., The checkout has no Git metadata; evidence is path and runtime bound., Production secret custody and disaster recovery are not locally provable.
- production implication:
  - state: PRODUCTION_BLOCKED
  - production ready: false
  - evidence level: E4
  - passed hard gates: SERVER_SIDE_ENCRYPTED_IMPLEMENTATION, LOCAL_POSTGRES_TRANSACTION_PROOF, RAW_COST_RESPONSE_REDACTION, MANUAL_BELOW_COST_CONFIRMATION
  - failed hard gates: NONE_VERIFIED
  - blocked hard gates: COST_KEY_PROVISIONING_AND_RECOVERY, REPRESENTATIVE_CLIENT_CATALOG, REPRESENTATIVE_MARKET_REPLAY, SOURCE_ACCESS_PERMISSION, CONTROLLED_PILOT
  - statement: The requested encryption implementation passes, but that does not provision a real secret or authorize pilot or production use.

## Блокеры

BLOCKERS:
- P0:
  - NONE_VERIFIED
- P1:
  - [BLK-P1-COST-KEY-OPERATIONS] No real external deployment key or protected recovery drill is available.; owner=Operations owner; resolution=Provision a non-repository key through the approved secret boundary and pass rotation plus recovery tests.
  - [BLK-P1-REPRESENTATIVE-CATALOG] The real or approved anonymized Yuri catalog is unavailable for representative validation.; owner=Yuri and data owner; resolution=Supply a provenance-bound representative workbook approved for measurement.
  - [BLK-P1-SOURCE-AUTHORITY] Production live Prom collection lacks an immutable scope-specific authority artifact.; owner=Source and product owners; resolution=Record current production-scope permission or policy evidence.
- business decisions:
  - NONE_VERIFIED
- source/access:
  - BLK-P1-SOURCE-AUTHORITY
- data:
  - BLK-P1-REPRESENTATIVE-CATALOG
- environment/reproducibility:
  - BLK-P1-COST-KEY-OPERATIONS
- unknowns:
  - NONE_VERIFIED

## Следующая часть

NEXT_STAGE:
- id: COST_KEY_PROVISIONING_AND_RECOVERY_VALIDATION
- title: COST_KEY_PROVISIONING_AND_RECOVERY_VALIDATION
- why it is next:
  - Implementation and local encrypted persistence are complete; real secret custody and recovery are the first unverified encryption-specific transitions.
- required inputs:
  - [INPUT-APPROVED-COST-KEY-SECRET] A generated 256-bit cost key delivered through the approved secret boundary; source=Operations owner or secret manager; required_state=available to the target runtime without repository or evidence exposure; available=false; evidence=docs/PROMPT_15_016_COST_PRIVACY_ADR_2026-07-18.md
  - [INPUT-RECOVERY-TARGET] A non-production backup and restore target with approved encrypted test data; source=Operations owner; required_state=isolated, recoverable and approved for a destructive recovery rehearsal; available=false; evidence=docs/PROMPT_15_016_FINAL_GATE_MANIFEST_2026-07-18.yaml
- expected artifacts:
  - [ART-COST-KEY-RECOVERY-REPORT] report: должен быть создан; purpose=Prove secret provisioning, old and new key rotation, backup restore and key-loss failure behavior.; required_fields=secret_boundary, rotation_result, restore_result, key_loss_result, no_key_disclosure_evidence
- acceptance criteria:
  - [AC-COST-KEY-PROVISIONING] predicate=The target runtime starts in SERVER_SIDE_ENCRYPTED mode while the key remains absent from source, database, logs and evidence.; evidence=Secret-manager configuration metadata plus redacted runtime probe; threshold=No raw key material or raw cost appears outside the authorized runtime boundary
  - [AC-COST-RECOVERY] predicate=Backup restore and key rotation preserve authorized reads, new writes use the active key, and retired-key behavior is explicit.; evidence=Reproducible non-production recovery and rotation report; threshold=Every positive and failure-path assertion passes
- stop condition:
  - gate key: STOP_GATE_COST_KEY_PROVISIONING_AND_RECOVERY_VALIDATION
  - allowed states: PASS, FAIL, BLOCKED, NO_GO
  - automatic transition: false
- client decisions required:
  - NONE_VERIFIED

STOP_GATE_PROMPT_15_016_COST_ENCRYPTION_IMPLEMENTATION = PASS

MACHINE_READABLE_SUMMARY:

```yaml
schema:
  name: metis_marko_machine_readable_stage_summary
  version: 1.1.0
  generated_at: "2026-07-19T00:16:40+02:00"
  report_id: REPORT-PROMPT-15-016-COST-ENCRYPTION
  audit_id: VALIDATION-PROMPT-15-016-COST-ENCRYPTION
stage:
  id: PROMPT_15_016_COST_ENCRYPTION_IMPLEMENTATION
  title: YURI_V1_SERVER_SIDE_ENCRYPTED_COST_IMPLEMENTATION
  status: PASS
  status_reason: AES-256-GCM persistence, external keyring validation, safe API and UI boundaries, migration 0013, regression tests and a rollback-only local PostgreSQL proof pass.
  acceptance_criteria_passed: true
  audit_complete: true
  production_ready: false
  secondary_findings: []
  evidence_refs:
  - docs/PROMPT_15_016_COST_PRIVACY_ADR_2026-07-18.md
  - backend/tests/test_cost_encryption.py
  - frontend/test/pricing_encrypted_cost_dialog_test.dart
  - scripts/prove_encrypted_cost_runtime.py
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
      root: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis
      realpath: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis
      repository_top_level: null
      git_commit: null
      branch: null
      detached_head: null
      dirty_before_audit: null
      identity_verified: false
      runtime_import_path: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis
      evidence_refs:
      - backend/src/metis
    marko:
      root: /Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko
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
    status: BLOCKED
    passed_gates:
    - COST_FREE_FAIR_MARKET_ESTIMATION
    failed_gates: []
    blocked_gates:
    - REPRESENTATIVE_CLIENT_CATALOG
    - REPRESENTATIVE_MARKET_REPLAY
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
  - docs/PROMPT_15_016_REQUIREMENTS_TRACE_2026-07-18.yaml
  maturity_class: PRICING_KERNEL_PROTOTYPE
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
    status: BLOCKED
    passed_gates:
    - SERVER_SIDE_ENCRYPTED_IMPLEMENTATION
    - LOCAL_POSTGRES_TRANSACTION_PROOF
    - RAW_COST_RESPONSE_REDACTION
    failed_gates: []
    blocked_gates:
    - COST_KEY_PROVISIONING_AND_RECOVERY
    - SOURCE_ACCESS_PERMISSION
    - CONTROLLED_PILOT
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
  - docs/PROMPT_15_016_COST_PRIVACY_ADR_2026-07-18.md
  - backend/tests/test_cost_encryption.py
  maturity_class: INTEGRATED_PRODUCT_SHELL
  existing_scraper:
    located: UNKNOWN
    physical_path: null
    entry_point: null
    entry_point_verified: NOT_APPLICABLE
    input_contract_verified: NOT_APPLICABLE
    output_contract_verified: NOT_APPLICABLE
    runtime_reverified: NOT_APPLICABLE
    single_request_verified: NOT_APPLICABLE
    small_batch_verified: NOT_APPLICABLE
    batch_ready: NOT_APPLICABLE
    parallel_safe: NOT_APPLICABLE
    timeout_bounded: NOT_APPLICABLE
    retry_safe: NOT_APPLICABLE
    idempotent: NOT_APPLICABLE
    queue_integrated: NOT_APPLICABLE
    dead_letter_integrated: NOT_APPLICABLE
    raw_storage_integrated: NOT_APPLICABLE
    structured_storage_integrated: NOT_APPLICABLE
    metis_evidence_integrated: NOT_APPLICABLE
    replayable: NOT_APPLICABLE
    observable: NOT_APPLICABLE
    load_tested: NOT_APPLICABLE
    production_proven: NOT_APPLICABLE
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
    evidence_refs: []
  reusable_as_is: []
  adapt_before_reuse: []
  reference_only: []
  do_not_port: []
  unknown_reuse_state: []
  evaluated_component_ids: []
  reuse_partition_valid: null
combined_system:
  maturity_class: INTEGRATED_INTERNAL_SYSTEM
  end_to_end_flow_verified: PARTIAL
  end_to_end_evidence_level: E4
  trace_coverage: null
  verified_trace_coverage: null
  integrated_trace_coverage: null
  last_verified_node: Local PostgreSQL encrypted-cost record through authenticated decrypt, safe derived metadata and rollback
  first_unverified_node: REAL_KEY_PROVISIONING_AND_BACKUP_RESTORE
  first_broken_transition: null
  production_eligible: false
  production_gate:
    status: BLOCKED
    passed_gates:
    - SERVER_SIDE_ENCRYPTED_IMPLEMENTATION
    - LOCAL_POSTGRES_TRANSACTION_PROOF
    - MANUAL_OPERATOR_DECISION
    failed_gates: []
    blocked_gates:
    - COST_KEY_PROVISIONING_AND_RECOVERY
    - REPRESENTATIVE_CLIENT_CATALOG
    - REPRESENTATIVE_MARKET_REPLAY
    - SOURCE_ACCESS_PERMISSION
    - CONTROLLED_PILOT
    unknown_gates: []
  recommendation_contract:
    explainable: VERIFIED
    auditable: VERIFIED
    reproducible: PARTIAL
    insufficient_data_abstention: VERIFIED
    manual_review_routing: VERIFIED
  evidence_refs:
  - scripts/prove_encrypted_cost_runtime.py
  - frontend/test/pricing_encrypted_cost_dialog_test.dart
  - backend/tests/test_cost_encryption.py
gaps:
  p0: []
  p1: []
  p2: []
  p3: []
  priority_partition_valid: null
  duplicate_gap_ids: []
  critical_dependency_chain:
  - COST_KEY_PROVISIONING_AND_RECOVERY
  - REPRESENTATIVE_CLIENT_CATALOG
  - CONTROLLED_PILOT
  - PRODUCTION_READINESS
business_decisions_required:
- decision_id: DECISION-PROMPT-15-016-COST-PRIVACY
  title: Yuri V1 cost privacy architecture
  status: APPROVED
  owner: Yuri and product owner
  options:
  - LOCAL_DEVICE_ONLY
  - SERVER_SIDE_ENCRYPTED
  recommended_option: SERVER_SIDE_ENCRYPTED
  recommendation_basis: Yuri explicitly authorized implementation of encryption after the tradeoff was explained.
  default_assumption_for_planning: Raw cost remains fail-closed wherever the validated external keyring is absent.
  implementation_blocked: false
  blocked_scope: []
  required_before_stage: null
  evidence_refs:
  - docs/PROMPT_15_016_COST_PRIVACY_ADR_2026-07-18.md
source_access_states:
- source_id: PROM-SOURCE-NOT-USED-IN-COST-STAGE
  source_name: Prom.ua marketplace source
  source_type: public_marketplace_http
  state: NOT_APPLICABLE
  scope: The encrypted-cost implementation and verification made no live marketplace request.
  basis: null
  verified_at: null
  expires_at: null
  allowed_operations: []
  prohibited_operations:
  - live collection was outside this stage
  blocking_scope: []
  evidence_refs: []
engineering_assumptions: []
future_hypotheses: []
unknowns:
- unknown_id: UNKNOWN-COST-STAGE-REPOSITORY-SNAPSHOT
  field_path: repository.*
  question: Which canonical Git snapshot owns this physical checkout?
  reason_unknown: The checkout exposes no Git metadata.
  impact: Evidence is bound to physical paths, runtime state and file content rather than a commit.
  resolver_type: REPOSITORY_OWNER_INPUT
  required_input: Canonical repository and commit or signed source snapshot
  owner: Repository maintainer
  blocks:
  - PRODUCTION_PROVENANCE
  target_stage: COST_KEY_PROVISIONING_AND_RECOVERY_VALIDATION
- unknown_id: UNKNOWN-COST-STAGE-METIS-READINESS
  field_path: metis.*
  question: What is the weighted Metis readiness outside this cost-encryption stage?
  reason_unknown: No full readiness scoring was authorized or rerun for this bounded implementation.
  impact: No new weighted Metis readiness claim is made.
  resolver_type: FUTURE_AUDIT
  required_input: Approved weighted readiness audit
  owner: Product and engineering owners
  blocks:
  - PRODUCTION_READINESS_SCORE
  target_stage: null
- unknown_id: UNKNOWN-COST-STAGE-MARKO-READINESS
  field_path: marko.*
  question: What is the weighted Marko readiness outside this cost-encryption stage?
  reason_unknown: No full readiness scoring was authorized or rerun for this bounded implementation.
  impact: No new weighted Marko readiness claim is made.
  resolver_type: FUTURE_AUDIT
  required_input: Approved weighted readiness audit
  owner: Product and engineering owners
  blocks:
  - PRODUCTION_READINESS_SCORE
  target_stage: null
- unknown_id: UNKNOWN-COST-STAGE-COMBINED-COVERAGE
  field_path: combined_system.*
  question: What fraction of the complete production flow is covered by the bounded encrypted-cost proof?
  reason_unknown: The proof covered encryption services, PostgreSQL and UI contracts but did not provision a real key or run a representative full-stack pilot.
  impact: Exact combined trace ratios and full end-to-end verification are not claimed.
  resolver_type: FUTURE_INTEGRATION_VALIDATION
  required_input: Real secret provisioning plus non-production recovery and representative workflow evidence
  owner: Operations, product and data owners
  blocks:
  - FULL_END_TO_END_COST_PROOF
  target_stage: COST_KEY_PROVISIONING_AND_RECOVERY_VALIDATION
next_stage:
  id: COST_KEY_PROVISIONING_AND_RECOVERY_VALIDATION
  title: COST_KEY_PROVISIONING_AND_RECOVERY_VALIDATION
  objective: Provision a real external key and prove rotation plus backup and restore without disclosing key material.
  why_it_is_next: Code and local encrypted persistence pass; operational key custody and recovery are the first encryption-specific unverified transitions.
  required_inputs:
  - approved external 256-bit cost key
  - isolated non-production recovery target
  expected_outputs:
  - redacted key-provisioning evidence
  - rotation and recovery report
  acceptance_criteria:
  - target runtime starts in SERVER_SIDE_ENCRYPTED mode without key disclosure
  - old and new key reads, active-key writes, backup restore and failure paths pass
  stop_condition: STOP_GATE_COST_KEY_PROVISIONING_AND_RECOVERY_VALIDATION
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
  - EMPTY_CATEGORY_VERIFIED:marko.reuse_partition
  - EMPTY_CATEGORY_VERIFIED:gaps
termination:
  stop_gate_key: STOP_GATE_PROMPT_15_016_COST_ENCRYPTION_IMPLEMENTATION
  stop_gate_value: PASS
  stage_status_matches_stop_gate: true
  next_stage_started: false
  execution_stopped: true
  no_content_after_summary: true
```

