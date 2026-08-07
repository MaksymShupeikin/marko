from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.services.calibration_eligibility import (
    evaluate_calibration_eligibility,
)
from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
)
from marko.services.semantic_candidate_gate import SEMANTIC_PRICING_GATE_VERSION
from metis.pricing import CohortRole, PricingPolicy, ProductTier


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
        "candidate_snapshot": {
            "semantic_gate": {
                "status": "PRICING_EVIDENCE",
                "reason": "OK",
                "gate_version": SEMANTIC_PRICING_GATE_VERSION,
                "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
            },
            "identity_admission": {
                "automatic_evidence_sufficient": True,
            },
        },
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
        "is_kemp": False,
        "is_dumping": False,
        "cohort_role": CohortRole.TARGET_MARKET.value,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_fully_verified_observation_is_calibration_eligible() -> None:
    decision = evaluate_calibration_eligibility(
        SimpleNamespace(), _observation(), _classification(), PricingPolicy(), NOW
    )

    assert decision.eligible is True
    assert decision.exclusion_codes == ()


def test_pre_shock_position_semantic_snapshot_is_not_current() -> None:
    stale_snapshot = {
        "semantic_gate": {
            "status": "PRICING_EVIDENCE",
            "reason": "OK",
            "gate_version": SEMANTIC_PRICING_GATE_VERSION,
            "extractor_version": "semantic-features-v40-damaged-condition",
        },
        "identity_admission": {
            "automatic_evidence_sufficient": True,
        },
    }

    decision = evaluate_calibration_eligibility(
        SimpleNamespace(),
        _observation(candidate_snapshot=stale_snapshot),
        _classification(),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_SEMANTIC_GATE_NOT_PASS" in decision.exclusion_codes


def test_dumping_target_observation_cannot_calibrate() -> None:
    decision = evaluate_calibration_eligibility(
        SimpleNamespace(),
        _observation(),
        _classification(is_dumping=True),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_DUMPING" in decision.exclusion_codes


def test_persisted_observation_without_namespace_proof_is_manual() -> None:
    """Real ORM rows cannot reuse a namespace-less legacy semantic snapshot."""

    decision = evaluate_calibration_eligibility(
        SimpleNamespace(),
        _observation(catalog_item_id=uuid4()),
        _classification(),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_SEMANTIC_GATE_NOT_PASS" in decision.exclusion_codes


def test_mpn_namespace_proof_cannot_enter_calibration_without_confirmed_oe() -> None:
    """A native KEMP/article match remains review-only at calibration."""

    decision = evaluate_calibration_eligibility(
        SimpleNamespace(),
        _observation(
            catalog_item_id=uuid4(),
            search_oe_norm="313452",
            extracted_oe_norms=["313452"],
            verified_matched_oe_norm="313452",
            comparison_identity_key="MPN:313452",
            candidate_snapshot={
                "semantic_gate": {
                    "status": "PRICING_EVIDENCE",
                    "reason": "OK",
                    "gate_version": SEMANTIC_PRICING_GATE_VERSION,
                    "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
                },
                "identity_admission": {
                    "automatic_evidence_sufficient": True,
                    "namespace_version": "identity-namespace-v1",
                    "seed_identity_namespace": "MPN",
                    "verified_identity_namespace": "MPN",
                    "comparison_identity_key": "MPN:313452",
                },
            },
        ),
        _classification(),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_SEMANTIC_GATE_NOT_PASS" in decision.exclusion_codes


def test_legacy_mpn_only_catalog_row_cannot_revive_calibration() -> None:
    """The catalog namespace remains a hard boundary for old observations."""

    decision = evaluate_calibration_eligibility(
        SimpleNamespace(
            identity_status="MPN_ONLY",
            oe_norm="77648791",
            mpn_norm="313452",
            part_numbers_norm=(),
        ),
        _observation(),
        _classification(),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_CUSTOMER_OE_MISSING" in decision.exclusion_codes


def test_verified_kemp_reference_is_calibration_eligible_but_not_target_market() -> None:
    """KEMP is a calibration anchor, not a competitor in the target cohort."""

    decision = evaluate_calibration_eligibility(
        SimpleNamespace(automatic_eligible=False),
        _observation(automatic_eligible=False),
        _classification(
            tier=ProductTier.KEMP.value,
            is_kemp=True,
            cohort_role=CohortRole.KEMP_REFERENCE.value,
        ),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is True
    assert decision.exclusion_codes == ()


def test_non_target_non_kemp_observation_cannot_use_reference_exception() -> None:
    decision = evaluate_calibration_eligibility(
        SimpleNamespace(automatic_eligible=False),
        _observation(automatic_eligible=False),
        _classification(cohort_role=CohortRole.MANUAL_REVIEW.value),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_NOT_AUTOMATIC_ELIGIBLE" in decision.exclusion_codes


@pytest.mark.parametrize(
    "snapshot",
    [
        {},
        {"semantic_gate": {"status": "REFERENCE_ONLY", "reason": "SEMANTIC_CONFLICT"}},
    ],
)
def test_missing_or_failed_semantic_gate_cannot_calibrate(snapshot) -> None:
    decision = evaluate_calibration_eligibility(
        SimpleNamespace(),
        _observation(candidate_snapshot=snapshot),
        _classification(),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_SEMANTIC_GATE_NOT_PASS" in decision.exclusion_codes


def test_stale_semantic_gate_version_cannot_calibrate() -> None:
    decision = evaluate_calibration_eligibility(
        SimpleNamespace(),
        _observation(
            candidate_snapshot={
                "semantic_gate": {
                    "status": "PRICING_EVIDENCE",
                    "reason": "OK",
                    "gate_version": "semantic-pricing-gate-v8-ambiguous-sellable-values",
                }
            }
        ),
        _classification(),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_SEMANTIC_GATE_NOT_PASS" in decision.exclusion_codes


def test_stale_semantic_extractor_cannot_calibrate() -> None:
    decision = evaluate_calibration_eligibility(
        SimpleNamespace(),
        _observation(
            candidate_snapshot={
                "semantic_gate": {
                    "status": "PRICING_EVIDENCE",
                    "reason": "OK",
                    "gate_version": SEMANTIC_PRICING_GATE_VERSION,
                    "extractor_version": "semantic-features-v37-commercial-unit-labels",
                }
            }
        ),
        _classification(),
        PricingPolicy(),
        NOW,
    )

    assert decision.eligible is False
    assert "CAL_SEMANTIC_GATE_NOT_PASS" in decision.exclusion_codes


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
