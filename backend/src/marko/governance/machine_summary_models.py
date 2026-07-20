"""Typed Section 16 machine-readable stage-summary schema."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
)

from .response_footer import EvidenceLevel, StageStatus


SCHEMA_NAME = "metis_marko_machine_readable_stage_summary"
SCHEMA_VERSION = "1.1.0"

Ratio: TypeAlias = Annotated[StrictFloat, Field(ge=0, le=1)]
Score: TypeAlias = Annotated[StrictFloat, Field(ge=0, le=100)]
PositiveRate: TypeAlias = Annotated[StrictFloat, Field(ge=0)]
NonNegativeInt: TypeAlias = Annotated[StrictInt, Field(ge=0)]


class VerificationState(StrEnum):
    VERIFIED = "VERIFIED"
    NOT_VERIFIED = "NOT_VERIFIED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CapabilityState(StrEnum):
    READY_VERIFIED = "READY_VERIFIED"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"
    CONTRADICTED = "CONTRADICTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ProductionGateStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NO_GO = "NO_GO"
    NOT_EVALUATED = "NOT_EVALUATED"


class RepositoryTopology(StrEnum):
    MONOREPO = "MONOREPO"
    MULTI_REPO = "MULTI_REPO"
    NESTED_REPOSITORIES = "NESTED_REPOSITORIES"
    MIXED_WORKTREE = "MIXED_WORKTREE"
    UNKNOWN = "UNKNOWN"


class QueueStability(StrEnum):
    STABLE = "STABLE"
    UNSTABLE = "UNSTABLE"
    NOT_MEASURED = "NOT_MEASURED"
    UNKNOWN = "UNKNOWN"


class MetisMaturity(StrEnum):
    RESEARCH_DATA_KERNEL = "RESEARCH_DATA_KERNEL"
    PRICING_KERNEL_PROTOTYPE = "PRICING_KERNEL_PROTOTYPE"
    INTEGRATED_INTERNAL_TOOL = "INTEGRATED_INTERNAL_TOOL"
    PILOT_CAPABLE_ENGINE = "PILOT_CAPABLE_ENGINE"
    PRODUCTION_CANDIDATE_ENGINE = "PRODUCTION_CANDIDATE_ENGINE"
    PRODUCTION_PRICING_ENGINE = "PRODUCTION_PRICING_ENGINE"
    UNKNOWN = "UNKNOWN"


class MarkoMaturity(StrEnum):
    PARTIAL_PRODUCT_REFERENCE = "PARTIAL_PRODUCT_REFERENCE"
    REUSABLE_PRODUCT_SHELL = "REUSABLE_PRODUCT_SHELL"
    INTEGRATED_PRODUCT_SHELL = "INTEGRATED_PRODUCT_SHELL"
    PILOT_CAPABLE_SAAS_SHELL = "PILOT_CAPABLE_SAAS_SHELL"
    PRODUCTION_CANDIDATE_SAAS_SHELL = "PRODUCTION_CANDIDATE_SAAS_SHELL"
    PRODUCTION_SAAS_SHELL = "PRODUCTION_SAAS_SHELL"
    INCOMPATIBLE_REFERENCE = "INCOMPATIBLE_REFERENCE"
    UNKNOWN = "UNKNOWN"


class CombinedMaturity(StrEnum):
    DISCONNECTED_COMPONENTS = "DISCONNECTED_COMPONENTS"
    PARTIAL_INTEGRATION = "PARTIAL_INTEGRATION"
    INTEGRATED_INTERNAL_SYSTEM = "INTEGRATED_INTERNAL_SYSTEM"
    HONEST_PILOT_CANDIDATE = "HONEST_PILOT_CANDIDATE"
    PRODUCTION_CANDIDATE = "PRODUCTION_CANDIDATE"
    PRODUCTION_SYSTEM = "PRODUCTION_SYSTEM"
    NO_GO_ARCHITECTURE = "NO_GO_ARCHITECTURE"
    UNKNOWN = "UNKNOWN"


class ReuseClassification(StrEnum):
    REUSABLE_AS_IS = "REUSABLE_AS_IS"
    ADAPT_BEFORE_REUSE = "ADAPT_BEFORE_REUSE"
    REFERENCE_ONLY = "REFERENCE_ONLY"
    DO_NOT_PORT = "DO_NOT_PORT"
    UNKNOWN = "UNKNOWN"


class GapPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class GapSystem(StrEnum):
    METIS = "METIS"
    MARKO = "MARKO"
    COMBINED = "COMBINED"
    SHARED = "SHARED"


class GapType(StrEnum):
    MISSING_IMPLEMENTATION = "MISSING_IMPLEMENTATION"
    PARTIAL_IMPLEMENTATION = "PARTIAL_IMPLEMENTATION"
    INTEGRATION_GAP = "INTEGRATION_GAP"
    DATA_MODEL_GAP = "DATA_MODEL_GAP"
    EVIDENCE_GAP = "EVIDENCE_GAP"
    REPLAY_GAP = "REPLAY_GAP"
    SECURITY_GAP = "SECURITY_GAP"
    TENANT_ISOLATION_GAP = "TENANT_ISOLATION_GAP"
    OBSERVABILITY_GAP = "OBSERVABILITY_GAP"
    DEPLOYMENT_GAP = "DEPLOYMENT_GAP"
    CAPACITY_GAP = "CAPACITY_GAP"
    SOURCE_ACCESS_GAP = "SOURCE_ACCESS_GAP"
    BUSINESS_DECISION_GAP = "BUSINESS_DECISION_GAP"
    UNKNOWN_GAP = "UNKNOWN_GAP"


class DecisionStatus(StrEnum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PROPOSED = "PROPOSED"
    MISSING = "MISSING"
    CONTRADICTORY = "CONTRADICTORY"
    DEFERRED = "DEFERRED"
    UNKNOWN = "UNKNOWN"


class SourceAccessState(StrEnum):
    PERMITTED = "PERMITTED"
    CONDITIONAL = "CONDITIONAL"
    NOT_PERMITTED = "NOT_PERMITTED"
    BLOCKED_PENDING_DECISION = "BLOCKED_PENDING_DECISION"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AssumptionStatus(StrEnum):
    UNVALIDATED = "UNVALIDATED"
    PARTIALLY_VALIDATED = "PARTIALLY_VALIDATED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class _SummaryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        serialize_by_alias=True,
        validate_by_alias=True,
        validate_by_name=True,
    )


class SchemaIdentity(_SummaryModel):
    name: Literal[SCHEMA_NAME] = SCHEMA_NAME
    version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    generated_at: StrictStr | None
    report_id: StrictStr | None
    audit_id: StrictStr | None


class SummarySecondaryFinding(_SummaryModel):
    type: StageStatus
    finding_id: StrictStr = Field(min_length=1)
    finding: StrictStr = Field(min_length=1)
    evidence_refs: tuple[StrictStr, ...] = ()


class MachineStage(_SummaryModel):
    id: StrictStr = Field(min_length=1)
    title: StrictStr = Field(min_length=1)
    status: StageStatus
    status_reason: StrictStr | None
    acceptance_criteria_passed: StrictBool | None
    audit_complete: StrictBool | None
    production_ready: StrictBool | None
    secondary_findings: tuple[SummarySecondaryFinding, ...] = ()
    evidence_refs: tuple[StrictStr, ...] = ()


class RepositoryComponent(_SummaryModel):
    root: StrictStr | None
    realpath: StrictStr | None
    repository_top_level: StrictStr | None
    git_commit: StrictStr | None
    branch: StrictStr | None
    detached_head: StrictBool | None
    dirty_before_audit: StrictBool | None
    identity_verified: StrictBool | None
    runtime_import_path: StrictStr | None
    evidence_refs: tuple[StrictStr, ...] = ()


class RepositoryComponents(_SummaryModel):
    metis: RepositoryComponent
    marko: RepositoryComponent


class RepositoryIdentity(_SummaryModel):
    audit_root: StrictStr | None
    audit_root_realpath: StrictStr | None
    topology: RepositoryTopology
    git_commit: StrictStr | None
    dirty_before_audit: StrictBool | None
    identity_verified: StrictBool | None
    runtime_import_identity: StrictStr | None
    components: RepositoryComponents
    duplicate_copies: tuple[StrictStr, ...] = ()
    unresolved_identity_conflicts: tuple[StrictStr, ...] = ()


class ReadinessInterval(_SummaryModel):
    lower: Score | None
    upper: Score | None


class ReadinessDimensionWeights(_SummaryModel):
    implementation: Ratio = 0.20
    verification: Ratio = 0.15
    integration: Ratio = 0.15
    auditability: Ratio = 0.15
    operations: Ratio = 0.15
    security: Ratio = 0.10
    documentation: Ratio = 0.10


class ReadinessDimensions(_SummaryModel):
    implementation: Ratio | None
    verification: Ratio | None
    integration: Ratio | None
    auditability: Ratio | None
    operations: Ratio | None
    security: Ratio | None
    documentation: Ratio | None


class CapabilityReadiness(_SummaryModel):
    capability_id: StrictStr = Field(min_length=1)
    name: StrictStr = Field(min_length=1)
    weight: Ratio
    critical: StrictBool
    dimensions: ReadinessDimensions
    evidence_level: EvidenceLevel
    raw_interval: ReadinessInterval
    effective_interval: ReadinessInterval
    unknown_dimension_weight: Ratio
    evidence_refs: tuple[StrictStr, ...] = ()


class ProductionGate(_SummaryModel):
    status: ProductionGateStatus
    passed_gates: tuple[StrictStr, ...] = ()
    failed_gates: tuple[StrictStr, ...] = ()
    blocked_gates: tuple[StrictStr, ...] = ()
    unknown_gates: tuple[StrictStr, ...] = ()


class StrongestDomain(_SummaryModel):
    domain_id: StrictStr = Field(min_length=1)
    name: StrictStr = Field(min_length=1)
    effective_readiness: Score
    evidence_level: EvidenceLevel
    critical: StrictBool
    why_strong: StrictStr = Field(min_length=1)
    limitations: tuple[StrictStr, ...] = ()
    evidence_refs: tuple[StrictStr, ...] = ()


class MissingCriticalDomain(_SummaryModel):
    domain_id: StrictStr = Field(min_length=1)
    name: StrictStr = Field(min_length=1)
    state: CapabilityState
    effective_readiness: Score
    evidence_level: EvidenceLevel
    reason: StrictStr = Field(min_length=1)
    blocks: tuple[StrictStr, ...] = ()
    gap_refs: tuple[StrictStr, ...] = ()
    evidence_refs: tuple[StrictStr, ...] = ()


class SystemReadinessBase(_SummaryModel):
    weighted_readiness: Score | None
    readiness_interval: ReadinessInterval
    readiness_scale: Literal["0_100"] = "0_100"
    score_basis: Literal["CONSERVATIVE_LOWER_BOUND"] = "CONSERVATIVE_LOWER_BOUND"
    critical_floor: Score | None
    evidence_level: EvidenceLevel | None
    evidence_level_semantics: Literal["CRITICAL_EVIDENCE_FLOOR"] = (
        "CRITICAL_EVIDENCE_FLOOR"
    )
    highest_evidence_level: EvidenceLevel | None
    unknown_weight: Ratio | None
    critical_unknown_count: NonNegativeInt | None
    engineering_weights_approved: StrictBool
    production_eligible: StrictBool
    production_gate: ProductionGate
    dimension_weights: ReadinessDimensionWeights = ReadinessDimensionWeights()
    capabilities: tuple[CapabilityReadiness, ...] = ()
    critical_capability_ids: tuple[StrictStr, ...] = ()
    strongest_domains: tuple[StrongestDomain, ...] = ()
    missing_critical_domains: tuple[MissingCriticalDomain, ...] = ()
    evidence_refs: tuple[StrictStr, ...] = ()


class MetisSummary(SystemReadinessBase):
    maturity_class: MetisMaturity


class ScraperCapacity(_SummaryModel):
    measured: StrictBool
    unique_urls: NonNegativeInt | None
    arrival_rate_urls_per_second: PositiveRate | None
    worker_service_rate_urls_per_second: PositiveRate | None
    active_workers: NonNegativeInt | None
    average_attempts_per_unique_url: Annotated[StrictFloat, Field(gt=0)] | None
    effective_worker_service_rate: PositiveRate | None
    total_capacity_urls_per_second: PositiveRate | None
    utilization_rho: PositiveRate | None
    queue_backlog: NonNegativeInt | None
    queue_stability: QueueStability
    estimated_drain_seconds: PositiveRate | None
    success_rate: Ratio | None
    retry_amplification: Annotated[StrictFloat, Field(ge=1)] | None
    latency_p50_seconds: PositiveRate | None
    latency_p95_seconds: PositiveRate | None
    latency_p99_seconds: PositiveRate | None
    raw_storage_bytes: NonNegativeInt | None
    structured_storage_bytes: NonNegativeInt | None
    memory_peak_bytes: NonNegativeInt | None
    cpu_average_percent: Score | None


class ExistingScraper(_SummaryModel):
    located: VerificationState
    physical_path: StrictStr | None
    entry_point: StrictStr | None
    entry_point_verified: VerificationState
    input_contract_verified: VerificationState
    output_contract_verified: VerificationState
    runtime_reverified: VerificationState
    single_request_verified: VerificationState
    small_batch_verified: VerificationState
    batch_ready: VerificationState
    parallel_safe: VerificationState
    timeout_bounded: VerificationState
    retry_safe: VerificationState
    idempotent: VerificationState
    queue_integrated: VerificationState
    dead_letter_integrated: VerificationState
    raw_storage_integrated: VerificationState
    structured_storage_integrated: VerificationState
    metis_evidence_integrated: VerificationState
    replayable: VerificationState
    observable: VerificationState
    load_tested: VerificationState
    production_proven: VerificationState
    capacity: ScraperCapacity
    evidence_refs: tuple[StrictStr, ...] = ()


class ReuseComponent(_SummaryModel):
    component_id: StrictStr = Field(min_length=1)
    component_path: StrictStr = Field(min_length=1)
    classification: ReuseClassification
    functional_fit: Ratio | None
    metis_invariant_compatibility: Ratio | None
    data_model_compatibility: Ratio | None
    verification_strength: Ratio | None
    adaptation_cost: Ratio | None
    reuse_score: Score | None
    required_adaptations: tuple[StrictStr, ...] = ()
    preserved_metis_invariants: tuple[StrictStr, ...] = ()
    violated_metis_invariants: tuple[StrictStr, ...] = ()
    evidence_refs: tuple[StrictStr, ...] = ()


class MarkoSummary(SystemReadinessBase):
    maturity_class: MarkoMaturity
    existing_scraper: ExistingScraper
    reusable_as_is: tuple[ReuseComponent, ...] = ()
    adapt_before_reuse: tuple[ReuseComponent, ...] = ()
    reference_only: tuple[ReuseComponent, ...] = ()
    do_not_port: tuple[ReuseComponent, ...] = ()
    unknown_reuse_state: tuple[ReuseComponent, ...] = ()
    evaluated_component_ids: tuple[StrictStr, ...] = ()
    reuse_partition_valid: StrictBool | None


class RecommendationContract(_SummaryModel):
    explainable: VerificationState
    auditable: VerificationState
    reproducible: VerificationState
    insufficient_data_abstention: VerificationState
    manual_review_routing: VerificationState


class CombinedSystemSummary(_SummaryModel):
    maturity_class: CombinedMaturity
    end_to_end_flow_verified: VerificationState
    end_to_end_evidence_level: EvidenceLevel | None
    trace_coverage: Ratio | None
    verified_trace_coverage: Ratio | None
    integrated_trace_coverage: Ratio | None
    last_verified_node: StrictStr | None
    first_unverified_node: StrictStr | None
    first_broken_transition: StrictStr | None
    production_eligible: StrictBool
    production_gate: ProductionGate
    recommendation_contract: RecommendationContract
    evidence_refs: tuple[StrictStr, ...] = ()


class GapRecord(_SummaryModel):
    gap_id: StrictStr = Field(min_length=1)
    system: GapSystem
    capability_id: StrictStr = Field(min_length=1)
    title: StrictStr = Field(min_length=1)
    description: StrictStr = Field(min_length=1)
    gap_type: GapType
    priority: GapPriority
    severity: Annotated[StrictInt, Field(ge=1, le=5)]
    likelihood: Annotated[StrictInt, Field(ge=1, le=5)]
    detection_difficulty: Annotated[StrictInt, Field(ge=1, le=5)]
    dependency_centrality: Annotated[StrictInt, Field(ge=1, le=3)]
    rpn: Annotated[StrictInt, Field(ge=1, le=375)]
    normalized_rpn: Score
    affected_invariants: tuple[StrictStr, ...] = ()
    blocks: tuple[StrictStr, ...] = ()
    evidence_refs: tuple[StrictStr, ...] = ()
    owner_type: StrictStr = Field(min_length=1)
    remediation_class: StrictStr = Field(min_length=1)
    acceptance_evidence_required: EvidenceLevel


class GapInventory(_SummaryModel):
    p0: tuple[GapRecord, ...] = ()
    p1: tuple[GapRecord, ...] = ()
    p2: tuple[GapRecord, ...] = ()
    p3: tuple[GapRecord, ...] = ()
    priority_partition_valid: StrictBool | None
    duplicate_gap_ids: tuple[StrictStr, ...] = ()
    critical_dependency_chain: tuple[StrictStr, ...] = ()


class BusinessDecisionRecord(_SummaryModel):
    decision_id: StrictStr = Field(min_length=1)
    title: StrictStr = Field(min_length=1)
    status: DecisionStatus
    owner: StrictStr = Field(min_length=1)
    options: tuple[StrictStr, ...] = ()
    recommended_option: StrictStr | None
    recommendation_basis: StrictStr | None
    default_assumption_for_planning: StrictStr | None
    implementation_blocked: StrictBool
    blocked_scope: tuple[StrictStr, ...] = ()
    required_before_stage: StrictStr | None
    evidence_refs: tuple[StrictStr, ...] = ()


class SourceAccessRecord(_SummaryModel):
    source_id: StrictStr = Field(min_length=1)
    source_name: StrictStr = Field(min_length=1)
    source_type: StrictStr = Field(min_length=1)
    state: SourceAccessState
    scope: StrictStr = Field(min_length=1)
    basis: StrictStr | None
    verified_at: StrictStr | None
    expires_at: StrictStr | None
    allowed_operations: tuple[StrictStr, ...] = ()
    prohibited_operations: tuple[StrictStr, ...] = ()
    blocking_scope: tuple[StrictStr, ...] = ()
    evidence_refs: tuple[StrictStr, ...] = ()


class EngineeringAssumptionRecord(_SummaryModel):
    assumption_id: StrictStr = Field(min_length=1)
    statement: StrictStr = Field(min_length=1)
    rationale: StrictStr = Field(min_length=1)
    affected_fields: tuple[StrictStr, ...] = ()
    impact_if_false: StrictStr = Field(min_length=1)
    validation_method: StrictStr = Field(min_length=1)
    required_by_stage: StrictStr | None
    status: AssumptionStatus
    evidence_refs: tuple[StrictStr, ...] = ()


class FutureHypothesisRecord(_SummaryModel):
    hypothesis_id: StrictStr = Field(min_length=1)
    statement: StrictStr = Field(min_length=1)
    expected_value: StrictStr = Field(min_length=1)
    required_data: tuple[StrictStr, ...] = ()
    falsification_test: StrictStr = Field(min_length=1)
    earliest_applicable_stage: StrictStr | None
    current_action: StrictStr = Field(min_length=1)
    evidence_refs: tuple[StrictStr, ...] = ()


class UnknownRecord(_SummaryModel):
    unknown_id: StrictStr = Field(min_length=1)
    field_path: StrictStr = Field(min_length=1)
    question: StrictStr = Field(min_length=1)
    reason_unknown: StrictStr = Field(min_length=1)
    impact: StrictStr = Field(min_length=1)
    resolver_type: StrictStr = Field(min_length=1)
    required_input: StrictStr = Field(min_length=1)
    owner: StrictStr = Field(min_length=1)
    blocks: tuple[StrictStr, ...] = ()
    target_stage: StrictStr | None


class MachineNextStage(_SummaryModel):
    id: StrictStr | None
    title: StrictStr | None
    objective: StrictStr | None
    why_it_is_next: StrictStr | None
    required_inputs: tuple[StrictStr, ...] = ()
    expected_outputs: tuple[StrictStr, ...] = ()
    acceptance_criteria: tuple[StrictStr, ...] = ()
    stop_condition: StrictStr | None
    client_decisions_required: tuple[StrictStr, ...] = ()
    started: Literal[False] = False
    new_direct_instruction_required: Literal[True] = True


class ValidationState(_SummaryModel):
    yaml_parse: StrictBool | None
    duplicate_key_check: StrictBool | None
    schema_validation: StrictBool | None
    required_field_validation: StrictBool | None
    enum_validation: StrictBool | None
    type_validation: StrictBool | None
    arithmetic_validation: StrictBool | None
    readiness_interval_validation: StrictBool | None
    evidence_ceiling_validation: StrictBool | None
    critical_floor_validation: StrictBool | None
    stop_gate_consistency: StrictBool | None
    production_gate_consistency: StrictBool | None
    reuse_partition_validation: StrictBool | None
    gap_partition_validation: StrictBool | None
    evidence_traceability: StrictBool | None
    reverse_trace_validation: StrictBool | None
    variation_validation: StrictBool | None
    hostile_review: StrictBool | None
    errors: tuple[StrictStr, ...] = ()
    warnings: tuple[StrictStr, ...] = ()


class TerminationState(_SummaryModel):
    stop_gate_key: StrictStr = Field(min_length=1)
    stop_gate_value: StageStatus
    stage_status_matches_stop_gate: StrictBool | None
    next_stage_started: Literal[False] = False
    execution_stopped: Literal[True] = True
    no_content_after_summary: Literal[True] = True


class P0IdentitySpineFullSuite(_SummaryModel):
    passed: NonNegativeInt
    failed: NonNegativeInt
    skipped: NonNegativeInt


class P0IdentitySpineSummary(_SummaryModel):
    """Prompt 15.017 evidence extension for the verified identity P0 gate."""

    query_only_supported: StrictBool
    sentinel_url_occurrences_runtime: NonNegativeInt
    identity_fields_separated: StrictBool
    legacy_rows_marked_unverified: StrictBool
    calibration_requires_automatic_eligible: StrictBool
    calibration_requires_hard_gate_pass: StrictBool
    calibration_requires_verified_oe: StrictBool
    empty_vs_schema_drift_distinguished: StrictBool
    offer_accounting_conservation_verified: StrictBool
    unconditional_source_confidence_one_occurrences: NonNegativeInt
    replay_network_requests: NonNegativeInt
    postgresql_migration_verified: StrictBool
    full_suite: P0IdentitySpineFullSuite
    remaining_blockers: tuple[StrictStr, ...] = ()


class MachineReadableSummary(_SummaryModel):
    schema_: SchemaIdentity = Field(alias="schema")
    stage: MachineStage
    repository: RepositoryIdentity
    metis: MetisSummary
    marko: MarkoSummary
    combined_system: CombinedSystemSummary
    gaps: GapInventory
    business_decisions_required: tuple[BusinessDecisionRecord, ...] = ()
    source_access_states: tuple[SourceAccessRecord, ...] = ()
    engineering_assumptions: tuple[EngineeringAssumptionRecord, ...] = ()
    future_hypotheses: tuple[FutureHypothesisRecord, ...] = ()
    unknowns: tuple[UnknownRecord, ...] = ()
    next_stage: MachineNextStage
    validation: ValidationState
    termination: TerminationState
    p0_identity_spine: P0IdentitySpineSummary | None = None
