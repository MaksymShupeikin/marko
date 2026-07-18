"""Metis independent-OE robust and hierarchical tier calibration."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
from typing import Iterable

from .statistics import clamp01, effective_sample_size, median, percentile
from .types import CalibrationPair, CoefficientModel, ProductTier, TierCoefficient


ZERO = Decimal("0")
ONE = Decimal("1")
_REFERENCE_TIERS = frozenset({ProductTier.BUDGET, ProductTier.KEMP})


@dataclass(frozen=True, slots=True)
class _CalibrationPoint:
    oe_norm: str
    log_ratio: Decimal
    weight: Decimal


def calibration_dataset_hash(
    pairs: Iterable[CalibrationPair], *, exclude_oe_norm: str | None = None
) -> str:
    """Hash the independent paired-OE dataset, not raw listing order."""
    grouped = _deduplicated_points(pairs, exclude_oe_norm=exclude_oe_norm)
    canonical = [
        {
            "category": category,
            "tier": tier.value,
            "oe_norm": point.oe_norm,
            "log_ratio": _decimal_text(point.log_ratio),
            "quality_weight": _decimal_text(point.weight),
        }
        for (category, tier), points in sorted(
            grouped.items(), key=lambda item: (item[0][0], item[0][1].value)
        )
        for point in sorted(points, key=lambda value: value.oe_norm)
    ]
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def fit_simple_coefficients(
    pairs: Iterable[CalibrationPair],
    *,
    min_pairs: int = 8,
    min_effective_pairs: Decimal | None = None,
    max_interval_ratio: Decimal = Decimal("3"),
    method_version: str = "tier-simple-v2",
    exclude_oe_norm: str | None = None,
) -> dict[tuple[str, ProductTier], TierCoefficient]:
    pair_list = tuple(pairs)
    effective_floor = min_effective_pairs or Decimal(min_pairs)
    grouped = _deduplicated_points(pair_list, exclude_oe_norm=exclude_oe_norm)
    dataset_hash = calibration_dataset_hash(pair_list, exclude_oe_norm=exclude_oe_norm)
    version = f"{method_version}:{dataset_hash[:12]}"
    result: dict[tuple[str, ProductTier], TierCoefficient] = {}
    for key, points in grouped.items():
        local_log = median(point.log_ratio for point in points)
        multiplier = _exp_decimal(local_log)
        n_effective = effective_sample_size(point.weight for point in points)
        low, high, confidence = _interval_and_confidence(
            points,
            center=local_log,
            minimum_support=Decimal(min_pairs),
        )
        reasons = _validation_reasons(
            sample_size=len(points),
            effective_size=n_effective,
            multiplier=multiplier,
            low=low,
            high=high,
            min_pairs=min_pairs,
            min_effective_pairs=effective_floor,
            max_interval_ratio=max_interval_ratio,
        )
        result[key] = TierCoefficient(
            category=key[0],
            tier=key[1],
            multiplier=multiplier,
            model=CoefficientModel.SIMPLE_MEDIAN,
            method_version=method_version,
            coefficient_version=version,
            sample_size=len(points),
            effective_sample_size=n_effective,
            confidence=confidence,
            validated=not reasons,
            log_effect=local_log,
            interval_low=low,
            interval_high=high,
            dataset_hash=dataset_hash,
            validation_reasons=tuple(reasons),
            excluded_oe_norm=_normalized_oe(exclude_oe_norm),
        )
    return result


def fit_shrinkage_coefficients(
    pairs: Iterable[CalibrationPair],
    *,
    shrinkage_k: Decimal = Decimal("10"),
    min_category_pairs: int = 8,
    min_global_pairs: int = 20,
    min_effective_pairs: Decimal | None = None,
    max_interval_ratio: Decimal = Decimal("3"),
    allow_global_fallback: bool = True,
    method_version: str = "tier-shrinkage-v2",
    exclude_oe_norm: str | None = None,
) -> dict[tuple[str, ProductTier], TierCoefficient]:
    if shrinkage_k <= ZERO:
        raise ValueError("shrinkage_k must be positive")
    pair_list = tuple(pairs)
    effective_floor = min_effective_pairs or Decimal(min_category_pairs)
    grouped = _deduplicated_points(pair_list, exclude_oe_norm=exclude_oe_norm)
    dataset_hash = calibration_dataset_hash(pair_list, exclude_oe_norm=exclude_oe_norm)
    version = f"{method_version}:{dataset_hash[:12]}"
    result: dict[tuple[str, ProductTier], TierCoefficient] = {}

    for (category, tier), points in grouped.items():
        local_log = median(point.log_ratio for point in points)
        local_effective = effective_sample_size(point.weight for point in points)
        global_points = [
            point
            for (other_category, other_tier), values in grouped.items()
            if other_tier == tier and other_category != category
            for point in values
        ]
        global_log = (
            median(point.log_ratio for point in global_points)
            if global_points
            else None
        )
        global_effective = effective_sample_size(
            point.weight for point in global_points
        )
        local_sufficient = (
            len(points) >= min_category_pairs and local_effective >= effective_floor
        )
        global_sufficient = (
            len(global_points) >= min_global_pairs
            and global_effective >= effective_floor
        )

        branch_reasons: list[str] = []
        if local_sufficient and global_sufficient and global_log is not None:
            weight = local_effective / (local_effective + shrinkage_k)
            log_effect = weight * local_log + (ONE - weight) * global_log
            interval_points = points
            minimum_support = Decimal(min_category_pairs)
        elif local_sufficient:
            weight = ONE
            log_effect = local_log
            interval_points = points
            minimum_support = Decimal(min_category_pairs)
            branch_reasons.append("GLOBAL_PRIOR_UNAVAILABLE")
        elif global_sufficient and global_log is not None and allow_global_fallback:
            weight = local_effective / (local_effective + shrinkage_k)
            log_effect = weight * local_log + (ONE - weight) * global_log
            interval_points = global_points
            minimum_support = Decimal(min_global_pairs)
            branch_reasons.append("CATEGORY_SPARSE_GLOBAL_FALLBACK")
        else:
            weight = (
                ONE
                if global_log is None
                else local_effective / (local_effective + shrinkage_k)
            )
            log_effect = (
                local_log
                if global_log is None
                else weight * local_log + (ONE - weight) * global_log
            )
            interval_points = points
            minimum_support = Decimal(min_category_pairs)
            branch_reasons.append("INSUFFICIENT_LOCAL_AND_GLOBAL_DATA")

        multiplier = _exp_decimal(log_effect)
        low, high, confidence = _interval_and_confidence(
            interval_points,
            center=log_effect,
            minimum_support=minimum_support,
        )
        validation_reasons = _validation_reasons(
            sample_size=len(points),
            effective_size=local_effective,
            multiplier=multiplier,
            low=low,
            high=high,
            min_pairs=min_category_pairs,
            min_effective_pairs=effective_floor,
            max_interval_ratio=max_interval_ratio,
            support_override=local_sufficient
            or (global_sufficient and allow_global_fallback),
        )
        if "INSUFFICIENT_LOCAL_AND_GLOBAL_DATA" in branch_reasons:
            validation_reasons.append("INSUFFICIENT_LOCAL_AND_GLOBAL_DATA")
            confidence = min(confidence, Decimal("0.39"))
        elif "CATEGORY_SPARSE_GLOBAL_FALLBACK" in branch_reasons:
            confidence = min(confidence, Decimal("0.69"))
        elif "GLOBAL_PRIOR_UNAVAILABLE" in branch_reasons:
            confidence = min(confidence, Decimal("0.79"))

        result[(category, tier)] = TierCoefficient(
            category=category,
            tier=tier,
            multiplier=multiplier,
            model=CoefficientModel.SHRINKAGE,
            method_version=method_version,
            coefficient_version=version,
            sample_size=len(points),
            effective_sample_size=local_effective,
            confidence=confidence,
            validated=not validation_reasons,
            log_effect=log_effect,
            global_log_effect=global_log,
            shrinkage_weight=weight,
            interval_low=low,
            interval_high=high,
            dataset_hash=dataset_hash,
            validation_reasons=tuple(
                dict.fromkeys(branch_reasons + validation_reasons)
            ),
            excluded_oe_norm=_normalized_oe(exclude_oe_norm),
        )
    return result


def _deduplicated_points(
    pairs: Iterable[CalibrationPair], *, exclude_oe_norm: str | None = None
) -> dict[tuple[str, ProductTier], list[_CalibrationPoint]]:
    excluded_oe = _normalized_oe(exclude_oe_norm)
    per_oe: dict[tuple[str, ProductTier, str], list[tuple[Decimal, Decimal]]] = (
        defaultdict(list)
    )
    for pair in pairs:
        category = pair.category.strip()
        oe_norm = _normalized_oe(pair.oe_norm)
        if (
            not category
            or not oe_norm
            or oe_norm == excluded_oe
            or pair.tier in _REFERENCE_TIERS
            or pair.tier in {ProductTier.USED, ProductTier.UNKNOWN}
            or pair.tier_price <= ZERO
            or pair.reference_price <= ZERO
            or pair.quality_weight <= ZERO
        ):
            continue
        log_ratio = Decimal(
            str(math.log(float(pair.tier_price / pair.reference_price)))
        )
        per_oe[(category, pair.tier, oe_norm)].append(
            (log_ratio, min(ONE, pair.quality_weight))
        )

    grouped: dict[tuple[str, ProductTier], list[_CalibrationPoint]] = defaultdict(list)
    for (category, tier, oe_norm), values in per_oe.items():
        grouped[(category, tier)].append(
            _CalibrationPoint(
                oe_norm=oe_norm,
                log_ratio=median(value for value, _ in values),
                weight=median(weight for _, weight in values),
            )
        )
    return dict(grouped)


def _validation_reasons(
    *,
    sample_size: int,
    effective_size: Decimal,
    multiplier: Decimal,
    low: Decimal | None,
    high: Decimal | None,
    min_pairs: int,
    min_effective_pairs: Decimal,
    max_interval_ratio: Decimal,
    support_override: bool | None = None,
) -> list[str]:
    reasons: list[str] = []
    support_valid = (
        sample_size >= min_pairs and effective_size >= min_effective_pairs
        if support_override is None
        else support_override
    )
    if not support_valid:
        if sample_size < min_pairs:
            reasons.append("TOO_FEW_CATEGORY_PAIRS")
        if effective_size < min_effective_pairs:
            reasons.append("LOW_EFFECTIVE_PAIR_COUNT")
    if multiplier <= ZERO or not multiplier.is_finite():
        reasons.append("INVALID_MULTIPLIER")
    if low is None or high is None or low <= ZERO or high < low:
        reasons.append("MISSING_UNCERTAINTY_INTERVAL")
    elif high / low > max_interval_ratio:
        reasons.append("WIDE_UNCERTAINTY_INTERVAL")
    return reasons


def _interval_and_confidence(
    points: list[_CalibrationPoint],
    *,
    center: Decimal,
    minimum_support: Decimal,
) -> tuple[Decimal | None, Decimal | None, Decimal]:
    if not points:
        return None, None, ZERO
    deviations = [abs(point.log_ratio - center) for point in points]
    robust_sigma = Decimal("1.4826") * median(deviations)
    if len(points) >= 4:
        q1 = percentile([point.log_ratio for point in points], Decimal("0.25"))
        q3 = percentile([point.log_ratio for point in points], Decimal("0.75"))
        robust_sigma = max(robust_sigma, (q3 - q1) / Decimal("1.349"))
    n_effective = effective_sample_size(point.weight for point in points)
    standard_error = robust_sigma / Decimal(
        str(math.sqrt(max(1.0, float(n_effective))))
    )
    low = _exp_decimal(center - Decimal("1.96") * standard_error)
    high = _exp_decimal(center + Decimal("1.96") * standard_error)
    support = clamp01(n_effective / max(ONE, minimum_support))
    stability = ONE / (ONE + standard_error)
    quality = sum((point.weight for point in points), ZERO) / Decimal(len(points))
    return low, high, clamp01(min(support, stability, quality))


def _normalized_oe(value: str | None) -> str | None:
    normalized = (value or "").strip().upper()
    return normalized or None


def _exp_decimal(value: Decimal) -> Decimal:
    return Decimal(str(math.exp(float(value))))


def _decimal_text(value: Decimal) -> str:
    if value == ZERO:
        return "0"
    return format(value.normalize(), "f")


__all__ = [
    "calibration_dataset_hash",
    "fit_shrinkage_coefficients",
    "fit_simple_coefficients",
]
