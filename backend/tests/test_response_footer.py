from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError
import pytest
import yaml

from marko.governance.response_footer import (
    EndOfResponse,
    EvidenceLevel,
    StageStatus,
    aggregate_status,
    build_self_check,
    evidence_capped_score,
    expected_stop_gate_key,
    normalize_stage_id,
    render_footer,
    safe_coverage,
    to_manifest,
    validate_contract,
    validate_rendered_footer,
)
from marko.governance.response_footer_cli import main as cli_main


def valid_payload() -> dict[str, Any]:
    return {
        "contract_version": "15.1",
        "stage_result": {
            "stage": {
                "id": "PROMPT_15_012_IMPLEMENTATION",
                "title": "END_OF_RESPONSE_CONTRACT_IMPLEMENTATION",
                "type": "IMPLEMENTATION",
                "scope_owner": "Cross-cutting",
            },
            "status": "PASS",
            "completed_scope": [
                {
                    "scope_item_id": "SCOPE-CONTRACT",
                    "result": "Typed footer contract and renderer implemented.",
                    "artifact_refs": [
                        "backend/src/marko/governance/response_footer.py"
                    ],
                    "evidence_refs": ["backend/tests/test_response_footer.py"],
                }
            ],
            "incomplete_scope": [],
            "strongest_verified_result": {
                "claim_id": "CLM-EXECUTABLE-CONTRACT",
                "result": "Canonical manifests are rendered and validated deterministically.",
                "evidence_level": "E3",
                "evidence_refs": ["backend/tests/test_response_footer.py"],
                "reproduction_status": "reproducible",
                "limitations": ["No representative operational evidence."],
            },
            "weakest_critical_area": {
                "area_id": "AREA-ADOPTION",
                "area": "Adoption by every response-producing surface",
                "score": 50,
                "evidence_level": "E2",
                "reason": "Repository instructions are located evidence, not operational proof.",
                "downstream_impact": "A non-compliant client could omit the footer.",
                "required_resolution": "Run cross-surface adoption validation.",
            },
            "evidence_quality": {
                "highest_level": "E3",
                "critical_floor": "E2",
                "material_claim_coverage": 1.0,
                "reproducible_claim_coverage": 1.0,
                "freshness_status": "verified",
                "representative_scope": "partial",
                "limitations": ["Local focused execution only."],
            },
            "production_implication": {
                "state": "DEVELOPMENT_ONLY",
                "production_ready": False,
                "evidence_level": "E3",
                "passed_hard_gates": ["FOOTER_CONTRACT_LOCAL_TESTS"],
                "failed_hard_gates": [],
                "blocked_hard_gates": [],
                "statement": "The governance component is locally verified; production readiness is not claimed.",
            },
        },
        "blockers": {
            "overall": "NONE_VERIFIED",
            "assessment_complete": True,
            "assessed_categories": [
                "business_decisions",
                "source_access",
                "data",
                "environment_reproducibility",
                "unknowns",
            ],
            "p0": [],
            "p1": [],
            "business_decisions": [],
            "source_access": [],
            "data": [],
            "environment_reproducibility": [],
            "unknowns": [],
        },
        "next_stage": {
            "id": "RESPONSE_FOOTER_ADOPTION_VALIDATION",
            "title": "CROSS_SURFACE_ADOPTION_VALIDATION",
            "why_it_is_next": [
                "Adoption evidence is required before any broader compliance claim."
            ],
            "required_inputs": [
                {
                    "input_id": "INPUT-CONTRACT",
                    "description": "Pinned Section 15.1 contract implementation",
                    "source": "current repository",
                    "required_state": "tests passing",
                    "currently_available": True,
                    "evidence_ref": "backend/tests/test_response_footer.py",
                }
            ],
            "expected_artifacts": [
                {
                    "artifact_id": "ART-ADOPTION-REPORT",
                    "type": "report",
                    "purpose": "Must be created to report cross-surface compliance.",
                    "required_fields": ["surface", "response", "validation_result"],
                }
            ],
            "acceptance_criteria": [
                {
                    "id": "AC-ADOPTION-01",
                    "predicate": "all sampled substantive responses validate",
                    "required_evidence": "pinned response corpus and validator output",
                    "threshold": "100%",
                }
            ],
            "stop_condition": {
                "gate_key": "STOP_GATE_RESPONSE_FOOTER_ADOPTION_VALIDATION",
                "allowed_states": ["PASS", "FAIL", "BLOCKED", "NO_GO"],
                "auto_continue": False,
            },
            "client_decisions_required": [],
            "started": False,
            "authorized": False,
        },
        "stop_gate": {
            "key": "STOP_GATE_PROMPT_15_012_IMPLEMENTATION",
            "primary_status": "PASS",
            "secondary_findings": [],
            "automatic_transition": False,
        },
    }


def contract_from(payload: dict[str, Any] | None = None) -> EndOfResponse:
    return EndOfResponse.model_validate(payload or valid_payload())


def issue_codes(payload: dict[str, Any]) -> set[str]:
    return {issue.code for issue in validate_contract(contract_from(payload))}


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        ("STAGE_01", "STAGE_01"),
        ("stage-02", "STAGE_02"),
        (" matching  gold---set ", "MATCHING_GOLD_SET"),
        ("PROMPT_15_011_REVIEW", "PROMPT_15_011_REVIEW"),
    ],
)
def test_stage_id_normalization_and_gate_key(raw: str, normalized: str) -> None:
    assert normalize_stage_id(raw) == normalized
    assert expected_stop_gate_key(raw) == f"STOP_GATE_{normalized}"


def test_status_precedence_is_canonical() -> None:
    assert aggregate_status([StageStatus.PASS, StageStatus.FAIL]) is StageStatus.FAIL
    assert (
        aggregate_status([StageStatus.FAIL, StageStatus.BLOCKED])
        is StageStatus.BLOCKED
    )
    assert (
        aggregate_status([StageStatus.BLOCKED, StageStatus.NO_GO])
        is StageStatus.NO_GO
    )


def test_math_helpers_guard_denominators_ranges_and_evidence_caps() -> None:
    assert safe_coverage(0, 0) == 0
    assert safe_coverage(3, 4) == 0.75
    assert evidence_capped_score(100, EvidenceLevel.E2) == 50
    assert evidence_capped_score(84, EvidenceLevel.E4) == 84
    with pytest.raises(ValueError):
        safe_coverage(2, 1)
    with pytest.raises(ValueError):
        safe_coverage(1, 0)
    with pytest.raises(ValueError):
        evidence_capped_score(101, EvidenceLevel.E5)


def test_valid_contract_passes_all_cross_field_checks() -> None:
    assert validate_contract(contract_from()) == ()


def test_publication_self_check_is_fully_true_for_valid_contract() -> None:
    self_check = build_self_check(contract_from())

    assert self_check
    assert all(self_check.values())


def test_boolean_string_inputs_are_normalized_to_machine_booleans() -> None:
    payload = valid_payload()
    payload["next_stage"]["required_inputs"][0]["currently_available"] = "true"
    contract = contract_from(payload)

    assert contract.next_stage.required_inputs[0].currently_available is True
    manifest = to_manifest(contract)
    assert (
        manifest["end_of_response"]["next_stage"]["required_inputs"][0][
            "currently_available"
        ]
        is True
    )


def test_non_normalized_stage_identity_is_rejected() -> None:
    payload = valid_payload()
    payload["stage_result"]["stage"]["id"] = "stage-01"
    with pytest.raises(ValidationError, match="stage id must be normalized"):
        contract_from(payload)


def test_renderer_emits_exact_order_and_stop_gate_as_last_line() -> None:
    rendered = render_footer(contract_from())

    assert rendered.index("STAGE_RESULT:") < rendered.index("BLOCKERS:")
    assert rendered.index("BLOCKERS:") < rendered.index("NEXT_STAGE:")
    assert rendered.splitlines()[-1] == (
        "STOP_GATE_PROMPT_15_012_IMPLEMENTATION = PASS"
    )
    assert validate_rendered_footer(rendered) == ()


def test_wrong_current_gate_key_and_status_are_rejected() -> None:
    payload = valid_payload()
    payload["stop_gate"]["key"] = "STOP_GATE_STAGE_01"
    payload["stop_gate"]["primary_status"] = "FAIL"

    assert {
        "GATE_KEY_MISMATCH",
        "STATUS_MISMATCH",
    }.issubset(issue_codes(payload))


def test_next_stop_condition_must_allow_all_terminal_states_once() -> None:
    payload = valid_payload()
    payload["next_stage"]["stop_condition"]["allowed_states"] = [
        "PASS",
        "FAIL",
        "BLOCKED",
        "BLOCKED",
    ]

    assert "NEXT_ALLOWED_STATES_INVALID" in issue_codes(payload)


def test_determined_next_stage_requires_inputs_and_traced_client_decisions() -> None:
    payload = valid_payload()
    payload["next_stage"]["required_inputs"] = []
    payload["next_stage"]["client_decisions_required"] = [
        {
            "decision_id": "DEC-THRESHOLD",
            "question": "Which approved precision threshold applies?",
            "alternatives": ["0.90", "0.95"],
            "architecture_impact": "Controls the acceptance gate.",
            "blocking": True,
            "default_forbidden": True,
            "evidence_refs": [],
        }
    ]

    assert {
        "NEXT_INPUTS_MISSING",
        "CLIENT_DECISION_UNTRACED",
    }.issubset(issue_codes(payload))


def test_more_severe_secondary_status_must_be_primary() -> None:
    payload = valid_payload()
    payload["stop_gate"]["secondary_findings"] = [
        {
            "status": "FAIL",
            "finding": "A focused secondary check failed.",
            "evidence_refs": ["test::secondary"],
        }
    ]

    assert "STATUS_PRECEDENCE_VIOLATION" in issue_codes(payload)


def test_pass_cannot_hide_hard_incomplete_scope_or_missing_result() -> None:
    payload = valid_payload()
    payload["stage_result"]["incomplete_scope"] = [
        {
            "scope_item_id": "SCOPE-HARD",
            "reason": "Required artifact is absent.",
            "hard_required": True,
            "external_dependency": False,
        }
    ]
    payload["stage_result"]["strongest_verified_result"]["claim_id"] = (
        "NONE_VERIFIED"
    )
    payload["stage_result"]["strongest_verified_result"]["evidence_refs"] = []

    assert {
        "PASS_WITH_HARD_INCOMPLETE",
        "PASS_WITHOUT_VERIFIED_RESULT",
    }.issubset(issue_codes(payload))


def test_evidence_floor_and_score_cannot_be_overstated() -> None:
    payload = valid_payload()
    payload["stage_result"]["weakest_critical_area"]["score"] = 75
    payload["stage_result"]["evidence_quality"]["critical_floor"] = "E3"

    assert {
        "EVIDENCE_SCORE_CAP_EXCEEDED",
        "CRITICAL_FLOOR_OVERSTATED",
    }.issubset(issue_codes(payload))


def test_production_ready_true_requires_e5_and_closed_hard_gates() -> None:
    payload = valid_payload()
    implication = payload["stage_result"]["production_implication"]
    implication["state"] = "PRODUCTION_READY_PROVEN"
    implication["production_ready"] = True
    implication["evidence_level"] = "E2"
    implication["blocked_hard_gates"] = ["DEPLOYMENT_RECOVERY"]

    assert {
        "PRODUCTION_EVIDENCE_TOO_WEAK",
        "PRODUCTION_HARD_GATE_OPEN",
        "PRODUCTION_CANDIDATE_WITH_OPEN_GATE",
    }.issubset(issue_codes(payload))


def test_audit_can_pass_while_production_is_false() -> None:
    payload = valid_payload()
    payload["stage_result"]["stage"]["type"] = "AUDIT"
    payload["stage_result"]["stage"]["title"] = "PROJECT_STATE_AUDIT"
    payload["stage_result"]["production_implication"]["state"] = (
        "PRODUCTION_BLOCKED"
    )
    payload["stage_result"]["production_implication"]["failed_hard_gates"] = [
        "DEPLOYMENT_NOT_PROVEN"
    ]

    assert validate_contract(contract_from(payload)) == ()


def test_none_verified_requires_complete_category_assessment() -> None:
    payload = valid_payload()
    payload["blockers"]["assessment_complete"] = False
    payload["blockers"]["assessed_categories"] = ["data"]
    payload["blockers"]["unknowns"] = ["repository_identity"]

    assert {
        "NONE_WITHOUT_ASSESSMENT",
        "NONE_WITH_PARTIAL_CATEGORIES",
        "NONE_WITH_FINDINGS",
        "UNKNOWNS_HIDDEN_BY_NONE",
    }.issubset(issue_codes(payload))


def test_unknown_not_assessed_is_valid_when_assessment_is_incomplete() -> None:
    payload = valid_payload()
    payload["blockers"]["overall"] = "UNKNOWN_NOT_ASSESSED"
    payload["blockers"]["assessment_complete"] = False
    payload["blockers"]["assessed_categories"] = ["data"]
    payload["blockers"]["unknowns"] = ["repository_identity"]

    assert validate_contract(contract_from(payload)) == ()


def test_blocked_requires_external_owner_and_unavailable_input() -> None:
    payload = valid_payload()
    payload["stage_result"]["status"] = "BLOCKED"
    payload["stage_result"]["incomplete_scope"] = [
        {
            "scope_item_id": "SCOPE-REPO-ID",
            "reason": "Repository identity requires maintainer confirmation.",
            "hard_required": True,
            "external_dependency": True,
        }
    ]
    payload["blockers"].update(
        {
            "overall": "BLOCKERS_FOUND",
            "p0": [
                {
                    "id": "BLK-P0-REPOSITORY-IDENTITY",
                    "priority": "P0",
                    "category": "environment_reproducibility",
                    "description": "Wrong repository copy is possible.",
                    "blocked_scope": ["SCOPE-REPO-ID"],
                    "affects_current_gate": True,
                    "affects_next_stage": True,
                    "affects_production": True,
                    "evidence_refs": ["workspace:no-git-metadata"],
                    "owner": "repository maintainer",
                    "resolution_condition": "Canonical repository identity is confirmed.",
                    "can_agent_resolve_now": False,
                }
            ],
            "environment_reproducibility": ["BLK-P0-REPOSITORY-IDENTITY"],
        }
    )
    payload["next_stage"]["id"] = (
        "PROMPT_15_012_IMPLEMENTATION_RESUME_AFTER_REPOSITORY_DECISION"
    )
    payload["next_stage"]["stop_condition"]["gate_key"] = (
        "STOP_GATE_PROMPT_15_012_IMPLEMENTATION_RESUME_AFTER_REPOSITORY_DECISION"
    )
    payload["next_stage"]["required_inputs"][0]["currently_available"] = False
    payload["stop_gate"]["primary_status"] = "BLOCKED"

    assert validate_contract(contract_from(payload)) == ()

    invalid = deepcopy(payload)
    invalid["blockers"]["p0"][0]["can_agent_resolve_now"] = True
    assert "BLOCKED_WITHOUT_EXTERNAL_DEPENDENCY" in issue_codes(invalid)


def test_fail_requires_observed_defect_e3_and_repair_successor() -> None:
    payload = valid_payload()
    payload["stage_result"]["status"] = "FAIL"
    payload["stage_result"]["incomplete_scope"] = [
        {
            "scope_item_id": "SCOPE-VALIDATOR",
            "reason": "Focused validator test fails.",
            "hard_required": True,
            "external_dependency": False,
        }
    ]
    payload["next_stage"]["id"] = (
        "PROMPT_15_012_IMPLEMENTATION_REPAIR_OR_REVALIDATION"
    )
    payload["next_stage"]["stop_condition"]["gate_key"] = (
        "STOP_GATE_PROMPT_15_012_IMPLEMENTATION_REPAIR_OR_REVALIDATION"
    )
    payload["stop_gate"]["primary_status"] = "FAIL"

    assert validate_contract(contract_from(payload)) == ()

    invalid = deepcopy(payload)
    invalid["next_stage"]["id"] = "STAGE_02"
    invalid["next_stage"]["stop_condition"]["gate_key"] = "STOP_GATE_STAGE_02"
    assert "FAIL_NEXT_STAGE_INVALID" in issue_codes(invalid)


def test_no_go_requires_reproducible_falsification_and_decision_successor() -> None:
    payload = valid_payload()
    payload["stage_result"]["status"] = "NO_GO"
    payload["stage_result"]["incomplete_scope"] = [
        {
            "scope_item_id": "SCOPE-APPROACH",
            "reason": "The bounded approach violates a hard invariant.",
            "hard_required": True,
            "external_dependency": False,
        }
    ]
    implication = payload["stage_result"]["production_implication"]
    implication["state"] = "PRODUCTION_BLOCKED"
    implication["failed_hard_gates"] = ["NON_NEGOTIABLE_INVARIANT"]
    payload["next_stage"]["id"] = "DECISION_GATE_ALTERNATIVE_APPROACH"
    payload["next_stage"]["stop_condition"]["gate_key"] = (
        "STOP_GATE_DECISION_GATE_ALTERNATIVE_APPROACH"
    )
    payload["stop_gate"]["primary_status"] = "NO_GO"

    assert validate_contract(contract_from(payload)) == ()

    invalid = deepcopy(payload)
    invalid["stage_result"]["strongest_verified_result"][
        "reproduction_status"
    ] = "not_reproducible"
    assert "NO_GO_WITHOUT_REPRODUCIBLE_FALSIFICATION" in issue_codes(invalid)


def test_none_authorized_is_valid_when_next_stage_cannot_be_determined() -> None:
    payload = valid_payload()
    payload["next_stage"].update(
        {
            "id": "NONE_AUTHORIZED",
            "title": "AWAITING_REQUIRED_DECISION",
            "expected_artifacts": [],
            "acceptance_criteria": [],
        }
    )
    payload["next_stage"]["stop_condition"]["gate_key"] = (
        "STOP_GATE_NONE_AUTHORIZED"
    )

    assert validate_contract(contract_from(payload)) == ()


def test_next_stage_artifact_cannot_claim_current_or_past_completion() -> None:
    payload = valid_payload()
    payload["next_stage"]["expected_artifacts"][0]["temporal_state"] = (
        "CURRENT_VERIFIED"
    )

    with pytest.raises(ValidationError, match="PLANNED_NOT_STARTED"):
        contract_from(payload)


def test_rendered_response_rejects_content_after_gate_and_duplicate_gate() -> None:
    rendered = render_footer(contract_from())
    response = (
        "STOP_GATE_PROMPT_15_012_IMPLEMENTATION = PASS\n\n"
        f"{rendered}\n\nNow starting the next stage."
    )

    codes = {issue.code for issue in validate_rendered_footer(response)}
    assert "STOP_GATE_NOT_LAST" in codes

    duplicate_only = (
        "STOP_GATE_PROMPT_15_012_IMPLEMENTATION = PASS\n\n" f"{rendered}"
    )
    duplicate_codes = {
        issue.code for issue in validate_rendered_footer(duplicate_only)
    }
    assert "STOP_GATE_COUNT_INVALID" in duplicate_codes


def test_explicit_body_status_must_align_with_footer() -> None:
    response = (
        "CURRENT_STAGE_STATUS: FAIL\n\n"
        "Focused test is reported as failing.\n\n"
        f"{render_footer(contract_from())}"
    )

    codes = {issue.code for issue in validate_rendered_footer(response)}
    assert "BODY_FOOTER_STATUS_MISMATCH" in codes


def test_manifest_and_human_footer_must_be_semantically_identical() -> None:
    contract = contract_from()
    response = render_footer(contract).replace(
        "- material claim coverage: 1.00",
        "- material claim coverage: 0.50",
    )

    codes = {
        issue.code
        for issue in validate_rendered_footer(response, expected_contract=contract)
    }
    assert "MANIFEST_FOOTER_MISMATCH" in codes


def test_cli_validates_and_renders_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = contract_from()
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        yaml.safe_dump(to_manifest(contract), sort_keys=False),
        encoding="utf-8",
    )

    assert cli_main(["--manifest", str(manifest_path)]) == 0
    assert "END_OF_RESPONSE_VALID" in capsys.readouterr().out

    assert cli_main(["--manifest", str(manifest_path), "--render"]) == 0
    rendered = capsys.readouterr().out
    assert rendered.rstrip().endswith(
        "STOP_GATE_PROMPT_15_012_IMPLEMENTATION = PASS"
    )

    assert cli_main(["--manifest", str(manifest_path), "--self-check"]) == 0
    self_check_output = capsys.readouterr().out
    assert '"stage_identity_present": true' in self_check_output


def test_cli_rejects_footer_that_diverges_from_manifest(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    contract = contract_from()
    manifest_path = tmp_path / "manifest.yaml"
    footer_path = tmp_path / "response.md"
    manifest_path.write_text(
        yaml.safe_dump(to_manifest(contract), sort_keys=False),
        encoding="utf-8",
    )
    footer_path.write_text(
        render_footer(contract).replace("- status: PASS", "- status: FAIL"),
        encoding="utf-8",
    )

    assert (
        cli_main(
            [
                "--manifest",
                str(manifest_path),
                "--footer",
                str(footer_path),
            ]
        )
        == 1
    )
    assert "MANIFEST_FOOTER_MISMATCH" in capsys.readouterr().err
