from __future__ import annotations

from decimal import Decimal
from random import Random

import pytest

from metis.pricing.statistics import (
    qn_scale,
    robust_price_dispersion,
    scaled_iqr,
    scaled_mad,
    sn_scale,
)


SAMPLE_SIZES = (2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 20)
DECIMAL_SCALES = (
    Decimal("1"),
    Decimal("0.01"),
    Decimal("0.000000000001"),
    Decimal("1000000000000"),
)
ARITHMETIC_TOLERANCE = Decimal("1e-23")


def _positive_shapes(sample_size: int) -> dict[str, tuple[Decimal, ...]]:
    clean = tuple(Decimal(100 + 5 * index) for index in range(sample_size))
    one_high = clean[:-1] + (clean[-1] * Decimal("20"),)
    one_low = (Decimal("1"),) + clean[1:]
    right_skew = tuple(Decimal(100 + index * index * 3) for index in range(sample_size))
    many_ties = tuple(
        Decimal(100 + 5 * (index // max(1, sample_size // 3)))
        for index in range(sample_size)
    )
    split = sample_size // 2
    two_clusters = tuple(
        Decimal(100 + index) if index < split else Decimal(200 + index)
        for index in range(sample_size)
    )
    return {
        "all_equal": (Decimal("100"),) * sample_size,
        "symmetric_clean": clean,
        "one_high_outlier": one_high,
        "one_low_outlier": one_low,
        "right_skew": right_skew,
        "many_ties": many_ties,
        "two_clusters": two_clusters,
    }


def _orderings(values: tuple[Decimal, ...], seed: int):
    shuffled = list(values)
    Random(seed).shuffle(shuffled)
    return {
        "sorted": tuple(sorted(values)),
        "reversed": tuple(sorted(values, reverse=True)),
        "deterministic_permutation": tuple(shuffled),
    }


def _close(left: Decimal, right: Decimal) -> bool:
    tolerance = max(ARITHMETIC_TOLERANCE, abs(right) * ARITHMETIC_TOLERANCE)
    return abs(left - right) <= tolerance


@pytest.mark.parametrize("sample_size", SAMPLE_SIZES)
def test_full_positive_price_variation_matrix(sample_size: int) -> None:
    """Exercise 13 n values x 7 shapes x 3 orders x 4 Decimal scales."""
    for shape_index, values in enumerate(_positive_shapes(sample_size).values()):
        base_profile = robust_price_dispersion(values)
        for ordered in _orderings(values, sample_size + shape_index).values():
            permutation_profile = robust_price_dispersion(ordered)
            assert permutation_profile == base_profile
            for decimal_scale in DECIMAL_SCALES:
                scaled_values = tuple(value * decimal_scale for value in ordered)
                profile = robust_price_dispersion(scaled_values)
                assert profile.sample_size == sample_size
                assert profile.center > Decimal("0")
                assert all(
                    value.is_finite() and value >= Decimal("0")
                    for value in profile.gaussian_scales.values()
                )
                for method, base_cv in base_profile.robust_cvs.items():
                    assert _close(profile.robust_cvs[method], base_cv)


@pytest.mark.parametrize("sample_size", SAMPLE_SIZES)
def test_left_skew_generic_scale_variations(sample_size: int) -> None:
    values = tuple(
        Decimal("-1") * Decimal(index * index + index % 2)
        for index in range(sample_size)
    )
    translated = tuple(value + Decimal("999.25") for value in values)

    for estimator in (scaled_iqr, scaled_mad, sn_scale, qn_scale):
        expected = estimator(values)
        assert estimator(tuple(reversed(values))) == expected
        assert estimator(translated) == expected


def test_cv_uses_median_center_not_mean_mutation() -> None:
    values = tuple(Decimal(value) for value in (100, 101, 103, 108, 300))
    profile = robust_price_dispersion(values)
    arithmetic_mean = sum(values, Decimal("0")) / Decimal(len(values))
    wrong_mean_cv = profile.selected_scale / arithmetic_mean

    assert profile.center == Decimal("103")
    assert profile.robust_cv == profile.selected_scale / profile.center
    assert profile.robust_cv != wrong_mean_cv
