from decimal import Decimal

from metis.pricing import ProductTier, classify_tier, normalize_brand


def test_brand_normalization_is_exact_and_punctuation_insensitive() -> None:
    assert normalize_brand("Mercedes-Benz") == "MERCEDESBENZ"


def test_used_marker_is_excluded_before_brand_tier() -> None:
    result = classify_tier(brand="Bosch", title="Датчик Bosch б/у")

    assert result.tier == ProductTier.USED
    assert result.is_used is True
    assert result.exclusion_reason == "USED_OR_REFURBISHED"


def test_kemp_is_classified_as_separate_direct_tier() -> None:
    result = classify_tier(brand="KEMP", title="Амортизатор")

    assert result.tier == ProductTier.KEMP
    assert result.is_kemp is True
    assert result.confidence == Decimal("0.99")


def test_exact_brand_rule_classifies_oes() -> None:
    result = classify_tier(brand="Bosch", title="Новий датчик")

    assert result.tier == ProductTier.OES
    assert result.confidence == Decimal("0.95")


def test_oem_text_conflicting_with_budget_brand_abstains() -> None:
    result = classify_tier(brand="Ridex", title="Оригинал OEM датчик")

    assert result.tier == ProductTier.UNKNOWN
    assert result.exclusion_reason == "TIER_CONFLICT"


def test_manual_override_is_auditable_reason() -> None:
    result = classify_tier(
        brand="Unknown",
        title="Деталь",
        manual_override=ProductTier.AFTERMARKET_A,
    )

    assert result.tier == ProductTier.AFTERMARKET_A
    assert result.reasons == ("MANUAL_OVERRIDE",)


def test_unknown_brand_abstains_instead_of_guessing_budget() -> None:
    result = classify_tier(brand="NoName", title="Деталь")

    assert result.tier == ProductTier.UNKNOWN
    assert result.confidence == Decimal("0")
