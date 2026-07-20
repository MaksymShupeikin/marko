from decimal import Decimal

import pytest

from metis.pricing import ProductTier, classify_tier, normalize_brand


def test_brand_normalization_is_exact_and_punctuation_insensitive() -> None:
    assert normalize_brand("Mercedes-Benz") == "MERCEDESBENZ"


@pytest.mark.parametrize(
    ("raw_brand", "expected"),
    [
        ("КЕМР", "KEMP"),
        ("КЕМП", "KEMP"),
        ("БОШ", "BOSCH"),
        ("ФЕБИ", "FEBI"),
    ],
)
def test_known_cyrillic_brand_aliases_normalize_to_latin(
    raw_brand: str, expected: str
) -> None:
    assert normalize_brand(raw_brand) == expected


def test_unknown_cyrillic_text_does_not_create_a_brand_rule() -> None:
    assert normalize_brand("Аналог") == ""


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
    result = classify_tier(
        brand="Bosch",
        title="Новий датчик",
        brand_tiers={"BOSCH": ProductTier.OES},
    )

    assert result.tier == ProductTier.OES
    assert result.confidence == Decimal("0.95")


def test_oem_text_conflicting_with_budget_brand_abstains() -> None:
    result = classify_tier(
        brand="Ridex",
        title="Оригинал OEM датчик",
        brand_tiers={"RIDEX": ProductTier.BUDGET},
    )

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


def test_unapproved_engineering_brand_is_not_a_runtime_default() -> None:
    result = classify_tier(brand="Bosch", title="Новий датчик")

    assert result.tier == ProductTier.UNKNOWN
    assert result.reasons == ("NO_TIER_EVIDENCE",)
