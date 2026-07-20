# METIS cross discovery measurement — validated result

Реализация завершена: восстановлен корректный description boundary Prom, закреплены 146 raw snapshots, независимость подтверждений переведена на seller_id, а exact-OE и one-hop cross discovery измерены на одной 30-OE выборке.

Фактический результат: exact OE дал 28/30 позиций и 91 seller candidate; OE + crosses — 28/30 и 155 candidates. Добавленные 64 строки остаются discovery ceiling: match/tier precision не размечены, поэтому pricing_eligible=false и ни одной рекомендации не выпущено.

Полный backend-контроль: ruff passed; 666 tests passed, 1 skipped. Workbook визуально проверен, formula errors не обнаружены.

[Открыть итоговый Excel](</Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/outputs/metis_cross_coverage_20260719/METIS_EXACT_OE_VS_CROSSES.xlsx>)

## Структурированный результат текущего этапа

STAGE_RESULT:
- stage:
  - id: METIS_CROSS_DISCOVERY_MEASUREMENT_2026_07_19
  - title: METIS CROSS DISCOVERY MEASUREMENT
  - type: IMPLEMENTATION
  - scope owner: Metis
- status: PASS
- completed scope:
  - [SCOPE-DESCRIPTION-BOUNDARY] Prom descriptionPlain and descriptionFull evidence is normalized into Product.description without modifying the frozen Prom parser.
    - artifacts: backend/src/marko/services/parser_models.py, scripts/capture_prom_product_descriptions.py, backend/tests/test_models.py, backend/tests/test_product_description_snapshot.py
    - evidence: 146 of 146 pinned product pages have descriptions, 146 gzip raw evidence files
  - [SCOPE-INDEPENDENT-CROSS-CONTRACT] One-hop cross links require CONFIRMED status and at least two independent sellers counted by stable seller ID with a name fallback.
    - artifacts: backend/src/metis/pricing/crosses.py, scripts/run_description_crosses_replay.py, backend/tests/test_description_crosses.py
    - evidence: 60 eligible links across 5 target OEs, same seller ID with different display names remains one independent seller
  - [SCOPE-SAME-SET-AB-DISCOVERY] Exact OE and OE plus one-hop crosses were measured over the same pinned 30-OE sample with independent KEMP retained and the owned seller excluded by seller ID.
    - artifacts: scripts/run_cross_discovery.py, .artifacts/metis_cross_coverage_20260719/METIS_CROSS_COVERAGE_SUMMARY.json, outputs/metis_cross_coverage_20260719/METIS_EXACT_OE_VS_CROSSES.xlsx
    - evidence: exact OE 28 of 30 positions and 91 seller candidates, cross discovery 28 of 30 positions and 155 seller candidates, 60 of 60 search queries replayed with zero network requests
  - [SCOPE-FAIL-CLOSED-PRICING] Every cross-discovered offer remains pricing_eligible false until category, human match, and human tier labels pass; no recommendation was emitted.
    - artifacts: scripts/run_cross_discovery.py, backend/tests/test_cross_discovery.py
    - evidence: match precision null, tier precision null, zero confident recommendations, zero erroneous upward recommendations emitted
  - [SCOPE-REVIEW-WORKBOOK-AND-DOD] A formula-driven review workbook and an explicit Milestone 1 Definition of Done were created and inspected.
    - artifacts: outputs/metis_cross_coverage_20260719/METIS_EXACT_OE_VS_CROSSES.xlsx, docs/METIS_MILESTONE_1_DEFINITION_OF_DONE_2026-07-19.md, docs/METIS_EXACT_OE_VS_CROSSES_DISCOVERY_2026-07-19.md
    - evidence: six rendered workbook ranges visually inspected, no spreadsheet formula error tokens
- strongest verified result:
  - claim: [CLM-SAME-SET-CROSS-DISCOVERY-MEASURED] On the same pinned 30-OE set, one-hop cross discovery added 64 unvalidated independent-seller candidates and improved the at-least-two-seller count from 19 to 20 positions, while recommendation emission remained disabled.
  - evidence level: E3
  - evidence: .artifacts/metis_cross_coverage_20260719/METIS_CROSS_COVERAGE_SUMMARY.json, outputs/metis_cross_coverage_20260719/METIS_EXACT_OE_VS_CROSSES.xlsx, 666 passed and 1 skipped
  - reproduction status: reproducible
  - limitations: The 30-OE discovery sample is not a production population estimate., Cross-match and tier precision remain unlabeled., Added candidates are not claimed as valid competitors or commercial lift.
- weakest critical area:
  - area: [AREA-CROSS-MATCH-AND-TIER-PRECISION] Independent cross-match and brand-tier validation
  - score/evidence floor: NOT_SCORED / E2
  - reason: The review workbook is complete, but its human match and tier labels are intentionally blank.
  - impact: Cross-derived offers cannot enter pricing and no commercial lift can be claimed.
  - required resolution: Independently label all 60 cross links and the retained offer review set, then compute precision and confidence intervals.
- evidence quality:
  - highest level: E3
  - critical floor: E2
  - material claim coverage: 1.00
  - reproducible claim coverage: 1.00
  - freshness status: verified
  - representative scope: non_representative
  - limitations: Live evidence is a stratified 30-OE discovery sample., Human validation has not started.
- production implication:
  - state: RESEARCH_ONLY
  - production ready: false
  - evidence level: E3
  - passed hard gates: PINNED_DESCRIPTION_EVIDENCE, MULTI_SELLER_CROSS_DISCOVERY, OFFLINE_REPLAY, FAIL_CLOSED_PRICING, REVIEW_WORKBOOK
  - failed hard gates: NONE_VERIFIED
  - blocked hard gates: INDEPENDENT_MATCH_PRECISION, APPROVED_NON_KEMP_TIER_POLICY, INDEPENDENT_TIER_PRECISION, REPRESENTATIVE_COMMERCIAL_VALIDATION
  - statement: The implementation and discovery measurement are complete; cross-derived automatic pricing and production readiness are not asserted.

## Блокеры

BLOCKERS:
- P0:
  - NONE_VERIFIED
- P1:
  - [BLK-APPROVED-NON-KEMP-TIER-POLICY] No customer-approved non-KEMP brand and tier policy exists for measuring or activating tier-aware cross pricing.; owner=customer or authorized domain expert; resolution=Approve a versioned non-KEMP brand and tier policy with provenance and effective date.
- business decisions:
  - BLK-APPROVED-NON-KEMP-TIER-POLICY
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
- id: METIS_CROSS_HUMAN_VALIDATION
- title: METIS CROSS HUMAN VALIDATION
- why it is next:
  - Coverage discovery is now measured, so the decision-critical unknowns are match precision and tier precision.
  - Human validation is mandatory before any cross-derived price action or commercial-lift claim.
- required inputs:
  - [INPUT-CROSS-REVIEW-WORKBOOK] The generated workbook containing 60 cross-link rows and 95 discovery-offer rows.; source=outputs/metis_cross_coverage_20260719/METIS_EXACT_OE_VS_CROSSES.xlsx; required_state=blank review controls ready for an independent domain reviewer; available=true; evidence=workbook visual inspection
  - [INPUT-APPROVED-TIER-POLICY] Customer-approved non-KEMP brand and tier rules with provenance and effective date.; source=customer or authorized domain expert; required_state=approved rather than draft; available=false; evidence=current Stage C preflight reports an empty approved non-KEMP dictionary
- expected artifacts:
  - [ART-COMPLETED-CROSS-REVIEW] dataset: должен быть создан; purpose=Provide independent match, tier, condition, and availability labels.; required_fields=human_match_label, human_tier_label, reviewer, notes
  - [ART-CROSS-PRECISION-REPORT] report: должен быть создан; purpose=Measure link precision, offer precision, tier precision, confidence intervals, coverage lift, and unsafe recommendation count.; required_fields=match_precision, tier_precision, confidence_intervals, actionable_position_lift, erroneous_upward_recommendations
- acceptance criteria:
  - [AC-CROSS-REVIEW-01] predicate=Every eligible link has MATCH, NOT_MATCH, or UNCERTAIN plus reviewer provenance.; evidence=completed link-review sheet; threshold=60 of 60 links labeled
  - [AC-CROSS-REVIEW-02] predicate=Every retained discovery candidate has match, tier, condition, and availability review fields resolved or explicitly uncertain.; evidence=completed offer-review sheet; threshold=95 of 95 rows reviewed
  - [AC-CROSS-REVIEW-03] predicate=Cross activation remains fail closed unless approved precision and safety thresholds pass.; evidence=precision report and recommendation replay; threshold=no activation from missing or unknown metrics
- stop condition:
  - gate key: STOP_GATE_METIS_CROSS_HUMAN_VALIDATION
  - allowed states: PASS, FAIL, BLOCKED, NO_GO
  - automatic transition: false
- client decisions required:
  - NONE_VERIFIED

STOP_GATE_METIS_CROSS_DISCOVERY_MEASUREMENT_2026_07_19 = PASS

MACHINE_READABLE_SUMMARY:
```yaml
schema:
  name: metis_marko_machine_readable_stage_summary
  version: 1.1.0
  generated_at: "2026-07-19T21:10:00+02:00"
  report_id: REPORT-METIS-CROSS-DISCOVERY-2026-07-19
  audit_id: VALIDATION-METIS-CROSS-DISCOVERY-2026-07-19
stage:
  id: METIS_CROSS_DISCOVERY_MEASUREMENT_2026_07_19
  title: METIS CROSS DISCOVERY MEASUREMENT
  status: PASS
  status_reason: The same-set exact-OE versus one-hop-cross discovery measurement, fail-closed controls, review workbook, and reproducible offline replay all passed.
  acceptance_criteria_passed: true
  audit_complete: true
  production_ready: false
  secondary_findings:
    - type: PASS
      finding_id: FINDING-CROSS-PRICING-FAIL-CLOSED
      finding: Cross-derived automatic pricing correctly remains disabled while match and tier precision are unlabeled.
      evidence_refs:
        - .artifacts/metis_cross_coverage_20260719/METIS_CROSS_COVERAGE_SUMMARY.json
        - backend/tests/test_cross_discovery.py
  evidence_refs:
    - 146 of 146 pinned descriptions available
    - 60 of 60 cross queries replayed with zero network requests
    - exact OE 28 of 30 positions and 91 seller candidates
    - cross discovery 28 of 30 positions and 155 seller candidates
    - 666 passed and 1 skipped
repository:
  audit_root: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия"
  audit_root_realpath: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия"
  topology: UNKNOWN
  git_commit: null
  dirty_before_audit: null
  identity_verified: false
  runtime_import_identity: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src"
  components:
    metis:
      root: backend/src/metis
      realpath: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis"
      repository_top_level: null
      git_commit: null
      branch: null
      detached_head: null
      dirty_before_audit: null
      identity_verified: false
      runtime_import_path: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/metis"
      evidence_refs:
        - backend/src/metis
    marko:
      root: backend/src/marko
      realpath: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko"
      repository_top_level: null
      git_commit: null
      branch: null
      detached_head: null
      dirty_before_audit: null
      identity_verified: false
      runtime_import_path: "/Users/leonidpofa/VSCodeHruchevoPY/SaaS/marko/marko — копия/backend/src/marko"
      evidence_refs:
        - backend/src/marko
  duplicate_copies: []
  unresolved_identity_conflicts:
    - NO_GIT_METADATA
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
  production_gate:
    status: BLOCKED
    passed_gates:
      - PINNED_DESCRIPTION_EVIDENCE
      - MULTI_SELLER_CROSS_DISCOVERY
      - OFFLINE_REPLAY
      - FAIL_CLOSED_PRICING
    failed_gates: []
    blocked_gates:
      - INDEPENDENT_MATCH_PRECISION
      - APPROVED_NON_KEMP_TIER_POLICY
      - INDEPENDENT_TIER_PRECISION
    unknown_gates:
      - REPRESENTATIVE_COMMERCIAL_VALIDATION
  dimension_weights: {implementation: 0.20, verification: 0.15, integration: 0.15, auditability: 0.15, operations: 0.15, security: 0.10, documentation: 0.10}
  capabilities: []
  critical_capability_ids: []
  strongest_domains: []
  missing_critical_domains: []
  evidence_refs:
    - backend/src/metis/pricing/crosses.py
    - scripts/run_description_crosses_replay.py
    - scripts/run_cross_discovery.py
  maturity_class: PRICING_KERNEL_PROTOTYPE
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
  production_gate:
    status: NOT_EVALUATED
    passed_gates: []
    failed_gates: []
    blocked_gates: []
    unknown_gates:
      - PROJECT_READINESS_NOT_ASSESSED
  dimension_weights: {implementation: 0.20, verification: 0.15, integration: 0.15, auditability: 0.15, operations: 0.15, security: 0.10, documentation: 0.10}
  capabilities: []
  critical_capability_ids: []
  strongest_domains: []
  missing_critical_domains: []
  evidence_refs:
    - backend/src/marko/services/parser_models.py
    - backend/src/marko/parsers/prom/gateway.py
  maturity_class: UNKNOWN
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
    parallel_safe: UNKNOWN
    timeout_bounded: VERIFIED
    retry_safe: VERIFIED
    idempotent: PARTIAL
    queue_integrated: UNKNOWN
    dead_letter_integrated: UNKNOWN
    raw_storage_integrated: VERIFIED
    structured_storage_integrated: VERIFIED
    metis_evidence_integrated: PARTIAL
    replayable: VERIFIED
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
      - 146 pinned product-page snapshots
      - 60 pinned search-query snapshots
      - backend/tests/test_product_description_snapshot.py
      - backend/tests/test_prom_search_boundary.py
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
  last_verified_node: CROSS_DISCOVERY_REVIEW_EXPORT
  first_unverified_node: INDEPENDENT_CROSS_MATCH_LABEL
  first_broken_transition: null
  production_eligible: false
  production_gate:
    status: BLOCKED
    passed_gates:
      - CROSS_DISCOVERY_REPLAY
      - INSUFFICIENT_DATA_ABSTENTION
    failed_gates: []
    blocked_gates:
      - HUMAN_MATCH_VALIDATION
      - HUMAN_TIER_VALIDATION
    unknown_gates:
      - COMMERCIAL_OUTCOME_VALIDATION
  recommendation_contract:
    explainable: PARTIAL
    auditable: VERIFIED
    reproducible: VERIFIED
    insufficient_data_abstention: VERIFIED
    manual_review_routing: VERIFIED
  evidence_refs:
    - outputs/metis_cross_coverage_20260719/METIS_EXACT_OE_VS_CROSSES.xlsx
    - .artifacts/metis_cross_coverage_20260719/METIS_CROSS_COVERAGE_SUMMARY.json
gaps:
  p0: []
  p1: []
  p2: []
  p3: []
  priority_partition_valid: true
  duplicate_gap_ids: []
  critical_dependency_chain: []
business_decisions_required:
  - decision_id: DECISION-APPROVED-NON-KEMP-TIER-POLICY
    title: Approve the non-KEMP brand and tier policy
    status: MISSING
    owner: customer or authorized domain expert
    options:
      - approve a versioned tier dictionary
      - keep all non-KEMP tiers UNKNOWN
    recommended_option: approve a versioned tier dictionary from independently reviewed evidence
    recommendation_basis: Tier precision cannot be measured or activated against draft or synthetic labels.
    default_assumption_for_planning: Non-KEMP tier-aware pricing remains disabled.
    implementation_blocked: true
    blocked_scope:
      - TIER_PRECISION
      - CROSS_DERIVED_AUTOMATIC_PRICING
    required_before_stage: METIS_CROSS_HUMAN_VALIDATION
    evidence_refs:
      - Stage C preflight reports an empty approved non-KEMP dictionary
source_access_states:
  - source_id: SOURCE-PROM-PINNED-DISCOVERY
    source_name: Prom public product and search pages used by the pinned experiment
    source_type: public_web
    state: UNKNOWN
    scope: 146 supplied product URLs and 60 bounded cross search queries
    basis: null
    verified_at: null
    expires_at: null
    allowed_operations: []
    prohibited_operations: []
    blocking_scope: []
    evidence_refs:
      - .artifacts/metis_cross_coverage_20260719/METIS_DESCRIPTION_SNAPSHOT_MANIFEST.json
engineering_assumptions: []
future_hypotheses:
  - hypothesis_id: HYPOTHESIS-CROSS-COMMERCIAL-LIFT
    statement: Independently validated one-hop crosses may increase actionable market coverage beyond exact OE alone.
    expected_value: More positions with at least two valid independent sellers without unacceptable precision or unsafe upward recommendations.
    required_data:
      - completed 60-link review
      - completed 95-offer review
      - approved tier policy
      - recommendation replay
    falsification_test: Reject the module if valid actionable-position lift is negligible or safety and precision thresholds fail.
    earliest_applicable_stage: METIS_CROSS_HUMAN_VALIDATION
    current_action: Keep the hypothesis separate from current facts and do not price or sell the module as proven lift.
    evidence_refs:
      - docs/METIS_EXACT_OE_VS_CROSSES_DISCOVERY_2026-07-19.md
unknowns:
  - unknown_id: UNKNOWN-REPOSITORY-SNAPSHOT
    field_path: repository.*
    question: Which canonical Git commit owns this workspace?
    reason_unknown: No Git metadata is present in the project tree.
    impact: Evidence is path and hash bound rather than commit bound.
    resolver_type: REPOSITORY_OWNER_INPUT
    required_input: Canonical repository identity or initialized Git metadata
    owner: repository maintainer
    blocks:
      - AUDITED_RELEASE
    target_stage: RELEASE_PROVENANCE
  - unknown_id: UNKNOWN-METIS-READINESS
    field_path: metis.*
    question: What is full-project Metis readiness?
    reason_unknown: This stage measured description-cross discovery only.
    impact: No weighted readiness or production eligibility score is claimed.
    resolver_type: PROJECT_STATE_AUDIT
    required_input: Representative project-wide audit
    owner: engineering
    blocks:
      - METIS_PRODUCTION_GATE
    target_stage: PROJECT_READINESS_ASSESSMENT
  - unknown_id: UNKNOWN-MARKO-READINESS
    field_path: marko.*
    question: What is full-project Marko readiness?
    reason_unknown: This stage changed and verified only extraction boundaries used by cross discovery.
    impact: No weighted Marko readiness score is claimed.
    resolver_type: PROJECT_STATE_AUDIT
    required_input: Representative project-wide audit
    owner: engineering
    blocks:
      - MARKO_PRODUCTION_GATE
    target_stage: PROJECT_READINESS_ASSESSMENT
  - unknown_id: UNKNOWN-COMBINED-TRACE
    field_path: combined_system.*
    question: What share of the full Marko to Metis recommendation trace is production verified?
    reason_unknown: The current path intentionally stops before human validation and recommendation emission.
    impact: Production and commercial-readiness claims remain blocked.
    resolver_type: END_TO_END_REVALIDATION
    required_input: Completed human labels and representative recommendation replay
    owner: engineering and domain reviewer
    blocks:
      - COMBINED_PRODUCTION_GATE
    target_stage: METIS_CROSS_HUMAN_VALIDATION
next_stage:
  id: METIS_CROSS_HUMAN_VALIDATION
  title: METIS CROSS HUMAN VALIDATION
  objective: Independently label the 60 cross links and 95 discovery offers, approve the tier policy, and measure precision and safety before pricing activation.
  why_it_is_next: Coverage discovery is measured; match precision and tier precision are now the decision-critical unknowns.
  required_inputs:
    - completed reviewer identity and provenance
    - generated cross review workbook
    - approved non-KEMP tier policy
  expected_outputs:
    - completed review dataset must be created
    - precision and confidence-interval report must be created
    - fail-closed recommendation replay must be created
  acceptance_criteria:
    - 60 of 60 links are labeled
    - 95 of 95 offers are reviewed
    - no cross activation occurs from missing or unknown metrics
  stop_condition: STOP_GATE_METIS_CROSS_HUMAN_VALIDATION with no automatic continuation
  client_decisions_required:
    - DECISION-APPROVED-NON-KEMP-TIER-POLICY
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
    - PROJECT_READINESS_NOT_ASSESSED
    - REPOSITORY_SNAPSHOT_NOT_GIT_BOUND
    - HUMAN_CROSS_LABELS_PENDING
    - EMPTY_CATEGORY_VERIFIED:marko.reuse_partition
    - EMPTY_CATEGORY_VERIFIED:gaps
termination:
  stop_gate_key: STOP_GATE_METIS_CROSS_DISCOVERY_MEASUREMENT_2026_07_19
  stop_gate_value: PASS
  stage_status_matches_stop_gate: true
  next_stage_started: false
  execution_stopped: true
  no_content_after_summary: true
```
