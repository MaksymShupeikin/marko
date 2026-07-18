from decimal import Decimal

import pytest

from metis.pricing.statistics import (
    effective_sample_size,
    geometric_mean,
    iqr_fences,
    log_coverage,
    mad,
    median,
    percentile,
    round_down_to_tick,
    round_to_tick,
    round_up_to_tick,
    winsorize,
)


def test_median_and_percentile_are_deterministic_for_even_samples() -> None:
    values = [Decimal("4"), Decimal("1"), Decimal("3"), Decimal("2")]

    assert median(values) == Decimal("2.5")
    assert percentile(values, Decimal("0.25")) == Decimal("1.75")
    assert percentile(values, Decimal("0.75")) == Decimal("3.25")


def test_mad_and_iqr_fences_are_robust_to_extreme_value() -> None:
    values = [
        Decimal("100"),
        Decimal("101"),
        Decimal("102"),
        Decimal("103"),
        Decimal("10000"),
    ]

    assert mad(values) == Decimal("1")
    low, high = iqr_fences(values)
    assert low < Decimal("100")
    assert high < Decimal("10000")


def test_effective_sample_size_uses_weights_not_raw_count() -> None:
    equal = effective_sample_size([Decimal("1")] * 5)
    concentrated = effective_sample_size(
        [Decimal("1"), Decimal("0.01"), Decimal("0.01"), Decimal("0.01")]
    )

    assert equal == Decimal("5")
    assert Decimal("1") < concentrated < Decimal("1.1")


def test_weighted_geometric_mean_cannot_hide_a_near_zero_factor() -> None:
    score = geometric_mean(
        {"coverage": Decimal("1"), "match": Decimal("0.01")},
        weights={"coverage": Decimal("1"), "match": Decimal("1")},
    )

    assert score == pytest.approx(Decimal("0.1"))


def test_log_coverage_is_bounded_and_monotonic() -> None:
    assert log_coverage(Decimal("0"), 10) == Decimal("0")
    assert log_coverage(Decimal("5"), 10) < log_coverage(Decimal("10"), 10)
    assert log_coverage(Decimal("100"), 10) == Decimal("1")


def test_tick_rounding_has_explicit_direction() -> None:
    value = Decimal("100.6")
    tick = Decimal("1")

    assert round_down_to_tick(value, tick) == Decimal("100")
    assert round_to_tick(value, tick) == Decimal("101")
    assert round_up_to_tick(Decimal("100.1"), tick) == Decimal("101")


def test_winsorization_caps_tails_without_becoming_primary_estimator() -> None:
    values = tuple(Decimal(value) for value in (1, 2, 3, 4, 100))
    result = winsorize(values, lower=Decimal("0.1"), upper=Decimal("0.9"))

    assert result[0] > Decimal("1")
    assert result[-1] < Decimal("100")
    assert median(result) == Decimal("3")


@pytest.mark.parametrize("function", [median, mad])
def test_empty_robust_statistics_are_rejected(function) -> None:
    with pytest.raises(ValueError):
        function([])
