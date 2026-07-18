"""Canonical, versioned recommendation-decision fingerprint contract."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import math
import unicodedata
from typing import Any, Iterable, Mapping

from metis.pricing import PricingResult, TierCoefficient, cluster_diagnostic_to_dict


DECISION_FINGERPRINT_VERSION = "recommendation-decision-fingerprint-v1"


def build_decision_fingerprint_payload(
    *,
    context_snapshot: Mapping[str, Any],
    result: PricingResult,
    observations: Iterable[Any],
    policy_config: Mapping[str, Any],
    coefficients: Iterable[TierCoefficient],
    parser_version: str,
    classifier_version: str,
    calibration_dataset_hash: str | None,
    coefficient_version: str | None,
    build_identity: str,
    price_tick: Decimal,
    price_tick_version: str,
) -> dict[str, Any]:
    observation_payload = []
    for observation in observations:
        evidence = getattr(observation, "comparison_evidence", None)
        if not isinstance(evidence, Mapping):
            evidence = None
        observation_payload.append(
            {
                "observation_id": str(observation.id),
                "raw_capture_id": (
                    str(observation.raw_capture_id)
                    if observation.raw_capture_id is not None
                    else None
                ),
                "source": observation.source,
                "source_listing_id": observation.source_listing_id,
                "seller_id": observation.seller_id,
                "price": observation.price,
                "currency": observation.currency,
                "currency_raw": observation.currency_raw,
                "currency_inferred": observation.currency_inferred,
                "observed_at": observation.observed_at,
                "evidence_contract_version": observation.evidence_contract_version,
                "comparability_policy_id": observation.comparability_policy_id,
                "comparability_policy_hash": observation.comparability_policy_hash,
                "seller_identity_verified": observation.seller_identity_verified,
                "source_provenance_verified": observation.source_provenance_verified,
                "automatic_eligible": observation.automatic_eligible,
                "comparison_evidence": evidence,
            }
        )
    observation_payload.sort(key=lambda item: item["observation_id"])
    coefficient_payload = [
        {
            "category": coefficient.category,
            "tier": coefficient.tier.value,
            "multiplier": coefficient.multiplier,
            "model": coefficient.model.value,
            "method_version": coefficient.method_version,
            "coefficient_version": coefficient.coefficient_version,
            "dataset_hash": coefficient.dataset_hash,
            "sample_size": coefficient.sample_size,
            "effective_sample_size": coefficient.effective_sample_size,
            "interval_low": coefficient.interval_low,
            "interval_high": coefficient.interval_high,
            "confidence": coefficient.confidence,
            "validated": coefficient.validated,
            "excluded_oe_norm": coefficient.excluded_oe_norm,
        }
        for coefficient in coefficients
    ]
    coefficient_payload.sort(key=lambda item: (item["category"], item["tier"]))
    policy_hash = canonical_sha256(policy_config)
    return canonicalize(
        {
            "fingerprint_version": DECISION_FINGERPRINT_VERSION,
            "input_context": context_snapshot,
            "observations": observation_payload,
            "eligible_observation_ids": sorted(
                offer.observation_id for offer in result.evidence
            ),
            "excluded_observations": sorted(
                (
                    {
                        "observation_id": item.observation_id,
                        "seller_id": item.seller_id,
                        "raw_price": item.raw_price,
                        "tier": item.tier.value if item.tier else None,
                        "reason": item.reason,
                        "stage": item.stage,
                    }
                    for item in result.excluded
                ),
                key=lambda item: (
                    item["observation_id"],
                    item["stage"],
                    item["reason"],
                ),
            ),
            "matching_and_comparability_policy": {
                "policy_id": result.comparability_policy_id,
                "policy_hash": result.comparability_policy_hash,
                "hard_gate_results": result.hard_gate_results,
                "failed_hard_gates": result.failed_hard_gates,
                "unknown_hard_fields": result.unknown_hard_fields,
            },
            "tier_coefficients": coefficient_payload,
            "coefficient_version": coefficient_version,
            "calibration_dataset_hash": calibration_dataset_hash,
            "pricing_policy": {
                "version": result.policy_version,
                "sha256": policy_hash,
                "config": policy_config,
            },
            "robust_diagnostic": cluster_diagnostic_to_dict(
                result.cluster_diagnostic
            ),
            "robust_policy_fingerprint": result.robust_policy_fingerprint,
            "parser_contract": {
                "parser_version": parser_version,
                "classifier_version": classifier_version,
                "comparison_evidence_contract": "comparison-evidence-v1",
            },
            "build_identity": build_identity or "NOT_AVAILABLE",
            "rounding_policy": {
                "price_tick": price_tick,
                "price_tick_version": price_tick_version,
            },
            "decision": {
                "action": result.action.value,
                "fair_price": result.fair_price,
                "recommended_price": result.recommended_price,
                "lower_bound": result.lower_bound,
                "upper_bound": result.upper_bound,
                "reasons": result.reasons,
                "automatic_eligible": result.automatic_eligible,
            },
        }
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Non-finite Decimal is forbidden in a fingerprint")
        normalized = format(value.normalize(), "f")
        return "0" if normalized in {"-0", ""} else normalized
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Non-finite float is forbidden in a fingerprint")
        return canonicalize(Decimal(str(value)))
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Enum):
        return canonicalize(value.value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {
            unicodedata.normalize("NFC", str(key)): canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        normalized = [canonicalize(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(
                item,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ),
        )
    if isinstance(value, (tuple, list)):
        return [canonicalize(item) for item in value]
    raise TypeError(f"Unsupported fingerprint value: {type(value).__name__}")


__all__ = [
    "DECISION_FINGERPRINT_VERSION",
    "build_decision_fingerprint_payload",
    "canonical_json",
    "canonical_sha256",
    "canonicalize",
]
