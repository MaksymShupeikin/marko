"""PROMPT_15_015 R-001..R-020 robust-v3.1 safety matrix."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import random

from metis.pricing import (
    CoefficientModel,
    CompetitorOffer,
    PricingPolicy,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    TierCoefficient,
    log_price_cluster_diagnostic,
    recommend_price,
    verified_comparison_evidence,
)


V31 = PricingPolicy(version="pricing-v3.1-heterogeneity-gated")
ABSTAIN = {
    RecommendationAction.MANUAL_REVIEW,
    RecommendationAction.INSUFFICIENT_DATA,
}


def _offer(index: int, price: str, *, seller_id: str | None = None):
    stable = seller_id or f"seller-{index}"
    return CompetitorOffer(
        observation_id=f"obs-{index}",
        seller_id=stable,
        seller_name=f"Seller {index}",
        price=Decimal(price),
        currency="UAH",
        currency_raw="UAH",
        is_available=True,
        age_hours=Decimal("0"),
        match_confidence=Decimal("0.95"),
        tier=ProductTier.BUDGET,
        tier_confidence=Decimal("0.95"),
        source_confidence=Decimal("1"),
        comparison_evidence=verified_comparison_evidence(
            stable_seller_id=stable, source_record_id=f"obs-{index}"
        ),
    )


def _market(prices, *, scale: Decimal = Decimal("1")):
    return [
        _offer(index, str(Decimal(str(price)) * scale))
        for index, price in enumerate(prices)
    ]


def _context(current: str = "80"):
    return ProductPricingContext(
        sku="ROBUST-V31", category="brakes", current_price=Decimal(current)
    )


BUDGET_COEFFICIENTS = {
    ("brakes", ProductTier.BUDGET): TierCoefficient(
        category="brakes",
        tier=ProductTier.BUDGET,
        multiplier=Decimal("1"),
        model=CoefficientModel.SHRINKAGE,
        method_version="robust-heterogeneity-test-v1",
        coefficient_version="robust-heterogeneity-test-v1:synthetic",
        sample_size=20,
        effective_sample_size=Decimal("18"),
        confidence=Decimal("0.95"),
        validated=True,
        log_effect=Decimal("0"),
        interval_low=Decimal("0.9"),
        interval_high=Decimal("1.1"),
        dataset_hash="a" * 64,
    )
}


def test_r001_clean_tight_grid_is_deterministic() -> None:
    first = recommend_price(
        _context(), _market((100, 105, 110, 115, 120)), BUDGET_COEFFICIENTS, policy=V31
    )
    second = recommend_price(
        _context(), _market((100, 105, 110, 115, 120)), BUDGET_COEFFICIENTS, policy=V31
    )
    assert first == second
    assert first.cluster_diagnostic is not None
    assert not first.cluster_diagnostic.flagged


def test_r002_all_equal_has_no_false_cluster() -> None:
    result = recommend_price(
        _context(), _market((100,) * 5), BUDGET_COEFFICIENTS, policy=V31
    )
    assert result.cluster_diagnostic is not None
    assert not result.cluster_diagnostic.flagged
    assert result.cluster_diagnostic.reason == "ZERO_GLOBAL_DEVIATION"


def test_r003_partial_degeneracy_abstains() -> None:
    result = recommend_price(
        _context(),
        _market((100, 100, 100, 100, 100, 105, 110, 115)),
        BUDGET_COEFFICIENTS,
        policy=V31,
    )
    assert result.action in ABSTAIN
    assert "ROBUST_SCALE_PARTIAL_DEGENERACY" in result.reasons


def test_r004_single_outlier_is_not_a_balanced_cluster() -> None:
    result = recommend_price(
        _context(),
        _market((100, 101, 102, 103, 104, 105, 106, 1000)),
        BUDGET_COEFFICIENTS,
        policy=V31,
    )
    assert result.cluster_diagnostic is not None
    assert not result.cluster_diagnostic.flagged
    assert any(item.reason == "ROBUST_OUTLIER" for item in result.excluded)


def test_r005_right_skew_is_deterministic() -> None:
    prices = (100, 101, 103, 108, 120, 160, 300)
    one = recommend_price(_context(), _market(prices), BUDGET_COEFFICIENTS, policy=V31)
    two = recommend_price(
        _context(), list(reversed(_market(prices))), BUDGET_COEFFICIENTS, policy=V31
    )
    assert (one.action, one.recommended_price, one.reasons) == (
        two.action,
        two.recommended_price,
        two.reasons,
    )


def test_r006_balanced_two_clusters_abstain_explicitly() -> None:
    result = recommend_price(
        _context(),
        _market((100, 101, 102, 103, 180, 181, 182, 183)),
        BUDGET_COEFFICIENTS,
        policy=V31,
    )
    assert result.action in ABSTAIN
    assert result.recommended_price is None
    assert "ROBUST_MULTIMODAL_COHORT" in result.reasons


def test_r007_unequal_clusters_record_policy_sensitivity() -> None:
    result = recommend_price(
        _context(),
        _market((100, 101, 180, 181, 182, 183, 184, 185)),
        BUDGET_COEFFICIENTS,
        policy=V31,
    )
    assert result.cluster_diagnostic is not None
    assert result.cluster_diagnostic.balance is not None
    assert result.cluster_diagnostic.balance <= Decimal("0.25")


def test_r008_three_clusters_do_not_become_automatic() -> None:
    result = recommend_price(
        _context(),
        _market((100, 101, 200, 201, 400, 401)),
        BUDGET_COEFFICIENTS,
        policy=V31,
    )
    assert result.action in ABSTAIN
    assert result.recommended_price is None


def test_r009_r010_small_samples_abstain() -> None:
    for prices in ((100, 105, 110), (100, 105, 110, 1000)):
        result = recommend_price(
            _context(), _market(prices), BUDGET_COEFFICIENTS, policy=V31
        )
        assert result.action in ABSTAIN
        assert result.recommended_price is None


def test_r011_matching_gate_precedes_dispersion() -> None:
    offers = [replace(item, comparison_evidence=None) for item in _market((100,) * 5)]
    result = recommend_price(_context(), offers, BUDGET_COEFFICIENTS, policy=V31)
    assert result.action in ABSTAIN
    assert result.cluster_diagnostic is None
    assert "MANUAL_MISSING_COMPARABILITY_EVIDENCE" in result.reasons


def test_r012_high_global_dispersion_abstains() -> None:
    result = recommend_price(
        _context(),
        _market((100, 120, 140, 160, 180, 200, 220, 240)),
        BUDGET_COEFFICIENTS,
        policy=replace(V31, max_dispersion=Decimal("0.20")),
    )
    assert result.action in ABSTAIN


def test_r013_duplicate_sellers_are_removed_before_diagnostic() -> None:
    offers = _market((100, 101, 102, 103, 180, 181, 182, 183))
    duplicate = replace(offers[0], observation_id="duplicate", price=Decimal("999"))
    result = recommend_price(
        _context(), [*offers, duplicate], BUDGET_COEFFICIENTS, policy=V31
    )
    assert result.unique_seller_count == 8
    assert result.cluster_diagnostic is not None
    assert result.cluster_diagnostic.sample_size == 8


def test_r014_multiplicative_scale_invariance() -> None:
    prices = (100, 101, 102, 103, 180, 181, 182, 183)
    base = recommend_price(_context(), _market(prices), BUDGET_COEFFICIENTS, policy=V31)
    scaled = recommend_price(
        _context("800"),
        _market(prices, scale=Decimal("10")),
        BUDGET_COEFFICIENTS,
        policy=V31,
    )
    assert base.action == scaled.action
    assert base.cluster_diagnostic is not None
    assert scaled.cluster_diagnostic is not None
    assert base.cluster_diagnostic.flagged == scaled.cluster_diagnostic.flagged


def test_r015_permutation_is_exact() -> None:
    offers = _market((100, 101, 102, 103, 180, 181, 182, 183))
    expected = recommend_price(_context(), offers, BUDGET_COEFFICIENTS, policy=V31)
    rng = random.Random(315)
    for _ in range(10):
        shuffled = list(offers)
        rng.shuffle(shuffled)
        actual = recommend_price(_context(), shuffled, BUDGET_COEFFICIENTS, policy=V31)
        assert actual.action == expected.action
        assert actual.recommended_price == expected.recommended_price
        assert actual.cluster_diagnostic == expected.cluster_diagnostic


def test_r016_boundary_point_removal_does_not_unlock_auto() -> None:
    prices = (100, 101, 102, 103, 180, 181, 182, 183)
    for reduced in (prices[1:], prices[:-1], prices[:3] + prices[4:]):
        result = recommend_price(
            _context(), _market(reduced), BUDGET_COEFFICIENTS, policy=V31
        )
        assert result.action in ABSTAIN


def test_r017_threshold_boundary_uses_documented_inclusive_side() -> None:
    prices = tuple(
        Decimal(value)
        for value in ("100", "101", "102", "103", "180", "181", "182", "183")
    )
    initial = log_price_cluster_diagnostic(
        prices,
        min_cluster_size=2,
        improvement_threshold=Decimal("0"),
        balance_threshold=Decimal("0"),
        separation_threshold=Decimal("0"),
        gap_threshold=Decimal("0"),
        sigma_floor=Decimal("0.01"),
    )
    assert initial.improvement is not None
    epsilon = Decimal("0.0000000000000000000000000001")
    at = log_price_cluster_diagnostic(
        prices,
        min_cluster_size=2,
        improvement_threshold=initial.improvement,
        balance_threshold=Decimal("0"),
        separation_threshold=Decimal("0"),
        gap_threshold=Decimal("0"),
        sigma_floor=Decimal("0.01"),
    )
    above = log_price_cluster_diagnostic(
        prices,
        min_cluster_size=2,
        improvement_threshold=initial.improvement + epsilon,
        balance_threshold=Decimal("0"),
        separation_threshold=Decimal("0"),
        gap_threshold=Decimal("0"),
        sigma_floor=Decimal("0.01"),
    )
    assert at.flagged
    assert not above.flagged


def test_r018_non_finite_zero_negative_are_hard_rejected() -> None:
    bad = (Decimal("NaN"), Decimal("Infinity"), Decimal("0"), Decimal("-1"))
    offers = [
        replace(_offer(index, "100"), price=value) for index, value in enumerate(bad)
    ]
    result = recommend_price(_context(), offers, BUDGET_COEFFICIENTS, policy=V31)
    assert result.action in ABSTAIN
    assert result.recommended_price is None
    assert all(item.reason == "NON_POSITIVE_PRICE" for item in result.excluded)


def test_r019_baseline_abstention_cannot_be_relaxed() -> None:
    permissive_candidate = replace(
        V31,
        robust_disagreement_threshold=Decimal("1000"),
        robust_cluster_improvement_threshold=Decimal("1"),
        sensitivity_tolerance=Decimal("1"),
    )
    result = recommend_price(
        _context(),
        _market((100, 101, 102, 103, 180, 181, 182, 183)),
        BUDGET_COEFFICIENTS,
        policy=permissive_candidate,
    )
    assert result.action in ABSTAIN
    assert result.recommended_price is None
    assert "ROBUST_BASELINE_ABSTENTION_NOT_RELAXABLE" in result.reasons


def test_r020_policy_remains_unactivated_without_representative_data() -> None:
    assert V31.robust_non_relaxation_enabled
    assert V31.robust_baseline_policy_version == "pricing-v2"
    assert V31.version == "pricing-v3.1-heterogeneity-gated"
