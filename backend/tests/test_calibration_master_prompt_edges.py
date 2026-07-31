"""WP-4 edge matrix for the owner-independent calibration path."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from metis.pricing import (
    CalibrationPair,
    ProductTier,
    calibration_dataset_hash,
    fit_simple_coefficients,
)
from metis.pricing.calibration import _exp_decimal


def _pair(index: int, tier_price: str = "200") -> CalibrationPair:
    return CalibrationPair(
        oe_norm=f"OE-{index}",
        category="synthetic-brakes",
        tier=ProductTier.OEM,
        tier_price=Decimal(tier_price),
        reference_price=Decimal("100"),
        quality_weight=Decimal("1"),
    )


def _coefficient(pairs: list[CalibrationPair]):
    result = fit_simple_coefficients(pairs, min_pairs=8)
    return result.get(("synthetic-brakes", ProductTier.OEM))


def test_n_zero_produces_no_coefficient() -> None:
    assert fit_simple_coefficients([], min_pairs=8) == {}


def test_n_one_and_n_seven_abstain_below_support_boundary() -> None:
    one = _coefficient([_pair(1)])
    seven = _coefficient([_pair(index) for index in range(7)])

    assert one is not None and one.validated is False
    assert seven is not None and seven.validated is False
    assert "TOO_FEW_CATEGORY_PAIRS" in one.validation_reasons
    assert "TOO_FEW_CATEGORY_PAIRS" in seven.validation_reasons


def test_n_eight_equal_ratios_validate_at_exact_boundary() -> None:
    coefficient = _coefficient([_pair(index) for index in range(8)])

    assert coefficient is not None
    assert coefficient.sample_size == 8
    assert coefficient.effective_sample_size == Decimal("8")
    assert coefficient.multiplier == Decimal("2.0")
    assert coefficient.interval_low == coefficient.interval_high
    assert coefficient.validated is True


def test_one_x100_outlier_does_not_move_the_median_coefficient() -> None:
    pairs = [_pair(index) for index in range(7)]
    pairs.append(_pair(7, "20000"))

    coefficient = _coefficient(pairs)

    assert coefficient is not None
    assert coefficient.sample_size == 8
    assert coefficient.multiplier == Decimal("2.0")
    assert coefficient.validated is True


def test_zero_and_negative_prices_are_excluded_not_coerced() -> None:
    pairs = [_pair(index) for index in range(8)]
    pairs.extend((_pair(8, "0"), _pair(9, "-1")))

    coefficient = _coefficient(pairs)

    assert coefficient is not None
    assert coefficient.sample_size == 8
    assert coefficient.multiplier == Decimal("2.0")


def test_padded_oe_is_canonicalized_before_hashing_and_deduplication() -> None:
    clean = _pair(1)
    padded = replace(clean, oe_norm=f"  {clean.oe_norm.lower()}  ")

    assert calibration_dataset_hash([clean]) == calibration_dataset_hash([padded])
    coefficient = _coefficient([clean, padded])

    assert coefficient is not None
    assert coefficient.sample_size == 1


def test_exp_decimal_never_persists_hidden_binary_float_digits() -> None:
    result = _exp_decimal(Decimal("0.1"))

    assert result == Decimal("1.10517091808")
    assert len(result.as_tuple().digits) <= 12
