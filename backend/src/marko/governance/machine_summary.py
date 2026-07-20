"""Executable Section 16 machine-readable summary contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Any, Iterable, Mapping

from pydantic import ValidationError
import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

from .machine_summary_models import (
    SCHEMA_NAME,
    AssumptionStatus,
    CapabilityReadiness,
    CombinedMaturity,
    ExistingScraper,
    GapInventory,
    GapPriority,
    MachineReadableSummary,
    MarkoMaturity,
    MarkoSummary,
    MetisMaturity,
    ProductionGateStatus,
    QueueStability,
    ReadinessDimensionWeights,
    ReadinessDimensions,
    ReuseClassification,
    SourceAccessState,
    SystemReadinessBase,
    VerificationState,
)
from .response_footer import (
    EndOfResponse,
    EvidenceLevel,
    StageStatus,
    ValidationIssue,
    aggregate_status,
    expected_stop_gate_key,
    validate_rendered_footer,
)


FLOAT_TOLERANCE = 1e-6
MACHINE_SUMMARY_HEADING = "MACHINE_READABLE_SUMMARY:"

_EVIDENCE_RANK = {level: index for index, level in enumerate(EvidenceLevel)}
_EVIDENCE_CAP = {
    EvidenceLevel.E0: 0.0,
    EvidenceLevel.E1: 25.0,
    EvidenceLevel.E2: 50.0,
    EvidenceLevel.E3: 75.0,
    EvidenceLevel.E4: 90.0,
    EvidenceLevel.E5: 100.0,
}
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_YAML_FENCE_RE = re.compile(r"```yaml[ \t]*\n(?P<body>.*?)\n```", re.DOTALL)
_UNRESOLVED_UNION_RE = re.compile(
    r"(?:PASS|FAIL|BLOCKED|NO_GO|VERIFIED|UNKNOWN)\s*\|\s*"
)
_UNRESOLVED_TEMPLATE_RE = re.compile(r"^<[^>]+>$")
_YAML_11_BOOL_RE = re.compile(
    r"(?im)^\s*(?:-\s+|[^#\n]+:\s*)(?:YES|NO|ON|OFF)\s*(?:#.*)?$"
)
_REQUIRED_COMBINED_PRODUCTION_GATES = frozenset(
    {
        "REPLAY",
        "SECURITY",
        "TENANT_ISOLATION",
        "DEPLOYMENT",
        "BACKUP_RESTORE",
        "OBSERVABILITY",
        "ROLLBACK_RECOVERY",
        "SOURCE_ACCESS",
        "ABSTENTION",
    }
)
_SCRAPER_PRODUCTION_FIELDS = (
    "runtime_reverified",
    "batch_ready",
    "parallel_safe",
    "timeout_bounded",
    "retry_safe",
    "idempotent",
    "queue_integrated",
    "raw_storage_integrated",
    "structured_storage_integrated",
    "metis_evidence_integrated",
    "replayable",
    "observable",
    "load_tested",
)


class MachineSummaryParseError(ValueError):
    """Raised when strict YAML parsing or schema construction fails."""


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueKeySafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise MachineSummaryParseError(f"duplicate YAML key: {key!r}")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_str(
    dumper: _NoAliasSafeDumper,
    value: str,
) -> ScalarNode:
    needs_quotes = bool(
        _TIMESTAMP_RE.fullmatch(value)
        or re.fullmatch(r"(?i:yes|no|on|off|null|true|false)", value)
    )
    return dumper.represent_scalar(
        "tag:yaml.org,2002:str",
        value,
        style='"' if needs_quotes else None,
    )


_NoAliasSafeDumper.add_representer(str, _represent_str)


@dataclass(frozen=True, slots=True)
class ReadinessCalculation:
    raw_lower: float
    raw_upper: float
    effective_lower: float
    effective_upper: float
    unknown_dimension_weight: float


@dataclass(frozen=True, slots=True)
class ScraperCapacityCalculation:
    effective_worker_service_rate: float
    total_capacity: float
    utilization_rho: float | None
    queue_stability: QueueStability
    estimated_drain_seconds: float | None


def evidence_cap(level: EvidenceLevel) -> float:
    return _EVIDENCE_CAP[level]


def calculate_readiness(
    dimensions: ReadinessDimensions,
    evidence_level: EvidenceLevel,
    weights: ReadinessDimensionWeights | None = None,
) -> ReadinessCalculation:
    """Calculate conservative readiness bounds with UNKNOWN dimensions retained."""
    active_weights = weights or ReadinessDimensionWeights()
    weight_values = active_weights.model_dump()
    if not math.isclose(sum(weight_values.values()), 1.0, abs_tol=FLOAT_TOLERANCE):
        raise ValueError("readiness dimension weights must sum to 1")

    lower = 0.0
    upper = 0.0
    unknown_weight = 0.0
    values = dimensions.model_dump()
    for name, weight in weight_values.items():
        value = values[name]
        if value is None:
            upper += weight
            unknown_weight += weight
        else:
            lower += weight * value
            upper += weight * value

    raw_lower = 100 * lower
    raw_upper = 100 * upper
    cap = evidence_cap(evidence_level)
    return ReadinessCalculation(
        raw_lower=raw_lower,
        raw_upper=raw_upper,
        effective_lower=min(raw_lower, cap),
        effective_upper=min(raw_upper, cap),
        unknown_dimension_weight=unknown_weight,
    )


def calculate_reuse_score(
    *,
    functional_fit: float,
    metis_invariant_compatibility: float,
    data_model_compatibility: float,
    verification_strength: float,
    adaptation_cost: float,
) -> float:
    values = (
        functional_fit,
        metis_invariant_compatibility,
        data_model_compatibility,
        verification_strength,
        adaptation_cost,
    )
    if any(not 0 <= value <= 1 for value in values):
        raise ValueError("reuse dimensions must be in [0, 1]")
    return 100 * (
        0.30 * functional_fit
        + 0.25 * metis_invariant_compatibility
        + 0.20 * data_model_compatibility
        + 0.15 * verification_strength
        + 0.10 * (1 - adaptation_cost)
    )


def calculate_gap_rpn(
    severity: int,
    likelihood: int,
    detection_difficulty: int,
    dependency_centrality: int,
) -> tuple[int, float]:
    if not 1 <= severity <= 5:
        raise ValueError("severity must be in [1, 5]")
    if not 1 <= likelihood <= 5:
        raise ValueError("likelihood must be in [1, 5]")
    if not 1 <= detection_difficulty <= 5:
        raise ValueError("detection_difficulty must be in [1, 5]")
    if not 1 <= dependency_centrality <= 3:
        raise ValueError("dependency_centrality must be in [1, 3]")
    rpn = severity * likelihood * detection_difficulty * dependency_centrality
    return rpn, 100 * (rpn - 1) / 374


def calculate_scraper_capacity(
    *,
    arrival_rate: float,
    worker_service_rate: float,
    active_workers: int,
    average_attempts: float,
    backlog: int,
) -> ScraperCapacityCalculation:
    if arrival_rate < 0 or worker_service_rate < 0 or active_workers < 0 or backlog < 0:
        raise ValueError("capacity inputs cannot be negative")
    if average_attempts <= 0:
        raise ValueError("average_attempts must be positive")
    effective = worker_service_rate / average_attempts
    total = active_workers * effective
    rho = arrival_rate / total if total > 0 else None
    if total > arrival_rate:
        stability = QueueStability.STABLE
        drain = backlog / (total - arrival_rate)
    else:
        stability = QueueStability.UNSTABLE
        drain = None
    return ScraperCapacityCalculation(effective, total, rho, stability, drain)


def _is_close(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=FLOAT_TOLERANCE, abs_tol=FLOAT_TOLERANCE)


def _validate_rfc3339(value: str | None) -> bool:
    if value is None or _TIMESTAMP_RE.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _walk_nodes(node: Node) -> Iterable[Node]:
    yield node
    if isinstance(node, MappingNode):
        for key, value in node.value:
            yield from _walk_nodes(key)
            yield from _walk_nodes(value)
    elif isinstance(node, SequenceNode):
        for item in node.value:
            yield from _walk_nodes(item)


def _reject_yaml_hazards(text: str) -> None:
    if "\t" in text:
        raise MachineSummaryParseError("tabs are forbidden in YAML")
    if _YAML_11_BOOL_RE.search(text):
        raise MachineSummaryParseError("unquoted YES/NO/ON/OFF are forbidden")
    if re.search(r"(?m)^\s*<<\s*:", text):
        raise MachineSummaryParseError("YAML merge keys are forbidden")
    try:
        tokens = tuple(yaml.scan(text, Loader=_UniqueKeySafeLoader))
    except yaml.YAMLError as exc:
        raise MachineSummaryParseError(str(exc)) from exc
    for token in tokens:
        if isinstance(token, (AnchorToken, AliasToken, TagToken)):
            raise MachineSummaryParseError(
                "YAML anchors, aliases, and explicit/custom tags are forbidden"
            )


def _reject_node_hazards(node: Node) -> None:
    for current in _walk_nodes(node):
        if current.tag == "tag:yaml.org,2002:timestamp":
            raise MachineSummaryParseError(
                "implicit YAML timestamps are forbidden; quote RFC 3339 strings"
            )
        if isinstance(current, ScalarNode) and isinstance(current.value, str):
            if current.value == "":
                raise MachineSummaryParseError("empty strings are forbidden")
            if _UNRESOLVED_UNION_RE.search(current.value):
                raise MachineSummaryParseError("unresolved enum union placeholder")
            if _UNRESOLVED_TEMPLATE_RE.fullmatch(current.value):
                raise MachineSummaryParseError("unresolved template placeholder")


def parse_machine_summary_yaml(text: str) -> MachineReadableSummary:
    """Strictly parse one safe YAML document and validate schema types."""
    _reject_yaml_hazards(text)
    try:
        nodes = tuple(yaml.compose_all(text, Loader=_UniqueKeySafeLoader))
    except (yaml.YAMLError, MachineSummaryParseError) as exc:
        raise MachineSummaryParseError(str(exc)) from exc
    if len(nodes) != 1 or nodes[0] is None:
        raise MachineSummaryParseError(
            "exactly one non-empty YAML document is required"
        )
    _reject_node_hazards(nodes[0])
    try:
        documents = tuple(yaml.load_all(text, Loader=_UniqueKeySafeLoader))
    except (yaml.YAMLError, MachineSummaryParseError) as exc:
        raise MachineSummaryParseError(str(exc)) from exc
    if len(documents) != 1 or not isinstance(documents[0], dict):
        raise MachineSummaryParseError("YAML root must be one mapping")
    try:
        return MachineReadableSummary.model_validate(documents[0])
    except ValidationError as exc:
        raise MachineSummaryParseError(str(exc)) from exc


def dump_machine_summary(summary: MachineReadableSummary) -> str:
    """Serialize deterministically without aliases or implicit timestamps."""
    return yaml.dump(
        summary.model_dump(mode="json"),
        Dumper=_NoAliasSafeDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1000,
    ).rstrip()


def validate_yaml_round_trip(summary: MachineReadableSummary) -> bool:
    rendered = dump_machine_summary(summary)
    reparsed = parse_machine_summary_yaml(rendered)
    return reparsed.model_dump(mode="json") == summary.model_dump(mode="json")


def render_machine_summary_block(summary: MachineReadableSummary) -> str:
    return f"{MACHINE_SUMMARY_HEADING}\n\n```yaml\n{dump_machine_summary(summary)}\n```"


def _unknown_covers(summary: MachineReadableSummary, path: str) -> bool:
    for unknown in summary.unknowns:
        declared = unknown.field_path
        if declared == path:
            return True
        if declared.endswith(".*") and path.startswith(declared[:-1]):
            return True
    return False


def _validate_capability(
    capability: CapabilityReadiness,
    weights: ReadinessDimensionWeights,
    path: str,
    add: Any,
) -> ReadinessCalculation:
    calculated = calculate_readiness(
        capability.dimensions,
        capability.evidence_level,
        weights,
    )
    expected = {
        f"{path}.raw_interval.lower": (
            capability.raw_interval.lower,
            calculated.raw_lower,
        ),
        f"{path}.raw_interval.upper": (
            capability.raw_interval.upper,
            calculated.raw_upper,
        ),
        f"{path}.effective_interval.lower": (
            capability.effective_interval.lower,
            calculated.effective_lower,
        ),
        f"{path}.effective_interval.upper": (
            capability.effective_interval.upper,
            calculated.effective_upper,
        ),
        f"{path}.unknown_dimension_weight": (
            capability.unknown_dimension_weight,
            calculated.unknown_dimension_weight,
        ),
    }
    for field_path, (actual, target) in expected.items():
        if not _is_close(actual, target):
            add(
                "CAPABILITY_ARITHMETIC_MISMATCH",
                field_path,
                f"expected {target:.6f}, got {actual}",
            )
    if capability.evidence_level != EvidenceLevel.E0 and not capability.evidence_refs:
        add(
            "CAPABILITY_EVIDENCE_UNTRACED",
            f"{path}.evidence_refs",
            "E1+ capability evidence requires references",
        )
    return calculated


def _validate_system_readiness(
    system: SystemReadinessBase,
    path: str,
    add: Any,
) -> None:
    dimension_weight_sum = sum(system.dimension_weights.model_dump().values())
    if not math.isclose(dimension_weight_sum, 1.0, abs_tol=FLOAT_TOLERANCE):
        add(
            "DIMENSION_WEIGHTS_INVALID",
            f"{path}.dimension_weights",
            f"weights sum to {dimension_weight_sum}, expected 1",
        )

    capabilities = system.capabilities
    if not capabilities:
        readiness_values = (
            system.weighted_readiness,
            system.readiness_interval.lower,
            system.readiness_interval.upper,
            system.critical_floor,
            system.evidence_level,
            system.highest_evidence_level,
            system.unknown_weight,
            system.critical_unknown_count,
        )
        if any(value is not None for value in readiness_values):
            add(
                "READINESS_WITHOUT_CAPABILITIES",
                path,
                "readiness values require traced capability records",
            )
        return

    capability_ids = [item.capability_id for item in capabilities]
    if len(capability_ids) != len(set(capability_ids)):
        add("DUPLICATE_CAPABILITY_ID", f"{path}.capabilities", "IDs must be unique")
    capability_weight_sum = sum(item.weight for item in capabilities)
    if not math.isclose(capability_weight_sum, 1.0, abs_tol=FLOAT_TOLERANCE):
        add(
            "CAPABILITY_WEIGHTS_INVALID",
            f"{path}.capabilities",
            f"weights sum to {capability_weight_sum}, expected 1",
        )

    calculations: dict[str, ReadinessCalculation] = {}
    by_id = {item.capability_id: item for item in capabilities}
    for index, capability in enumerate(capabilities):
        calculations[capability.capability_id] = _validate_capability(
            capability,
            system.dimension_weights,
            f"{path}.capabilities[{index}]",
            add,
        )

    declared_critical = set(system.critical_capability_ids)
    modeled_critical = {item.capability_id for item in capabilities if item.critical}
    if not declared_critical or declared_critical != modeled_critical:
        add(
            "CRITICAL_CAPABILITY_SET_INVALID",
            f"{path}.critical_capability_ids",
            "critical IDs must be non-empty and equal capability critical flags",
        )
        return

    weighted_lower = sum(
        item.weight * calculations[item.capability_id].effective_lower
        for item in capabilities
    )
    weighted_upper = sum(
        item.weight * calculations[item.capability_id].effective_upper
        for item in capabilities
    )
    unknown_weight = sum(
        item.weight * calculations[item.capability_id].unknown_dimension_weight
        for item in capabilities
    )
    critical_floor = min(
        calculations[item_id].effective_lower for item_id in declared_critical
    )
    critical_evidence = min(
        (by_id[item_id].evidence_level for item_id in declared_critical),
        key=_EVIDENCE_RANK.__getitem__,
    )
    highest_evidence = max(
        (item.evidence_level for item in capabilities),
        key=_EVIDENCE_RANK.__getitem__,
    )
    critical_unknown_count = sum(
        calculations[item_id].unknown_dimension_weight > FLOAT_TOLERANCE
        for item_id in declared_critical
    )
    checks = {
        f"{path}.weighted_readiness": (system.weighted_readiness, weighted_lower),
        f"{path}.readiness_interval.lower": (
            system.readiness_interval.lower,
            weighted_lower,
        ),
        f"{path}.readiness_interval.upper": (
            system.readiness_interval.upper,
            weighted_upper,
        ),
        f"{path}.critical_floor": (system.critical_floor, critical_floor),
        f"{path}.unknown_weight": (system.unknown_weight, unknown_weight),
    }
    for field_path, (actual, expected) in checks.items():
        if not _is_close(actual, expected):
            add(
                "SYSTEM_READINESS_MISMATCH",
                field_path,
                f"expected {expected:.6f}, got {actual}",
            )
    if system.evidence_level != critical_evidence:
        add(
            "CRITICAL_EVIDENCE_FLOOR_MISMATCH",
            f"{path}.evidence_level",
            f"expected {critical_evidence.value}",
        )
    if system.highest_evidence_level != highest_evidence:
        add(
            "HIGHEST_EVIDENCE_MISMATCH",
            f"{path}.highest_evidence_level",
            f"expected {highest_evidence.value}",
        )
    if system.critical_unknown_count != critical_unknown_count:
        add(
            "CRITICAL_UNKNOWN_COUNT_MISMATCH",
            f"{path}.critical_unknown_count",
            f"expected {critical_unknown_count}",
        )
    if system.production_eligible and (
        system.evidence_level is None
        or _EVIDENCE_RANK[system.evidence_level] < _EVIDENCE_RANK[EvidenceLevel.E4]
        or system.critical_unknown_count != 0
        or system.critical_floor is None
        or system.production_gate.status != ProductionGateStatus.PASS
        or system.missing_critical_domains
    ):
        add(
            "SYSTEM_PRODUCTION_ELIGIBILITY_UNPROVEN",
            f"{path}.production_eligible",
            "system production eligibility requires E4+, zero critical unknowns, no missing critical domain, and gate PASS",
        )


def _validate_production_gate(
    *,
    eligible: bool,
    gate: Any,
    path: str,
    add: Any,
) -> None:
    all_gate_ids = (
        gate.passed_gates + gate.failed_gates + gate.blocked_gates + gate.unknown_gates
    )
    if len(all_gate_ids) != len(set(all_gate_ids)):
        add("DUPLICATE_PRODUCTION_GATE", path, "gate IDs must be disjoint")
    if eligible and gate.status != ProductionGateStatus.PASS:
        add(
            "PRODUCTION_ELIGIBLE_GATE_MISMATCH",
            f"{path}.status",
            "production_eligible=true requires gate PASS",
        )
    if gate.status == ProductionGateStatus.PASS and not eligible:
        add(
            "PRODUCTION_GATE_PASS_WITHOUT_ELIGIBILITY",
            f"{path}.status",
            "production gate PASS requires production_eligible=true",
        )
    if gate.status == ProductionGateStatus.PASS and (
        gate.failed_gates or gate.blocked_gates or gate.unknown_gates
    ):
        add(
            "PRODUCTION_GATE_PASS_WITH_OPEN_GATES",
            path,
            "PASS forbids failed, blocked, or unknown gates",
        )


def _validate_scraper(
    scraper: ExistingScraper,
    validation_warnings: tuple[str, ...],
    add: Any,
) -> None:
    path = "marko.existing_scraper"
    if scraper.located == VerificationState.VERIFIED:
        if scraper.physical_path is None or not scraper.evidence_refs:
            add(
                "LOCATED_SCRAPER_UNTRACED",
                path,
                "located=VERIFIED requires physical_path and evidence refs",
            )
    if scraper.production_proven == VerificationState.VERIFIED:
        for field in _SCRAPER_PRODUCTION_FIELDS:
            if getattr(scraper, field) != VerificationState.VERIFIED:
                add(
                    "SCRAPER_PRODUCTION_PROOF_INCOMPLETE",
                    f"{path}.{field}",
                    "production_proven requires VERIFIED",
                )
        if not scraper.capacity.measured:
            add(
                "SCRAPER_PRODUCTION_WITHOUT_CAPACITY",
                f"{path}.capacity.measured",
                "production proof requires measured capacity",
            )
    if scraper.batch_ready == VerificationState.VERIFIED:
        batch_requirements = (
            "input_contract_verified",
            "output_contract_verified",
            "runtime_reverified",
            "small_batch_verified",
            "timeout_bounded",
            "retry_safe",
            "idempotent",
        )
        for field in batch_requirements:
            if getattr(scraper, field) != VerificationState.VERIFIED:
                add(
                    "SCRAPER_BATCH_READINESS_UNPROVEN",
                    f"{path}.{field}",
                    "batch_ready=VERIFIED requires this prerequisite",
                )
    if scraper.parallel_safe == VerificationState.VERIFIED and (
        scraper.runtime_reverified != VerificationState.VERIFIED
        or scraper.small_batch_verified != VerificationState.VERIFIED
        or not scraper.evidence_refs
    ):
        add(
            "SCRAPER_PARALLEL_SAFETY_UNPROVEN",
            f"{path}.parallel_safe",
            "parallel safety requires runtime, batch, and traced concurrency evidence",
        )
    if scraper.queue_integrated == VerificationState.VERIFIED:
        queue_requirements = (
            "retry_safe",
            "idempotent",
            "dead_letter_integrated",
            "raw_storage_integrated",
            "structured_storage_integrated",
            "metis_evidence_integrated",
        )
        for field in queue_requirements:
            if getattr(scraper, field) != VerificationState.VERIFIED:
                add(
                    "SCRAPER_QUEUE_INTEGRATION_UNPROVEN",
                    f"{path}.{field}",
                    "queue_integrated=VERIFIED requires this prerequisite",
                )

    capacity = scraper.capacity
    numeric_fields = (
        "unique_urls",
        "arrival_rate_urls_per_second",
        "worker_service_rate_urls_per_second",
        "active_workers",
        "average_attempts_per_unique_url",
        "effective_worker_service_rate",
        "total_capacity_urls_per_second",
        "utilization_rho",
        "queue_backlog",
        "estimated_drain_seconds",
        "success_rate",
        "retry_amplification",
        "latency_p50_seconds",
        "latency_p95_seconds",
        "latency_p99_seconds",
        "raw_storage_bytes",
        "structured_storage_bytes",
        "memory_peak_bytes",
        "cpu_average_percent",
    )
    if not capacity.measured:
        if any(getattr(capacity, field) is not None for field in numeric_fields):
            add(
                "UNMEASURED_CAPACITY_HAS_VALUES",
                f"{path}.capacity",
                "measured=false requires null capacity measurements",
            )
        if capacity.queue_stability not in {
            QueueStability.NOT_MEASURED,
            QueueStability.UNKNOWN,
        }:
            add(
                "UNMEASURED_QUEUE_STABILITY",
                f"{path}.capacity.queue_stability",
                "unmeasured capacity cannot claim stable/unstable",
            )
        return

    required = {
        "unique_urls": capacity.unique_urls,
        "arrival_rate_urls_per_second": capacity.arrival_rate_urls_per_second,
        "worker_service_rate_urls_per_second": (
            capacity.worker_service_rate_urls_per_second
        ),
        "active_workers": capacity.active_workers,
        "average_attempts_per_unique_url": capacity.average_attempts_per_unique_url,
        "queue_backlog": capacity.queue_backlog,
        "success_rate": capacity.success_rate,
        "retry_amplification": capacity.retry_amplification,
        "latency_p50_seconds": capacity.latency_p50_seconds,
        "latency_p95_seconds": capacity.latency_p95_seconds,
        "latency_p99_seconds": capacity.latency_p99_seconds,
        "raw_storage_bytes": capacity.raw_storage_bytes,
        "structured_storage_bytes": capacity.structured_storage_bytes,
        "memory_peak_bytes": capacity.memory_peak_bytes,
        "cpu_average_percent": capacity.cpu_average_percent,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        add(
            "MEASURED_CAPACITY_MISSING_INPUT",
            f"{path}.capacity",
            f"missing {', '.join(missing)}",
        )
        return
    if capacity.unique_urls == 0:
        add(
            "MEASURED_CAPACITY_EMPTY_BATCH",
            f"{path}.capacity.unique_urls",
            "measured capacity requires at least one unique URL",
        )
    if not _is_close(
        capacity.retry_amplification,
        capacity.average_attempts_per_unique_url,
    ):
        add(
            "RETRY_AMPLIFICATION_MISMATCH",
            f"{path}.capacity.retry_amplification",
            "retry amplification must equal attempts_total / unique_urls_total",
        )
    calculation = calculate_scraper_capacity(
        arrival_rate=capacity.arrival_rate_urls_per_second,
        worker_service_rate=capacity.worker_service_rate_urls_per_second,
        active_workers=capacity.active_workers,
        average_attempts=capacity.average_attempts_per_unique_url,
        backlog=capacity.queue_backlog,
    )
    checks = {
        "effective_worker_service_rate": (
            capacity.effective_worker_service_rate,
            calculation.effective_worker_service_rate,
        ),
        "total_capacity_urls_per_second": (
            capacity.total_capacity_urls_per_second,
            calculation.total_capacity,
        ),
        "utilization_rho": (capacity.utilization_rho, calculation.utilization_rho),
        "estimated_drain_seconds": (
            capacity.estimated_drain_seconds,
            calculation.estimated_drain_seconds,
        ),
    }
    for field, (actual, expected) in checks.items():
        if not _is_close(actual, expected):
            add(
                "SCRAPER_CAPACITY_MISMATCH",
                f"{path}.capacity.{field}",
                f"expected {expected}, got {actual}",
            )
    if capacity.queue_stability != calculation.queue_stability:
        add(
            "QUEUE_STABILITY_MISMATCH",
            f"{path}.capacity.queue_stability",
            f"expected {calculation.queue_stability.value}",
        )
    if scraper.production_proven == VerificationState.VERIFIED and (
        calculation.queue_stability != QueueStability.STABLE
        or calculation.utilization_rho is None
        or calculation.utilization_rho > 0.70 + FLOAT_TOLERANCE
    ):
        add(
            "SCRAPER_PRODUCTION_CAPACITY_UNSAFE",
            f"{path}.capacity",
            "production proof requires stable measured capacity at rho <= 0.70",
        )
    if (
        calculation.utilization_rho is not None
        and calculation.utilization_rho > 0.70 + FLOAT_TOLERANCE
        and "SCRAPER_UTILIZATION_ABOVE_ENGINEERING_TARGET" not in validation_warnings
    ):
        add(
            "MISSING_UTILIZATION_WARNING",
            "validation.warnings",
            "rho > 0.70 must be disclosed as an engineering-target warning",
        )
    if (
        capacity.latency_p50_seconds is not None
        and capacity.latency_p95_seconds is not None
        and capacity.latency_p99_seconds is not None
        and not (
            capacity.latency_p50_seconds
            <= capacity.latency_p95_seconds
            <= capacity.latency_p99_seconds
        )
    ):
        add(
            "SCRAPER_LATENCY_ORDER_INVALID",
            f"{path}.capacity",
            "latency must satisfy p50 <= p95 <= p99",
        )


def _validate_reuse(marko: MarkoSummary, add: Any) -> None:
    arrays: Mapping[ReuseClassification, tuple[Any, ...]] = {
        ReuseClassification.REUSABLE_AS_IS: marko.reusable_as_is,
        ReuseClassification.ADAPT_BEFORE_REUSE: marko.adapt_before_reuse,
        ReuseClassification.REFERENCE_ONLY: marko.reference_only,
        ReuseClassification.DO_NOT_PORT: marko.do_not_port,
        ReuseClassification.UNKNOWN: marko.unknown_reuse_state,
    }
    all_records: list[Any] = []
    for classification, records in arrays.items():
        for index, record in enumerate(records):
            all_records.append(record)
            path = f"marko.{classification.value.lower()}[{index}]"
            if record.classification != classification:
                add(
                    "REUSE_CLASSIFICATION_MISMATCH",
                    path,
                    f"array requires {classification.value}",
                )
            dimensions = (
                record.functional_fit,
                record.metis_invariant_compatibility,
                record.data_model_compatibility,
                record.verification_strength,
                record.adaptation_cost,
            )
            if all(value is not None for value in dimensions):
                expected = calculate_reuse_score(
                    functional_fit=record.functional_fit,
                    metis_invariant_compatibility=record.metis_invariant_compatibility,
                    data_model_compatibility=record.data_model_compatibility,
                    verification_strength=record.verification_strength,
                    adaptation_cost=record.adaptation_cost,
                )
                if not _is_close(record.reuse_score, expected):
                    add(
                        "REUSE_SCORE_MISMATCH",
                        f"{path}.reuse_score",
                        f"expected {expected:.6f}",
                    )
            elif record.reuse_score is not None:
                add(
                    "REUSE_SCORE_WITH_UNKNOWN_DIMENSION",
                    f"{path}.reuse_score",
                    "point score forbidden while a reuse dimension is unknown",
                )
            if classification == ReuseClassification.REUSABLE_AS_IS:
                if (
                    any(value is None for value in dimensions)
                    or record.metis_invariant_compatibility != 1.0
                    or record.data_model_compatibility != 1.0
                    or record.verification_strength < 0.75
                    or record.violated_metis_invariants
                    or record.required_adaptations
                    or not record.evidence_refs
                ):
                    add(
                        "REUSABLE_AS_IS_UNPROVEN",
                        path,
                        "REUSABLE_AS_IS requires complete compatible traced evidence",
                    )

    ids = [record.component_id for record in all_records]
    unique = len(ids) == len(set(ids))
    complete = set(ids) == set(marko.evaluated_component_ids)
    expected_valid = unique and complete
    assessment_not_run = not ids and not marko.evaluated_component_ids
    if not assessment_not_run and marko.reuse_partition_valid is not expected_valid:
        add(
            "REUSE_PARTITION_FLAG_MISMATCH",
            "marko.reuse_partition_valid",
            f"expected {str(expected_valid).lower()}",
        )
    if not unique:
        add("REUSE_PARTITION_OVERLAP", "marko", "component IDs overlap reuse arrays")
    if not complete:
        add(
            "REUSE_PARTITION_INCOMPLETE",
            "marko.evaluated_component_ids",
            "reuse union must equal evaluated components",
        )
    if assessment_not_run and marko.reuse_partition_valid is False:
        add(
            "REUSE_EMPTY_PARTITION_FLAG_INVALID",
            "marko.reuse_partition_valid",
            "an empty partition is either verified true or unassessed null",
        )


def _validate_gaps(gaps: GapInventory, add: Any) -> None:
    arrays = {
        GapPriority.P0: gaps.p0,
        GapPriority.P1: gaps.p1,
        GapPriority.P2: gaps.p2,
        GapPriority.P3: gaps.p3,
    }
    all_records: list[Any] = []
    for priority, records in arrays.items():
        for index, record in enumerate(records):
            all_records.append(record)
            path = f"gaps.{priority.value.lower()}[{index}]"
            if record.priority != priority:
                add(
                    "GAP_PRIORITY_MISMATCH",
                    path,
                    f"array requires {priority.value}",
                )
            rpn, normalized = calculate_gap_rpn(
                record.severity,
                record.likelihood,
                record.detection_difficulty,
                record.dependency_centrality,
            )
            if record.rpn != rpn or not _is_close(record.normalized_rpn, normalized):
                add(
                    "GAP_RPN_MISMATCH",
                    path,
                    f"expected rpn={rpn}, normalized={normalized:.6f}",
                )
            if not record.evidence_refs:
                add(
                    "GAP_UNTRACED",
                    f"{path}.evidence_refs",
                    "every gap requires evidence",
                )

    ids = [record.gap_id for record in all_records]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    expected_valid = not duplicates
    if tuple(sorted(gaps.duplicate_gap_ids)) != tuple(duplicates):
        add(
            "DUPLICATE_GAP_LIST_MISMATCH",
            "gaps.duplicate_gap_ids",
            f"expected {duplicates}",
        )
    if all_records and gaps.priority_partition_valid is not expected_valid:
        add(
            "GAP_PARTITION_FLAG_MISMATCH",
            "gaps.priority_partition_valid",
            f"expected {str(expected_valid).lower()}",
        )
    if not all_records and gaps.priority_partition_valid is False:
        add(
            "GAP_EMPTY_PARTITION_FLAG_INVALID",
            "gaps.priority_partition_valid",
            "an empty partition is either verified true or unassessed null",
        )


def _collect_global_ids(summary: MachineReadableSummary) -> list[tuple[str, str]]:
    values: list[tuple[str, str]] = []
    values.extend(
        (item.capability_id, "capability") for item in summary.metis.capabilities
    )
    values.extend(
        (item.capability_id, "capability") for item in summary.marko.capabilities
    )
    for records in (
        summary.marko.reusable_as_is,
        summary.marko.adapt_before_reuse,
        summary.marko.reference_only,
        summary.marko.do_not_port,
        summary.marko.unknown_reuse_state,
    ):
        values.extend((item.component_id, "reuse_component") for item in records)
    for records in (summary.gaps.p0, summary.gaps.p1, summary.gaps.p2, summary.gaps.p3):
        values.extend((item.gap_id, "gap") for item in records)
    values.extend(
        (item.decision_id, "business_decision")
        for item in summary.business_decisions_required
    )
    values.extend((item.source_id, "source") for item in summary.source_access_states)
    values.extend(
        (item.assumption_id, "assumption") for item in summary.engineering_assumptions
    )
    values.extend(
        (item.hypothesis_id, "hypothesis") for item in summary.future_hypotheses
    )
    values.extend((item.unknown_id, "unknown") for item in summary.unknowns)
    return values


def validate_summary(summary: MachineReadableSummary) -> tuple[ValidationIssue, ...]:
    """Validate Section 16 arithmetic, evidence, partition, and gate invariants."""
    issues: list[ValidationIssue] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append(ValidationIssue(code, path, message))

    if summary.schema_.name != SCHEMA_NAME:
        add("SCHEMA_NAME_INVALID", "schema.name", "unexpected schema name")
    if summary.schema_.generated_at is not None and not _validate_rfc3339(
        summary.schema_.generated_at
    ):
        add(
            "GENERATED_AT_INVALID",
            "schema.generated_at",
            "generated_at must be an explicit RFC 3339 string",
        )

    stage = summary.stage
    termination = summary.termination
    expected_key = expected_stop_gate_key(stage.id)
    if termination.stop_gate_key != expected_key:
        add(
            "STOP_GATE_KEY_MISMATCH",
            "termination.stop_gate_key",
            f"expected {expected_key}",
        )
    if stage.status != termination.stop_gate_value:
        add(
            "STOP_GATE_STATUS_MISMATCH",
            "termination.stop_gate_value",
            "stage status and stop-gate value must match",
        )
    if termination.stage_status_matches_stop_gate is not True:
        add(
            "STOP_GATE_MATCH_FLAG_INVALID",
            "termination.stage_status_matches_stop_gate",
            "must be true after validation",
        )
    aggregated = aggregate_status(
        (stage.status, *(item.type for item in stage.secondary_findings))
    )
    if aggregated != stage.status:
        add(
            "STATUS_PRECEDENCE_VIOLATION",
            "stage.secondary_findings",
            f"primary status must be {aggregated.value}",
        )
    if not stage.status_reason or not stage.evidence_refs:
        add(
            "STAGE_RESULT_UNTRACED",
            "stage",
            "status requires a reason and evidence references",
        )

    if stage.status == StageStatus.PASS:
        if (
            stage.acceptance_criteria_passed is not True
            or stage.audit_complete is not True
        ):
            add(
                "PASS_WITHOUT_COMPLETION",
                "stage",
                "PASS requires acceptance_criteria_passed=true and audit_complete=true",
            )
        required_validation_flags = (
            "yaml_parse",
            "duplicate_key_check",
            "schema_validation",
            "required_field_validation",
            "enum_validation",
            "type_validation",
            "arithmetic_validation",
            "readiness_interval_validation",
            "evidence_ceiling_validation",
            "critical_floor_validation",
            "stop_gate_consistency",
            "production_gate_consistency",
            "reuse_partition_validation",
            "gap_partition_validation",
            "evidence_traceability",
            "reverse_trace_validation",
            "variation_validation",
            "hostile_review",
        )
        for field in required_validation_flags:
            if getattr(summary.validation, field) is not True:
                add(
                    "PASS_WITH_INCOMPLETE_VALIDATION",
                    f"validation.{field}",
                    "PASS requires true",
                )
        if summary.validation.errors:
            add(
                "PASS_WITH_VALIDATION_ERRORS",
                "validation.errors",
                "PASS requires an empty errors array",
            )

    next_stage = summary.next_stage
    if next_stage.started or not next_stage.new_direct_instruction_required:
        add(
            "NEXT_STAGE_AUTO_STARTED",
            "next_stage",
            "next stage must remain stopped pending direct instruction",
        )
    if any(
        value is None
        for value in (
            next_stage.id,
            next_stage.title,
            next_stage.objective,
            next_stage.why_it_is_next,
            next_stage.stop_condition,
        )
    ):
        add(
            "NEXT_STAGE_INCOMPLETE",
            "next_stage",
            "next-stage identity, objective, reason, and stop condition are required",
        )
    if (
        not next_stage.required_inputs
        or not next_stage.expected_outputs
        or not next_stage.acceptance_criteria
    ):
        add(
            "NEXT_STAGE_CONTRACT_INCOMPLETE",
            "next_stage",
            "inputs, future outputs, and acceptance criteria are required",
        )
    next_id = next_stage.id or ""
    if stage.status == StageStatus.FAIL and not any(
        token in next_id for token in ("REPAIR", "REVALIDATION")
    ):
        add(
            "FAIL_NEXT_STAGE_INVALID",
            "next_stage.id",
            "FAIL must lead to repair/revalidation",
        )
    if stage.status == StageStatus.BLOCKED and not any(
        token in next_id for token in ("RESUME", "DEPENDENCY", "INPUT", "DECISION")
    ):
        add(
            "BLOCKED_NEXT_STAGE_INVALID",
            "next_stage.id",
            "BLOCKED must resolve dependency and resume",
        )
    if stage.status == StageStatus.NO_GO and (
        "IMPLEMENTATION" in next_id
        or not any(
            token in next_id
            for token in ("DECISION", "REDESIGN", "ALTERNATIVE", "REPLACEMENT")
        )
    ):
        add(
            "NO_GO_NEXT_STAGE_INVALID",
            "next_stage.id",
            "NO_GO requires a decision/redesign successor",
        )

    repository = summary.repository
    if repository.identity_verified is True:
        if (
            repository.topology.value == "UNKNOWN"
            or repository.git_commit is None
            or repository.audit_root_realpath is None
            or repository.runtime_import_identity is None
            or repository.unresolved_identity_conflicts
            or repository.duplicate_copies
            or repository.components.metis.identity_verified is not True
            or repository.components.marko.identity_verified is not True
        ):
            add(
                "REPOSITORY_IDENTITY_OVERSTATED",
                "repository.identity_verified",
                "combined identity requires verified components and no conflicts",
            )
    for component_name in ("metis", "marko"):
        component = getattr(repository.components, component_name)
        if component.identity_verified is True and (
            component.root is None
            or component.realpath is None
            or component.repository_top_level is None
            or component.git_commit is None
            or component.runtime_import_path is None
            or not component.evidence_refs
        ):
            add(
                "COMPONENT_IDENTITY_UNTRACED",
                f"repository.components.{component_name}",
                "identity_verified=true requires complete snapshot and evidence",
            )
        if component.dirty_before_audit is True and not any(
            token in evidence_ref.lower()
            for evidence_ref in component.evidence_refs
            for token in ("diff", "dirty", "patch", "snapshot")
        ):
            add(
                "DIRTY_WORKTREE_UNSNAPSHOTTED",
                f"repository.components.{component_name}.dirty_before_audit",
                "dirty worktree requires a diff/patch/snapshot evidence reference",
            )
    if repository.topology.value == "MONOREPO" and (
        repository.components.metis.repository_top_level
        != repository.components.marko.repository_top_level
        or repository.components.metis.git_commit
        != repository.components.marko.git_commit
    ):
        add(
            "MONOREPO_COMPONENT_SNAPSHOT_MISMATCH",
            "repository.components",
            "MONOREPO requires one top-level and commit for Metis and Marko",
        )

    _validate_system_readiness(summary.metis, "metis", add)
    _validate_system_readiness(summary.marko, "marko", add)
    _validate_production_gate(
        eligible=summary.metis.production_eligible,
        gate=summary.metis.production_gate,
        path="metis.production_gate",
        add=add,
    )
    _validate_production_gate(
        eligible=summary.marko.production_eligible,
        gate=summary.marko.production_gate,
        path="marko.production_gate",
        add=add,
    )
    _validate_production_gate(
        eligible=summary.combined_system.production_eligible,
        gate=summary.combined_system.production_gate,
        path="combined_system.production_gate",
        add=add,
    )

    for path, domains in (
        ("metis", summary.metis.strongest_domains),
        ("marko", summary.marko.strongest_domains),
    ):
        for index, domain in enumerate(domains):
            if (
                domain.effective_readiness < 50
                or _EVIDENCE_RANK[domain.evidence_level]
                < _EVIDENCE_RANK[EvidenceLevel.E2]
                or not domain.evidence_refs
                or domain.effective_readiness > evidence_cap(domain.evidence_level)
            ):
                add(
                    "STRONGEST_DOMAIN_UNSUPPORTED",
                    f"{path}.strongest_domains[{index}]",
                    "strongest domains require traced E2+ evidence and capped readiness >= 50",
                )

    production_metis_classes = {
        MetisMaturity.PRODUCTION_CANDIDATE_ENGINE,
        MetisMaturity.PRODUCTION_PRICING_ENGINE,
    }
    production_marko_classes = {
        MarkoMaturity.PRODUCTION_CANDIDATE_SAAS_SHELL,
        MarkoMaturity.PRODUCTION_SAAS_SHELL,
    }
    if summary.metis.maturity_class in production_metis_classes and (
        summary.metis.highest_evidence_level is None
        or _EVIDENCE_RANK[summary.metis.highest_evidence_level]
        < _EVIDENCE_RANK[EvidenceLevel.E4]
    ):
        add(
            "METIS_MATURITY_OVERSTATED",
            "metis.maturity_class",
            "production class requires E4+",
        )
    if summary.marko.maturity_class in production_marko_classes and (
        summary.marko.highest_evidence_level is None
        or _EVIDENCE_RANK[summary.marko.highest_evidence_level]
        < _EVIDENCE_RANK[EvidenceLevel.E4]
    ):
        add(
            "MARKO_MATURITY_OVERSTATED",
            "marko.maturity_class",
            "production class requires E4+",
        )

    combined = summary.combined_system
    if combined.end_to_end_flow_verified == VerificationState.VERIFIED and (
        combined.end_to_end_evidence_level is None
        or _EVIDENCE_RANK[combined.end_to_end_evidence_level]
        < _EVIDENCE_RANK[EvidenceLevel.E4]
        or not combined.evidence_refs
    ):
        add(
            "END_TO_END_EVIDENCE_TOO_WEAK",
            "combined_system.end_to_end_flow_verified",
            "VERIFIED end-to-end flow requires traced E4+ evidence",
        )
    if combined.maturity_class in {
        CombinedMaturity.PRODUCTION_CANDIDATE,
        CombinedMaturity.PRODUCTION_SYSTEM,
    } and (
        combined.end_to_end_evidence_level is None
        or _EVIDENCE_RANK[combined.end_to_end_evidence_level]
        < _EVIDENCE_RANK[EvidenceLevel.E4]
    ):
        add(
            "COMBINED_MATURITY_OVERSTATED",
            "combined_system.maturity_class",
            "production class requires E4+ end-to-end evidence",
        )

    _validate_scraper(summary.marko.existing_scraper, summary.validation.warnings, add)
    _validate_reuse(summary.marko, add)
    _validate_gaps(summary.gaps, add)

    if combined.production_eligible:
        recommendation_states = combined.recommendation_contract.model_dump().values()
        if (
            not summary.metis.production_eligible
            or not summary.marko.production_eligible
            or combined.end_to_end_flow_verified != VerificationState.VERIFIED
            or combined.end_to_end_evidence_level is None
            or _EVIDENCE_RANK[combined.end_to_end_evidence_level]
            < _EVIDENCE_RANK[EvidenceLevel.E4]
            or any(
                state != VerificationState.VERIFIED for state in recommendation_states
            )
            or summary.metis.critical_unknown_count != 0
            or summary.marko.critical_unknown_count != 0
            or summary.gaps.p0
            or summary.gaps.p1
            or any(
                source.state
                in {
                    SourceAccessState.UNKNOWN,
                    SourceAccessState.NOT_PERMITTED,
                    SourceAccessState.BLOCKED_PENDING_DECISION,
                }
                for source in summary.source_access_states
            )
            or not _REQUIRED_COMBINED_PRODUCTION_GATES.issubset(
                set(combined.production_gate.passed_gates)
            )
        ):
            add(
                "COMBINED_PRODUCTION_ELIGIBILITY_UNPROVEN",
                "combined_system.production_eligible",
                "combined production predicate is incomplete",
            )

    if stage.production_ready is True and not combined.production_eligible:
        add(
            "STAGE_PRODUCTION_READY_OVERSTATED",
            "stage.production_ready",
            "stage production_ready=true requires combined eligibility",
        )

    for index, source in enumerate(summary.source_access_states):
        if source.state not in {
            SourceAccessState.UNKNOWN,
            SourceAccessState.NOT_APPLICABLE,
        } and (
            source.basis is None
            or source.verified_at is None
            or not source.evidence_refs
        ):
            add(
                "SOURCE_STATE_UNTRACED",
                f"source_access_states[{index}]",
                "verified source state requires basis, timestamp, and evidence",
            )
        for timestamp_field in ("verified_at", "expires_at"):
            value = getattr(source, timestamp_field)
            if value is not None and not _validate_rfc3339(value):
                add(
                    "SOURCE_TIMESTAMP_INVALID",
                    f"source_access_states[{index}].{timestamp_field}",
                    "timestamp must be RFC 3339",
                )

    for index, decision in enumerate(summary.business_decisions_required):
        if (
            decision.status.value in {"APPROVED", "REJECTED"}
            and not decision.evidence_refs
        ):
            add(
                "BUSINESS_DECISION_UNTRACED",
                f"business_decisions_required[{index}]",
                "approved/rejected decisions require evidence",
            )
    for index, assumption in enumerate(summary.engineering_assumptions):
        if (
            assumption.status == AssumptionStatus.VALIDATED
            and not assumption.evidence_refs
        ):
            add(
                "VALIDATED_ASSUMPTION_UNTRACED",
                f"engineering_assumptions[{index}]",
                "validated assumptions require evidence",
            )

    global_ids = _collect_global_ids(summary)
    id_values = [item[0] for item in global_ids]
    duplicates = sorted({item for item in id_values if id_values.count(item) > 1})
    if duplicates:
        add("GLOBAL_ID_COLLISION", "summary", f"duplicate IDs: {duplicates}")

    material_nulls = {
        "schema.generated_at": summary.schema_.generated_at,
        "schema.report_id": summary.schema_.report_id,
        "repository.identity_verified": summary.repository.identity_verified,
        "repository.git_commit": summary.repository.git_commit,
        "repository.dirty_before_audit": summary.repository.dirty_before_audit,
        "repository.components.metis.git_commit": (
            summary.repository.components.metis.git_commit
        ),
        "repository.components.marko.git_commit": (
            summary.repository.components.marko.git_commit
        ),
        "metis.weighted_readiness": summary.metis.weighted_readiness,
        "metis.readiness_interval.lower": summary.metis.readiness_interval.lower,
        "metis.readiness_interval.upper": summary.metis.readiness_interval.upper,
        "metis.critical_floor": summary.metis.critical_floor,
        "metis.evidence_level": summary.metis.evidence_level,
        "metis.highest_evidence_level": summary.metis.highest_evidence_level,
        "metis.unknown_weight": summary.metis.unknown_weight,
        "metis.critical_unknown_count": summary.metis.critical_unknown_count,
        "marko.weighted_readiness": summary.marko.weighted_readiness,
        "marko.readiness_interval.lower": summary.marko.readiness_interval.lower,
        "marko.readiness_interval.upper": summary.marko.readiness_interval.upper,
        "marko.critical_floor": summary.marko.critical_floor,
        "marko.evidence_level": summary.marko.evidence_level,
        "marko.highest_evidence_level": summary.marko.highest_evidence_level,
        "marko.unknown_weight": summary.marko.unknown_weight,
        "marko.critical_unknown_count": summary.marko.critical_unknown_count,
        "combined_system.end_to_end_evidence_level": combined.end_to_end_evidence_level,
        "combined_system.trace_coverage": combined.trace_coverage,
        "combined_system.verified_trace_coverage": combined.verified_trace_coverage,
        "combined_system.integrated_trace_coverage": combined.integrated_trace_coverage,
    }
    for path, value in material_nulls.items():
        if value is None and not _unknown_covers(summary, path):
            add(
                "MATERIAL_NULL_UNEXPLAINED",
                path,
                "material null requires a matching unknown record",
            )

    category_assessment_paths = {
        "business_decisions_required": summary.business_decisions_required,
        "source_access_states": summary.source_access_states,
        "marko.reuse_partition": (
            summary.marko.reusable_as_is
            + summary.marko.adapt_before_reuse
            + summary.marko.reference_only
            + summary.marko.do_not_port
            + summary.marko.unknown_reuse_state
        ),
        "gaps": summary.gaps.p0 + summary.gaps.p1 + summary.gaps.p2 + summary.gaps.p3,
    }
    for path, values in category_assessment_paths.items():
        if not values and not _unknown_covers(summary, path):
            warning = f"EMPTY_CATEGORY_VERIFIED:{path}"
            if warning not in summary.validation.warnings:
                add(
                    "EMPTY_CATEGORY_ASSESSMENT_UNCLEAR",
                    path,
                    f"declare unknown or validation warning {warning}",
                )

    identity_spine = summary.p0_identity_spine
    if identity_spine is not None and summary.stage.status == StageStatus.PASS:
        required_true = {
            "query_only_supported": identity_spine.query_only_supported,
            "identity_fields_separated": identity_spine.identity_fields_separated,
            "legacy_rows_marked_unverified": (
                identity_spine.legacy_rows_marked_unverified
            ),
            "calibration_requires_automatic_eligible": (
                identity_spine.calibration_requires_automatic_eligible
            ),
            "calibration_requires_hard_gate_pass": (
                identity_spine.calibration_requires_hard_gate_pass
            ),
            "calibration_requires_verified_oe": (
                identity_spine.calibration_requires_verified_oe
            ),
            "empty_vs_schema_drift_distinguished": (
                identity_spine.empty_vs_schema_drift_distinguished
            ),
            "offer_accounting_conservation_verified": (
                identity_spine.offer_accounting_conservation_verified
            ),
            "postgresql_migration_verified": (
                identity_spine.postgresql_migration_verified
            ),
        }
        for field_name, value in required_true.items():
            if not value:
                add(
                    "P0_IDENTITY_SPINE_PASS_CONTRADICTION",
                    f"p0_identity_spine.{field_name}",
                    "PASS requires this P0 identity-spine invariant to be true",
                )
        required_zero = {
            "sentinel_url_occurrences_runtime": (
                identity_spine.sentinel_url_occurrences_runtime
            ),
            "unconditional_source_confidence_one_occurrences": (
                identity_spine.unconditional_source_confidence_one_occurrences
            ),
            "replay_network_requests": identity_spine.replay_network_requests,
            "full_suite.failed": identity_spine.full_suite.failed,
        }
        for field_name, value in required_zero.items():
            if value != 0:
                add(
                    "P0_IDENTITY_SPINE_PASS_CONTRADICTION",
                    f"p0_identity_spine.{field_name}",
                    "PASS requires this P0 identity-spine counter to be zero",
                )
        if identity_spine.full_suite.passed == 0:
            add(
                "P0_IDENTITY_SPINE_FULL_SUITE_EMPTY",
                "p0_identity_spine.full_suite.passed",
                "PASS requires at least one passing full-suite test",
            )
        if identity_spine.remaining_blockers:
            add(
                "P0_IDENTITY_SPINE_BLOCKERS_REMAIN",
                "p0_identity_spine.remaining_blockers",
                "PASS requires an empty P0 identity-spine blocker list",
            )

    return tuple(issues)


def validate_machine_response(
    response: str,
    *,
    expected_summary: MachineReadableSummary | None = None,
    expected_footer: EndOfResponse | None = None,
) -> tuple[ValidationIssue, ...]:
    """Validate the Section 15 footer followed by exactly one final YAML block."""
    issues: list[ValidationIssue] = []

    def add(code: str, path: str, message: str) -> None:
        issues.append(ValidationIssue(code, path, message))

    matches = tuple(_YAML_FENCE_RE.finditer(response))
    if len(matches) != 1:
        add(
            "YAML_BLOCK_COUNT_INVALID",
            "response",
            f"exactly one fenced YAML block is required, found {len(matches)}",
        )
        return tuple(issues)
    match = matches[0]
    if response[match.end() :].strip():
        add(
            "CONTENT_AFTER_MACHINE_SUMMARY",
            "response",
            "no content is allowed after the closing YAML fence",
        )

    heading_start = response.rfind(MACHINE_SUMMARY_HEADING, 0, match.start())
    if heading_start < 0:
        add(
            "MACHINE_SUMMARY_HEADING_MISSING",
            "response",
            f"expected {MACHINE_SUMMARY_HEADING}",
        )
        footer_text = response[: match.start()].rstrip()
    else:
        between = response[heading_start + len(MACHINE_SUMMARY_HEADING) : match.start()]
        if between.strip():
            add(
                "CONTENT_BETWEEN_SUMMARY_HEADING_AND_YAML",
                "response",
                "only whitespace is allowed before the YAML fence",
            )
        footer_text = response[:heading_start].rstrip()

    issues.extend(
        validate_rendered_footer(
            footer_text,
            expected_contract=expected_footer,
        )
    )
    try:
        summary = parse_machine_summary_yaml(match.group("body"))
    except MachineSummaryParseError as exc:
        add("MACHINE_SUMMARY_PARSE_FAILED", "response", str(exc))
        return tuple(issues)
    issues.extend(validate_summary(summary))
    if not validate_yaml_round_trip(summary):
        add(
            "YAML_ROUND_TRIP_MISMATCH",
            "response",
            "parse/serialize/parse changed semantics",
        )
    if expected_summary is not None and (
        summary.model_dump(mode="json") != expected_summary.model_dump(mode="json")
    ):
        add(
            "SUMMARY_MANIFEST_MISMATCH",
            "response",
            "final YAML differs from the expected machine summary",
        )

    gate_match = re.search(
        r"^STOP_GATE_([A-Z0-9_]+) = (PASS|FAIL|BLOCKED|NO_GO)$",
        footer_text,
        flags=re.MULTILINE,
    )
    if gate_match is None:
        add(
            "HUMAN_STOP_GATE_MISSING",
            "response",
            "human-readable stop-gate is required",
        )
    else:
        rendered_key = f"STOP_GATE_{gate_match.group(1)}"
        if rendered_key != summary.termination.stop_gate_key:
            add(
                "HUMAN_MACHINE_GATE_KEY_MISMATCH",
                "response",
                "human and machine stop-gate keys differ",
            )
        if gate_match.group(2) != summary.termination.stop_gate_value.value:
            add(
                "HUMAN_MACHINE_GATE_STATUS_MISMATCH",
                "response",
                "human and machine stop-gate statuses differ",
            )
    return tuple(issues)


def build_machine_self_check(
    summary: MachineReadableSummary,
    *,
    response: str | None = None,
) -> dict[str, bool]:
    summary_codes = {issue.code for issue in validate_summary(summary)}
    rendered_response = response
    if rendered_response is None:
        rendered_response = render_machine_summary_block(summary)
    return {
        "schema_version_present": summary.schema_.version == "1.1.0",
        "stage_stop_gate_consistent": not bool(
            summary_codes
            & {
                "STOP_GATE_KEY_MISMATCH",
                "STOP_GATE_STATUS_MISMATCH",
                "STOP_GATE_MATCH_FLAG_INVALID",
            }
        ),
        "audit_pass_separated_from_production": (
            summary.stage.production_ready is not True
            or summary.combined_system.production_eligible
        ),
        "readme_not_treated_as_implementation": (
            "STRONGEST_DOMAIN_UNSUPPORTED" not in summary_codes
        ),
        "unit_tests_not_treated_as_end_to_end": (
            "END_TO_END_EVIDENCE_TOO_WEAK" not in summary_codes
        ),
        "average_does_not_hide_critical_floor": not any(
            code in {"SYSTEM_READINESS_MISMATCH", "CRITICAL_CAPABILITY_SET_INVALID"}
            for code in summary_codes
        ),
        "evidence_ceilings_valid": not any(
            "EVIDENCE" in code or "READINESS_MISMATCH" in code for code in summary_codes
        ),
        "unknowns_not_coerced": "MATERIAL_NULL_UNEXPLAINED" not in summary_codes,
        "located_scraper_not_treated_as_scale_ready": not any(
            code.startswith("SCRAPER_BATCH_") for code in summary_codes
        ),
        "parallel_safety_supported": (
            "SCRAPER_PARALLEL_SAFETY_UNPROVEN" not in summary_codes
        ),
        "queue_integration_supported": (
            "SCRAPER_QUEUE_INTEGRATION_UNPROVEN" not in summary_codes
        ),
        "metis_evidence_integration_supported": (
            summary.marko.existing_scraper.metis_evidence_integrated
            != VerificationState.VERIFIED
            or "SCRAPER_QUEUE_INTEGRATION_UNPROVEN" not in summary_codes
        ),
        "marko_does_not_replace_metis": (
            "REUSABLE_AS_IS_UNPROVEN" not in summary_codes
        ),
        "record_types_separated": True,
        "missing_evidence_cannot_create_recommendation": (
            "COMBINED_PRODUCTION_ELIGIBILITY_UNPROVEN" not in summary_codes
            and "SYSTEM_PRODUCTION_ELIGIBILITY_UNPROVEN" not in summary_codes
        ),
        "replayability_supported_when_claimed": (
            summary.marko.existing_scraper.replayable != VerificationState.VERIFIED
            or bool(summary.marko.existing_scraper.evidence_refs)
        ),
        "repository_copy_verified_or_explicitly_unknown": (
            summary.repository.identity_verified is True
            or _unknown_covers(summary, "repository.identity_verified")
        ),
        "ids_unique": "GLOBAL_ID_COLLISION" not in summary_codes,
        "readiness_formulas_valid": not any(
            "ARITHMETIC" in code
            or "READINESS_MISMATCH" in code
            or code.endswith("WEIGHTS_INVALID")
            for code in summary_codes
        ),
        "reuse_partition_valid": not any(
            code.startswith("REUSE_") for code in summary_codes
        ),
        "gap_partition_valid": not any(
            code.startswith("GAP_") or code.startswith("DUPLICATE_GAP")
            for code in summary_codes
        ),
        "next_stage_not_started": not summary.next_stage.started,
        "yaml_round_trip_valid": validate_yaml_round_trip(summary),
        "validation_errors_empty": not summary.validation.errors,
        "no_summary_contract_issues": not summary_codes,
        "summary_is_final_block": not rendered_response.split("```")[-1].strip(),
    }
