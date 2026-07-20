from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from marko.services.calibration_eligibility import (
    evaluate_calibration_eligibility,
)
from metis.pricing import PricingPolicy, ProductTier


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def _observation(**overrides):
    values = {
        "automatic_eligible": True,
        "comparability_hard_gate_result": "PASS",
        "oe_verification_status": "VERIFIED_EXACT",
        "search_oe_norm": "1K0121251",
        "extracted_oe_norms": ["1K0121251"],
        "verified_matched_oe_norm": "1K0121251",
        "comparison_identity_key": "1K0121251",
        "via_cross": False,
        "cross_link_id": None,
        "seller_identity_verified": True,
        "source_provenance_verified": True,
        "price": Decimal("100"),
        "currency": "UAH",
        "is_available": True,
        "observed_at": NOW - timedelta(hours=1),
        "match_confidence": Decimal("0.95"),
        "source_confidence": Decimal("0.90"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _classification(**overrides):
    values = {
        "tier": ProductTier.OEM.value,
        "tier_confidence": Decimal("0.90"),
        "is_used": False,
        "is_owned": False,
        "exclusion_reason": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fully_verified_observation_is_calibration_eligible() -> None:
    decision = evaluate_calibration_eligibility(
        SimpleNamespace(), _observation(), _classification(), PricingPolicy(), NOW
    )

    assert decision.eligible is True
    assert decision.exclusion_codes == ()


@pytest.mark.parametrize(
    ("observation_change", "classification_change", "expected"),
    [
        ({"automatic_eligible": False}, {}, "CAL_NOT_AUTOMATIC_ELIGIBLE"),
        (
            {"comparability_hard_gate_result": "MANUAL_REVIEW"},
            {},
            "CAL_HARD_GATE_NOT_PASS",
        ),
        (
            {"comparability_hard_gate_result": "REJECT"},
            {},
            "CAL_HARD_GATE_NOT_PASS",
        ),
        ({"oe_verification_status": "UNKNOWN"}, {}, "CAL_OE_NOT_VERIFIED"),
        ({"verified_matched_oe_norm": None}, {}, "CAL_OE_NOT_VERIFIED"),
        ({"comparison_identity_key": None}, {}, "CAL_IDENTITY_KEY_MISSING"),
        (
            {"extracted_oe_norms": ["8K0615121"]},
            {},
            "CAL_IDENTITY_EVIDENCE_INCONSISTENT",
        ),
        ({"seller_identity_verified": False}, {}, "CAL_SELLER_NOT_VERIFIED"),
        (
            {"source_provenance_verified": False},
            {},
            "CAL_PROVENANCE_NOT_VERIFIED",
        ),
        (
            {"source_confidence": Decimal("0.49")},
            {},
            "CAL_SOURCE_CONFIDENCE_LOW",
        ),
        ({"match_confidence": Decimal("0.49")}, {}, "CAL_MATCH_CONFIDENCE_LOW"),
        ({"price": Decimal("0")}, {}, "CAL_INVALID_PRICE"),
        ({"price": "NaN"}, {}, "CAL_INVALID_PRICE"),
        (
            {},
            {"tier_confidence": Decimal("0.59")},
            "CAL_TIER_CONFIDENCE_LOW",
        ),
        ({}, {"tier_confidence": "NaN"}, "CAL_TIER_CONFIDENCE_LOW"),
        ({}, {"is_used": True}, "CAL_USED"),
        ({}, {"is_owned": True}, "CAL_OWNED"),
        ({}, {"tier": "unknown"}, "CAL_TIER_UNKNOWN"),
        (
            {},
            {"exclusion_reason": "TIER_CONFLICT"},
            "CAL_TIER_CONFLICT",
        ),
        ({"is_available": False}, {}, "CAL_UNAVAILABLE"),
        ({"currency": "USD"}, {}, "CAL_CURRENCY_MISMATCH"),
        (
            {"observed_at": NOW - timedelta(hours=73)},
            {},
            "CAL_STALE",
        ),
    ],
)
def test_each_failed_gate_excludes_with_stable_reason(
    observation_change,
    classification_change,
    expected,
) -> None:
    decision = evaluate_calibration_eligibility(
        SimpleNamespace(),
        _observation(**observation_change),
        _classification(**classification_change),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert expected in decision.exclusion_codes
