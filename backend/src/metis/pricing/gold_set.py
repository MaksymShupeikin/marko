"""Versioned, fail-closed comparability gold-set evaluator.

The bundled fixture is an engineering/adversarial set. It proves that known
unsafe paths are killed, but cannot approve production activation without
representative labels and a business release policy.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .comparability import evaluate_comparison_evidence, verified_comparison_evidence
from .types import DimensionEvidence, EvidenceState, HardGateResult


GOLD_SET_SCHEMA_VERSION = "comparability-gold-set-v2"
_ALLOWED_SPLITS = frozenset({"train", "calibration", "test"})
_ALLOWED_LABELS = frozenset({"comparable", "conflict", "insufficient"})
_ALLOWED_RETRIEVAL_KINDS = frozenset({"fuzzy", "sku", "model"})
_ALLOWED_MUTATIONS = frozenset(
    {
        "none",
        "dimension_state",
        "missing_raw_currency",
        "unverified_provenance",
        "missing_stable_seller_id",
        "tampered_provenance_hash",
        "currency_conflict",
    }
)
_LEAKAGE_KEYS = (
    "product_family",
    "oe_family",
    "seller_family",
    "observed_period",
)


class GoldSetContractError(ValueError):
    """A labeled fixture is ambiguous or violates its versioned contract."""


def load_gold_set(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GoldSetContractError("GOLD_SET_INVALID_JSON") from exc
    if not isinstance(payload, dict):
        raise GoldSetContractError("GOLD_SET_ROOT_NOT_OBJECT")
    payload["_sha256"] = hashlib.sha256(raw).hexdigest()
    return payload


def evaluate_gold_set(payload: Mapping[str, Any]) -> dict[str, Any]:
    errors = _contract_errors(payload)
    if errors:
        return _failed_report(payload, errors)

    case_results = [_evaluate_case(case) for case in payload["cases"]]
    mismatches = [
        result["case_id"]
        for result in case_results
        if result["actual_result"] != result["expected_result"]
    ]
    automatic = [item for item in case_results if item["actual_result"] == "PASS"]
    unsafe_automatic = [
        item for item in automatic if item["gold_label"] != "comparable"
    ]
    comparable = [item for item in case_results if item["gold_label"] == "comparable"]
    conflicts = [item for item in case_results if item["gold_label"] == "conflict"]
    true_comparable = sum(item["actual_result"] == "PASS" for item in comparable)
    true_conflict = sum(item["actual_result"] == "REJECT" for item in conflicts)
    implementation_passed = bool(
        not mismatches
        and not unsafe_automatic
        and case_results
        and payload["release_policy"]["engineering_unsafe_auto_count_max"] == 0
    )
    approval = payload["approval"]
    policy = payload["release_policy"]
    activation_ready = bool(
        implementation_passed
        and payload["representative"] is True
        and approval["domain_policy_approved"] is True
        and approval["representative_labels_approved"] is True
        and policy["alpha"] is not None
        and policy["epsilon"] is not None
        and policy["loss_weights"] is not None
    )
    return {
        "schema_version": "comparability-gold-set-report-v1",
        "dataset_id": payload["dataset_id"],
        "dataset_version": payload["dataset_version"],
        "dataset_sha256": payload.get("_sha256", "NOT_COMPUTED"),
        "data_class": payload["data_class"],
        "representative": payload["representative"],
        "case_count": len(case_results),
        "split_counts": {
            split: sum(item["split"] == split for item in case_results)
            for split in sorted(_ALLOWED_SPLITS)
        },
        "split_leakage_detected": False,
        "case_results": case_results,
        "mismatched_case_ids": mismatches,
        "counts": {
            "automatic": len(automatic),
            "unsafe_automatic": len(unsafe_automatic),
            "comparable": len(comparable),
            "conflict": len(conflicts),
            "abstained_or_rejected": len(case_results) - len(automatic),
        },
        "metrics": {
            "unsafe_auto_rate": _ratio(len(unsafe_automatic), len(automatic)),
            "comparability_precision": _ratio(
                true_comparable, true_comparable + len(unsafe_automatic)
            ),
            "conflict_recall": _ratio(true_conflict, len(conflicts)),
            "auto_coverage": _ratio(len(automatic), len(comparable)),
            "abstention_rate": _ratio(
                len(case_results) - len(automatic), len(case_results)
            ),
        },
        "binomial_release_bound": {
            "alpha": policy["alpha"],
            "epsilon": policy["epsilon"],
            "p_upper": None,
            "required_representative_n": None,
            "status": "BLOCKED_POLICY"
            if policy["alpha"] is None or policy["epsilon"] is None
            else "NOT_APPLICABLE_NON_REPRESENTATIVE_DATA",
        },
        "engineering_gate": "PASS" if implementation_passed else "FAIL",
        "production_activation": "PASS" if activation_ready else "BLOCKED_DATA",
        "activation_blockers": _activation_blockers(payload),
        "contract_errors": [],
    }


def _contract_errors(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != GOLD_SET_SCHEMA_VERSION:
        errors.append("GOLD_SET_SCHEMA_VERSION_MISMATCH")
    required = (
        "dataset_id",
        "dataset_version",
        "data_class",
        "representative",
        "approval",
        "release_policy",
        "split_contract",
        "cases",
    )
    for key in required:
        if key not in payload:
            errors.append(f"GOLD_SET_MISSING_{key.upper()}")
    if errors:
        return errors
    if not isinstance(payload["cases"], list) or not payload["cases"]:
        return ["GOLD_SET_CASES_EMPTY"]
    if not isinstance(payload["representative"], bool):
        errors.append("GOLD_SET_REPRESENTATIVE_NOT_BOOLEAN")
    approval = payload["approval"]
    policy = payload["release_policy"]
    split_contract = payload["split_contract"]
    if not isinstance(approval, Mapping):
        errors.append("GOLD_SET_APPROVAL_NOT_OBJECT")
    if not isinstance(policy, Mapping):
        errors.append("GOLD_SET_RELEASE_POLICY_NOT_OBJECT")
    if not isinstance(split_contract, Mapping):
        errors.append("GOLD_SET_SPLIT_CONTRACT_NOT_OBJECT")
    if errors:
        return errors
    if set(split_contract.get("splits", ())) != _ALLOWED_SPLITS:
        errors.append("GOLD_SET_SPLITS_INCOMPLETE")
    if tuple(split_contract.get("leakage_keys", ())) != _LEAKAGE_KEYS:
        errors.append("GOLD_SET_LEAKAGE_KEYS_INVALID")
    if policy.get("engineering_unsafe_auto_count_max") != 0:
        errors.append("GOLD_SET_ENGINEERING_GATE_MUST_BE_ZERO")

    seen_ids: set[str] = set()
    split_values: dict[str, dict[str, set[str]]] = {key: {} for key in _LEAKAGE_KEYS}
    for raw_case in payload["cases"]:
        if not isinstance(raw_case, Mapping):
            errors.append("GOLD_SET_CASE_NOT_OBJECT")
            continue
        case_id = str(raw_case.get("case_id", ""))
        if not case_id or case_id in seen_ids:
            errors.append("GOLD_SET_CASE_ID_MISSING_OR_DUPLICATE")
        seen_ids.add(case_id)
        split = raw_case.get("split")
        if split not in _ALLOWED_SPLITS:
            errors.append(f"GOLD_SET_INVALID_SPLIT:{case_id}")
        if raw_case.get("gold_label") not in _ALLOWED_LABELS:
            errors.append(f"GOLD_SET_INVALID_LABEL:{case_id}")
        if raw_case.get("expected_result") not in {
            item.value for item in HardGateResult
        }:
            errors.append(f"GOLD_SET_INVALID_EXPECTED_RESULT:{case_id}")
        if raw_case.get("retrieval_kind") not in _ALLOWED_RETRIEVAL_KINDS:
            errors.append(f"GOLD_SET_INVALID_RETRIEVAL_KIND:{case_id}")
        if not str(raw_case.get("category", "")).strip():
            errors.append(f"GOLD_SET_MISSING_CATEGORY:{case_id}")
        mutation = raw_case.get("mutation")
        if (
            not isinstance(mutation, Mapping)
            or mutation.get("kind") not in _ALLOWED_MUTATIONS
        ):
            errors.append(f"GOLD_SET_INVALID_MUTATION:{case_id}")
        for key in _LEAKAGE_KEYS:
            value = str(raw_case.get(key, "")).strip()
            if not value:
                errors.append(f"GOLD_SET_MISSING_{key.upper()}:{case_id}")
                continue
            split_values[key].setdefault(value, set()).add(str(split))
    for key, values in split_values.items():
        for value, splits in values.items():
            if len(splits) > 1:
                errors.append(f"GOLD_SET_SPLIT_LEAKAGE:{key}:{value}")
    return sorted(set(errors))


def _evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(case["case_id"])
    seller_id = str(case["seller_family"])
    currency_raw: str | None = "UAH"
    currency_normalized = "UAH"
    evidence = verified_comparison_evidence(
        stable_seller_id=seller_id,
        source_record_id=case_id,
        retrieval_kind=str(case["retrieval_kind"]),
    )
    mutation = case["mutation"]
    kind = mutation["kind"]
    if kind == "dimension_state":
        dimensions = dict(evidence.dimensions)
        dimensions[str(mutation["dimension"])] = DimensionEvidence(
            state=EvidenceState(str(mutation["state"]))
        )
        evidence = replace(evidence, dimensions=dimensions)
    elif kind == "missing_raw_currency":
        currency_raw = None
    elif kind == "unverified_provenance":
        evidence = replace(
            evidence, provenance=replace(evidence.provenance, verified=False)
        )
    elif kind == "missing_stable_seller_id":
        seller_id = ""
        evidence = replace(
            evidence,
            seller_identity=replace(
                evidence.seller_identity,
                stable_seller_id=None,
                identity_source=None,
                verified=False,
            ),
        )
    elif kind == "tampered_provenance_hash":
        evidence = replace(
            evidence,
            provenance=replace(evidence.provenance, raw_evidence_sha256="tampered"),
        )
    elif kind == "currency_conflict":
        currency_raw = "USD"
        currency_normalized = "USD"
    decision = evaluate_comparison_evidence(
        evidence,
        seller_id=seller_id,
        currency_raw=currency_raw,
        currency_normalized=currency_normalized,
        required_currency="UAH",
        category=str(case["category"]),
    )
    return {
        "case_id": case_id,
        "split": case["split"],
        "retrieval_kind": case["retrieval_kind"],
        "category": case["category"],
        "gold_label": case["gold_label"],
        "expected_result": case["expected_result"],
        "actual_result": decision.hard_gate_result.value,
        "automatic_eligible": decision.automatic_eligible,
        "reason_codes": list(decision.reason_codes),
    }


def _activation_blockers(payload: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if payload["representative"] is not True:
        blockers.append("REPRESENTATIVE_GOLD_SET_REQUIRED")
    approval = payload["approval"]
    if approval["domain_policy_approved"] is not True:
        blockers.append("DOMAIN_POLICY_APPROVAL_REQUIRED")
    if approval["representative_labels_approved"] is not True:
        blockers.append("REPRESENTATIVE_LABEL_APPROVAL_REQUIRED")
    release = payload["release_policy"]
    if release["alpha"] is None:
        blockers.append("BUSINESS_ALPHA_REQUIRED")
    if release["epsilon"] is None:
        blockers.append("BUSINESS_EPSILON_REQUIRED")
    if release["loss_weights"] is None:
        blockers.append("BUSINESS_LOSS_WEIGHTS_REQUIRED")
    return blockers


def _failed_report(payload: Mapping[str, Any], errors: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "comparability-gold-set-report-v1",
        "dataset_id": payload.get("dataset_id", "UNKNOWN"),
        "dataset_version": payload.get("dataset_version", "UNKNOWN"),
        "dataset_sha256": payload.get("_sha256", "NOT_COMPUTED"),
        "engineering_gate": "FAIL",
        "production_activation": "BLOCKED_DATA",
        "contract_errors": errors,
    }


def _ratio(numerator: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return str(Decimal(numerator) / Decimal(denominator))


__all__ = [
    "GOLD_SET_SCHEMA_VERSION",
    "GoldSetContractError",
    "evaluate_gold_set",
    "load_gold_set",
]
