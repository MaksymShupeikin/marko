"""Strict validator for PROMPT_15_013 scraper architecture audit summaries."""

from __future__ import annotations

import math
from typing import Any, Mapping

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken, TagToken


SCRAPER_AUDIT_SCHEMA_VERSION = "scraper-architecture-audit.v2"
GATE_ENUMS = frozenset({"PASS", "FAIL", "BLOCKED", "NO_GO"})
VERIFICATION_ENUMS = frozenset(
    {
        "VERIFIED",
        "NOT_VERIFIED",
        "PARTIAL",
        "BLOCKED",
        "UNKNOWN",
        "NOT_APPLICABLE",
    }
)
QUEUE_STABILITY_ENUMS = frozenset(
    {"STABLE", "UNSTABLE", "UNKNOWN", "NOT_APPLICABLE"}
)
CAPACITY_MODEL_ENUMS = frozenset(
    {"MEASURED_END_TO_END", "DERIVED_BOTTLENECK", "HYBRID", "UNKNOWN"}
)
EVIDENCE_CAP = {"E0": 0, "E1": 25, "E2": 50, "E3": 75, "E4": 90, "E5": 100}


class ScraperAuditSummaryError(ValueError):
    pass


class _UniqueLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _UniqueLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ScraperAuditSummaryError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def parse_scraper_audit_yaml(text: str) -> dict[str, Any]:
    try:
        for token in yaml.scan(text):
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                raise ScraperAuditSummaryError(
                    "YAML aliases, anchors, and explicit tags are forbidden"
                )
        payload = yaml.load(text, Loader=_UniqueLoader)
    except yaml.YAMLError as exc:
        raise ScraperAuditSummaryError(str(exc)) from exc
    if not isinstance(payload, dict):
        raise ScraperAuditSummaryError("scraper audit root must be a mapping")
    issues = validate_scraper_audit_summary(payload)
    if issues:
        raise ScraperAuditSummaryError("; ".join(issues))
    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    round_trip = yaml.load(rendered, Loader=_UniqueLoader)
    if round_trip != payload:
        raise ScraperAuditSummaryError("YAML round-trip equality failed")
    return payload


def validate_scraper_audit_summary(payload: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if payload.get("schema_version") != SCRAPER_AUDIT_SCHEMA_VERSION:
        issues.append("schema_version must be scraper-architecture-audit.v2")

    stage = _mapping(payload, "scraper_architecture_audit", issues)
    gates = _mapping(payload, "gates", issues)
    readiness = _mapping(payload, "readiness", issues)
    production = _mapping(gates, "production_eligibility", issues)
    audit_gate = _mapping(gates, "audit_artifact", issues)
    scaling_gate = _mapping(gates, "scraper_scaling", issues)

    for name, gate in (
        ("audit_artifact", audit_gate),
        ("scraper_scaling", scaling_gate),
        ("production_eligibility", production),
    ):
        status = gate.get("status")
        if status not in GATE_ENUMS:
            issues.append(f"gates.{name}.status has invalid enum {status!r}")
        if not isinstance(gate.get("reasons"), list):
            issues.append(f"gates.{name}.reasons must be a list")

    if stage.get("status") != audit_gate.get("status"):
        issues.append("stage status must equal audit_artifact gate status")
    if stage.get("execution_stopped") is not True:
        issues.append("execution_stopped must be true")
    if stage.get("next_stage_started") is not False:
        issues.append("next_stage_started must be false")
    eligible = production.get("status") == "PASS"
    if production.get("eligible") is not eligible:
        issues.append("production eligible must equal production gate PASS")
    if readiness.get("production_eligible") is not eligible:
        issues.append("readiness production_eligible conflicts with production gate")

    evidence_level = readiness.get("evidence_level")
    if evidence_level not in EVIDENCE_CAP:
        issues.append("readiness.evidence_level must be E0..E5")
    score = readiness.get("weighted_score")
    if score is not None:
        if not _number(score) or not 0 <= float(score) <= 100:
            issues.append("readiness.weighted_score must be null or in [0, 100]")
        elif evidence_level in EVIDENCE_CAP and float(score) > EVIDENCE_CAP[evidence_level]:
            issues.append("readiness.weighted_score exceeds evidence ceiling")

    capacity = _mapping(payload, "capacity_model", issues)
    if capacity.get("model_kind") not in CAPACITY_MODEL_ENUMS:
        issues.append("capacity_model.model_kind is invalid")
    if capacity.get("queue_stability") not in QUEUE_STABILITY_ENUMS:
        issues.append("capacity_model.queue_stability is invalid")
    utilization = _mapping(capacity, "utilization", issues)
    if capacity.get("queue_stability") == "STABLE":
        required = [utilization.get(name) for name in ("worker", "source", "database", "queue")]
        if any(value is None or not _number(value) or float(value) >= 1 for value in required):
            issues.append("STABLE queue requires every required utilization below one")
    terminal_capacity = _mapping(capacity, "capacity_items_per_second", issues).get(
        "terminal"
    )
    arrival = capacity.get("lambda_item_per_second")
    open_drain = capacity.get("drain_seconds_with_arrivals")
    if (
        terminal_capacity is None
        or arrival is None
        or float(terminal_capacity) <= float(arrival)
    ) and open_drain is not None:
        issues.append("open-flow drain must be null when capacity is unknown/insufficient")

    reconciliation = _mapping(payload, "reconciliation", issues)
    submitted = reconciliation.get("submitted")
    admitted = reconciliation.get("admitted")
    dedup = reconciliation.get("deduplicated")
    rejected = reconciliation.get("rejected")
    if all(value is not None for value in (submitted, admitted, dedup, rejected)):
        if submitted != admitted + dedup + rejected:
            issues.append("submitted must equal admitted + deduplicated + rejected")
    if reconciliation.get("reconciled") is True and reconciliation.get(
        "unaccounted_loss"
    ) != 0:
        issues.append("reconciled=true requires unaccounted_loss=0")

    existing = _mapping(payload, "existing_scraper", issues)
    for key, value in existing.items():
        if key in {"parser_internals_changed"}:
            if not isinstance(value, bool):
                issues.append(f"existing_scraper.{key} must be boolean")
        elif key != "production_proven" and value not in VERIFICATION_ENUMS:
            issues.append(f"existing_scraper.{key} has invalid verification enum")
    if existing.get("production_proven") not in VERIFICATION_ENUMS:
        issues.append("existing_scraper.production_proven has invalid enum")

    next_stage = _mapping(payload, "next_stage", issues)
    if next_stage.get("direct_user_instruction_required") is not True:
        issues.append("next stage must require direct user instruction")

    if not isinstance(payload.get("unknowns"), list):
        issues.append("unknowns must be a list")
    validation = _mapping(payload, "validation", issues)
    for field in (
        "structural_validation_passed",
        "mathematical_validation_passed",
        "unit_consistency_passed",
        "no_retry_double_counting_passed",
        "readiness_evidence_ceiling_passed",
        "stop_gate_consistency_passed",
        "semantic_validation_passed",
        "yaml_parse_passed",
        "yaml_round_trip_passed",
        "hostile_review_passed",
        "variation_tests_passed",
    ):
        if not isinstance(validation.get(field), bool):
            issues.append(f"validation.{field} must be boolean")
    return issues


def _mapping(
    parent: Mapping[str, Any],
    key: str,
    issues: list[str],
) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        issues.append(f"{key} must be a mapping")
        return {}
    return value


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


__all__ = [
    "SCRAPER_AUDIT_SCHEMA_VERSION",
    "ScraperAuditSummaryError",
    "parse_scraper_audit_yaml",
    "validate_scraper_audit_summary",
]
