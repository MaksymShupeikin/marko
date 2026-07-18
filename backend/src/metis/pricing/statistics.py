"""Deterministic robust-statistics helpers used by the Metis engine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP
import math
from types import MappingProxyType

from .types import RobustDispersionProfile, RobustScaleMethod


ZERO = Decimal("0")
ONE = Decimal("1")

ROBUST_DISPERSION_PROFILE_VERSION = "rc-scale-v1"
ROBUST_SCALE_CORRECTION_PROFILE_VERSION = "robustbase-modern-v1"

# Gaussian-consistency constants are strings so the Decimal core never passes
# through binary float. The corrected Qn constant differs from the historical
# 2.2219 printed in Rousseeuw-Croux (1993); robustbase has used the corrected
# value since 2010. See https://rdrr.io/cran/robustbase/src/R/qnsn.R.
IQR_NORMAL_DENOMINATOR = Decimal("1.348979500392163")
MAD_NORMAL_CONSTANT = Decimal("1.482602218505602")
LEGACY_MAD_NORMAL_CONSTANT = Decimal("1.4826")
SN_NORMAL_CONSTANT = Decimal("1.1926")
QN_NORMAL_CONSTANT = Decimal("2.219144465985076")
QN_HISTORICAL_NORMAL_CONSTANT = Decimal("2.2219")

_SN_FINITE_CORRECTIONS: Mapping[int, Decimal] = MappingProxyType(
    {
        2: Decimal("0.743"),
        3: Decimal("1.851"),
        4: Decimal("0.954"),
        5: Decimal("1.351"),
        6: Decimal("0.993"),
        7: Decimal("1.198"),
        8: Decimal("1.005"),
        9: Decimal("1.131"),
    }
)
_QN_FINITE_CORRECTIONS: Mapping[int, Decimal] = MappingProxyType(
    {
        2: Decimal("0.399356"),
        3: Decimal("0.99365"),
        4: Decimal("0.51321"),
        5: Decimal("0.84401"),
        6: Decimal("0.61220"),
        7: Decimal("0.85877"),
        8: Decimal("0.66993"),
        9: Decimal("0.87344"),
        10: Decimal("0.72014"),
        11: Decimal("0.88906"),
        12: Decimal("0.75743"),
    }
)


def _finite_decimals(values: Iterable[Decimal], *, name: str) -> tuple[Decimal, ...]:
    collected = tuple(values)
    if not collected:
        raise ValueError(f"{name} requires at least one value")
    if any(
        not isinstance(value, Decimal) or not value.is_finite() for value in collected
    ):
        raise ValueError(f"{name} requires finite Decimal values")
    return collected


def _order_statistic(values: Sequence[Decimal], rank_1_based: int) -> Decimal:
    """Return the exact 1-based order statistic without median averaging."""
    collected = _finite_decimals(values, name="order statistic")
    if rank_1_based < 1 or rank_1_based > len(collected):
        raise ValueError("order-statistic rank is outside the sample")
    return sorted(collected)[rank_1_based - 1]


def _low_median(values: Sequence[Decimal]) -> Decimal:
    return _order_statistic(values, (len(values) + 1) // 2)


def _high_median(values: Sequence[Decimal]) -> Decimal:
    return _order_statistic(values, len(values) // 2 + 1)


def scaled_iqr(values: Iterable[Decimal]) -> Decimal:
    """Return linear-interpolated IQR on a Gaussian-consistent scale."""
    collected = _finite_decimals(values, name="scaled_iqr")
    q1 = percentile(collected, Decimal("0.25"))
    q3 = percentile(collected, Decimal("0.75"))
    return (q3 - q1) / IQR_NORMAL_DENOMINATOR


def scaled_mad(values: Iterable[Decimal]) -> Decimal:
    """Return raw MAD multiplied by the precise Gaussian consistency factor."""
    collected = _finite_decimals(values, name="scaled_mad")
    return MAD_NORMAL_CONSTANT * mad(collected)


def _sn_finite_correction(sample_size: int) -> Decimal:
    if sample_size < 2:
        return ONE
    if sample_size <= 9:
        return _SN_FINITE_CORRECTIONS[sample_size]
    if sample_size % 2 == 0:
        return ONE
    n = Decimal(sample_size)
    return n / (n - Decimal("0.9"))


def _qn_finite_denominator(sample_size: int) -> Decimal:
    """Return robustbase's f_n; Qn must divide by this for n >= 13."""
    n = Decimal(sample_size)
    if sample_size % 2:
        return (
            ONE
            + (Decimal("1.60188") + (Decimal("-2.1284") - Decimal("5.172") / n) / n) / n
        )
    return (
        ONE
        + (
            Decimal("3.67561")
            + (Decimal("1.9654") + (Decimal("6.987") - Decimal("77") / n) / n) / n
        )
        / n
    )


def _qn_finite_correction(sample_size: int) -> Decimal:
    if sample_size < 2:
        return ONE
    if sample_size <= 12:
        return _QN_FINITE_CORRECTIONS[sample_size]
    return ONE / _qn_finite_denominator(sample_size)


def sn_scale(
    values: Iterable[Decimal], *, finite_sample_correction: bool = True
) -> Decimal:
    """Exact Rousseeuw-Croux Sn with inner high and outer low medians."""
    collected = _finite_decimals(values, name="sn_scale")
    if len(collected) == 1:
        return ZERO
    row_scales = tuple(
        _high_median(tuple(abs(value - peer) for peer in collected))
        for value in collected
    )
    raw = _low_median(row_scales)
    correction = (
        _sn_finite_correction(len(collected)) if finite_sample_correction else ONE
    )
    return correction * SN_NORMAL_CONSTANT * raw


def qn_scale(
    values: Iterable[Decimal], *, finite_sample_correction: bool = True
) -> Decimal:
    """Exact corrected Qn using only i < j distances and a 1-based k rank."""
    collected = _finite_decimals(values, name="qn_scale")
    sample_size = len(collected)
    if sample_size == 1:
        return ZERO
    distances = tuple(
        abs(collected[left] - collected[right])
        for left in range(sample_size - 1)
        for right in range(left + 1, sample_size)
    )
    h = sample_size // 2 + 1
    rank = h * (h - 1) // 2
    raw = _order_statistic(distances, rank)
    correction = _qn_finite_correction(sample_size) if finite_sample_correction else ONE
    return correction * QN_NORMAL_CONSTANT * raw


def robust_price_dispersion(
    values: Iterable[Decimal],
    *,
    selected_method: RobustScaleMethod = RobustScaleMethod.QN,
    sample_stage: str = "post_clean",
    finite_sample_correction: bool = True,
    profile_version: str = ROBUST_DISPERSION_PROFILE_VERSION,
    correction_profile_version: str = ROBUST_SCALE_CORRECTION_PROFILE_VERSION,
) -> RobustDispersionProfile:
    """Build a deterministic comparison profile for positive market prices."""
    collected = _finite_decimals(values, name="robust_price_dispersion")
    if any(value <= ZERO for value in collected):
        raise ValueError("robust_price_dispersion requires positive prices")
    try:
        method = RobustScaleMethod(selected_method)
    except ValueError as exc:
        raise ValueError("unsupported robust scale method") from exc
    if sample_stage not in {"pre_clean", "post_clean"}:
        raise ValueError("sample_stage must be pre_clean or post_clean")
    if profile_version != ROBUST_DISPERSION_PROFILE_VERSION:
        raise ValueError("unsupported robust dispersion profile version")
    if correction_profile_version != ROBUST_SCALE_CORRECTION_PROFILE_VERSION:
        raise ValueError("unsupported robust scale correction profile version")

    center = median(collected)
    if center <= ZERO:
        raise ValueError("robust_price_dispersion requires a positive median")
    q1 = percentile(collected, Decimal("0.25"))
    q3 = percentile(collected, Decimal("0.75"))
    raw_iqr = q3 - q1
    raw_mad = mad(collected)
    scales = {
        RobustScaleMethod.IQR.value: raw_iqr / IQR_NORMAL_DENOMINATOR,
        RobustScaleMethod.MAD.value: MAD_NORMAL_CONSTANT * raw_mad,
        RobustScaleMethod.SN.value: sn_scale(
            collected, finite_sample_correction=finite_sample_correction
        ),
        RobustScaleMethod.QN.value: qn_scale(
            collected, finite_sample_correction=finite_sample_correction
        ),
    }
    cvs = {name: value / center for name, value in scales.items()}
    zero_methods = tuple(name for name, value in scales.items() if value == ZERO)
    all_zero = len(zero_methods) == len(scales)
    partial_degeneracy = bool(zero_methods) and not all_zero
    cv_min = min(cvs.values())
    cv_max = max(cvs.values())
    cv_span = cv_max - cv_min
    cv_center = median(cvs.values())
    if all_zero:
        cv_relative_span: Decimal | None = ZERO
    elif partial_degeneracy or cv_center <= ZERO:
        cv_relative_span = None
    else:
        cv_relative_span = cv_span / cv_center

    if method == RobustScaleMethod.LEGACY_MAD:
        selected_scale = LEGACY_MAD_NORMAL_CONSTANT * raw_mad
    else:
        selected_scale = scales[method.value]

    return RobustDispersionProfile(
        version=profile_version,
        correction_profile_version=correction_profile_version,
        finite_sample_correction=finite_sample_correction,
        sample_stage=sample_stage,
        sample_size=len(collected),
        center=center,
        q1=q1,
        q3=q3,
        raw_iqr=raw_iqr,
        raw_mad=raw_mad,
        gaussian_scales=MappingProxyType(scales),
        robust_cvs=MappingProxyType(cvs),
        selected_method=method,
        selected_scale=selected_scale,
        robust_cv=selected_scale / center,
        zero_scale_methods=zero_methods,
        all_scales_zero=all_zero,
        partial_scale_degeneracy=partial_degeneracy,
        cv_min=cv_min,
        cv_max=cv_max,
        cv_span=cv_span,
        cv_median=cv_center,
        cv_relative_span=cv_relative_span,
    )


def dispersion_profile_to_dict(
    profile: RobustDispersionProfile | None,
) -> dict[str, object] | None:
    """Serialize Decimal profile values canonically for trace/API/replay."""
    if profile is None:
        return None
    return {
        "profile_version": profile.version,
        "correction_profile_version": profile.correction_profile_version,
        "finite_sample_correction": profile.finite_sample_correction,
        "sample_stage": profile.sample_stage,
        "sample_size": profile.sample_size,
        "center": str(profile.center),
        "q1": str(profile.q1),
        "q3": str(profile.q3),
        "raw_iqr": str(profile.raw_iqr),
        "raw_mad": str(profile.raw_mad),
        "gaussian_scales": {
            name: str(value) for name, value in profile.gaussian_scales.items()
        },
        "robust_cvs": {name: str(value) for name, value in profile.robust_cvs.items()},
        "selected_method": profile.selected_method.value,
        "selected_scale": str(profile.selected_scale),
        "robust_cv": str(profile.robust_cv),
        "zero_scale_methods": list(profile.zero_scale_methods),
        "all_scales_zero": profile.all_scales_zero,
        "partial_scale_degeneracy": profile.partial_scale_degeneracy,
        "cv_min": str(profile.cv_min),
        "cv_max": str(profile.cv_max),
        "cv_span": str(profile.cv_span),
        "cv_median": str(profile.cv_median),
        "cv_relative_span": (
            str(profile.cv_relative_span)
            if profile.cv_relative_span is not None
            else None
        ),
    }


def robust_dispersion_trace(
    *,
    selected_method: RobustScaleMethod,
    pre_clean: RobustDispersionProfile | None,
    post_clean: RobustDispersionProfile | None,
    profile_version: str = ROBUST_DISPERSION_PROFILE_VERSION,
    correction_profile_version: str = ROBUST_SCALE_CORRECTION_PROFILE_VERSION,
    finite_sample_correction: bool = True,
) -> dict[str, object]:
    """Return the versioned immutable-calculation-trace payload."""
    return {
        "profile_version": profile_version,
        "correction_profile_version": correction_profile_version,
        "finite_sample_correction": finite_sample_correction,
        "selected_method": selected_method.value,
        "pre_clean": dispersion_profile_to_dict(pre_clean),
        "post_clean": dispersion_profile_to_dict(post_clean),
        "constants": {
            "mad_normal": str(MAD_NORMAL_CONSTANT),
            "legacy_mad_normal": str(LEGACY_MAD_NORMAL_CONSTANT),
            "iqr_normal_denominator": str(IQR_NORMAL_DENOMINATOR),
            "sn_normal": str(SN_NORMAL_CONSTANT),
            "qn_normal": str(QN_NORMAL_CONSTANT),
        },
    }


def clamp01(value: Decimal) -> Decimal:
    return min(ONE, max(ZERO, value))


def median(values: Iterable[Decimal]) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median requires at least one value")
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / Decimal(2)


def percentile(values: Iterable[Decimal], quantile: Decimal) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if quantile < ZERO or quantile > ONE:
        raise ValueError("quantile must be between zero and one")
    if len(ordered) == 1:
        return ordered[0]
    position = quantile * Decimal(len(ordered) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered) - 1)
    fraction = position - Decimal(lower_index)
    return (
        ordered[lower_index] + (ordered[upper_index] - ordered[lower_index]) * fraction
    )


def mad(values: Iterable[Decimal]) -> Decimal:
    collected = tuple(values)
    center = median(collected)
    return median(abs(value - center) for value in collected)


def iqr_fences(
    values: Iterable[Decimal], *, multiplier: Decimal = Decimal("1.5")
) -> tuple[Decimal, Decimal]:
    collected = tuple(values)
    q1 = percentile(collected, Decimal("0.25"))
    q3 = percentile(collected, Decimal("0.75"))
    spread = q3 - q1
    return q1 - multiplier * spread, q3 + multiplier * spread


def winsorize(
    values: Iterable[Decimal], *, lower: Decimal, upper: Decimal
) -> tuple[Decimal, ...]:
    collected = tuple(values)
    if not collected:
        return ()
    if lower < ZERO or upper > ONE or lower >= upper:
        raise ValueError("winsor quantiles must satisfy 0 <= lower < upper <= 1")
    lower_value = percentile(collected, lower)
    upper_value = percentile(collected, upper)
    return tuple(min(upper_value, max(lower_value, value)) for value in collected)


def effective_sample_size(weights: Iterable[Decimal]) -> Decimal:
    collected = tuple(weight for weight in weights if weight > ZERO)
    if not collected:
        return ZERO
    total = sum(collected, ZERO)
    squared = sum((weight * weight for weight in collected), ZERO)
    if squared == ZERO:
        return ZERO
    return (total * total) / squared


def geometric_mean(
    scores: Mapping[str, Decimal],
    *,
    weights: Mapping[str, Decimal] | None = None,
    epsilon: Decimal = Decimal("0.000001"),
) -> Decimal:
    if not scores:
        return ZERO
    if epsilon <= ZERO:
        raise ValueError("epsilon must be positive")
    selected_weights = weights or {name: ONE for name in scores}
    numerator = 0.0
    denominator = ZERO
    for name, score in scores.items():
        weight = Decimal(str(selected_weights.get(name, ONE)))
        if weight <= ZERO:
            raise ValueError("geometric-mean weights must be positive")
        bounded = max(epsilon, clamp01(score))
        numerator += float(weight) * math.log(float(bounded))
        denominator += weight
    if denominator <= ZERO:
        return ZERO
    return clamp01(Decimal(str(math.exp(numerator / float(denominator)))))


def log_coverage(count: Decimal, reference_count: int) -> Decimal:
    if count <= ZERO or reference_count <= 0:
        return ZERO
    value = math.log1p(float(count)) / math.log1p(reference_count)
    return clamp01(Decimal(str(value)))


def round_down_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= ZERO:
        raise ValueError("price_tick must be positive")
    return (value / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def round_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= ZERO:
        raise ValueError("price_tick must be positive")
    return (value / tick).to_integral_value(rounding=ROUND_HALF_UP) * tick


def round_up_to_tick(value: Decimal, tick: Decimal) -> Decimal:
    if tick <= ZERO:
        raise ValueError("price_tick must be positive")
    return (value / tick).to_integral_value(rounding=ROUND_CEILING) * tick


__all__ = [
    "IQR_NORMAL_DENOMINATOR",
    "LEGACY_MAD_NORMAL_CONSTANT",
    "MAD_NORMAL_CONSTANT",
    "QN_NORMAL_CONSTANT",
    "ROBUST_DISPERSION_PROFILE_VERSION",
    "ROBUST_SCALE_CORRECTION_PROFILE_VERSION",
    "SN_NORMAL_CONSTANT",
    "clamp01",
    "dispersion_profile_to_dict",
    "effective_sample_size",
    "geometric_mean",
    "iqr_fences",
    "log_coverage",
    "mad",
    "median",
    "percentile",
    "qn_scale",
    "robust_dispersion_trace",
    "robust_price_dispersion",
    "round_down_to_tick",
    "round_to_tick",
    "round_up_to_tick",
    "scaled_iqr",
    "scaled_mad",
    "sn_scale",
    "winsorize",
]
