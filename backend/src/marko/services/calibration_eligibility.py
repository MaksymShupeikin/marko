"""Fail-closed, explainable selector for market calibration observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from metis.pricing import HardGateResult, ProductTier
from marko.services.offer_identity import (
    OeVerificationStatus,
    persisted_identity_fields_consistent,
)


CALIBRATION_ELIGIBILITY_VERSION = "calibration-eligibility-v1"


@dataclass(frozen=True, slots=True)
class CalibrationEligibilityDecision:
    eligible: bool
    exclusion_codes: tuple[str, ...]


def evaluate_calibration_eligibility(
    item: Any,
    observation: Any,
    classification: Any,
    policy: Any,
    now: datetime,
) -> CalibrationEligibilityDecision:
    """Evaluate every gate deterministically and return persisted reason codes.

    ``item`` remains part of the public signature to make accidental use of the
    catalog query as candidate identity visible in reviews. It is deliberately
    not consulted: identity comes only from verified observation fields.
    """

    del item
    reasons: list[str] = []
    if observation.automatic_eligible is not True:
        reasons.append("CAL_NOT_AUTOMATIC_ELIGIBLE")
    if observation.comparability_hard_gate_result != HardGateResult.PASS.value:
        reasons.append("CAL_HARD_GATE_NOT_PASS")
    if observation.oe_verification_status not in {
        OeVerificationStatus.VERIFIED_EXACT.value,
        OeVerificationStatus.VERIFIED_CROSS.value,
    } or not _present(observation.verified_matched_oe_norm):
        reasons.append("CAL_OE_NOT_VERIFIED")
    if not _present(observation.comparison_identity_key):
        reasons.append("CAL_IDENTITY_KEY_MISSING")
    if not persisted_identity_fields_consistent(observation):
        reasons.append("CAL_IDENTITY_EVIDENCE_INCONSISTENT")
    if observation.seller_identity_verified is not True:
        reasons.append("CAL_SELLER_NOT_VERIFIED")
    if observation.source_provenance_verified is not True:
        reasons.append("CAL_PROVENANCE_NOT_VERIFIED")

    price = _finite_decimal(observation.price)
    if price is None or price <= 0:
        reasons.append("CAL_INVALID_PRICE")
    if (
        str(observation.currency or "").strip().upper()
        != str(policy.currency).strip().upper()
    ):
        reasons.append("CAL_CURRENCY_MISMATCH")
    if observation.is_available is not True:
        reasons.append("CAL_UNAVAILABLE")
    if observation.observed_at is None:
        reasons.append("CAL_STALE")
    else:
        try:
            age_seconds = (now - observation.observed_at).total_seconds()
        except (AttributeError, TypeError, ValueError):
            age_seconds = None
        if age_seconds is None or Decimal(str(max(0.0, age_seconds) / 3600)) > Decimal(
            str(policy.max_age_hours)
        ):
            reasons.append("CAL_STALE")
    if _below_threshold(
        observation.match_confidence,
        policy.match_confidence_min,
    ):
        reasons.append("CAL_MATCH_CONFIDENCE_LOW")
    if _below_threshold(
        observation.source_confidence,
        policy.source_confidence_min,
    ):
        reasons.append("CAL_SOURCE_CONFIDENCE_LOW")
    if _below_threshold(
        classification.tier_confidence,
        policy.tier_confidence_min,
    ):
        reasons.append("CAL_TIER_CONFIDENCE_LOW")
    try:
        tier = ProductTier(classification.tier)
    except (TypeError, ValueError):
        tier = ProductTier.UNKNOWN
    if classification.is_used:
        reasons.append("CAL_USED")
    if classification.is_owned:
        reasons.append("CAL_OWNED")
    if tier == ProductTier.UNKNOWN:
        reasons.append("CAL_TIER_UNKNOWN")
    if classification.exclusion_reason == "TIER_CONFLICT":
        reasons.append("CAL_TIER_CONFLICT")

    codes = tuple(dict.fromkeys(reasons))
    return CalibrationEligibilityDecision(eligible=not codes, exclusion_codes=codes)


def calibration_identity_record(
    observation: Any,
    classification: Any,
    *,
    role: str,
) -> dict[str, Any]:
    """Canonical evidence identity committed into the calibration dataset hash."""

    return {
        "role": role,
        "observation_id": str(observation.id),
        "search_oe_norm": observation.search_oe_norm,
        "comparison_identity_key": observation.comparison_identity_key,
        "verified_matched_oe_norm": observation.verified_matched_oe_norm,
        "oe_verification_status": observation.oe_verification_status,
        "comparability_policy_hash": observation.comparability_policy_hash,
        "source_confidence_method_version": (
            observation.source_confidence_method_version
        ),
        "tier_method_version": classification.method_version,
        "price": format(Decimal(str(observation.price)), "f"),
        "currency": observation.currency,
        "seller_id": observation.seller_id,
        "observed_at": observation.observed_at.isoformat(),
    }


def _present(value: Any) -> bool:
    return bool(str(value or "").strip())


def _finite_decimal(value: Any) -> Decimal | None:
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return decimal if decimal.is_finite() else None


def _below_threshold(value: Any, threshold: Any) -> bool:
    decimal = _finite_decimal(value)
    expected = _finite_decimal(threshold)
    return decimal is None or expected is None or decimal < expected


__all__ = [
    "CALIBRATION_ELIGIBILITY_VERSION",
    "CalibrationEligibilityDecision",
    "calibration_identity_record",
    "evaluate_calibration_eligibility",
]
