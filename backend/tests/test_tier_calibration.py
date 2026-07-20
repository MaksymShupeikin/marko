from dataclasses import replace
from decimal import Decimal

import pytest

from metis.pricing import (
    CalibrationPair,
    CoefficientModel,
    ProductTier,
    calibration_dataset_hash,
    fit_shrinkage_coefficients,
    fit_simple_coefficients,
)


def pair(
    oe: str,
    category: str,
    tier_price: str,
    reference_price: str = "100",
    tier: ProductTier = ProductTier.OEM,
    quality_weight: str = "1",
) -> CalibrationPair:
    return CalibrationPair(
        oe_norm=oe,
        category=category,
        tier=tier,
        tier_price=Decimal(tier_price),
        reference_price=Decimal(reference_price),
        quality_weight=Decimal(quality_weight),
    )


def test_simple_coefficient_uses_category_level_unique_oe_pairs() -> None:
    pairs = [
        pair("OE-1", "brakes", "200"),
        pair("OE-1", "brakes", "220"),
        pair("OE-2", "brakes", "300"),
        pair("OE-3", "brakes", "400"),
    ]

    coefficient = fit_simple_coefficients(pairs, min_pairs=3)[
        ("brakes", ProductTier.OEM)
    ]

    assert coefficient.model == CoefficientModel.SIMPLE_MEDIAN
    assert coefficient.sample_size == 3
    assert coefficient.multiplier == pytest.approx(Decimal("3"))
    assert coefficient.validated is True


def test_simple_coefficient_is_not_validated_from_one_position() -> None:
    coefficient = fit_simple_coefficients(
        [pair("OE-1", "filters", "250")], min_pairs=3
    )[("filters", ProductTier.OEM)]

    assert coefficient.sample_size == 1
    assert coefficient.validated is False


def test_shrinkage_moves_sparse_category_toward_leave_one_category_out_global() -> None:
    pairs = [pair("RARE", "rare", "400")]
    pairs.extend(pair(f"OE-{index}", "common", "200") for index in range(20))

    coefficient = fit_shrinkage_coefficients(
        pairs,
        shrinkage_k=Decimal("10"),
        min_category_pairs=8,
        min_global_pairs=20,
    )[("rare", ProductTier.OEM)]

    assert coefficient.model == CoefficientModel.SHRINKAGE
    assert coefficient.shrinkage_weight == pytest.approx(Decimal(1) / Decimal(11))
    assert Decimal("2") < coefficient.multiplier < Decimal("2.5")
    assert coefficient.global_log_effect is not None
    assert coefficient.validated is True


def test_shrinkage_does_not_reuse_category_as_its_own_global_prior() -> None:
    coefficient = fit_shrinkage_coefficients(
        [pair(f"OE-{index}", "only-category", "200") for index in range(8)],
        min_category_pairs=8,
    )[("only-category", ProductTier.OEM)]

    assert coefficient.global_log_effect is None
    assert coefficient.shrinkage_weight == Decimal("1")


def test_reference_and_invalid_pairs_do_not_train_coefficients() -> None:
    result = fit_simple_coefficients(
        [
            pair("OE-1", "filters", "100", tier=ProductTier.BUDGET),
            pair("OE-2", "filters", "-1"),
        ]
    )

    assert result == {}


def test_simple_model_uses_median_not_mean() -> None:
    pairs = [
        pair("OE-1", "brakes", "200"),
        pair("OE-2", "brakes", "210"),
        pair("OE-3", "brakes", "10000"),
    ]

    coefficient = fit_simple_coefficients(pairs, min_pairs=3)[
        ("brakes", ProductTier.OEM)
    ]

    assert coefficient.multiplier == pytest.approx(Decimal("2.1"))
    assert coefficient.multiplier < Decimal("10")


def test_duplicate_listings_of_one_oe_collapse_to_one_calibration_unit() -> None:
    pairs = [pair("OE-1", "brakes", str(price)) for price in (200, 220, 240)]
    pairs.extend([pair("OE-2", "brakes", "300"), pair("OE-3", "brakes", "400")])

    coefficient = fit_simple_coefficients(pairs, min_pairs=3)[
        ("brakes", ProductTier.OEM)
    ]

    assert coefficient.sample_size == 3
    assert coefficient.multiplier == pytest.approx(Decimal("3"))


def test_dense_category_remains_close_to_local_effect() -> None:
    pairs = [pair(f"DENSE-{index}", "dense", "400") for index in range(100)]
    pairs.extend(pair(f"GLOBAL-{index}", "global", "200") for index in range(25))

    coefficient = fit_shrinkage_coefficients(
        pairs,
        shrinkage_k=Decimal("10"),
        min_category_pairs=8,
        min_global_pairs=20,
    )[("dense", ProductTier.OEM)]

    assert coefficient.shrinkage_weight == pytest.approx(
        Decimal("100") / Decimal("110")
    )
    assert Decimal("3.7") < coefficient.multiplier < Decimal("4")


def test_global_prior_excludes_target_category() -> None:
    pairs = [pair(f"TARGET-{index}", "target", "1000") for index in range(20)]
    pairs.extend(pair(f"OTHER-{index}", "other", "200") for index in range(20))

    coefficient = fit_shrinkage_coefficients(
        pairs,
        min_category_pairs=8,
        min_global_pairs=20,
    )[("target", ProductTier.OEM)]

    assert coefficient.global_log_effect == pytest.approx(Decimal("0.6931471805599453"))


def test_target_oe_is_excluded_from_its_applied_coefficient() -> None:
    pairs = [pair("TARGET", "brakes", "10000")]
    pairs.extend(pair(f"OE-{index}", "brakes", "200") for index in range(8))

    full = fit_simple_coefficients(pairs, min_pairs=8)[("brakes", ProductTier.OEM)]
    leave_one_out = fit_simple_coefficients(
        pairs, min_pairs=8, exclude_oe_norm="target"
    )[("brakes", ProductTier.OEM)]

    assert full.sample_size == 9
    assert leave_one_out.sample_size == 8
    assert leave_one_out.excluded_oe_norm == "TARGET"
    assert leave_one_out.multiplier == pytest.approx(Decimal("2"))


def test_insufficient_local_and_global_data_is_unvalidated() -> None:
    coefficient = fit_shrinkage_coefficients(
        [pair("ONLY", "rare", "250")],
        min_category_pairs=8,
        min_global_pairs=20,
    )[("rare", ProductTier.OEM)]

    assert coefficient.validated is False
    assert "INSUFFICIENT_LOCAL_AND_GLOBAL_DATA" in coefficient.validation_reasons


def test_dataset_order_does_not_change_hash_or_result() -> None:
    pairs = [
        pair("OE-3", "brakes", "300"),
        pair("OE-1", "brakes", "200"),
        pair("OE-2", "brakes", "250"),
    ]

    forward = fit_simple_coefficients(pairs, min_pairs=3)[("brakes", ProductTier.OEM)]
    reverse = fit_simple_coefficients(reversed(pairs), min_pairs=3)[
        ("brakes", ProductTier.OEM)
    ]

    assert calibration_dataset_hash(pairs) == calibration_dataset_hash(reversed(pairs))
    assert forward.multiplier == reverse.multiplier
    assert forward.coefficient_version == reverse.coefficient_version


def test_dataset_hash_changes_when_verified_identity_evidence_changes() -> None:
    baseline = replace(
        pair("OE-1", "brakes", "200"),
        identity_evidence=(
            {
                "observation_id": "obs-1",
                "comparison_identity_key": "OE-1",
                "verified_matched_oe_norm": "OE-1",
                "oe_verification_status": "VERIFIED_EXACT",
                "comparability_policy_hash": "a" * 64,
                "source_confidence_method_version": "source-confidence-v1",
                "tier_method_version": "brand-tier-v1",
                "price": "200",
                "currency": "UAH",
                "seller_id": "seller-1",
                "observed_at": "2026-07-19T12:00:00+00:00",
            },
        ),
    )
    changed = replace(
        baseline,
        identity_evidence=(
            {**baseline.identity_evidence[0], "observation_id": "obs-2"},
        ),
    )

    assert calibration_dataset_hash([baseline]) != calibration_dataset_hash([changed])


def test_quality_weights_reduce_effective_pair_count() -> None:
    pairs = [pair("OE-1", "brakes", "200", quality_weight="1")]
    pairs.extend(
        pair(f"OE-{index}", "brakes", "200", quality_weight="0.01")
        for index in range(2, 9)
    )

    coefficient = fit_simple_coefficients(
        pairs,
        min_pairs=8,
        min_effective_pairs=Decimal("5"),
    )[("brakes", ProductTier.OEM)]

    assert coefficient.sample_size == 8
    assert coefficient.effective_sample_size < Decimal("2")
    assert coefficient.validated is False
    assert "LOW_EFFECTIVE_PAIR_COUNT" in coefficient.validation_reasons
