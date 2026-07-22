from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from metis.fitment import (
    FEATURE_WEIGHTS,
    Availability,
    CommercialContext,
    ComparableOffer,
    CompatibilityStatus,
    Condition,
    EvidenceClaim,
    EvidencePolarity,
    FitmentFeature,
    PartIdentity,
    PriceComparabilityStatus,
    SellerRelation,
    SourceTier,
    StatementStatus,
    advise_price,
    assess_compatibility,
    assess_price_comparability,
    build_market_envelope,
    normalize_part_number,
)
from metis.pricing.types import ProductTier


NOW = datetime(2026, 7, 21, tzinfo=UTC)


def claim(
    feature: FitmentFeature,
    *,
    value: str = "1",
    source_tier: SourceTier = SourceTier.A,
    source_id: str | None = None,
    correlation_group: str | None = None,
) -> EvidenceClaim:
    evidence_id = f"ev-{feature.value}-{source_id or 'official'}"
    numeric = Decimal(value)
    return EvidenceClaim(
        evidence_id=evidence_id,
        feature=feature,
        value=numeric,
        source_id=source_id or "official-catalog",
        source_type="official_manufacturer_catalog",
        source_tier=source_tier,
        source_reliability=Decimal("0.95"),
        extraction_confidence=Decimal("0.95"),
        independence_factor=Decimal("1"),
        freshness_factor=Decimal("1"),
        correlation_group=correlation_group or source_id or "official-catalog",
        polarity=(
            EvidencePolarity.SUPPORTS
            if numeric > 0
            else EvidencePolarity.CONTRADICTS
            if numeric < 0
            else EvidencePolarity.UNKNOWN
        ),
        statement_status=StatementStatus.FACT,
        claim_value={"verified": numeric > 0},
        retrieved_at=NOW,
        source_url="https://catalog.example/item",
        source_document_sha256="a" * 64,
    )


def complete_claims(*, identity_feature: FitmentFeature = FitmentFeature.OE_EXACT):
    return [
        claim(feature)
        for feature in FitmentFeature
        if feature != FitmentFeature.CROSS_CONFIRMED
        and feature != FitmentFeature.OE_SUPERSESSION
        and (
            feature != FitmentFeature.OE_EXACT
            or identity_feature == FitmentFeature.OE_EXACT
        )
    ] + (
        [claim(identity_feature)] if identity_feature != FitmentFeature.OE_EXACT else []
    )


def identity(*, side: str = "right") -> PartIdentity:
    return PartIdentity(
        category="shock_absorber",
        axle="rear",
        side=side,
        vehicle_make="Toyota",
        vehicle_model="Camry",
        generation="XV40",
        year_from=2006,
        year_to=2011,
        manufacturer_article="21956RR",
        oe_numbers=("48530-89025",),
        side_specific=True,
    )


def commercial(*, relation: SellerRelation = SellerRelation.INDEPENDENT):
    return CommercialContext(
        condition=Condition.NEW,
        package_quantity=Decimal("1"),
        unit_basis="piece",
        currency="UAH",
        tier=ProductTier.AFTERMARKET_B,
        availability=Availability.IN_STOCK,
        seller_relation=relation,
        stable_seller_id_verified=True,
        seller_group_id="seller-group",
        product_identity_key="brand:article",
    )


def test_feature_weights_are_exactly_normalized() -> None:
    assert sum(FEATURE_WEIGHTS.values(), Decimal("0")) == Decimal("1")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("48530-89025", "4853089025"),
        ("48530 89025", "4853089025"),
        ("001-AB", "001AB"),
        (None, None),
    ],
)
def test_part_number_normalization_preserves_leading_zeroes(raw, expected) -> None:
    assert normalize_part_number(raw) == expected


def test_authoritative_complete_evidence_confirms_fitment() -> None:
    assessment = assess_compatibility(identity(), identity(), complete_claims())

    assert assessment.status == CompatibilityStatus.CONFIRMED_COMPATIBLE
    assert assessment.probability >= Decimal("0.90")
    assert assessment.authoritative_confirmation is True
    assert assessment.requires_manual_review is False


def test_left_right_conflict_is_a_non_overridable_hard_rejection() -> None:
    claims = [
        claim(FitmentFeature.SIDE, value="-1")
        if item.feature == FitmentFeature.SIDE
        else item
        for item in complete_claims()
    ]
    assessment = assess_compatibility(
        identity(side="right"), identity(side="left"), claims
    )

    assert assessment.status == CompatibilityStatus.NOT_COMPATIBLE
    assert assessment.probability <= Decimal("0.10")
    assert "SIDE_MISMATCH" in assessment.hard_rejections


def test_unverified_structured_side_conflict_requires_review_not_hard_rejection() -> (
    None
):
    assessment = assess_compatibility(
        identity(side="right"), identity(side="left"), complete_claims()
    )

    assert assessment.status == CompatibilityStatus.LIKELY_COMPATIBLE
    assert "SIDE_MISMATCH" not in assessment.hard_rejections
    assert "UNVERIFIED_SIDE_MISMATCH" in assessment.reason_codes
    assert assessment.requires_manual_review is True


def test_copied_sources_in_one_correlation_group_count_once() -> None:
    duplicated = [
        claim(
            FitmentFeature.OE_EXACT,
            source_tier=SourceTier.C,
            source_id=f"mirror-{index}",
            correlation_group="shared-upstream",
        )
        for index in range(10)
    ]
    assessment = assess_compatibility(identity(), identity(), duplicated)

    assert (
        assessment.feature_consensus[FitmentFeature.OE_EXACT].independent_group_count
        == 1
    )
    assert assessment.authoritative_confirmation is False
    assert assessment.status != CompatibilityStatus.CONFIRMED_COMPATIBLE


def test_unknown_zero_claim_does_not_increase_coverage_or_fill_identity() -> None:
    assessment = assess_compatibility(
        identity(),
        identity(),
        [claim(FitmentFeature.OE_EXACT, value="0")],
    )

    assert assessment.coverage == Decimal("0.0000")
    assert "verified_identifier" in assessment.missing_critical_fields
    assert assessment.authoritative_confirmation is False


def test_correlated_copies_cannot_outvote_a_conflict_in_same_upstream_group() -> None:
    claims = [
        claim(
            FitmentFeature.OE_EXACT,
            source_id=f"mirror-{index}",
            correlation_group="shared-upstream",
        )
        for index in range(10)
    ]
    claims.append(
        claim(
            FitmentFeature.OE_EXACT,
            value="-1",
            source_id="upstream-correction",
            correlation_group="shared-upstream",
        )
    )

    assessment = assess_compatibility(identity(), identity(), claims)
    consensus = assessment.feature_consensus[FitmentFeature.OE_EXACT]

    assert consensus.consensus == Decimal("0.0000")
    assert consensus.independent_group_count == 1
    assert consensus.contradiction is True
    assert "CRITICAL_EVIDENCE_CONFLICT" in assessment.reason_codes
    assert assessment.status != CompatibilityStatus.CONFIRMED_COMPATIBLE


def test_any_explicit_evidence_conflict_prevents_confirmed_status() -> None:
    claims = [
        item for item in complete_claims() if item.feature != FitmentFeature.BODY
    ]
    claims.append(claim(FitmentFeature.BODY, value="-1"))

    assessment = assess_compatibility(identity(), identity(), claims)

    assert assessment.probability >= Decimal("0.90")
    assert assessment.status == CompatibilityStatus.LIKELY_COMPATIBLE
    assert assessment.requires_manual_review is True
    assert "NEGATIVE_EVIDENCE_PRESENT" in assessment.reason_codes


def test_two_independent_tier_b_sources_are_authoritative_but_score_gated() -> None:
    claims = complete_claims()
    claims = [
        item
        for item in claims
        if item.feature
        not in {FitmentFeature.OE_EXACT, FitmentFeature.ARTICLE_IDENTITY}
    ]
    claims.extend(
        [
            claim(
                FitmentFeature.OE_EXACT,
                source_tier=SourceTier.B,
                source_id="partsouq",
                correlation_group="partsouq-upstream",
            ),
            claim(
                FitmentFeature.OE_EXACT,
                source_tier=SourceTier.B,
                source_id="seven-zap",
                correlation_group="seven-zap-upstream",
            ),
        ]
    )
    assessment = assess_compatibility(identity(), identity(), claims)

    assert assessment.authoritative_confirmation is True
    assert assessment.status == CompatibilityStatus.LIKELY_COMPATIBLE
    assert assessment.requires_manual_review is True
    assert "FITMENT_SCORE_BELOW_CONFIRMED_THRESHOLD" in assessment.reason_codes


def test_missing_identity_evidence_stays_fail_closed() -> None:
    claims = [
        claim(feature)
        for feature in FitmentFeature
        if feature
        not in {
            FitmentFeature.OE_EXACT,
            FitmentFeature.OE_SUPERSESSION,
            FitmentFeature.CROSS_CONFIRMED,
            FitmentFeature.ARTICLE_IDENTITY,
        }
    ]
    assessment = assess_compatibility(identity(), identity(), claims)

    assert "verified_identifier" in assessment.missing_critical_fields
    assert assessment.status == CompatibilityStatus.UNCERTAIN
    assert assessment.requires_manual_review is True


def test_negative_exact_oe_is_missing_identity_and_terminal_without_bridge() -> None:
    claims = complete_claims()
    claims = [
        item
        for item in claims
        if item.feature
        not in {FitmentFeature.OE_EXACT, FitmentFeature.ARTICLE_IDENTITY}
    ]
    claims.append(claim(FitmentFeature.OE_EXACT, value="-1"))

    assessment = assess_compatibility(identity(), identity(), claims)

    assert "verified_identifier" in assessment.missing_critical_fields
    assert "OE_IDENTITY_CONFLICT" in assessment.hard_rejections
    assert assessment.status == CompatibilityStatus.NOT_COMPATIBLE


def test_negative_exact_oe_can_be_resolved_by_authoritative_supersession() -> None:
    claims = complete_claims(identity_feature=FitmentFeature.OE_SUPERSESSION)
    claims.append(claim(FitmentFeature.OE_EXACT, value="-1"))

    assessment = assess_compatibility(identity(), identity(), claims)

    assert "OE_IDENTITY_CONFLICT" not in assessment.hard_rejections
    assert "verified_identifier" not in assessment.missing_critical_fields
    assert assessment.authoritative_confirmation is True


def test_physical_match_does_not_make_owned_offer_price_comparable() -> None:
    fitment = assess_compatibility(identity(), identity(), complete_claims())
    result = assess_price_comparability(
        fitment,
        commercial(),
        commercial(relation=SellerRelation.OWN),
        source_quality=Decimal("0.9"),
        freshness_factor=Decimal("1"),
    )

    assert result.status == PriceComparabilityStatus.NOT_COMPARABLE
    assert result.eligible_for_pricing is False
    assert result.competitor_weight == 0
    assert "OWN_OR_RELATED_SELLER" in result.reason_codes


def test_unknown_package_or_unit_requires_manual_review() -> None:
    fitment = assess_compatibility(identity(), identity(), complete_claims())
    incomplete = CommercialContext(
        condition=Condition.NEW,
        currency="UAH",
        tier=ProductTier.AFTERMARKET_B,
        availability=Availability.IN_STOCK,
        seller_relation=SellerRelation.INDEPENDENT,
        stable_seller_id_verified=True,
    )
    result = assess_price_comparability(
        fitment,
        commercial(),
        incomplete,
        source_quality=Decimal("0.9"),
        freshness_factor=Decimal("1"),
    )

    assert result.status == PriceComparabilityStatus.MANUAL_REVIEW
    assert result.eligible_for_pricing is False
    assert {"PACKAGE_QUANTITY_UNKNOWN", "UNIT_BASIS_UNKNOWN"}.issubset(
        result.reason_codes
    )


def test_likely_fitment_is_not_admitted_to_pricing_before_review() -> None:
    claims = complete_claims()
    claims = [
        item
        for item in claims
        if item.feature
        not in {FitmentFeature.OE_EXACT, FitmentFeature.ARTICLE_IDENTITY}
    ]
    claims.append(
        claim(
            FitmentFeature.OE_EXACT,
            source_tier=SourceTier.B,
            source_id="single-catalog",
        )
    )
    fitment = assess_compatibility(identity(), identity(), claims)

    result = assess_price_comparability(
        fitment,
        commercial(),
        commercial(),
        source_quality=Decimal("0.9"),
        freshness_factor=Decimal("1"),
    )

    assert fitment.status == CompatibilityStatus.LIKELY_COMPATIBLE
    assert fitment.requires_manual_review is True
    assert result.status == PriceComparabilityStatus.MANUAL_REVIEW
    assert result.eligible_for_pricing is False
    assert "FITMENT_REVIEW_REQUIRED" in result.reason_codes


def test_competitor_weight_follows_versioned_product_formula() -> None:
    fitment = assess_compatibility(identity(), identity(), complete_claims())
    result = assess_price_comparability(
        fitment,
        commercial(),
        commercial(),
        source_quality=Decimal("0.8"),
        freshness_factor=Decimal("0.95"),
    )

    assert result.eligible_for_pricing is True
    expected = (
        fitment.probability**2
        * Decimal("0.8")
        * Decimal("1")
        * Decimal("1")
        * Decimal("0.95")
        * Decimal("1")
        * Decimal("1")
    ).quantize(Decimal("0.000001"))
    assert result.competitor_weight == expected


def test_market_envelope_caps_duplicate_article_and_requires_independent_sellers() -> (
    None
):
    fitment = assess_compatibility(identity(), identity(), complete_claims())
    price_assessment = assess_price_comparability(
        fitment,
        commercial(),
        commercial(),
        source_quality=Decimal("1"),
        freshness_factor=Decimal("1"),
    )
    offers = [
        ComparableOffer(
            offer_id=f"cheap-{index}",
            price=Decimal("100"),
            assessment=price_assessment,
            brand_article_key="copied:article",
            seller_group_id="copied-network",
        )
        for index in range(20)
    ] + [
        ComparableOffer(
            offer_id="external-1",
            price=Decimal("200"),
            assessment=price_assessment,
            brand_article_key="brand:a",
            seller_group_id="seller-a",
        ),
        ComparableOffer(
            offer_id="external-2",
            price=Decimal("300"),
            assessment=price_assessment,
            brand_article_key="brand:b",
            seller_group_id="seller-b",
        ),
    ]
    envelope = build_market_envelope(offers)

    assert envelope.independent_seller_count == 3
    assert envelope.evidence_sufficient is True
    assert envelope.effective_weight <= Decimal("3")
    assert envelope.weighted_median == Decimal("200")


def test_price_advice_is_always_manual_and_change_is_clipped() -> None:
    fitment = assess_compatibility(identity(), identity(), complete_claims())
    assessment = assess_price_comparability(
        fitment,
        commercial(),
        commercial(),
        source_quality=Decimal("1"),
        freshness_factor=Decimal("1"),
    )
    market = build_market_envelope(
        [
            ComparableOffer(
                offer_id=f"offer-{index}",
                price=price,
                assessment=assessment,
                brand_article_key=f"brand:{index}",
                seller_group_id=f"seller:{index}",
            )
            for index, price in enumerate(
                (Decimal("200"), Decimal("220"), Decimal("240")), start=1
            )
        ]
    )
    advice = advise_price(current_price=Decimal("100"), market=market)

    assert advice.requires_manual_approval is True
    assert advice.action == "consider_raise"
    assert advice.recommended_price == Decimal("120")


def test_evidence_value_and_polarity_are_validated() -> None:
    with pytest.raises(ValueError, match="polarity"):
        EvidenceClaim(
            evidence_id="bad",
            feature=FitmentFeature.SIDE,
            value=Decimal("-1"),
            source_id="source",
            source_type="official",
            source_tier=SourceTier.A,
            source_reliability=Decimal("1"),
            extraction_confidence=Decimal("1"),
            independence_factor=Decimal("1"),
            freshness_factor=Decimal("1"),
            correlation_group="source",
            polarity=EvidencePolarity.SUPPORTS,
            statement_status=StatementStatus.FACT,
            claim_value={},
            retrieved_at=NOW,
        )


def test_unknown_statement_cannot_carry_positive_evidence() -> None:
    with pytest.raises(ValueError, match="UNKNOWN evidence"):
        EvidenceClaim(
            evidence_id="bad-unknown",
            feature=FitmentFeature.OE_EXACT,
            value=Decimal("1"),
            source_id="source",
            source_type="official",
            source_tier=SourceTier.A,
            source_reliability=Decimal("1"),
            extraction_confidence=Decimal("1"),
            independence_factor=Decimal("1"),
            freshness_factor=Decimal("1"),
            correlation_group="source",
            polarity=EvidencePolarity.SUPPORTS,
            statement_status=StatementStatus.UNKNOWN,
            claim_value={},
            retrieved_at=NOW,
        )
