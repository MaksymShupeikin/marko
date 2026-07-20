from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from marko.governance.machine_summary import (
    MachineSummaryParseError,
    build_machine_self_check,
    calculate_gap_rpn,
    calculate_readiness,
    calculate_reuse_score,
    calculate_scraper_capacity,
    dump_machine_summary,
    parse_machine_summary_yaml,
    render_machine_summary_block,
    validate_machine_response,
    validate_summary,
    validate_yaml_round_trip,
)
from marko.governance.machine_summary_cli import main as cli_main
from marko.governance.machine_summary_models import (
    MachineReadableSummary,
    QueueStability,
    ReadinessDimensions,
)
from marko.governance.response_footer import EndOfResponse, render_footer
from test_response_footer import valid_payload as valid_footer_payload


def _repository_component(root: str) -> dict[str, Any]:
    return {
        "root": root,
        "realpath": root,
        "repository_top_level": "/workspace",
        "git_commit": "a" * 40,
        "branch": "main",
        "detached_head": False,
        "dirty_before_audit": False,
        "identity_verified": True,
        "runtime_import_path": root,
        "evidence_refs": [f"repo:{root}"],
    }


def _capability(capability_id: str, name: str) -> dict[str, Any]:
    return {
        "capability_id": capability_id,
        "name": name,
        "weight": 1.0,
        "critical": True,
        "dimensions": {
            "implementation": 0.8,
            "verification": 0.8,
            "integration": 0.8,
            "auditability": 0.8,
            "operations": 0.8,
            "security": 0.8,
            "documentation": 0.8,
        },
        "evidence_level": "E3",
        "raw_interval": {"lower": 80.0, "upper": 80.0},
        "effective_interval": {"lower": 75.0, "upper": 75.0},
        "unknown_dimension_weight": 0.0,
        "evidence_refs": [f"test::{capability_id}"],
    }


def _system(
    capability_id: str,
    capability_name: str,
    maturity_class: str,
) -> dict[str, Any]:
    return {
        "weighted_readiness": 75.0,
        "readiness_interval": {"lower": 75.0, "upper": 75.0},
        "readiness_scale": "0_100",
        "score_basis": "CONSERVATIVE_LOWER_BOUND",
        "critical_floor": 75.0,
        "evidence_level": "E3",
        "evidence_level_semantics": "CRITICAL_EVIDENCE_FLOOR",
        "highest_evidence_level": "E3",
        "unknown_weight": 0.0,
        "critical_unknown_count": 0,
        "engineering_weights_approved": False,
        "maturity_class": maturity_class,
        "production_eligible": False,
        "production_gate": {
            "status": "FAIL",
            "passed_gates": [],
            "failed_gates": ["END_TO_END_NOT_PROVEN"],
            "blocked_gates": [],
            "unknown_gates": [],
        },
        "dimension_weights": {
            "implementation": 0.20,
            "verification": 0.15,
            "integration": 0.15,
            "auditability": 0.15,
            "operations": 0.15,
            "security": 0.10,
            "documentation": 0.10,
        },
        "capabilities": [_capability(capability_id, capability_name)],
        "critical_capability_ids": [capability_id],
        "strongest_domains": [
            {
                "domain_id": capability_id,
                "name": capability_name,
                "effective_readiness": 75.0,
                "evidence_level": "E3",
                "critical": True,
                "why_strong": "Focused executable evidence exists.",
                "limitations": ["No E4 integration evidence."],
                "evidence_refs": [f"test::{capability_id}"],
            }
        ],
        "missing_critical_domains": [],
        "evidence_refs": [f"test::{capability_id}"],
    }


def _unmeasured_capacity() -> dict[str, Any]:
    return {
        "measured": False,
        "unique_urls": None,
        "arrival_rate_urls_per_second": None,
        "worker_service_rate_urls_per_second": None,
        "active_workers": None,
        "average_attempts_per_unique_url": None,
        "effective_worker_service_rate": None,
        "total_capacity_urls_per_second": None,
        "utilization_rho": None,
        "queue_backlog": None,
        "queue_stability": "NOT_MEASURED",
        "estimated_drain_seconds": None,
        "success_rate": None,
        "retry_amplification": None,
        "latency_p50_seconds": None,
        "latency_p95_seconds": None,
        "latency_p99_seconds": None,
        "raw_storage_bytes": None,
        "structured_storage_bytes": None,
        "memory_peak_bytes": None,
        "cpu_average_percent": None,
    }


def _scraper() -> dict[str, Any]:
    return {
        "located": "VERIFIED",
        "physical_path": "backend/src/marko/parsers/prom",
        "entry_point": "PromGateway.fetch",
        "entry_point_verified": "VERIFIED",
        "input_contract_verified": "VERIFIED",
        "output_contract_verified": "VERIFIED",
        "runtime_reverified": "VERIFIED",
        "single_request_verified": "VERIFIED",
        "small_batch_verified": "VERIFIED",
        "batch_ready": "VERIFIED",
        "parallel_safe": "VERIFIED",
        "timeout_bounded": "VERIFIED",
        "retry_safe": "VERIFIED",
        "idempotent": "VERIFIED",
        "queue_integrated": "VERIFIED",
        "dead_letter_integrated": "VERIFIED",
        "raw_storage_integrated": "VERIFIED",
        "structured_storage_integrated": "VERIFIED",
        "metis_evidence_integrated": "VERIFIED",
        "replayable": "VERIFIED",
        "observable": "PARTIAL",
        "load_tested": "NOT_VERIFIED",
        "production_proven": "NOT_VERIFIED",
        "capacity": _unmeasured_capacity(),
        "evidence_refs": ["test::scraper-contract"],
    }


def valid_payload() -> dict[str, Any]:
    reuse_score = calculate_reuse_score(
        functional_fit=0.8,
        metis_invariant_compatibility=1.0,
        data_model_compatibility=0.8,
        verification_strength=0.75,
        adaptation_cost=0.5,
    )
    rpn, normalized_rpn = calculate_gap_rpn(4, 3, 3, 3)
    metis = _system(
        "METIS_GOVERNANCE_CONTRACT",
        "Metis governance contract",
        "PRICING_KERNEL_PROTOTYPE",
    )
    marko = _system(
        "MARKO_GOVERNANCE_INTEGRATION",
        "Marko governance integration",
        "REUSABLE_PRODUCT_SHELL",
    )
    marko.update(
        {
            "existing_scraper": _scraper(),
            "reusable_as_is": [],
            "adapt_before_reuse": [
                {
                    "component_id": "MARKO_AUTH_WORKSPACE",
                    "component_path": "backend/src/marko/api",
                    "classification": "ADAPT_BEFORE_REUSE",
                    "functional_fit": 0.8,
                    "metis_invariant_compatibility": 1.0,
                    "data_model_compatibility": 0.8,
                    "verification_strength": 0.75,
                    "adaptation_cost": 0.5,
                    "reuse_score": reuse_score,
                    "required_adaptations": ["Preserve Metis evidence ownership."],
                    "preserved_metis_invariants": ["Metis owns recommendation logic."],
                    "violated_metis_invariants": [],
                    "evidence_refs": ["test::reuse"],
                }
            ],
            "reference_only": [],
            "do_not_port": [],
            "unknown_reuse_state": [],
            "evaluated_component_ids": ["MARKO_AUTH_WORKSPACE"],
            "reuse_partition_valid": True,
        }
    )
    return {
        "schema": {
            "name": "metis_marko_machine_readable_stage_summary",
            "version": "1.1.0",
            "generated_at": "2026-07-17T12:00:00+02:00",
            "report_id": "REPORT-PROMPT-15-013",
            "audit_id": "VALIDATION-PROMPT-15-013",
        },
        "stage": {
            "id": "PROMPT_15_013_IMPLEMENTATION",
            "title": "MACHINE_READABLE_SUMMARY_IMPLEMENTATION",
            "status": "PASS",
            "status_reason": "The Section 16 contract and validation suite passed.",
            "acceptance_criteria_passed": True,
            "audit_complete": True,
            "production_ready": False,
            "secondary_findings": [],
            "evidence_refs": ["tests/test_machine_summary.py"],
        },
        "repository": {
            "audit_root": "/workspace",
            "audit_root_realpath": "/workspace",
            "topology": "MONOREPO",
            "git_commit": "a" * 40,
            "dirty_before_audit": False,
            "identity_verified": True,
            "runtime_import_identity": "/workspace/backend/src",
            "components": {
                "metis": _repository_component("/workspace/backend/src/metis"),
                "marko": _repository_component("/workspace/backend/src/marko"),
            },
            "duplicate_copies": [],
            "unresolved_identity_conflicts": [],
        },
        "metis": metis,
        "marko": marko,
        "combined_system": {
            "maturity_class": "PARTIAL_INTEGRATION",
            "end_to_end_flow_verified": "PARTIAL",
            "end_to_end_evidence_level": "E3",
            "trace_coverage": 0.5,
            "verified_trace_coverage": 0.5,
            "integrated_trace_coverage": 0.25,
            "last_verified_node": "structured observation",
            "first_unverified_node": "operator review",
            "first_broken_transition": "recommendation -> operator review",
            "production_eligible": False,
            "production_gate": {
                "status": "FAIL",
                "passed_gates": [],
                "failed_gates": ["END_TO_END_NOT_PROVEN"],
                "blocked_gates": [],
                "unknown_gates": [],
            },
            "recommendation_contract": {
                "explainable": "PARTIAL",
                "auditable": "PARTIAL",
                "reproducible": "NOT_VERIFIED",
                "insufficient_data_abstention": "VERIFIED",
                "manual_review_routing": "PARTIAL",
            },
            "evidence_refs": ["test::combined"],
        },
        "gaps": {
            "p0": [],
            "p1": [
                {
                    "gap_id": "GAP-END-TO-END",
                    "system": "COMBINED",
                    "capability_id": "END_TO_END_FLOW",
                    "title": "End-to-end flow is not integrated",
                    "description": "E4 end-to-end evidence is absent.",
                    "gap_type": "INTEGRATION_GAP",
                    "priority": "P1",
                    "severity": 4,
                    "likelihood": 3,
                    "detection_difficulty": 3,
                    "dependency_centrality": 3,
                    "rpn": rpn,
                    "normalized_rpn": normalized_rpn,
                    "affected_invariants": ["REPLAYABLE_RECOMMENDATION"],
                    "blocks": ["PRODUCTION", "PILOT"],
                    "evidence_refs": ["test::combined"],
                    "owner_type": "ENGINEERING",
                    "remediation_class": "IMPLEMENT_AND_VERIFY",
                    "acceptance_evidence_required": "E4",
                }
            ],
            "p2": [],
            "p3": [],
            "priority_partition_valid": True,
            "duplicate_gap_ids": [],
            "critical_dependency_chain": ["GAP-END-TO-END"],
        },
        "business_decisions_required": [
            {
                "decision_id": "DEC-PRODUCTION-THRESHOLD",
                "title": "Approve production threshold",
                "status": "MISSING",
                "owner": "CLIENT",
                "options": ["0.90", "0.95"],
                "recommended_option": None,
                "recommendation_basis": None,
                "default_assumption_for_planning": None,
                "implementation_blocked": False,
                "blocked_scope": ["PRODUCTION"],
                "required_before_stage": "PRODUCTION_VALIDATION",
                "evidence_refs": [],
            }
        ],
        "source_access_states": [
            {
                "source_id": "SOURCE-PUBLIC-COMPETITOR",
                "source_name": "Public competitor pages",
                "source_type": "PUBLIC_COMPETITOR_SOURCE",
                "state": "NOT_PERMITTED",
                "scope": "Automated competitor collection",
                "basis": "Current fail-closed source-access policy.",
                "verified_at": "2026-07-17T12:00:00+02:00",
                "expires_at": None,
                "allowed_operations": ["REPLAY_PINNED_EVIDENCE"],
                "prohibited_operations": ["LIVE_COLLECTION"],
                "blocking_scope": ["LIVE_COLLECTION"],
                "evidence_refs": ["test::source-gate"],
            }
        ],
        "engineering_assumptions": [
            {
                "assumption_id": "ASSUMPTION-READINESS-WEIGHTS",
                "statement": "Default engineering readiness weights apply.",
                "rationale": "No approved business weights exist.",
                "affected_fields": [
                    "metis.weighted_readiness",
                    "marko.weighted_readiness",
                ],
                "impact_if_false": "Readiness bounds must be recalculated.",
                "validation_method": "Obtain business approval.",
                "required_by_stage": "PRODUCTION_VALIDATION",
                "status": "UNVALIDATED",
                "evidence_refs": [],
            }
        ],
        "future_hypotheses": [
            {
                "hypothesis_id": "HYPOTHESIS-ADOPTION",
                "statement": "All response surfaces can adopt the contract.",
                "expected_value": "100% valid sampled responses",
                "required_data": ["Pinned response corpus"],
                "falsification_test": "Run the validator over every sampled surface.",
                "earliest_applicable_stage": "MACHINE_SUMMARY_ADOPTION_VALIDATION",
                "current_action": "DEFER",
                "evidence_refs": [],
            }
        ],
        "unknowns": [],
        "next_stage": {
            "id": "MACHINE_SUMMARY_ADOPTION_VALIDATION",
            "title": "MACHINE SUMMARY ADOPTION VALIDATION",
            "objective": "Validate cross-surface summary adoption.",
            "why_it_is_next": "Local contract evidence precedes adoption evidence.",
            "required_inputs": ["Pinned contract and response corpus"],
            "expected_outputs": ["A cross-surface validation report must be created."],
            "acceptance_criteria": ["100% of sampled responses validate."],
            "stop_condition": "STOP_GATE_MACHINE_SUMMARY_ADOPTION_VALIDATION",
            "client_decisions_required": [],
            "started": False,
            "new_direct_instruction_required": True,
        },
        "validation": {
            "yaml_parse": True,
            "duplicate_key_check": True,
            "schema_validation": True,
            "required_field_validation": True,
            "enum_validation": True,
            "type_validation": True,
            "arithmetic_validation": True,
            "readiness_interval_validation": True,
            "evidence_ceiling_validation": True,
            "critical_floor_validation": True,
            "stop_gate_consistency": True,
            "production_gate_consistency": True,
            "reuse_partition_validation": True,
            "gap_partition_validation": True,
            "evidence_traceability": True,
            "reverse_trace_validation": True,
            "variation_validation": True,
            "hostile_review": True,
            "errors": [],
            "warnings": [],
        },
        "termination": {
            "stop_gate_key": "STOP_GATE_PROMPT_15_013_IMPLEMENTATION",
            "stop_gate_value": "PASS",
            "stage_status_matches_stop_gate": True,
            "next_stage_started": False,
            "execution_stopped": True,
            "no_content_after_summary": True,
        },
    }


def summary_from(payload: dict[str, Any] | None = None) -> MachineReadableSummary:
    return MachineReadableSummary.model_validate(payload or valid_payload())


def issue_codes(payload: dict[str, Any]) -> set[str]:
    return {issue.code for issue in validate_summary(summary_from(payload))}


def test_valid_summary_passes_and_round_trips() -> None:
    summary = summary_from()

    assert validate_summary(summary) == ()
    assert validate_yaml_round_trip(summary)
    assert parse_machine_summary_yaml(dump_machine_summary(summary)) == summary


def test_readiness_unknown_dimension_retains_denominator_and_evidence_cap() -> None:
    dimensions = ReadinessDimensions(
        implementation=1.0,
        verification=None,
        integration=1.0,
        auditability=1.0,
        operations=1.0,
        security=1.0,
        documentation=1.0,
    )

    calculated = calculate_readiness(dimensions, "E3")

    assert calculated.raw_lower == pytest.approx(85.0)
    assert calculated.raw_upper == pytest.approx(100.0)
    assert calculated.effective_lower == 75.0
    assert calculated.effective_upper == 75.0
    assert calculated.unknown_dimension_weight == 0.15


def test_e3_raw_score_90_is_capped_at_75() -> None:
    dimensions = ReadinessDimensions(
        implementation=0.9,
        verification=0.9,
        integration=0.9,
        auditability=0.9,
        operations=0.9,
        security=0.9,
        documentation=0.9,
    )
    calculated = calculate_readiness(dimensions, "E3")

    assert calculated.raw_lower == pytest.approx(90.0)
    assert calculated.effective_lower == 75.0


def test_gap_rpn_and_reuse_score_formulas() -> None:
    rpn, normalized = calculate_gap_rpn(5, 5, 5, 3)
    assert rpn == 375
    assert normalized == 100
    assert (
        calculate_reuse_score(
            functional_fit=1,
            metis_invariant_compatibility=1,
            data_model_compatibility=1,
            verification_strength=1,
            adaptation_cost=0,
        )
        == 100
    )


def test_capacity_math_distinguishes_stable_and_overloaded_queue() -> None:
    stable = calculate_scraper_capacity(
        arrival_rate=2,
        worker_service_rate=2,
        active_workers=2,
        average_attempts=1,
        backlog=20,
    )
    overloaded = calculate_scraper_capacity(
        arrival_rate=4,
        worker_service_rate=2,
        active_workers=2,
        average_attempts=1,
        backlog=20,
    )

    assert stable.queue_stability is QueueStability.STABLE
    assert stable.utilization_rho == 0.5
    assert stable.estimated_drain_seconds == 10
    assert overloaded.queue_stability is QueueStability.UNSTABLE
    assert overloaded.estimated_drain_seconds is None


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("schema: 1\nschema: 2\n", "duplicate YAML key"),
        ("a: &x 1\nb: *x\n", "anchors, aliases"),
        ("generated_at: 2026-07-17T12:00:00Z\n", "implicit YAML timestamps"),
        ("flag: YES\n", "YES/NO/ON/OFF"),
        ("a: 1\n---\nb: 2\n", "exactly one"),
    ],
)
def test_strict_yaml_rejects_parser_dependent_constructs(
    text: str, message: str
) -> None:
    with pytest.raises(MachineSummaryParseError, match=message):
        parse_machine_summary_yaml(text)


def test_numeric_strings_and_boolean_strings_are_rejected() -> None:
    payload = valid_payload()
    payload["metis"]["weighted_readiness"] = "75.0"
    payload["stage"]["audit_complete"] = "true"

    with pytest.raises(Exception):
        summary_from(payload)


def test_stage_and_stop_gate_must_match() -> None:
    payload = valid_payload()
    payload["termination"]["stop_gate_key"] = "STOP_GATE_STAGE_01"
    payload["termination"]["stop_gate_value"] = "FAIL"

    assert {
        "STOP_GATE_KEY_MISMATCH",
        "STOP_GATE_STATUS_MISMATCH",
    }.issubset(issue_codes(payload))


def test_audit_pass_does_not_imply_production_pass() -> None:
    payload = valid_payload()
    payload["stage"]["title"] = "PROJECT STATE AUDIT"

    assert validate_summary(summary_from(payload)) == ()
    assert payload["stage"]["status"] == "PASS"
    assert payload["combined_system"]["production_eligible"] is False


def test_pass_requires_complete_validation_and_no_errors() -> None:
    payload = valid_payload()
    payload["validation"]["arithmetic_validation"] = False
    payload["validation"]["errors"] = ["ARITHMETIC_FAILED"]

    assert {
        "PASS_WITH_INCOMPLETE_VALIDATION",
        "PASS_WITH_VALIDATION_ERRORS",
    }.issubset(issue_codes(payload))


def test_material_null_requires_unknown_record() -> None:
    payload = valid_payload()
    payload["schema"]["report_id"] = None
    assert "MATERIAL_NULL_UNEXPLAINED" in issue_codes(payload)

    payload["unknowns"] = [
        {
            "unknown_id": "UNKNOWN-REPORT-ID",
            "field_path": "schema.report_id",
            "question": "Which report ID is authoritative?",
            "reason_unknown": "No report registry was supplied.",
            "impact": "Historical comparison cannot bind the record.",
            "resolver_type": "CLIENT_INPUT",
            "required_input": "Approved report ID",
            "owner": "CLIENT",
            "blocks": ["READINESS_HISTORY"],
            "target_stage": None,
        }
    ]
    assert "MATERIAL_NULL_UNEXPLAINED" not in issue_codes(payload)


def test_readiness_arithmetic_and_critical_floor_are_recomputed() -> None:
    payload = valid_payload()
    payload["metis"]["weighted_readiness"] = 82.0
    payload["metis"]["critical_floor"] = 20.0
    payload["metis"]["capabilities"][0]["effective_interval"]["lower"] = 90.0

    codes = issue_codes(payload)
    assert "CAPABILITY_ARITHMETIC_MISMATCH" in codes
    assert "SYSTEM_READINESS_MISMATCH" in codes


def test_located_scraper_does_not_imply_runtime_or_batch_readiness() -> None:
    payload = valid_payload()
    scraper = payload["marko"]["existing_scraper"]
    for field in (
        "entry_point_verified",
        "input_contract_verified",
        "output_contract_verified",
        "runtime_reverified",
        "single_request_verified",
        "small_batch_verified",
        "batch_ready",
        "parallel_safe",
        "timeout_bounded",
        "retry_safe",
        "idempotent",
        "queue_integrated",
        "dead_letter_integrated",
        "raw_storage_integrated",
        "structured_storage_integrated",
        "metis_evidence_integrated",
        "replayable",
        "observable",
        "load_tested",
        "production_proven",
    ):
        scraper[field] = "NOT_VERIFIED"

    assert validate_summary(summary_from(payload)) == ()


def test_batch_and_queue_claims_require_prerequisites() -> None:
    payload = valid_payload()
    scraper = payload["marko"]["existing_scraper"]
    scraper["input_contract_verified"] = "NOT_VERIFIED"
    scraper["dead_letter_integrated"] = "NOT_VERIFIED"

    assert {
        "SCRAPER_BATCH_READINESS_UNPROVEN",
        "SCRAPER_QUEUE_INTEGRATION_UNPROVEN",
    }.issubset(issue_codes(payload))


def test_scraper_production_proven_requires_scale_evidence() -> None:
    payload = valid_payload()
    scraper = payload["marko"]["existing_scraper"]
    scraper["production_proven"] = "VERIFIED"

    assert {
        "SCRAPER_PRODUCTION_PROOF_INCOMPLETE",
        "SCRAPER_PRODUCTION_WITHOUT_CAPACITY",
    }.issubset(issue_codes(payload))


def test_measured_overloaded_queue_requires_unstable_and_null_drain() -> None:
    payload = valid_payload()
    capacity = payload["marko"]["existing_scraper"]["capacity"]
    capacity.update(
        {
            "measured": True,
            "unique_urls": 100,
            "arrival_rate_urls_per_second": 4.0,
            "worker_service_rate_urls_per_second": 2.0,
            "active_workers": 2,
            "average_attempts_per_unique_url": 1.0,
            "effective_worker_service_rate": 2.0,
            "total_capacity_urls_per_second": 4.0,
            "utilization_rho": 1.0,
            "queue_backlog": 20,
            "queue_stability": "UNSTABLE",
            "estimated_drain_seconds": None,
            "success_rate": 0.95,
            "retry_amplification": 1.0,
            "latency_p50_seconds": 1.0,
            "latency_p95_seconds": 2.0,
            "latency_p99_seconds": 3.0,
            "raw_storage_bytes": 1000,
            "structured_storage_bytes": 500,
            "memory_peak_bytes": 1024,
            "cpu_average_percent": 50.0,
        }
    )
    payload["validation"]["warnings"] = ["SCRAPER_UTILIZATION_ABOVE_ENGINEERING_TARGET"]

    assert validate_summary(summary_from(payload)) == ()


def test_reusable_as_is_is_forbidden_when_metis_invariant_is_violated() -> None:
    payload = valid_payload()
    record = payload["marko"]["adapt_before_reuse"].pop()
    record["classification"] = "REUSABLE_AS_IS"
    record["violated_metis_invariants"] = ["Evidence provenance is lost."]
    record["required_adaptations"] = []
    payload["marko"]["reusable_as_is"] = [record]

    assert "REUSABLE_AS_IS_UNPROVEN" in issue_codes(payload)


def test_reuse_and_gap_partitions_reject_duplicate_ids() -> None:
    payload = valid_payload()
    payload["marko"]["reference_only"] = deepcopy(
        payload["marko"]["adapt_before_reuse"]
    )
    payload["marko"]["reference_only"][0]["classification"] = "REFERENCE_ONLY"
    payload["gaps"]["p2"] = deepcopy(payload["gaps"]["p1"])
    payload["gaps"]["p2"][0]["priority"] = "P2"

    assert {
        "REUSE_PARTITION_OVERLAP",
        "DUPLICATE_GAP_LIST_MISMATCH",
    }.issubset(issue_codes(payload))


def test_empty_gap_list_requires_audit_warning_or_unknown() -> None:
    payload = valid_payload()
    payload["gaps"]["p1"] = []
    payload["gaps"]["critical_dependency_chain"] = []

    assert "EMPTY_CATEGORY_ASSESSMENT_UNCLEAR" in issue_codes(payload)

    payload["validation"]["warnings"] = ["EMPTY_CATEGORY_VERIFIED:gaps"]
    assert "EMPTY_CATEGORY_ASSESSMENT_UNCLEAR" not in issue_codes(payload)


def test_end_to_end_verified_requires_e4() -> None:
    payload = valid_payload()
    payload["combined_system"]["end_to_end_flow_verified"] = "VERIFIED"

    assert "END_TO_END_EVIDENCE_TOO_WEAK" in issue_codes(payload)


def test_combined_production_claim_requires_all_hard_gates() -> None:
    payload = valid_payload()
    payload["combined_system"]["production_eligible"] = True
    payload["combined_system"]["production_gate"] = {
        "status": "PASS",
        "passed_gates": [],
        "failed_gates": [],
        "blocked_gates": [],
        "unknown_gates": [],
    }

    assert "COMBINED_PRODUCTION_ELIGIBILITY_UNPROVEN" in issue_codes(payload)


def test_unknown_source_state_blocks_production_claim() -> None:
    payload = valid_payload()
    payload["source_access_states"][0]["state"] = "UNKNOWN"
    payload["combined_system"]["production_eligible"] = True
    payload["combined_system"]["production_gate"]["status"] = "PASS"
    payload["combined_system"]["production_gate"]["failed_gates"] = []

    assert "COMBINED_PRODUCTION_ELIGIBILITY_UNPROVEN" in issue_codes(payload)


def test_dirty_repository_requires_snapshot_evidence_but_not_automatic_fail() -> None:
    payload = valid_payload()
    component = payload["repository"]["components"]["marko"]
    component["dirty_before_audit"] = True

    assert "DIRTY_WORKTREE_UNSNAPSHOTTED" in issue_codes(payload)

    component["evidence_refs"].append("command:git-diff-snapshot")
    assert "DIRTY_WORKTREE_UNSNAPSHOTTED" not in issue_codes(payload)


def test_duplicate_repository_copy_forbids_verified_aggregate_identity() -> None:
    payload = valid_payload()
    payload["repository"]["duplicate_copies"] = ["/workspace-copy"]

    assert "REPOSITORY_IDENTITY_OVERSTATED" in issue_codes(payload)


def test_missing_data_abstention_is_required_for_production() -> None:
    payload = valid_payload()
    payload["combined_system"]["production_eligible"] = True
    payload["combined_system"]["production_gate"]["status"] = "PASS"
    payload["combined_system"]["production_gate"]["failed_gates"] = []
    payload["combined_system"]["recommendation_contract"][
        "insufficient_data_abstention"
    ] = "NOT_VERIFIED"

    assert "COMBINED_PRODUCTION_ELIGIBILITY_UNPROVEN" in issue_codes(payload)


def test_status_precedence_preserves_secondary_fail_under_blocked() -> None:
    payload = valid_payload()
    payload["stage"]["status"] = "BLOCKED"
    payload["stage"]["secondary_findings"] = [
        {
            "type": "FAIL",
            "finding_id": "FINDING-RETRY",
            "finding": "Retry idempotency failed.",
            "evidence_refs": ["test::retry"],
        }
    ]
    payload["next_stage"]["id"] = "PROMPT_15_013_RESUME_AFTER_INPUT"
    payload["termination"]["stop_gate_value"] = "BLOCKED"

    assert "STATUS_PRECEDENCE_VIOLATION" not in issue_codes(payload)


def test_no_go_requires_decision_successor() -> None:
    payload = valid_payload()
    payload["stage"]["status"] = "NO_GO"
    payload["termination"]["stop_gate_value"] = "NO_GO"
    payload["next_stage"]["id"] = "STAGE_02_IMPLEMENTATION"

    assert "NO_GO_NEXT_STAGE_INVALID" in issue_codes(payload)


def _passing_p0_identity_spine() -> dict[str, Any]:
    return {
        "query_only_supported": True,
        "sentinel_url_occurrences_runtime": 0,
        "identity_fields_separated": True,
        "legacy_rows_marked_unverified": True,
        "calibration_requires_automatic_eligible": True,
        "calibration_requires_hard_gate_pass": True,
        "calibration_requires_verified_oe": True,
        "empty_vs_schema_drift_distinguished": True,
        "offer_accounting_conservation_verified": True,
        "unconditional_source_confidence_one_occurrences": 0,
        "replay_network_requests": 0,
        "postgresql_migration_verified": True,
        "full_suite": {"passed": 762, "failed": 0, "skipped": 4},
        "remaining_blockers": [],
    }


def test_p0_identity_spine_extension_accepts_closed_gate() -> None:
    payload = valid_payload()
    payload["p0_identity_spine"] = _passing_p0_identity_spine()

    assert validate_summary(summary_from(payload)) == ()


@pytest.mark.parametrize(
    ("field_path", "bad_value"),
    [
        (("query_only_supported",), False),
        (("sentinel_url_occurrences_runtime",), 1),
        (("replay_network_requests",), 1),
        (("full_suite", "failed"), 1),
        (("full_suite", "passed"), 0),
        (("remaining_blockers",), ["P0 remains open"]),
    ],
)
def test_p0_identity_spine_extension_rejects_pass_contradictions(
    field_path: tuple[str, ...],
    bad_value: object,
) -> None:
    payload = valid_payload()
    extension = _passing_p0_identity_spine()
    target: dict[str, Any] = extension
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = bad_value
    payload["p0_identity_spine"] = extension

    codes = issue_codes(payload)
    assert codes & {
        "P0_IDENTITY_SPINE_PASS_CONTRADICTION",
        "P0_IDENTITY_SPINE_FULL_SUITE_EMPTY",
        "P0_IDENTITY_SPINE_BLOCKERS_REMAIN",
    }


def _footer_for_summary() -> EndOfResponse:
    payload = valid_footer_payload()
    payload["stage_result"]["stage"]["id"] = "PROMPT_15_013_IMPLEMENTATION"
    payload["stage_result"]["stage"]["title"] = (
        "MACHINE_READABLE_SUMMARY_IMPLEMENTATION"
    )
    payload["stop_gate"]["key"] = "STOP_GATE_PROMPT_15_013_IMPLEMENTATION"
    return EndOfResponse.model_validate(payload)


def test_combined_response_requires_footer_gate_then_final_yaml() -> None:
    summary = summary_from()
    footer = _footer_for_summary()
    response = f"Implementation complete.\n\n{render_footer(footer)}\n\n{render_machine_summary_block(summary)}"

    assert (
        validate_machine_response(
            response,
            expected_summary=summary,
            expected_footer=footer,
        )
        == ()
    )


def test_combined_response_rejects_content_after_yaml_and_status_drift() -> None:
    payload = valid_payload()
    payload["termination"]["stop_gate_value"] = "FAIL"
    summary = summary_from(payload)
    footer = _footer_for_summary()
    response = (
        f"{render_footer(footer)}\n\n{render_machine_summary_block(summary)}\nextra"
    )

    codes = {issue.code for issue in validate_machine_response(response)}
    assert "CONTENT_AFTER_MACHINE_SUMMARY" in codes
    assert "HUMAN_MACHINE_GATE_STATUS_MISMATCH" in codes


def test_machine_self_check_is_fully_true() -> None:
    assert all(build_machine_self_check(summary_from()).values())


def test_cli_validates_renders_and_self_checks(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = summary_from()
    manifest = tmp_path / "summary.yaml"
    manifest.write_text(dump_machine_summary(summary), encoding="utf-8")

    assert cli_main(["--manifest", str(manifest)]) == 0
    assert "MACHINE_READABLE_SUMMARY_VALID" in capsys.readouterr().out

    assert cli_main(["--manifest", str(manifest), "--render"]) == 0
    assert capsys.readouterr().out.rstrip().endswith("```")

    assert cli_main(["--manifest", str(manifest), "--self-check"]) == 0
    assert '"yaml_round_trip_valid": true' in capsys.readouterr().out


def test_cli_rejects_manifest_with_duplicate_keys(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest = tmp_path / "invalid.yaml"
    manifest.write_text("schema: 1\nschema: 2\n", encoding="utf-8")

    assert cli_main(["--manifest", str(manifest)]) == 2
    assert "duplicate YAML key" in capsys.readouterr().err


def test_cli_validates_complete_response_against_both_manifests(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    summary = summary_from()
    footer = _footer_for_summary()
    summary_path = tmp_path / "summary.yaml"
    footer_path = tmp_path / "footer.yaml"
    response_path = tmp_path / "response.md"
    summary_path.write_text(dump_machine_summary(summary), encoding="utf-8")
    footer_path.write_text(
        yaml.safe_dump(
            {"end_of_response": footer.model_dump(mode="json")},
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    response_path.write_text(
        f"{render_footer(footer)}\n\n{render_machine_summary_block(summary)}",
        encoding="utf-8",
    )

    assert (
        cli_main(
            [
                "--manifest",
                str(summary_path),
                "--footer-manifest",
                str(footer_path),
                "--response",
                str(response_path),
            ]
        )
        == 0
    )
    assert "MACHINE_READABLE_SUMMARY_VALID" in capsys.readouterr().out
