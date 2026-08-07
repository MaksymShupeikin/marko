from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from marko.services.comparability_activation import (
    build_comparability_activation_payload,
    comparability_activation_artifact_verified,
    validate_comparability_activation_payload,
)
from marko.services.decision_fingerprint import canonical_sha256


_LOCKED_GATES = (
    "locked_true_matches",
    "locked_hard_negatives",
    "false_matches",
    "false_match_upper_95",
    "false_not_matches",
    "automatic_match_recall",
    "automatic_decision_coverage",
    "pricing_eligible_sample",
    "pricing_ineligible_sample",
    "unsafe_admitted",
    "pricing_eligible_admission_rate",
    "owned_store_exclusion",
    "seller_deduplication",
    "provider_terminal_rate",
    "provider_budget_exhausted",
    "candidate_terminal_accounting",
)
_SHADOW_GATES = (
    "shadow_product_count",
    "all_candidates_labelled",
    "shadow_parity_mismatches",
    "provider_terminal_rate",
    "provider_budget_exhausted",
)


def _runtime() -> dict[str, str]:
    return {
        "contract_version": "comparability-v2",
        "schema_version": "marko-product-comparability-output-v2",
        "prompt_version": "marko-product-comparability-v3.4",
        "provider": "openai_responses",
        "model_id": "gpt-5.6-luna",
        "model_settings_hash": "a" * 64,
    }


def _artifact() -> dict[str, object]:
    locked = {
        "evaluation_version": "comparability-acceptance-v1",
        "profile": "locked",
        "status": "LOCKED_ACCEPT",
        "promotion_eligible": True,
        "dataset": {
            "pairs": 400,
            "true_matches": 100,
            "hard_negatives": 300,
            "truth_sha256": "b" * 64,
            "predictions_sha256": "c" * 64,
        },
        "gates": [
            {"name": name, "passed": True, "actual": 0, "threshold": 0}
            for name in _LOCKED_GATES
        ],
    }
    shadow = {
        "evaluation_version": "comparability-acceptance-v1",
        "profile": "shadow",
        "status": "SHADOW_ACCEPT",
        "promotion_eligible": True,
        "dataset": {
            "pairs": 1200,
            "true_matches": 300,
            "hard_negatives": 900,
            "truth_sha256": "d" * 64,
            "predictions_sha256": "e" * 64,
        },
        "gates": [
            {
                "name": name,
                "passed": True,
                "actual": 200 if name == "shadow_product_count" else 0,
                "threshold": 200 if name == "shadow_product_count" else 0,
            }
            for name in _SHADOW_GATES
        ],
    }
    return {
        "artifact_version": "comparability-automatic-activation-v1",
        "promotion_authorized": True,
        "locked_truth_schema_version": "comparability-locked-truth-v2",
        "identity_fingerprint_version": "comparability-review-identity-v2",
        "runtime_identity": _runtime(),
        "locked_acceptance_result": locked,
        "locked_acceptance_sha256": canonical_sha256(locked),
        "shadow_acceptance_result": shadow,
        "shadow_acceptance_sha256": canonical_sha256(shadow),
        "approval": {
            "decision": "APPROVE",
            "product_owner_id": "product-owner-1",
            "risk_owner_id": "risk-owner-1",
            "approved_at": "2026-08-05T12:00:00Z",
        },
    }


def _write_artifact(path: Path, payload: object) -> str:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_typed_comparability_activation_requires_complete_release_evidence(
    tmp_path: Path,
) -> None:
    artifact = _artifact()
    path = tmp_path / "activation.json"
    digest = _write_artifact(path, artifact)

    assert validate_comparability_activation_payload(
        artifact,
        expected_runtime_identity=_runtime(),
    ).valid
    assert comparability_activation_artifact_verified(
        str(path),
        digest,
        expected_runtime_identity=_runtime(),
    )

    built = build_comparability_activation_payload(
        locked_acceptance_result=artifact["locked_acceptance_result"],
        shadow_acceptance_result=artifact["shadow_acceptance_result"],
        runtime_identity=_runtime(),
        product_owner_id="product-owner-1",
        risk_owner_id="risk-owner-1",
        approved_at="2026-08-05T12:00:00Z",
    )
    assert built == artifact


def test_exact_hash_of_arbitrary_json_cannot_activate_comparability(
    tmp_path: Path,
) -> None:
    path = tmp_path / "not-an-approval.json"
    digest = _write_artifact(path, {"approved": False})

    assert not comparability_activation_artifact_verified(str(path), digest)


def test_failed_or_tampered_locked_gate_fails_closed(tmp_path: Path) -> None:
    artifact = _artifact()
    locked = artifact["locked_acceptance_result"]
    assert isinstance(locked, dict)
    locked["gates"][2]["passed"] = False
    artifact["locked_acceptance_sha256"] = canonical_sha256(locked)
    path = tmp_path / "failed-locked.json"
    digest = _write_artifact(path, artifact)

    validation = validate_comparability_activation_payload(artifact)

    assert not validation.valid
    assert "LOCKED_GATES_INCOMPLETE" in validation.reason_codes
    assert not comparability_activation_artifact_verified(str(path), digest)


def test_stale_fingerprint_runtime_or_same_approver_fails_closed() -> None:
    stale = _artifact()
    stale["identity_fingerprint_version"] = "comparability-review-identity-v1"
    assert "IDENTITY_FINGERPRINT_CONTRACT_STALE" in (
        validate_comparability_activation_payload(stale).reason_codes
    )

    mismatched_runtime = validate_comparability_activation_payload(
        _artifact(),
        expected_runtime_identity={**_runtime(), "prompt_version": "future-v9"},
    )
    assert "RUNTIME_IDENTITY_MISMATCH" in mismatched_runtime.reason_codes

    same_approver = deepcopy(_artifact())
    approval = same_approver["approval"]
    assert isinstance(approval, dict)
    approval["risk_owner_id"] = approval["product_owner_id"]
    assert "INDEPENDENT_APPROVAL_MISSING" in (
        validate_comparability_activation_payload(same_approver).reason_codes
    )
