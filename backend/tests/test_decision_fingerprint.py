"""Canonical fingerprint stability and evidence-mutation sensitivity."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

from marko.infrastructure.db.models import MarketObservation, PricingRecommendation
from marko.services.decision_fingerprint import (
    build_decision_fingerprint_payload,
    canonical_sha256,
)
from metis.pricing import (
    CompetitorOffer,
    ProductPricingContext,
    ProductTier,
    comparison_evidence_to_dict,
    recommend_price,
    verified_comparison_evidence,
)


def _result():
    offers = [
        CompetitorOffer(
            observation_id=f"obs-{index}",
            seller_id=f"seller-{index}",
            seller_name=f"Seller {index}",
            price=Decimal(100 + index),
            currency="UAH",
            currency_raw="UAH",
            is_available=True,
            age_hours=Decimal("1"),
            match_confidence=Decimal("0.95"),
            tier=ProductTier.BUDGET,
            tier_confidence=Decimal("0.95"),
            source_confidence=Decimal("1"),
            semantic_gate_current=True,
            automatic_eligible=True,
            comparison_evidence=verified_comparison_evidence(
                stable_seller_id=f"seller-{index}",
                source_record_id=f"obs-{index}",
            ),
        )
        for index in range(5)
    ]
    return recommend_price(
        ProductPricingContext(
            sku="SKU-FP",
            category="brakes",
            current_price=Decimal("100"),
        ),
        offers,
        {},
    )


def _observation(index: int):
    evidence = verified_comparison_evidence(
        stable_seller_id=f"seller-{index}",
        source_record_id=f"obs-{index}",
    )
    return SimpleNamespace(
        id=f"obs-{index}",
        raw_capture_id=f"capture-{index}",
        source="persisted_replay",
        source_listing_id=f"listing-{index}",
        seller_id=f"seller-{index}",
        price=Decimal(100 + index),
        currency="UAH",
        currency_raw="UAH",
        currency_inferred=False,
        observed_at=datetime(2026, 7, 18, 12, index, tzinfo=UTC),
        evidence_contract_version="comparison-evidence-v1",
        comparability_policy_id=evidence.policy_id,
        comparability_policy_hash=evidence.policy_hash,
        seller_identity_verified=True,
        source_provenance_verified=True,
        automatic_eligible=True,
        comparison_evidence=comparison_evidence_to_dict(evidence),
    )


def _payload(observations):
    return build_decision_fingerprint_payload(
        context_snapshot={
            "sku": "SKU-FP",
            "category": "brakes",
            "current_price": "100.00",
            "currency": "UAH",
        },
        result=_result(),
        observations=observations,
        policy_config={"version": "pricing-v2", "price_tick": "1.00"},
        coefficients=(),
        parser_version="prom-parser-adapter-v2",
        classifier_version="brand-tier-v1",
        calibration_dataset_hash=None,
        coefficient_version=None,
        build_identity="test-build",
        price_tick=Decimal("1.00"),
        price_tick_version="uah-integer-v1",
    )


def test_fingerprint_is_permutation_unicode_and_decimal_stable() -> None:
    observations = [_observation(index) for index in range(5)]
    left = _payload(observations)
    right = _payload(list(reversed(observations)))

    assert isinstance(left, dict)
    assert canonical_sha256(left) == canonical_sha256(right)
    assert canonical_sha256(
        {"name": "e\u0301", "price": Decimal("1.00")}
    ) == canonical_sha256({"price": Decimal("1"), "name": "é"})


def test_fingerprint_changes_when_raw_provenance_changes() -> None:
    observations = [_observation(index) for index in range(5)]
    baseline = _payload(observations)
    mutated_observations = deepcopy(observations)
    mutated_observations[0].comparison_evidence["provenance"]["raw_evidence_sha256"] = (
        "f" * 64
    )

    assert canonical_sha256(_payload(mutated_observations)) != canonical_sha256(
        baseline
    )


def test_database_metadata_enforces_auto_evidence_and_fingerprint_contract() -> None:
    observation_constraints = {
        constraint.name for constraint in MarketObservation.__table__.constraints
    }
    recommendation_constraints = {
        constraint.name for constraint in PricingRecommendation.__table__.constraints
    }
    assert "ck_market_observation_auto_evidence" in observation_constraints
    assert "ck_pricing_recommendation_auto_evidence" in recommendation_constraints
    auto_constraint = next(
        constraint
        for constraint in PricingRecommendation.__table__.constraints
        if constraint.name == "ck_pricing_recommendation_auto_evidence"
    )
    assert "decision_fingerprint IS NOT NULL" in str(auto_constraint.sqltext)
