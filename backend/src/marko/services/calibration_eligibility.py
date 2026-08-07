"""Fail-closed, explainable selector for market calibration observations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from metis.pricing import CohortRole, HardGateResult, ProductTier
from marko.services.offer_identity import (
    OeVerificationStatus,
    persisted_identity_fields_consistent,
)
from marko.services.market_price import effective_observation_price
from marko.services.pricing_runs import customer_identity_available
from marko.services.semantic_candidate_gate import (
    semantic_gate_snapshot_is_current,
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
    catalog query as candidate identity visible in reviews.  Candidate identity
    still comes only from verified observation fields; the item is consulted
    only for the negative boundary that prevents a legacy MPN-only row from
    reviving an otherwise internally consistent observation.
    """

    reasons: list[str] = []
    # Bounded runs already enforce this before acquisition.  Keep the same
    # invariant at calibration so old/legacy observations cannot be revived by
    # a later coefficient build.  Lightweight callers that do not expose the
    # catalog identity fields retain the historical pure-observation contract;
    # real ORM/frozen catalog rows always expose ``identity_status``.
    if hasattr(item, "identity_status") and not customer_identity_available(item):
        reasons.append("CAL_CUSTOMER_OE_MISSING")
    # ``automatic_eligible`` is the target-market admission flag.  A KEMP
    # observation deliberately has ``KEMP_REFERENCE`` cohort role and must not
    # enter the target median, but it is still the independently verified
    # anchor required to fit a cross-tier coefficient.  Keep that reference
    # lane explicit instead of weakening the gate for arbitrary non-target
    # rows.
    kemp_reference_lane = (
        getattr(classification, "is_kemp", False) is True
        and str(getattr(classification, "cohort_role", "")).strip()
        == CohortRole.KEMP_REFERENCE.value
    )
    if observation.automatic_eligible is not True and not kemp_reference_lane:
        reasons.append("CAL_NOT_AUTOMATIC_ELIGIBLE")
    if observation.comparability_hard_gate_result != HardGateResult.PASS.value:
        reasons.append("CAL_HARD_GATE_NOT_PASS")
    if not _persisted_semantic_gate_passed(observation):
        # Scalar fields are intentionally not sufficient evidence: a legacy
        # row or a hand-built fixture can say ``PASS`` while its category-aware
        # semantic gate is absent or ``REFERENCE_ONLY``.  Calibration is the
        # one place where that silent mismatch would turn into a coefficient,
        # so require the immutable gate trace as well.
        reasons.append("CAL_SEMANTIC_GATE_NOT_PASS")
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

    try:
        price = effective_observation_price(observation)
    except ValueError:
        price = None
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
    # A dumping flag is a diagnostic exclusion, not a harmless annotation.
    # It can be present on a stale/manual classification even when the tier is
    # otherwise a target-market tier. Letting such a row train a coefficient
    # would turn an intentionally rejected price into calibration evidence.
    if getattr(classification, "is_dumping", False):
        reasons.append("CAL_DUMPING")
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
        "price": format(effective_observation_price(observation), "f"),
        "currency": observation.currency,
        "seller_id": observation.seller_id,
        "observed_at": observation.observed_at.isoformat(),
    }


def _present(value: Any) -> bool:
    return bool(str(value or "").strip())


def _persisted_semantic_gate_passed(observation: Any) -> bool:
    return semantic_gate_snapshot_is_current(
        getattr(observation, "candidate_snapshot", None),
        expected_source_listing_id=getattr(observation, "source_listing_id", None),
        expected_raw_capture_id=getattr(observation, "raw_capture_id", None),
        expected_identity_key=getattr(
            observation, "comparison_identity_key", None
        ),
        require_identity_namespace=(
            getattr(observation, "catalog_item_id", None) is not None
        ),
    )


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
