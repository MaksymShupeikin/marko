from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
from random import Random

import pytest

from metis.pricing import RobustScaleMethod
from metis.pricing.statistics import (
    QN_HISTORICAL_NORMAL_CONSTANT,
    QN_NORMAL_CONSTANT,
    _high_median,
    _low_median,
    _order_statistic,
    _qn_finite_correction,
    dispersion_profile_to_dict,
    qn_scale,
    robust_dispersion_trace,
    robust_price_dispersion,
    scaled_iqr,
    scaled_mad,
    sn_scale,
)


ORACLE = json.loads(
    (Path(__file__).parent / "fixtures" / "robust_scale_oracle_v1.json").read_text()
)
TOLERANCE = Decimal(ORACLE["provenance"]["decimal_tolerance"])
ARITHMETIC_TOLERANCE = Decimal("1e-24")


def _close(actual: Decimal, expected: str, tolerance: Decimal = TOLERANCE) -> bool:
    return abs(actual - Decimal(expected)) <= tolerance


def test_even_sample_low_and_high_medians_are_distinct_order_statistics() -> None:
    values = tuple(Decimal(value) for value in (1, 2, 3, 4))

    assert _order_statistic(values, 1) == Decimal("1")
    assert _low_median(values) == Decimal("2")
    assert _high_median(values) == Decimal("3")
    with pytest.raises(ValueError, match="rank"):
        _order_statistic(values, 0)
    with pytest.raises(ValueError, match="rank"):
        _order_statistic(values, 5)


@pytest.mark.parametrize("vector", ORACLE["vectors"], ids=lambda value: value["id"])
def test_locked_robustbase_contract_vectors(vector: dict[str, object]) -> None:
    values = tuple(Decimal(value) for value in vector["values"])
    profile = robust_price_dispersion(values)

    assert profile.center == Decimal(vector["median"])
    assert profile.raw_iqr == Decimal(vector["raw_iqr"])
    assert _close(profile.gaussian_scales["iqr"], vector["scaled_iqr"])
    assert _close(profile.gaussian_scales["mad"], vector["scaled_mad"])
    assert _close(profile.gaussian_scales["sn"], vector["sn"])
    assert _close(profile.gaussian_scales["qn"], vector["qn"])


def test_qn_uses_only_pair_distances_and_one_based_k_rank() -> None:
    values = tuple(Decimal(value) for value in (0, 10))

    assert qn_scale(values) == (
        Decimal("10") * QN_NORMAL_CONSTANT * Decimal("0.399356")
    )


def test_sn_includes_self_distance_and_uses_high_then_low_median() -> None:
    values = tuple(Decimal(value) for value in (100, 105, 110, 1000))
    self_distance_witness = tuple(Decimal(value) for value in (0, 1, 2))

    # The hand-derived raw Sn order statistic is 10. Excluding the self-zero or
    # averaging either even median would produce a different value.
    assert sn_scale(values, finite_sample_correction=False) == Decimal("11.9260")
    assert sn_scale(values) == Decimal("11.3774040")
    assert sn_scale(self_distance_witness, finite_sample_correction=False) == Decimal(
        "1.1926"
    )


def test_qn_n13_divides_by_finite_denominator_instead_of_multiplying() -> None:
    values = tuple(Decimal(value) for value in range(13))
    uncorrected = qn_scale(values, finite_sample_correction=False)
    corrected = qn_scale(values, finite_sample_correction=True)
    correction = _qn_finite_correction(13)

    assert correction < Decimal("1")
    assert abs(corrected - uncorrected * correction) <= ARITHMETIC_TOLERANCE
    assert corrected < uncorrected


def test_tight_oracle_detects_historical_qn_constant_substitution() -> None:
    values = tuple(Decimal(value) for value in (100, 105, 110, 115, 120))
    actual = qn_scale(values)
    wrong = (
        Decimal("5")
        * QN_HISTORICAL_NORMAL_CONSTANT
        * _qn_finite_correction(len(values))
    )

    assert abs(actual - wrong) > TOLERANCE


@pytest.mark.parametrize(
    "function",
    [scaled_iqr, scaled_mad, sn_scale, qn_scale],
)
def test_scale_estimators_reject_empty_or_non_finite_input(function) -> None:
    with pytest.raises(ValueError):
        function([])
    for non_finite in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValueError, match="finite"):
            function([Decimal("1"), Decimal(non_finite)])


def test_generic_scale_accepts_negative_values_but_price_profile_does_not() -> None:
    values = [Decimal("-2"), Decimal("0"), Decimal("2")]

    assert sn_scale(values) >= Decimal("0")
    assert qn_scale(values) >= Decimal("0")
    with pytest.raises(ValueError, match="positive prices"):
        robust_price_dispersion(values)


def test_singleton_scales_are_zero_without_granting_domain_sufficiency() -> None:
    value = [Decimal("12.34")]

    assert scaled_iqr(value) == Decimal("0")
    assert scaled_mad(value) == Decimal("0")
    assert sn_scale(value) == Decimal("0")
    assert qn_scale(value) == Decimal("0")
    assert robust_price_dispersion(value).all_scales_zero is True


def test_ties_are_explicit_partial_degeneracy_not_a_silent_fallback() -> None:
    profile = robust_price_dispersion(
        [Decimal(value) for value in (100, 100, 100, 105, 110)]
    )

    assert profile.gaussian_scales["iqr"] > Decimal("0")
    assert profile.gaussian_scales["mad"] == Decimal("0")
    assert profile.gaussian_scales["sn"] == Decimal("0")
    assert profile.gaussian_scales["qn"] == Decimal("0")
    assert profile.partial_scale_degeneracy is True
    assert profile.all_scales_zero is False
    assert profile.cv_relative_span is None


def test_all_equal_prices_are_valid_zero_scale_not_partial_degeneracy() -> None:
    profile = robust_price_dispersion([Decimal("100")] * 5)

    assert profile.all_scales_zero is True
    assert profile.partial_scale_degeneracy is False
    assert profile.robust_cv == Decimal("0")
    assert profile.cv_relative_span == Decimal("0")


def test_legacy_method_preserves_exact_historical_dispersion_constant() -> None:
    profile = robust_price_dispersion(
        [Decimal(value) for value in (100, 105, 110, 115, 120)],
        selected_method=RobustScaleMethod.LEGACY_MAD,
    )

    assert profile.selected_scale == Decimal("7.413000")
    assert profile.robust_cv == Decimal("7.413000") / Decimal("110")
    assert profile.selected_scale != profile.gaussian_scales["mad"]


def test_profile_serialization_is_canonical_and_mapping_is_immutable() -> None:
    profile = robust_price_dispersion(
        (Decimal(value) for value in (100, 105, 110, 115, 120))
    )
    serialized = dispersion_profile_to_dict(profile)

    assert serialized["selected_method"] == "qn"
    assert isinstance(serialized["robust_cv"], str)
    with pytest.raises(TypeError):
        profile.gaussian_scales["qn"] = Decimal("0")  # type: ignore[index]

    trace = robust_dispersion_trace(
        selected_method=profile.selected_method,
        pre_clean=None,
        post_clean=profile,
    )
    encoded = json.dumps(trace, sort_keys=True)
    assert '"qn_normal": "2.219144465985076"' in encoded


@pytest.mark.parametrize("sample_size", [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 20])
def test_variations_preserve_scale_invariants(sample_size: int) -> None:
    rng = Random(sample_size)
    base = [
        Decimal(index * index + (index % 3)) / Decimal("100")
        for index in range(sample_size)
    ]
    rng.shuffle(base)
    translated = [value + Decimal("1234.56") for value in base]
    transformed = [Decimal("-3.25") * value + Decimal("99") for value in base]

    for estimator in (scaled_iqr, scaled_mad, sn_scale, qn_scale):
        scale = estimator(base)
        assert scale >= Decimal("0")
        assert estimator(tuple(reversed(base))) == scale
        assert estimator(translated) == scale
        expected = abs(Decimal("-3.25")) * scale
        assert abs(estimator(transformed) - expected) <= ARITHMETIC_TOLERANCE


def test_price_cv_is_scale_invariant_and_input_is_not_mutated() -> None:
    values = [Decimal(value) for value in (100, 101, 103, 108, 120, 160, 300)]
    before = list(values)
    scaled = [Decimal("1000") * value for value in values]

    first = robust_price_dispersion(values)
    second = robust_price_dispersion(scaled)

    assert values == before
    assert dict(first.robust_cvs) == dict(second.robust_cvs)
