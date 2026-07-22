from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from marko.services.fitment_source_adapters import (
    CachePolicy,
    CircuitBreaker,
    RetrievalErrorCode,
    RetryPolicy,
    SourceAccessStatus,
    SourceAdapterPolicy,
    SourceCapability,
    SourceRetrievalError,
    cache_key,
)
from metis.fitment import (
    PriceUnitStatus,
    PricingStrategy,
    RecommendationAction,
    SellerRelation,
    SourceTier,
    WeightedMarketOffer,
    build_robust_market_statistics,
    calculate_contribution_floor,
    freshness_decay,
    normalize_price_unit,
    posterior_source_reliability,
    recommend_market_price,
    resolve_seller_relation,
    weighted_quantile,
)


def _offer(
    offer_id: str,
    price: str,
    *,
    seller: str,
    article: str,
    fitment: str = "0.95",
    source: str = "0.90",
    preserve_if_outlier: bool = False,
) -> WeightedMarketOffer:
    return WeightedMarketOffer(
        offer_id=offer_id,
        normalized_unit_price=Decimal(price),
        fitment_score=Decimal(fitment),
        price_comparability=Decimal("1"),
        source_quality=Decimal(source),
        availability_factor=Decimal("1"),
        freshness_factor=Decimal("1"),
        seller_independence_factor=Decimal("1"),
        unit_certainty=Decimal("1"),
        part_identity_key=article,
        seller_group_id=seller,
        preserve_if_outlier=preserve_if_outlier,
    )


def test_beta_reliability_is_claim_specific_and_reproducible() -> None:
    cold = posterior_source_reliability(SourceTier.B, "oe")
    learned = posterior_source_reliability(
        SourceTier.B,
        "oe",
        confirmed_count=12,
        rejected_count=3,
    )
    weak_claim = posterior_source_reliability(
        SourceTier.B,
        "side",
        confirmed_count=0,
        rejected_count=4,
    )

    assert cold.reliability == Decimal("0.8000")
    assert learned.reliability == Decimal("0.8000")
    assert weak_claim.reliability == Decimal("0.5714")
    assert learned.claim_type == "oe"
    assert weak_claim.claim_type == "side"


def test_beta_reliability_rejects_invalid_feedback_counts() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        posterior_source_reliability(
            SourceTier.A,
            "oe",
            confirmed_count=-1,
        )


def test_weak_copied_catalog_signals_never_prove_ownership() -> None:
    result = resolve_seller_relation(
        {
            "same_catalog_sku_pattern": 1,
            "same_description_template": 1,
            "same_image_set": 1,
            "synchronized_prices": 1,
        }
    )

    assert result.relation == SellerRelation.UNKNOWN
    assert result.relation_score == Decimal("0.3000")
    assert result.strong_identifier_present is False
    assert "CORRELATED_WEAK_SIGNALS_CAPPED" in result.reason_codes


def test_deterministic_seller_identifier_marks_own_store() -> None:
    result = resolve_seller_relation({"same_platform_owner_id": 1})

    assert result.relation == SellerRelation.OWN
    assert result.relation_score == Decimal("1.0000")
    assert result.deterministic_match is True


def test_pair_price_is_normalized_but_unknown_kit_is_not() -> None:
    pair = normalize_price_unit(
        Decimal("1000"), quantity_in_offer=None, unit_basis="pair"
    )
    unknown = normalize_price_unit(
        Decimal("1000"), quantity_in_offer=Decimal("2"), unit_basis="kit"
    )

    assert pair.status == PriceUnitStatus.NORMALIZED_PAIR
    assert pair.normalized_price_per_piece == Decimal("500.00")
    assert pair.certainty_factor == Decimal("0.95")
    assert unknown.status == PriceUnitStatus.UNKNOWN
    assert unknown.normalized_price_per_piece is None


def test_freshness_and_weighted_quantile_boundaries() -> None:
    assert freshness_decay(Decimal("0")) == Decimal("1.0000")
    assert freshness_decay(Decimal("30")) == Decimal("0.3679")
    values = [
        (Decimal("100"), Decimal("1")),
        (Decimal("200"), Decimal("2")),
        (Decimal("300"), Decimal("1")),
    ]
    assert weighted_quantile(values, Decimal("0")) == Decimal("100")
    assert weighted_quantile(values, Decimal("0.5")) == Decimal("200")
    assert weighted_quantile(values, Decimal("1")) == Decimal("300")


def test_market_statistics_cap_duplicates_and_audit_outliers() -> None:
    offers = [
        *[
            _offer(
                f"duplicate-{index}",
                "100",
                seller="copied-network",
                article="same-article",
            )
            for index in range(8)
        ],
        _offer("market-1", "200", seller="seller-1", article="a-1"),
        _offer("market-2", "210", seller="seller-2", article="a-2"),
        _offer("market-3", "220", seller="seller-3", article="a-3"),
        _offer("bad-outlier", "100000", seller="seller-4", article="a-4"),
    ]

    result = build_robust_market_statistics(offers)

    assert result.independent_seller_groups >= 3
    assert result.effective_sample_size >= Decimal("2")
    assert result.weighted_median is not None
    assert result.weighted_median < Decimal("100000")
    assert any(
        row.offer_id == "bad-outlier"
        and row.reason_codes == ("LOG_MAD_PRICE_OUTLIER",)
        for row in result.decisions
    )
    copied_weight = sum(
        row.capped_weight
        for row in result.decisions
        if row.offer_id.startswith("duplicate-")
    )
    assert copied_weight <= Decimal("1")


def test_market_recommendation_abstains_without_independent_sample() -> None:
    market = build_robust_market_statistics(
        [_offer("only", "200", seller="seller-1", article="a-1")]
    )

    result = recommend_market_price(
        current_price=Decimal("180"),
        currency="UAH",
        market=market,
    )

    assert result.action == RecommendationAction.INSUFFICIENT_EVIDENCE
    assert result.recommended_price is None
    assert result.requires_manual_approval is True
    assert result.automatic_price_change_allowed is False


def test_recommendation_obeys_floor_guardrail_and_human_only_boundary() -> None:
    market = build_robust_market_statistics(
        [
            _offer("o1", "300", seller="s1", article="a1"),
            _offer("o2", "310", seller="s2", article="a2"),
            _offer("o3", "320", seller="s3", article="a3"),
            _offer("o4", "330", seller="s4", article="a4"),
            _offer("o5", "340", seller="s5", article="a5"),
        ]
    )

    result = recommend_market_price(
        current_price=Decimal("200"),
        currency="UAH",
        market=market,
        strategy=PricingStrategy.BALANCED,
        approved_price_floor=Decimal("250"),
        max_increase_rate=Decimal("0.20"),
        minimum_confidence=Decimal("0.50"),
        price_tick=Decimal("1"),
    )

    assert result.action == RecommendationAction.CONSIDER_RAISE
    assert result.recommended_price == Decimal("250")
    assert "PRICE_FLOOR_OVERRIDES_CHANGE_GUARDRAIL" in result.warnings
    assert result.price_floor == Decimal("250")
    assert result.automatic_price_change_allowed is False
    assert result.requires_manual_approval is True


def test_contribution_floor_uses_margin_as_share_of_sale_price() -> None:
    assert calculate_contribution_floor(
        Decimal("100"),
        fixed_cost_per_order=Decimal("10"),
        variable_rate=Decimal("0.10"),
        target_contribution_margin_rate=Decimal("0.20"),
    ) == Decimal("157.14")


def test_source_policy_is_fail_closed_and_retry_is_bounded() -> None:
    policy = SourceAdapterPolicy(
        source_id="example",
        capabilities=frozenset({SourceCapability.SEARCH_BY_OE}),
        access_status=SourceAccessStatus.UNKNOWN,
        access_reference="",
        robots_checked=False,
        terms_checked=False,
        authentication_required=False,
        rate_limit="1 rps",
        retry_policy=RetryPolicy(max_attempts=3),
        cache_policy=CachePolicy(
            fact_ttl=timedelta(days=30),
            document_ttl=timedelta(days=7),
        ),
        policy_version="v1",
    )

    with pytest.raises(SourceRetrievalError) as caught:
        policy.require(SourceCapability.SEARCH_BY_OE)
    assert caught.value.code == RetrievalErrorCode.SOURCE_NOT_PERMITTED
    assert caught.value.retryable is False
    assert policy.retry_policy.delay(0, random_value=0) == 1
    assert policy.retry_policy.delay(20, random_value=1) <= 60


def test_circuit_breaker_and_cache_key_are_deterministic() -> None:
    now = datetime(2026, 7, 21, tzinfo=UTC)
    breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=timedelta(minutes=5))
    breaker.record_failure(now=now)
    assert breaker.allow_request(now=now) is True
    breaker.record_failure(now=now)
    assert breaker.allow_request(now=now + timedelta(minutes=4)) is False
    assert breaker.allow_request(now=now + timedelta(minutes=5)) is True
    first = cache_key(
        source_id="PartSouq",
        capability=SourceCapability.SEARCH_BY_OE,
        query={"oe": "48530-89025", "market": "EU"},
    )
    second = cache_key(
        source_id="partsouq",
        capability=SourceCapability.SEARCH_BY_OE,
        query={"market": "EU", "oe": "48530-89025"},
    )
    assert first == second
