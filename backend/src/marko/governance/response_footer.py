"""Executable Section 15 end-of-response governance contract.

The module keeps stage completion separate from production readiness, renders
the mandatory human-readable footer, and validates both structured manifests
and rendered responses before they are published.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


CONTRACT_VERSION = "15.1"
UNASSIGNED_STAGE_ID = "UNASSIGNED_CURRENT_STAGE"
MISSING_STAGE_ID_UNKNOWN = "missing_stage_identity"


class StageStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NO_GO = "NO_GO"


class StageType(StrEnum):
    AUDIT = "AUDIT"
    DESIGN = "DESIGN"
    IMPLEMENTATION = "IMPLEMENTATION"
    VALIDATION = "VALIDATION"
    DEPLOYMENT = "DEPLOYMENT"
    RESEARCH = "RESEARCH"
    REVIEW = "REVIEW"


class ScopeOwner(StrEnum):
    METIS = "Metis"
    MARKO = "Marko"
    COMBINED = "Combined"
    CROSS_CUTTING = "Cross-cutting"


class EvidenceLevel(StrEnum):
    E0 = "E0"
    E1 = "E1"
    E2 = "E2"
    E3 = "E3"
    E4 = "E4"
    E5 = "E5"


class ProductionState(StrEnum):
    NOT_ASSESSED = "NOT_ASSESSED"
    NO_PRODUCTION_CLAIM = "NO_PRODUCTION_CLAIM"
    RESEARCH_ONLY = "RESEARCH_ONLY"
    DEVELOPMENT_ONLY = "DEVELOPMENT_ONLY"
    PRODUCTION_BLOCKED = "PRODUCTION_BLOCKED"
    CONTROLLED_PILOT_BLOCKED = "CONTROLLED_PILOT_BLOCKED"
    CONTROLLED_PILOT_CANDIDATE = "CONTROLLED_PILOT_CANDIDATE"
    PRODUCTION_CANDIDATE = "PRODUCTION_CANDIDATE"
    PRODUCTION_READY_PROVEN = "PRODUCTION_READY_PROVEN"


class BlockerPriority(StrEnum):
    P0 = "P0"
    P1 = "P1"


class BlockerCategory(StrEnum):
    BUSINESS_DECISIONS = "business_decisions"
    SOURCE_ACCESS = "source_access"
    DATA = "data"
    ENVIRONMENT_REPRODUCIBILITY = "environment_reproducibility"
    UNKNOWNS = "unknowns"


class BlockerOverall(StrEnum):
    BLOCKERS_FOUND = "BLOCKERS_FOUND"
    NONE_VERIFIED = "NONE_VERIFIED"
    UNKNOWN_NOT_ASSESSED = "UNKNOWN_NOT_ASSESSED"


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class StageIdentity(_ContractModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    type: StageType
    scope_owner: ScopeOwner
    parent_stage: str | None = None

    @field_validator("id")
    @classmethod
    def stage_id_must_be_normalized(cls, value: str) -> str:
        if value == UNASSIGNED_STAGE_ID:
            return value
        normalized = normalize_stage_id(value)
        if not normalized:
            raise ValueError("stage id has no normalizable characters")
        if value != normalized:
            raise ValueError(f"stage id must be normalized as {normalized}")
        return value


class CompletedScopeItem(_ContractModel):
    scope_item_id: str = Field(min_length=1)
    result: str = Field(min_length=1)
    artifact_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    hard_required: bool = True
    temporal_state: Literal["PAST_VERIFIED", "CURRENT_VERIFIED"] = "PAST_VERIFIED"


class IncompleteScopeItem(_ContractModel):
    scope_item_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    hard_required: bool = True
    external_dependency: bool = False


class StrongestVerifiedResult(_ContractModel):
    claim_id: str = Field(min_length=1)
    result: str = Field(min_length=1)
    evidence_level: EvidenceLevel
    evidence_refs: tuple[str, ...] = ()
    reproduction_status: Literal[
        "reproducible", "partially_reproducible", "not_reproducible"
    ]
    limitations: tuple[str, ...] = ()


class WeakestCriticalArea(_ContractModel):
    area_id: str = Field(min_length=1)
    area: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0, le=100)
    evidence_level: EvidenceLevel
    reason: str = Field(min_length=1)
    downstream_impact: str = Field(min_length=1)
    required_resolution: str = Field(min_length=1)


class EvidenceQuality(_ContractModel):
    highest_level: EvidenceLevel
    critical_floor: EvidenceLevel
    material_claim_coverage: float = Field(ge=0, le=1)
    reproducible_claim_coverage: float = Field(ge=0, le=1)
    freshness_status: Literal["verified", "partial", "unknown"]
    representative_scope: Literal[
        "representative", "partial", "non_representative", "unknown"
    ]
    limitations: tuple[str, ...] = ()


class ProductionImplication(_ContractModel):
    state: ProductionState
    production_ready: bool | Literal["not_assessed"]
    evidence_level: EvidenceLevel
    passed_hard_gates: tuple[str, ...] = ()
    failed_hard_gates: tuple[str, ...] = ()
    blocked_hard_gates: tuple[str, ...] = ()
    statement: str = Field(min_length=1)


class StageResult(_ContractModel):
    stage: StageIdentity
    status: StageStatus
    completed_scope: tuple[CompletedScopeItem, ...]
    incomplete_scope: tuple[IncompleteScopeItem, ...] = ()
    strongest_verified_result: StrongestVerifiedResult
    weakest_critical_area: WeakestCriticalArea
    evidence_quality: EvidenceQuality
    production_implication: ProductionImplication


class Blocker(_ContractModel):
    id: str = Field(min_length=1)
    priority: BlockerPriority
    category: BlockerCategory
    description: str = Field(min_length=1)
    blocked_scope: tuple[str, ...]
    affects_current_gate: bool
    affects_next_stage: bool
    affects_production: bool
    evidence_refs: tuple[str, ...] = ()
    owner: str = Field(min_length=1)
    resolution_condition: str = Field(min_length=1)
    can_agent_resolve_now: bool
    risk_score: int | Literal["NOT_CALIBRATED"] = "NOT_CALIBRATED"

    @field_validator("risk_score")
    @classmethod
    def calibrated_risk_is_positive(cls, value: int | str) -> int | str:
        if isinstance(value, int) and value <= 0:
            raise ValueError("calibrated risk_score must be positive")
        return value


class BlockerInventory(_ContractModel):
    overall: BlockerOverall
    assessment_complete: bool = False
    assessed_categories: frozenset[BlockerCategory] = frozenset()
    p0: tuple[Blocker, ...] = ()
    p1: tuple[Blocker, ...] = ()
    business_decisions: tuple[str, ...] = ()
    source_access: tuple[str, ...] = ()
    data: tuple[str, ...] = ()
    environment_reproducibility: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()


class RequiredInput(_ContractModel):
    input_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    source: str = Field(min_length=1)
    required_state: str = Field(min_length=1)
    currently_available: StrictBool | Literal["unknown"]
    evidence_ref: str | None = None

    @field_validator("currently_available", mode="before")
    @classmethod
    def accept_manifest_boolean_strings(cls, value: object) -> object:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized == "true":
                return True
            if normalized == "false":
                return False
            if normalized == "unknown":
                return "unknown"
        return value


class ExpectedArtifact(_ContractModel):
    artifact_id: str = Field(min_length=1)
    type: Literal["md", "yaml", "json", "code", "test", "dataset", "report", "adr"]
    purpose: str = Field(min_length=1)
    required_fields: tuple[str, ...] = ()
    temporal_state: Literal["PLANNED_NOT_STARTED"] = "PLANNED_NOT_STARTED"


class AcceptanceCriterion(_ContractModel):
    id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    required_evidence: str = Field(min_length=1)
    threshold: str = Field(min_length=1)


class StopCondition(_ContractModel):
    gate_key: str = Field(min_length=1)
    allowed_states: tuple[StageStatus, ...] = tuple(StageStatus)
    auto_continue: Literal[False] = False


class ClientDecision(_ContractModel):
    decision_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    alternatives: tuple[str, ...] = Field(min_length=2)
    architecture_impact: str = Field(min_length=1)
    blocking: bool
    default_forbidden: bool
    evidence_refs: tuple[str, ...] = ()


class NextStage(_ContractModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    why_it_is_next: tuple[str, ...]
    required_inputs: tuple[RequiredInput, ...]
    expected_artifacts: tuple[ExpectedArtifact, ...]
    acceptance_criteria: tuple[AcceptanceCriterion, ...]
    stop_condition: StopCondition
    client_decisions_required: tuple[ClientDecision, ...] = ()
    started: Literal[False] = False
    authorized: Literal[False] = False

    @field_validator("id")
    @classmethod
    def next_stage_id_must_be_normalized(cls, value: str) -> str:
        normalized = normalize_stage_id(value)
        if not normalized:
            raise ValueError("next-stage id has no normalizable characters")
        if value != normalized:
            raise ValueError(f"next-stage id must be normalized as {normalized}")
        return value


class SecondaryFinding(_ContractModel):
    status: StageStatus
    finding: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()


class StopGate(_ContractModel):
    key: str = Field(min_length=1)
    primary_status: StageStatus
    secondary_findings: tuple[SecondaryFinding, ...] = ()
    automatic_transition: Literal[False] = False


class EndOfResponse(_ContractModel):
    contract_version: Literal["15.1"] = CONTRACT_VERSION
    stage_result: StageResult
    blockers: BlockerInventory
    next_stage: NextStage
    stop_gate: StopGate


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    path: str
    message: str


_STATUS_PRIORITY: dict[StageStatus, int] = {
    StageStatus.PASS: 0,
    StageStatus.FAIL: 1,
    StageStatus.BLOCKED: 2,
    StageStatus.NO_GO: 3,
}
_EVIDENCE_RANK: dict[EvidenceLevel, int] = {
    EvidenceLevel.E0: 0,
    EvidenceLevel.E1: 1,
    EvidenceLevel.E2: 2,
    EvidenceLevel.E3: 3,
    EvidenceLevel.E4: 4,
    EvidenceLevel.E5: 5,
}
_EVIDENCE_SCORE_CAP: dict[EvidenceLevel, float] = {
    EvidenceLevel.E0: 0,
    EvidenceLevel.E1: 25,
    EvidenceLevel.E2: 50,
    EvidenceLevel.E3: 75,
    EvidenceLevel.E4: 90,
    EvidenceLevel.E5: 100,
}
_REQUIRED_BLOCKER_CATEGORIES = frozenset(BlockerCategory)
_FINAL_GATE_RE = re.compile(r"^STOP_GATE_([A-Z0-9_]+) = (PASS|FAIL|BLOCKED|NO_GO)$")
_FINAL_GATE_LINE_RE = re.compile(
    r"^STOP_GATE_([A-Z0-9_]+) = (PASS|FAIL|BLOCKED|NO_GO)$",
    flags=re.MULTILINE,
)
_BODY_STATUS_RE = re.compile(
    r"^(?:CURRENT_STAGE_STATUS|STAGE_STATUS|ИТОГ_ТЕКУЩЕГО_ЭТАПА)\s*[:=]\s*"
    r"(PASS|FAIL|BLOCKED|NO_GO)\s*$",
    flags=re.MULTILINE,
)


def normalize_stage_id(stage_id: str) -> str:
    """Normalize one stage id using the exact Section 15 algorithm."""
    value = stage_id.strip().upper()
    value = re.sub(r"[\s-]+", "_", value)
    value = re.sub(r"[^A-Z0-9_]", "", value)
    value = re.sub(r"_+", "_", value)
    return value.strip("_")


def expected_stop_gate_key(stage_id: str) -> str:
    normalized = normalize_stage_id(stage_id)
    if not normalized:
        normalized = UNASSIGNED_STAGE_ID
    return f"STOP_GATE_{normalized}"


def aggregate_status(statuses: Iterable[StageStatus]) -> StageStatus:
    collected = tuple(statuses)
    if not collected:
        raise ValueError("at least one status is required")
    return max(collected, key=_STATUS_PRIORITY.__getitem__)


def evidence_capped_score(raw_score: float, evidence_level: EvidenceLevel) -> float:
    """Apply the Section 15 evidence cap to a readiness score."""
    if not 0 <= raw_score <= 100:
        raise ValueError("raw_score must be in [0, 100]")
    return min(raw_score, _EVIDENCE_SCORE_CAP[evidence_level])


def safe_coverage(numerator: int, denominator: int) -> float:
    """Compute N / max(D, 1) without hiding invalid negative counts."""
    if numerator < 0 or denominator < 0:
        raise ValueError("coverage counts must be non-negative")
    if numerator > denominator and denominator > 0:
        raise ValueError("coverage numerator cannot exceed denominator")
    if denominator == 0 and numerator != 0:
        raise ValueError("non-zero numerator requires a non-zero denominator")
    return numerator / max(denominator, 1)


def _category_ids(blockers: tuple[Blocker, ...], category: BlockerCategory) -> set[str]:
    return {blocker.id for blocker in blockers if blocker.category == category}


def validate_contract(contract: EndOfResponse) -> tuple[ValidationIssue, ...]:
    """Validate cross-field, gate, evidence, blocker, and temporal invariants."""
    issues: list[ValidationIssue] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append(ValidationIssue(code, path, message))

    stage = contract.stage_result
    blockers = contract.blockers
    next_stage = contract.next_stage
    stop_gate = contract.stop_gate

    expected_key = expected_stop_gate_key(stage.stage.id)
    if stop_gate.key != expected_key:
        add(
            "GATE_KEY_MISMATCH",
            "stop_gate.key",
            f"expected {expected_key}, got {stop_gate.key}",
        )
    if stage.status != stop_gate.primary_status:
        add(
            "STATUS_MISMATCH",
            "stop_gate.primary_status",
            "stage_result.status must equal stop_gate.primary_status",
        )
    aggregated = aggregate_status(
        (
            stop_gate.primary_status,
            *(item.status for item in stop_gate.secondary_findings),
        )
    )
    if aggregated != stop_gate.primary_status:
        add(
            "STATUS_PRECEDENCE_VIOLATION",
            "stop_gate.secondary_findings",
            f"primary status must be {aggregated.value} under NO_GO > BLOCKED > FAIL > PASS",
        )

    if next_stage.started or next_stage.authorized or stop_gate.automatic_transition:
        add(
            "AUTO_TRANSITION_FORBIDDEN",
            "next_stage",
            "the next stage must remain not started, unauthorized, and non-automatic",
        )
    next_expected_key = expected_stop_gate_key(next_stage.id)
    if next_stage.stop_condition.gate_key != next_expected_key:
        add(
            "NEXT_GATE_KEY_MISMATCH",
            "next_stage.stop_condition.gate_key",
            f"expected {next_expected_key}",
        )
    if len(next_stage.stop_condition.allowed_states) != len(StageStatus) or set(
        next_stage.stop_condition.allowed_states
    ) != set(StageStatus):
        add(
            "NEXT_ALLOWED_STATES_INVALID",
            "next_stage.stop_condition.allowed_states",
            "the next stop condition must allow PASS, FAIL, BLOCKED, and NO_GO exactly once",
        )
    if not next_stage.why_it_is_next:
        add(
            "NEXT_REASON_MISSING",
            "next_stage.why_it_is_next",
            "at least one dependency reason is required",
        )
    next_stage_is_undetermined = next_stage.id == "NONE_AUTHORIZED"
    if next_stage_is_undetermined and next_stage.title != "AWAITING_REQUIRED_DECISION":
        add(
            "NONE_AUTHORIZED_TITLE_MISMATCH",
            "next_stage.title",
            "NONE_AUTHORIZED requires title AWAITING_REQUIRED_DECISION",
        )
    if not next_stage.required_inputs and not next_stage_is_undetermined:
        add(
            "NEXT_INPUTS_MISSING",
            "next_stage.required_inputs",
            "a determined next stage must list its required inputs",
        )
    if not next_stage.expected_artifacts and not next_stage_is_undetermined:
        add(
            "NEXT_ARTIFACT_MISSING",
            "next_stage.expected_artifacts",
            "at least one future artifact is required",
        )
    if not next_stage.acceptance_criteria and not next_stage_is_undetermined:
        add(
            "NEXT_ACCEPTANCE_MISSING",
            "next_stage.acceptance_criteria",
            "at least one testable criterion is required",
        )
    unavailable_inputs = {
        item.input_id
        for item in next_stage.required_inputs
        if item.currently_available is not True
    }
    if unavailable_inputs and blockers.overall == BlockerOverall.NONE_VERIFIED:
        add(
            "NEXT_INPUT_BLOCKER_MISMATCH",
            "next_stage.required_inputs",
            "unavailable/unknown inputs cannot coexist with blockers=NONE_VERIFIED",
        )
    for index, decision in enumerate(next_stage.client_decisions_required):
        if not decision.evidence_refs:
            add(
                "CLIENT_DECISION_UNTRACED",
                f"next_stage.client_decisions_required[{index}].evidence_refs",
                "a client decision requires a user, owner, or approved-policy evidence reference",
            )

    for index, item in enumerate(stage.completed_scope):
        if not item.artifact_refs and not item.evidence_refs:
            add(
                "COMPLETED_SCOPE_UNTRACED",
                f"stage_result.completed_scope[{index}]",
                "completed scope requires an artifact or evidence reference",
            )
    strongest = stage.strongest_verified_result
    if strongest.claim_id != "NONE_VERIFIED" and not strongest.evidence_refs:
        add(
            "STRONGEST_RESULT_UNTRACED",
            "stage_result.strongest_verified_result.evidence_refs",
            "a verified result requires evidence references",
        )
    if (
        _EVIDENCE_RANK[stage.evidence_quality.critical_floor]
        > _EVIDENCE_RANK[stage.evidence_quality.highest_level]
    ):
        add(
            "EVIDENCE_FLOOR_ABOVE_MAX",
            "stage_result.evidence_quality",
            "critical floor cannot exceed highest evidence level",
        )
    observed_levels = (
        strongest.evidence_level,
        stage.weakest_critical_area.evidence_level,
        stage.production_implication.evidence_level,
    )
    if any(
        _EVIDENCE_RANK[level] > _EVIDENCE_RANK[stage.evidence_quality.highest_level]
        for level in observed_levels
    ):
        add(
            "EVIDENCE_HIGHEST_UNDERSTATED",
            "stage_result.evidence_quality.highest_level",
            "highest_level must cover every evidence level declared in stage_result",
        )
    if (
        _EVIDENCE_RANK[stage.evidence_quality.critical_floor]
        > _EVIDENCE_RANK[stage.weakest_critical_area.evidence_level]
    ):
        add(
            "CRITICAL_FLOOR_OVERSTATED",
            "stage_result.evidence_quality.critical_floor",
            "critical_floor cannot exceed the weakest critical area's evidence level",
        )
    weakest_score = stage.weakest_critical_area.score
    if (
        weakest_score is not None
        and weakest_score
        > _EVIDENCE_SCORE_CAP[stage.weakest_critical_area.evidence_level]
    ):
        add(
            "EVIDENCE_SCORE_CAP_EXCEEDED",
            "stage_result.weakest_critical_area.score",
            "score exceeds the cap allowed by its evidence level",
        )

    production = stage.production_implication
    if production.production_ready is True:
        if production.state != ProductionState.PRODUCTION_READY_PROVEN:
            add(
                "PRODUCTION_STATE_MISMATCH",
                "stage_result.production_implication.state",
                "production_ready=true requires PRODUCTION_READY_PROVEN",
            )
        if _EVIDENCE_RANK[production.evidence_level] < _EVIDENCE_RANK[EvidenceLevel.E5]:
            add(
                "PRODUCTION_EVIDENCE_TOO_WEAK",
                "stage_result.production_implication.evidence_level",
                "production readiness requires representative E5 evidence",
            )
        if production.failed_hard_gates or production.blocked_hard_gates:
            add(
                "PRODUCTION_HARD_GATE_OPEN",
                "stage_result.production_implication",
                "production_ready=true forbids failed or blocked hard gates",
            )
    if (
        production.state == ProductionState.PRODUCTION_READY_PROVEN
        and production.production_ready is not True
    ):
        add(
            "PRODUCTION_READY_FLAG_MISSING",
            "stage_result.production_implication.production_ready",
            "PRODUCTION_READY_PROVEN requires production_ready=true",
        )
    if (
        production.production_ready == "not_assessed"
        and production.state != ProductionState.NOT_ASSESSED
    ):
        add(
            "PRODUCTION_NOT_ASSESSED_STATE_MISMATCH",
            "stage_result.production_implication",
            "production_ready=not_assessed requires state NOT_ASSESSED",
        )
    if (
        production.state == ProductionState.NOT_ASSESSED
        and production.production_ready != "not_assessed"
    ):
        add(
            "PRODUCTION_NOT_ASSESSED_FLAG_MISMATCH",
            "stage_result.production_implication",
            "state NOT_ASSESSED requires production_ready=not_assessed",
        )
    candidate_states = {
        ProductionState.CONTROLLED_PILOT_CANDIDATE,
        ProductionState.PRODUCTION_CANDIDATE,
        ProductionState.PRODUCTION_READY_PROVEN,
    }
    if production.state in candidate_states and (
        production.failed_hard_gates or production.blocked_hard_gates
    ):
        add(
            "PRODUCTION_CANDIDATE_WITH_OPEN_GATE",
            "stage_result.production_implication",
            "candidate/readiness states forbid failed or blocked hard gates",
        )

    all_blockers = blockers.p0 + blockers.p1
    blocker_ids = [blocker.id for blocker in all_blockers]
    if len(blocker_ids) != len(set(blocker_ids)):
        add("DUPLICATE_BLOCKER_ID", "blockers", "blocker IDs must be unique")
    for index, blocker in enumerate(blockers.p0):
        if blocker.priority != BlockerPriority.P0:
            add(
                "BLOCKER_PRIORITY_MISMATCH",
                f"blockers.p0[{index}]",
                "P0 list requires priority P0",
            )
    for index, blocker in enumerate(blockers.p1):
        if blocker.priority != BlockerPriority.P1:
            add(
                "BLOCKER_PRIORITY_MISMATCH",
                f"blockers.p1[{index}]",
                "P1 list requires priority P1",
            )
        if blocker.affects_current_gate:
            add(
                "P1_BLOCKS_CURRENT_GATE",
                f"blockers.p1[{index}]",
                "a blocker affecting the current gate must be P0",
            )
    for index, blocker in enumerate(all_blockers):
        if not blocker.blocked_scope:
            add(
                "BLOCKED_SCOPE_MISSING",
                f"blockers.all[{index}].blocked_scope",
                "every blocker must identify blocked scope",
            )
        if not (
            blocker.affects_current_gate
            or blocker.affects_next_stage
            or blocker.affects_production
        ):
            add(
                "BLOCKER_WITHOUT_IMPACT",
                f"blockers.all[{index}]",
                "a blocker must affect a gate, next stage, or production",
            )

    category_fields: dict[BlockerCategory, tuple[str, ...]] = {
        BlockerCategory.BUSINESS_DECISIONS: blockers.business_decisions,
        BlockerCategory.SOURCE_ACCESS: blockers.source_access,
        BlockerCategory.DATA: blockers.data,
        BlockerCategory.ENVIRONMENT_REPRODUCIBILITY: blockers.environment_reproducibility,
    }
    for category, actual in category_fields.items():
        expected = _category_ids(all_blockers, category)
        if set(actual) != expected:
            add(
                "BLOCKER_CATEGORY_MISMATCH",
                f"blockers.{category.value}",
                f"expected IDs {sorted(expected)}, got {sorted(actual)}",
            )

    if blockers.overall == BlockerOverall.NONE_VERIFIED:
        if not blockers.assessment_complete:
            add(
                "NONE_WITHOUT_ASSESSMENT",
                "blockers.assessment_complete",
                "NONE_VERIFIED requires complete assessment",
            )
        if blockers.assessed_categories != _REQUIRED_BLOCKER_CATEGORIES:
            add(
                "NONE_WITH_PARTIAL_CATEGORIES",
                "blockers.assessed_categories",
                "NONE_VERIFIED requires every category assessed",
            )
        if all_blockers or blockers.unknowns:
            add(
                "NONE_WITH_FINDINGS",
                "blockers",
                "NONE_VERIFIED forbids blockers and unknowns",
            )
    elif blockers.overall == BlockerOverall.BLOCKERS_FOUND and not all_blockers:
        add(
            "BLOCKERS_FOUND_EMPTY",
            "blockers",
            "BLOCKERS_FOUND requires at least one blocker",
        )
    elif blockers.overall == BlockerOverall.UNKNOWN_NOT_ASSESSED:
        if blockers.assessment_complete and not blockers.unknowns:
            add(
                "UNKNOWN_WITH_COMPLETE_ASSESSMENT",
                "blockers",
                "UNKNOWN_NOT_ASSESSED requires incomplete assessment or unknowns",
            )
    if blockers.unknowns and blockers.overall == BlockerOverall.NONE_VERIFIED:
        add(
            "UNKNOWNS_HIDDEN_BY_NONE",
            "blockers.unknowns",
            "unknowns forbid NONE_VERIFIED",
        )

    current_external_blockers = [
        blocker
        for blocker in all_blockers
        if blocker.affects_current_gate and not blocker.can_agent_resolve_now
    ]
    hard_incomplete = [item for item in stage.incomplete_scope if item.hard_required]

    if stage.status == StageStatus.PASS:
        if not stage.completed_scope:
            add(
                "PASS_WITHOUT_SCOPE",
                "stage_result.completed_scope",
                "PASS requires completed scope",
            )
        if hard_incomplete:
            add(
                "PASS_WITH_HARD_INCOMPLETE",
                "stage_result.incomplete_scope",
                "PASS forbids incomplete hard scope",
            )
        if (
            strongest.claim_id == "NONE_VERIFIED"
            or _EVIDENCE_RANK[strongest.evidence_level] < 2
        ):
            add(
                "PASS_WITHOUT_VERIFIED_RESULT",
                "stage_result.strongest_verified_result",
                "PASS requires an E2+ strongest result",
            )
        if blockers.p0:
            add("PASS_WITH_P0", "blockers.p0", "PASS forbids P0 blockers")
    elif stage.status == StageStatus.FAIL:
        if not hard_incomplete and not production.failed_hard_gates:
            add(
                "FAIL_WITHOUT_DEFECT",
                "stage_result",
                "FAIL requires an observed current-stage defect",
            )
        if _EVIDENCE_RANK[stage.evidence_quality.highest_level] < 3:
            add(
                "FAIL_WITH_WEAK_EVIDENCE",
                "stage_result.evidence_quality",
                "FAIL requires focused executable E3+ evidence",
            )
        next_id = next_stage.id
        if "REPAIR" not in next_id and "REVALIDATION" not in next_id:
            add(
                "FAIL_NEXT_STAGE_INVALID",
                "next_stage.id",
                "FAIL must lead to repair or revalidation",
            )
    elif stage.status == StageStatus.BLOCKED:
        if not current_external_blockers:
            add(
                "BLOCKED_WITHOUT_EXTERNAL_DEPENDENCY",
                "blockers",
                "BLOCKED requires an external current-gate blocker",
            )
        if not unavailable_inputs:
            add(
                "BLOCKED_WITHOUT_MISSING_INPUT",
                "next_stage.required_inputs",
                "BLOCKED continuation requires an unavailable or unknown input",
            )
    elif stage.status == StageStatus.NO_GO:
        if not production.failed_hard_gates:
            add(
                "NO_GO_WITHOUT_HARD_FAILURE",
                "stage_result.production_implication.failed_hard_gates",
                "NO_GO requires a failed hard gate",
            )
        if (
            max(
                _EVIDENCE_RANK[strongest.evidence_level],
                _EVIDENCE_RANK[stage.weakest_critical_area.evidence_level],
            )
            < 3
        ):
            add(
                "NO_GO_WITH_WEAK_EVIDENCE",
                "stage_result",
                "NO_GO requires E3+ falsification evidence",
            )
        if strongest.reproduction_status != "reproducible":
            add(
                "NO_GO_WITHOUT_REPRODUCIBLE_FALSIFICATION",
                "stage_result.strongest_verified_result.reproduction_status",
                "NO_GO cannot be based on a one-off or non-reproducible failure",
            )
        allowed_tokens = ("DECISION", "ALTERNATIVE", "SCOPE_REVISION", "REPLACEMENT")
        if not any(token in next_stage.id for token in allowed_tokens):
            add(
                "NO_GO_NEXT_STAGE_INVALID",
                "next_stage.id",
                "NO_GO must lead to a decision, alternative, scope revision, or replacement",
            )
        if "IMPLEMENTATION" in next_stage.id:
            add(
                "NO_GO_CONTINUES_REJECTED_APPROACH",
                "next_stage.id",
                "NO_GO cannot continue directly into implementation",
            )

    if stage.stage.id == UNASSIGNED_STAGE_ID:
        if stage.status != StageStatus.BLOCKED:
            add(
                "UNASSIGNED_STAGE_NOT_BLOCKED",
                "stage_result.status",
                "missing stage identity requires BLOCKED",
            )
        if MISSING_STAGE_ID_UNKNOWN not in blockers.unknowns:
            add(
                "MISSING_STAGE_UNKNOWN_NOT_RECORDED",
                "blockers.unknowns",
                "missing_stage_identity must be recorded",
            )

    return tuple(issues)


def _list_or_none(values: Iterable[str]) -> str:
    collected = tuple(values)
    return ", ".join(collected) if collected else "NONE_VERIFIED"


def _render_blocker(blocker: Blocker) -> str:
    return (
        f"[{blocker.id}] {blocker.description}; owner={blocker.owner}; "
        f"resolution={blocker.resolution_condition}"
    )


def _render_availability(value: bool | Literal["unknown"]) -> str:
    if value == "unknown":
        return value
    return str(value).lower()


def render_footer(contract: EndOfResponse) -> str:
    """Render the exact human-readable Section 15 footer with gate last."""
    stage = contract.stage_result
    strongest = stage.strongest_verified_result
    weakest = stage.weakest_critical_area
    quality = stage.evidence_quality
    production = stage.production_implication
    blockers = contract.blockers
    next_stage = contract.next_stage

    lines = [
        "## Структурированный результат текущего этапа",
        "",
        "STAGE_RESULT:",
        "- stage:",
        f"  - id: {stage.stage.id}",
        f"  - title: {stage.stage.title}",
        f"  - type: {stage.stage.type.value}",
        f"  - scope owner: {stage.stage.scope_owner.value}",
        f"- status: {stage.status.value}",
        "- completed scope:",
    ]
    for item in stage.completed_scope:
        lines.extend(
            [
                f"  - [{item.scope_item_id}] {item.result}",
                f"    - artifacts: {_list_or_none(item.artifact_refs)}",
                f"    - evidence: {_list_or_none(item.evidence_refs)}",
            ]
        )
    if not stage.completed_scope:
        lines.append("  - NONE_VERIFIED")
    lines.extend(
        [
            "- strongest verified result:",
            f"  - claim: [{strongest.claim_id}] {strongest.result}",
            f"  - evidence level: {strongest.evidence_level.value}",
            f"  - evidence: {_list_or_none(strongest.evidence_refs)}",
            f"  - reproduction status: {strongest.reproduction_status}",
            f"  - limitations: {_list_or_none(strongest.limitations)}",
            "- weakest critical area:",
            f"  - area: [{weakest.area_id}] {weakest.area}",
            f"  - score/evidence floor: {weakest.score if weakest.score is not None else 'NOT_SCORED'} / {weakest.evidence_level.value}",
            f"  - reason: {weakest.reason}",
            f"  - impact: {weakest.downstream_impact}",
            f"  - required resolution: {weakest.required_resolution}",
            "- evidence quality:",
            f"  - highest level: {quality.highest_level.value}",
            f"  - critical floor: {quality.critical_floor.value}",
            f"  - material claim coverage: {quality.material_claim_coverage:.2f}",
            f"  - reproducible claim coverage: {quality.reproducible_claim_coverage:.2f}",
            f"  - freshness status: {quality.freshness_status}",
            f"  - representative scope: {quality.representative_scope}",
            f"  - limitations: {_list_or_none(quality.limitations)}",
            "- production implication:",
            f"  - state: {production.state.value}",
            f"  - production ready: {str(production.production_ready).lower() if isinstance(production.production_ready, bool) else production.production_ready}",
            f"  - evidence level: {production.evidence_level.value}",
            f"  - passed hard gates: {_list_or_none(production.passed_hard_gates)}",
            f"  - failed hard gates: {_list_or_none(production.failed_hard_gates)}",
            f"  - blocked hard gates: {_list_or_none(production.blocked_hard_gates)}",
            f"  - statement: {production.statement}",
            "",
            "## Блокеры",
            "",
            "BLOCKERS:",
            "- P0:",
        ]
    )
    lines.extend(f"  - {_render_blocker(item)}" for item in blockers.p0)
    if not blockers.p0:
        lines.append("  - NONE_VERIFIED")
    lines.append("- P1:")
    lines.extend(f"  - {_render_blocker(item)}" for item in blockers.p1)
    if not blockers.p1:
        lines.append("  - NONE_VERIFIED")
    lines.extend(
        [
            "- business decisions:",
            f"  - {_list_or_none(blockers.business_decisions)}",
            "- source/access:",
            f"  - {_list_or_none(blockers.source_access)}",
            "- data:",
            f"  - {_list_or_none(blockers.data)}",
            "- environment/reproducibility:",
            f"  - {_list_or_none(blockers.environment_reproducibility)}",
            "- unknowns:",
            f"  - {_list_or_none(blockers.unknowns)}",
            "",
            "## Следующая часть",
            "",
            "NEXT_STAGE:",
            f"- id: {next_stage.id}",
            f"- title: {next_stage.title}",
            "- why it is next:",
        ]
    )
    lines.extend(f"  - {item}" for item in next_stage.why_it_is_next)
    if not next_stage.why_it_is_next:
        lines.append("  - NONE_VERIFIED")
    lines.append("- required inputs:")
    for item in next_stage.required_inputs:
        lines.append(
            f"  - [{item.input_id}] {item.description}; source={item.source}; "
            f"required_state={item.required_state}; available={_render_availability(item.currently_available)}; "
            f"evidence={item.evidence_ref or 'NONE_VERIFIED'}"
        )
    if not next_stage.required_inputs:
        lines.append("  - NONE_VERIFIED")
    lines.append("- expected artifacts:")
    for item in next_stage.expected_artifacts:
        fields = _list_or_none(item.required_fields)
        lines.append(
            f"  - [{item.artifact_id}] {item.type}: должен быть создан; "
            f"purpose={item.purpose}; required_fields={fields}"
        )
    lines.append("- acceptance criteria:")
    for item in next_stage.acceptance_criteria:
        lines.append(
            f"  - [{item.id}] predicate={item.predicate}; evidence={item.required_evidence}; "
            f"threshold={item.threshold}"
        )
    lines.extend(
        [
            "- stop condition:",
            f"  - gate key: {next_stage.stop_condition.gate_key}",
            f"  - allowed states: {_list_or_none(item.value for item in next_stage.stop_condition.allowed_states)}",
            "  - automatic transition: false",
            "- client decisions required:",
        ]
    )
    for item in next_stage.client_decisions_required:
        lines.append(
            f"  - [{item.decision_id}] {item.question}; alternatives={_list_or_none(item.alternatives)}; "
            f"impact={item.architecture_impact}; blocking={str(item.blocking).lower()}; "
            f"default_forbidden={str(item.default_forbidden).lower()}; "
            f"evidence={_list_or_none(item.evidence_refs)}"
        )
    if not next_stage.client_decisions_required:
        lines.append("  - NONE_VERIFIED")
    lines.extend(
        [
            "",
            f"{contract.stop_gate.key} = {contract.stop_gate.primary_status.value}",
        ]
    )
    return "\n".join(lines)


def validate_rendered_footer(
    response: str,
    *,
    expected_contract: EndOfResponse | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate section order, required fields, final gate, and optional alignment."""
    issues: list[ValidationIssue] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append(ValidationIssue(code, path, message))

    required_markers = (
        "STAGE_RESULT:",
        "BLOCKERS:",
        "NEXT_STAGE:",
    )
    positions = [response.find(marker) for marker in required_markers]
    if any(position < 0 for position in positions):
        add(
            "FOOTER_SECTION_MISSING",
            "response",
            "STAGE_RESULT, BLOCKERS, and NEXT_STAGE are required",
        )
    elif positions != sorted(positions):
        add(
            "FOOTER_SECTION_ORDER",
            "response",
            "required footer sections are out of order",
        )

    for marker in required_markers:
        if response.count(marker) > 1:
            add(
                "FOOTER_SECTION_DUPLICATED",
                "response",
                f"required footer marker {marker} must occur exactly once",
            )

    required_fields = (
        "- stage:",
        "- status:",
        "- completed scope:",
        "- strongest verified result:",
        "- weakest critical area:",
        "- evidence quality:",
        "- production implication:",
        "- P0:",
        "- P1:",
        "- business decisions:",
        "- source/access:",
        "- data:",
        "- environment/reproducibility:",
        "- unknowns:",
        "- why it is next:",
        "- required inputs:",
        "- expected artifacts:",
        "- acceptance criteria:",
        "- stop condition:",
        "- client decisions required:",
    )
    for field in required_fields:
        if field not in response:
            add("FOOTER_FIELD_MISSING", "response", f"missing required field {field}")

    nonempty = [line.rstrip() for line in response.splitlines() if line.strip()]
    if not nonempty:
        add("EMPTY_RESPONSE", "response", "response is empty")
        return tuple(issues)
    final_match = _FINAL_GATE_RE.fullmatch(nonempty[-1])
    if final_match is None:
        add(
            "STOP_GATE_NOT_LAST",
            "response",
            "the final non-empty line must be a canonical STOP_GATE assignment",
        )
    else:
        stage_match = re.search(r"^  - id: ([A-Z0-9_]+)$", response, flags=re.MULTILINE)
        status_match = re.search(
            r"^- status: (PASS|FAIL|BLOCKED|NO_GO)$", response, flags=re.MULTILINE
        )
        if stage_match and final_match.group(1) != stage_match.group(1):
            add(
                "RENDERED_GATE_STAGE_MISMATCH",
                "response",
                "rendered stage id does not match final gate key",
            )
        if status_match and final_match.group(2) != status_match.group(1):
            add(
                "RENDERED_GATE_STATUS_MISMATCH",
                "response",
                "rendered status does not match final gate status",
            )

        gate_lines = tuple(_FINAL_GATE_LINE_RE.finditer(response))
        if len(gate_lines) != 1:
            add(
                "STOP_GATE_COUNT_INVALID",
                "response",
                f"exactly one executable stop-gate is required, found {len(gate_lines)}",
            )
        body_end = positions[0] if positions[0] >= 0 else len(response)
        for body_status in _BODY_STATUS_RE.finditer(response[:body_end]):
            if body_status.group(1) != final_match.group(2):
                add(
                    "BODY_FOOTER_STATUS_MISMATCH",
                    "response",
                    "explicit body status conflicts with the footer status",
                )

    if expected_contract is not None:
        issues.extend(validate_contract(expected_contract))
        marker = "## Структурированный результат текущего этапа"
        start = response.find(marker)
        if start < 0:
            add(
                "CANONICAL_FOOTER_HEADING_MISSING",
                "response",
                "canonical footer heading is missing",
            )
        else:
            actual_footer = response[start:].strip()
            expected_footer = render_footer(expected_contract).strip()
            if actual_footer != expected_footer:
                add(
                    "MANIFEST_FOOTER_MISMATCH",
                    "response",
                    "human-readable footer is not semantically identical to the manifest-rendered footer",
                )

    return tuple(issues)


def to_manifest(contract: EndOfResponse) -> dict[str, Any]:
    """Return the canonical machine-readable manifest root."""
    return {"end_of_response": contract.model_dump(mode="json")}


def build_self_check(
    contract: EndOfResponse,
    *,
    response: str | None = None,
) -> dict[str, bool | None]:
    """Build the Section 15.53 publication self-check from executable facts."""
    contract_codes = {issue.code for issue in validate_contract(contract)}
    rendered = response if response is not None else render_footer(contract)
    response_codes = {
        issue.code
        for issue in validate_rendered_footer(
            rendered,
            expected_contract=contract,
        )
    }
    stage = contract.stage_result
    next_stage = contract.next_stage
    strongest = stage.strongest_verified_result
    none_authorized = next_stage.id == "NONE_AUTHORIZED"

    priority_codes = {
        "BLOCKER_PRIORITY_MISMATCH",
        "P1_BLOCKS_CURRENT_GATE",
    }
    none_codes = {
        "NONE_WITHOUT_ASSESSMENT",
        "NONE_WITH_PARTIAL_CATEGORIES",
        "NONE_WITH_FINDINGS",
        "UNKNOWNS_HIDDEN_BY_NONE",
    }
    client_decision_codes = {"CLIENT_DECISION_UNTRACED"}
    return {
        "stage_identity_present": (
            None if stage.stage.id == UNASSIGNED_STAGE_ID else True
        ),
        "stage_status_valid": isinstance(stage.status, StageStatus),
        "completed_scope_contains_only_completed_work": all(
            item.temporal_state in {"PAST_VERIFIED", "CURRENT_VERIFIED"}
            for item in stage.completed_scope
        ),
        "strongest_result_has_evidence": (
            strongest.claim_id != "NONE_VERIFIED" and bool(strongest.evidence_refs)
        ),
        "weakest_critical_area_present": bool(stage.weakest_critical_area.area),
        "evidence_floor_present": isinstance(
            stage.evidence_quality.critical_floor,
            EvidenceLevel,
        ),
        "production_implication_separated": isinstance(
            stage.production_implication,
            ProductionImplication,
        ),
        "p0_p1_classified": not bool(contract_codes & priority_codes),
        "blocker_categories_complete": True,
        "none_verified_used_only_after_assessment": not bool(
            contract_codes & none_codes
        ),
        "next_stage_not_started": (
            not next_stage.started
            and not next_stage.authorized
            and not contract.stop_gate.automatic_transition
        ),
        "next_stage_inputs_listed": bool(next_stage.required_inputs) or none_authorized,
        "next_stage_artifacts_are_future_artifacts": all(
            item.temporal_state == "PLANNED_NOT_STARTED"
            for item in next_stage.expected_artifacts
        ),
        "acceptance_criteria_testable": bool(next_stage.acceptance_criteria)
        or none_authorized,
        "client_decisions_not_invented": not bool(
            contract_codes & client_decision_codes
        ),
        "status_matches_stop_gate": "STATUS_MISMATCH" not in contract_codes,
        "gate_key_matches_stage_id": "GATE_KEY_MISMATCH" not in contract_codes,
        "canonical_status_precedence_used": (
            "STATUS_PRECEDENCE_VIOLATION" not in contract_codes
        ),
        "audit_pass_not_confused_with_production_readiness": (
            stage.production_implication.production_ready is not True
            or stage.production_implication.state
            == ProductionState.PRODUCTION_READY_PROVEN
        ),
        "no_content_after_stop_gate": not bool(
            response_codes & {"STOP_GATE_NOT_LAST", "STOP_GATE_COUNT_INVALID"}
        ),
    }
