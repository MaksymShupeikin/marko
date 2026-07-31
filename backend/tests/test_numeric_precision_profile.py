from decimal import Decimal

from marko.services.decision_fingerprint import build_decision_fingerprint_payload
from metis.pricing import (
    CompetitorOffer,
    ProductPricingContext,
    ProductTier,
    recommend_price,
    verified_comparison_evidence,
)
from metis.pricing.numeric import (
    TRANSCENDENTAL_PROFILE_VERSION,
    TRANSCENDENTAL_RELATIVE_TOLERANCE,
    decimal_exp,
    decimal_ln,
    decimal_log1p,
    decimal_pow,
    decimal_sqrt,
)


def test_transcendental_profile_has_stable_twelve_digit_outputs() -> None:
    assert TRANSCENDENTAL_PROFILE_VERSION == "decimal-libm-12sig-v1"
    assert TRANSCENDENTAL_RELATIVE_TOLERANCE == Decimal("1e-11")
    assert decimal_ln(Decimal("1.25")) == Decimal("0.223143551314")
    assert decimal_exp(Decimal("0.1")) == Decimal("1.10517091808")
    assert decimal_sqrt(Decimal("2")) == Decimal("1.41421356237")
    assert decimal_log1p(Decimal("5")) == Decimal("1.79175946923")
    assert decimal_pow(Decimal("2"), Decimal("-0.5")) == Decimal(
        "0.707106781187"
    )


def test_decision_fingerprint_carries_numeric_profile() -> None:
    offers = [
        CompetitorOffer(
            observation_id=f"obs-{index}",
            seller_id=f"seller-{index}",
            seller_name=f"Seller {index}",
            price=Decimal(100 + index),
            currency="UAH",
            is_available=True,
            age_hours=Decimal("0"),
            match_confidence=Decimal("1"),
            tier=ProductTier.BUDGET,
            tier_confidence=Decimal("1"),
            source_confidence=Decimal("1"),
            comparison_evidence=verified_comparison_evidence(
                stable_seller_id=f"seller-{index}",
                source_record_id=f"obs-{index}",
            ),
        )
        for index in range(4)
    ]
    pricing_context = ProductPricingContext(
        sku="SKU-NUMERIC",
        category="parts",
        current_price=Decimal("100"),
    )
    result = recommend_price(pricing_context, offers, {})

    payload = build_decision_fingerprint_payload(
        context_snapshot={"sku": pricing_context.sku},
        result=result,
        observations=[],
        policy_config={},
        coefficients=(),
        parser_version="parser-v1",
        classifier_version="classifier-v1",
        calibration_dataset_hash=None,
        coefficient_version=None,
        build_identity="test",
        price_tick=Decimal("1"),
        price_tick_version="tick-v1",
    )

    assert payload["numeric_precision"] == {
        "profile_version": TRANSCENDENTAL_PROFILE_VERSION,
        "relative_tolerance": str(TRANSCENDENTAL_RELATIVE_TOLERANCE),
    }
