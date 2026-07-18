from __future__ import annotations

from decimal import Decimal

from metis.pricing import (
    CompetitorOffer,
    PricingPolicy,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    RobustScaleMethod,
    recommend_price,
)
from metis.pricing.statistics import mad


def _offer(index: int, price: str, *, seller_id: str | None = None) -> CompetitorOffer:
    return CompetitorOffer(
        observation_id=f"obs-{index}",
        seller_id=seller_id or f"seller-{index}",
        seller_name=f"Seller {index}",
        price=Decimal(price),
        currency="UAH",
        is_available=True,
        age_hours=Decimal("0"),
        match_confidence=Decimal("0.95"),
        tier=ProductTier.BUDGET,
        tier_confidence=Decimal("0.95"),
    )


def _context(current_price: str = "800") -> ProductPricingContext:
    return ProductPricingContext(
        sku="ROBUST-1",
        category="brakes",
        current_price=Decimal(current_price),
    )


def _market(prices: tuple[str, ...]) -> list[CompetitorOffer]:
    return [_offer(index, price) for index, price in enumerate(prices)]


def test_v2_scalar_dispersion_remains_exact_legacy_mad_path() -> None:
    prices = ("1000", "1050", "1100", "1150", "1200")
    result = recommend_price(_context(), _market(prices), {})
    center = Decimal("1100")
    expected = Decimal("1.4826") * mad(Decimal(value) for value in prices) / center

    assert result.policy_version == "pricing-v2"
    assert result.dispersion_method == RobustScaleMethod.LEGACY_MAD
    assert result.dispersion == expected
    assert result.dispersion_profile is not None
    assert result.dispersion_profile.robust_cv == expected


def test_v3_defaults_to_corrected_qn_while_fair_price_stays_median() -> None:
    policy = PricingPolicy(version="pricing-v3-robust-dispersion")
    result = recommend_price(
        _context(),
        _market(("1000", "1050", "1100", "1150", "1200")),
        {},
        policy=policy,
    )

    assert policy.dispersion_method == RobustScaleMethod.QN
    assert result.dispersion_method == RobustScaleMethod.QN
    assert result.fair_price == Decimal("1100")
    assert result.dispersion_profile is not None
    assert result.dispersion == result.dispersion_profile.robust_cvs["qn"]


def test_pre_and_post_profiles_expose_cleaning_without_changing_outlier_policy() -> (
    None
):
    prices = ("1000", "1010", "1020", "1030", "1040", "1050", "1060", "10000")
    result = recommend_price(_context(), _market(prices), {})

    assert result.outlier_method == "iqr"
    assert result.pre_clean_dispersion_profile is not None
    assert result.dispersion_profile is not None
    assert result.pre_clean_dispersion_profile.sample_stage == "pre_clean"
    assert result.dispersion_profile.sample_stage == "post_clean"
    assert result.pre_clean_dispersion_profile.sample_size == 8
    assert result.dispersion_profile.sample_size == 7
    assert result.pre_clean_dispersion_profile.cv_max > result.dispersion_profile.cv_max


def test_profiles_are_built_after_seller_deduplication() -> None:
    offers = _market(("1000", "1050", "1100", "1150", "1200"))
    offers.append(_offer(99, "9999", seller_id="seller-0"))

    result = recommend_price(_context(), offers, {})

    assert result.pre_clean_dispersion_profile is not None
    assert result.pre_clean_dispersion_profile.sample_size == 5
    assert result.unique_seller_count == 5
    assert any(item.reason == "SELLER_DUPLICATE" for item in result.excluded)


def test_small_n_keeps_descriptive_profile_but_never_enables_automatic_action() -> None:
    result = recommend_price(
        _context(),
        _market(("1000", "1050", "1100")),
        {},
        policy=PricingPolicy(version="pricing-v3-robust-dispersion"),
    )

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert result.recommended_price is None
    assert result.dispersion_profile is not None
    assert result.dispersion_profile.sample_size == 3


def test_v3_partial_scale_degeneracy_is_fail_closed() -> None:
    prices = ("100", "100", "100", "100", "100", "105", "110", "115")
    policy = PricingPolicy(version="pricing-v3-robust-dispersion")
    result = recommend_price(_context("80"), _market(prices), {}, policy=policy)

    assert result.dispersion_profile is not None
    assert result.dispersion_profile.partial_scale_degeneracy is True
    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert result.action_gates_passed is False
    assert "ROBUST_SCALE_PARTIAL_DEGENERACY" in result.reasons


def test_v2_shadow_profile_does_not_change_legacy_partial_degeneracy_decision() -> None:
    prices = ("100", "100", "100", "100", "100", "105", "110", "115")
    result = recommend_price(_context("80"), _market(prices), {})

    assert result.dispersion_profile is not None
    assert result.dispersion_profile.partial_scale_degeneracy is True
    assert "ROBUST_SCALE_PARTIAL_DEGENERACY" not in result.reasons


def test_all_equal_v3_cohort_is_valid_zero_scale_not_false_degeneracy() -> None:
    policy = PricingPolicy(version="pricing-v3-robust-dispersion")
    result = recommend_price(
        _context("80"), _market(("100", "100", "100", "100", "100")), {}, policy=policy
    )

    assert result.dispersion_profile is not None
    assert result.dispersion_profile.all_scales_zero is True
    assert result.dispersion_profile.partial_scale_degeneracy is False
    assert "ROBUST_SCALE_PARTIAL_DEGENERACY" not in result.reasons


def test_capacity_guard_fails_closed_without_sampling_or_legacy_fallback() -> None:
    policy = PricingPolicy(
        version="pricing-v3-robust-dispersion",
        robust_scale_max_cohort_size=5,
    )
    result = recommend_price(
        _context(),
        _market(("1000", "1010", "1020", "1030", "1040", "1050")),
        {},
        policy=policy,
    )

    assert result.action == RecommendationAction.MANUAL_REVIEW
    assert result.dispersion_profile is None
    assert result.dispersion_method == RobustScaleMethod.QN
    assert result.reasons == ("ROBUST_SCALE_CAPACITY_EXCEEDED",)
