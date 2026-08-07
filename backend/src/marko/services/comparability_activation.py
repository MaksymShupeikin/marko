"""Typed, fail-closed activation contract for automatic comparability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from marko.services.decision_fingerprint import canonical_sha256


COMPARABILITY_ACTIVATION_ARTIFACT_VERSION = (
    "comparability-automatic-activation-v1"
)
COMPARABILITY_LOCKED_TRUTH_SCHEMA_VERSION = "comparability-locked-truth-v2"
COMPARABILITY_IDENTITY_FINGERPRINT_VERSION = "comparability-review-identity-v2"

_RUNTIME_FIELDS = frozenset(
    {
        "contract_version",
        "schema_version",
        "prompt_version",
        "provider",
        "model_id",
        "model_settings_hash",
    }
)
_LOCKED_GATES = frozenset(
    {
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
    }
)
_SHADOW_GATES = frozenset(
    {
        "shadow_product_count",
        "all_candidates_labelled",
        "shadow_parity_mismatches",
        "provider_terminal_rate",
        "provider_budget_exhausted",
    }
)


@dataclass(frozen=True, slots=True)
class ComparabilityActivationValidation:
    valid: bool
    reason_codes: tuple[str, ...]


def build_comparability_activation_payload(
    *,
    locked_acceptance_result: Mapping[str, Any],
    shadow_acceptance_result: Mapping[str, Any],
    runtime_identity: Mapping[str, str],
    product_owner_id: str,
    risk_owner_id: str,
    approved_at: str,
) -> dict[str, Any]:
    """Build an artifact only when every embedded release gate is valid."""

    payload: dict[str, Any] = {
        "artifact_version": COMPARABILITY_ACTIVATION_ARTIFACT_VERSION,
        "promotion_authorized": True,
        "locked_truth_schema_version": COMPARABILITY_LOCKED_TRUTH_SCHEMA_VERSION,
        "identity_fingerprint_version": (
            COMPARABILITY_IDENTITY_FINGERPRINT_VERSION
        ),
        "runtime_identity": dict(runtime_identity),
        "locked_acceptance_result": dict(locked_acceptance_result),
        "locked_acceptance_sha256": canonical_sha256(locked_acceptance_result),
        "shadow_acceptance_result": dict(shadow_acceptance_result),
        "shadow_acceptance_sha256": canonical_sha256(shadow_acceptance_result),
        "approval": {
            "decision": "APPROVE",
            "product_owner_id": product_owner_id.strip(),
            "risk_owner_id": risk_owner_id.strip(),
            "approved_at": approved_at.strip(),
        },
    }
    validation = validate_comparability_activation_payload(
        payload,
        expected_runtime_identity=runtime_identity,
    )
    if not validation.valid:
        raise ValueError(
            "comparability activation evidence is invalid: "
            + ", ".join(validation.reason_codes)
        )
    return payload


def _sha256_text(value: object) -> bool:
    normalized = str(value or "").strip().casefold()
    return len(normalized) == 64 and all(
        character in "0123456789abcdef" for character in normalized
    )


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _passed_gate_names(result: Mapping[str, Any]) -> set[str]:
    gates = result.get("gates")
    if not isinstance(gates, list):
        return set()
    return {
        str(gate.get("name") or "")
        for gate in gates
        if isinstance(gate, Mapping) and gate.get("passed") is True
    }


def _all_reported_gates_passed(result: Mapping[str, Any]) -> bool:
    gates = result.get("gates")
    return bool(gates) and isinstance(gates, list) and all(
        isinstance(gate, Mapping) and gate.get("passed") is True for gate in gates
    )


def _valid_approval(approval: Mapping[str, Any]) -> bool:
    product_owner = str(approval.get("product_owner_id") or "").strip()
    risk_owner = str(approval.get("risk_owner_id") or "").strip()
    if not product_owner or not risk_owner or product_owner == risk_owner:
        return False
    if str(approval.get("decision") or "").strip().upper() != "APPROVE":
        return False
    approved_at = str(approval.get("approved_at") or "").strip()
    try:
        timestamp = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return timestamp.tzinfo is not None


def validate_comparability_activation_payload(
    payload: Mapping[str, Any],
    *,
    expected_runtime_identity: Mapping[str, str] | None = None,
) -> ComparabilityActivationValidation:
    """Validate release evidence rather than merely trusting a file hash."""

    reasons: list[str] = []
    if payload.get("artifact_version") != COMPARABILITY_ACTIVATION_ARTIFACT_VERSION:
        reasons.append("ACTIVATION_ARTIFACT_VERSION_INVALID")
    if payload.get("promotion_authorized") is not True:
        reasons.append("ACTIVATION_NOT_AUTHORIZED")
    if payload.get("locked_truth_schema_version") != (
        COMPARABILITY_LOCKED_TRUTH_SCHEMA_VERSION
    ):
        reasons.append("LOCKED_TRUTH_SCHEMA_STALE")
    if payload.get("identity_fingerprint_version") != (
        COMPARABILITY_IDENTITY_FINGERPRINT_VERSION
    ):
        reasons.append("IDENTITY_FINGERPRINT_CONTRACT_STALE")

    runtime = _mapping(payload.get("runtime_identity"))
    if any(not str(runtime.get(field) or "").strip() for field in _RUNTIME_FIELDS):
        reasons.append("RUNTIME_IDENTITY_INCOMPLETE")
    if not _sha256_text(runtime.get("model_settings_hash")):
        reasons.append("MODEL_SETTINGS_HASH_INVALID")
    if expected_runtime_identity is not None and any(
        str(runtime.get(field) or "") != str(expected_runtime_identity.get(field) or "")
        for field in _RUNTIME_FIELDS
    ):
        reasons.append("RUNTIME_IDENTITY_MISMATCH")

    locked = _mapping(payload.get("locked_acceptance_result"))
    if payload.get("locked_acceptance_sha256") != canonical_sha256(locked):
        reasons.append("LOCKED_ACCEPTANCE_HASH_MISMATCH")
    if (
        locked.get("evaluation_version") != "comparability-acceptance-v1"
        or locked.get("profile") != "locked"
        or locked.get("status") != "LOCKED_ACCEPT"
        or locked.get("promotion_eligible") is not True
    ):
        reasons.append("LOCKED_ACCEPTANCE_NOT_PASSED")
    locked_dataset = _mapping(locked.get("dataset"))
    if (
        locked_dataset.get("pairs") != 400
        or locked_dataset.get("true_matches") != 100
        or locked_dataset.get("hard_negatives") != 300
        or not _sha256_text(locked_dataset.get("truth_sha256"))
        or not _sha256_text(locked_dataset.get("predictions_sha256"))
    ):
        reasons.append("LOCKED_DENOMINATOR_INVALID")
    if not _all_reported_gates_passed(locked) or not _LOCKED_GATES.issubset(
        _passed_gate_names(locked)
    ):
        reasons.append("LOCKED_GATES_INCOMPLETE")

    shadow = _mapping(payload.get("shadow_acceptance_result"))
    if payload.get("shadow_acceptance_sha256") != canonical_sha256(shadow):
        reasons.append("SHADOW_ACCEPTANCE_HASH_MISMATCH")
    if (
        shadow.get("evaluation_version") != "comparability-acceptance-v1"
        or shadow.get("profile") != "shadow"
        or shadow.get("status") != "SHADOW_ACCEPT"
        or shadow.get("promotion_eligible") is not True
    ):
        reasons.append("SHADOW_ACCEPTANCE_NOT_PASSED")
    passed_shadow_gates = _passed_gate_names(shadow)
    shadow_product_gate = next(
        (
            gate
            for gate in shadow.get("gates", [])
            if isinstance(gate, Mapping) and gate.get("name") == "shadow_product_count"
        ),
        None,
    )
    if (
        not _all_reported_gates_passed(shadow)
        or not _SHADOW_GATES.issubset(passed_shadow_gates)
        or not isinstance(shadow_product_gate, Mapping)
        or shadow_product_gate.get("actual") != 200
    ):
        reasons.append("SHADOW_GATES_INCOMPLETE")

    if not _valid_approval(_mapping(payload.get("approval"))):
        reasons.append("INDEPENDENT_APPROVAL_MISSING")
    return ComparabilityActivationValidation(
        valid=not reasons,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )


def comparability_activation_artifact_verified(
    path_value: str | None,
    expected_sha256: str | None,
    *,
    expected_runtime_identity: Mapping[str, str] | None = None,
) -> bool:
    """Require an exact hash and a semantically valid comparability artifact."""

    path_text = str(path_value or "").strip()
    expected = str(expected_sha256 or "").strip().casefold()
    if not path_text or not _sha256_text(expected):
        return False
    try:
        raw = Path(path_text).expanduser().read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return False
    if hashlib.sha256(raw).hexdigest() != expected or not isinstance(payload, Mapping):
        return False
    return validate_comparability_activation_payload(
        payload,
        expected_runtime_identity=expected_runtime_identity,
    ).valid


__all__ = [
    "COMPARABILITY_ACTIVATION_ARTIFACT_VERSION",
    "COMPARABILITY_IDENTITY_FINGERPRINT_VERSION",
    "COMPARABILITY_LOCKED_TRUTH_SCHEMA_VERSION",
    "ComparabilityActivationValidation",
    "build_comparability_activation_payload",
    "comparability_activation_artifact_verified",
    "validate_comparability_activation_payload",
]
