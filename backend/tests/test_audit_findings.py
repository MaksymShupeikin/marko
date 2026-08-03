"""Аудит 2026-07-27: доказательства находок (§4 матрица вариаций 1-10).

Файл создан агентом-аудитором согласно CONSTRAINT_6(a).
Тесты НЕ проверяют желаемое поведение — они фиксируют фактическое,
чтобы находка была воспроизводима. Названия начинаются с audit_.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from metis.pricing.candidate_selection import norm_oem, norm_text
from metis.pricing.comparability import normalize_oe
from metis.pricing.statistics import (
    effective_sample_size,
    geometric_mean,
    iqr_fences,
    log_coverage,
    mad,
    median,
    percentile,
    qn_scale,
    robust_price_dispersion,
    sn_scale,
    winsorize,
)
from metis.pricing.tiering import classify_tier, normalize_brand
from metis.pricing.types import ProductTier


# --- §4 вариация 1: n = 0 -------------------------------------------------


def test_audit_var01_empty_sample_raises_not_returns_none() -> None:
    """n=0: median/percentile/mad поднимают ValueError, а не возвращают None."""

    with pytest.raises(ValueError):
        median([])
    with pytest.raises(ValueError):
        percentile([], Decimal("0.5"))
    with pytest.raises(ValueError):
        mad([])
    with pytest.raises(ValueError):
        robust_price_dispersion([])
    # effective_sample_size на пустом входе НЕ падает, а возвращает 0.
    assert effective_sample_size([]) == Decimal("0")
    # geometric_mean на пустом входе НЕ падает, а возвращает 0.
    assert geometric_mean({}) == Decimal("0")


# --- §4 вариация 2: n = 1 -------------------------------------------------


def test_audit_var02_single_point() -> None:
    one = [Decimal("100")]
    assert median(one) == Decimal("100")
    assert percentile(one, Decimal("0.25")) == Decimal("100")
    assert mad(one) == Decimal("0")
    assert sn_scale(one) == Decimal("0")
    assert qn_scale(one) == Decimal("0")
    profile = robust_price_dispersion(one)
    assert profile.sample_size == 1
    assert profile.all_scales_zero is True
    assert profile.robust_cv == Decimal("0")
    # cv_relative_span при полном вырождении = 0 (не None).
    assert profile.cv_relative_span == Decimal("0")


# --- §4 вариация 3: n = 2, чётная медиана ---------------------------------


def test_audit_var03_two_points_even_median() -> None:
    two = [Decimal("100"), Decimal("201")]
    assert median(two) == Decimal("150.5")
    assert percentile(two, Decimal("0.5")) == Decimal("150.5")
    profile = robust_price_dispersion(two)
    assert profile.sample_size == 2
    # ни одна шкала не равна нулю при двух различных значениях
    assert profile.all_scales_zero is False


# --- §4 вариация 4: n = 3 -------------------------------------------------


def test_audit_var04_three_points() -> None:
    three = [Decimal("90"), Decimal("100"), Decimal("110")]
    assert median(three) == Decimal("100")
    profile = robust_price_dispersion(three)
    assert profile.sample_size == 3
    assert profile.center == Decimal("100")


# --- §4 вариация 5: все значения равны, CV = 0/0 --------------------------


def test_audit_var05_zero_dispersion() -> None:
    same = [Decimal("100")] * 5
    profile = robust_price_dispersion(same)
    assert profile.all_scales_zero is True
    assert profile.partial_scale_degeneracy is False
    assert profile.robust_cv == Decimal("0")
    assert profile.cv_relative_span == Decimal("0")


def test_audit_var05b_outlier_is_invisible_to_every_robust_scale() -> None:
    """ФАКТ: 7 одинаковых цен + выброс x10 дают robust_cv = 0.

    Все четыре шкалы (IQR, MAD, Sn, Qn) равны нулю, поэтому профиль
    рапортует «нулевой разброс», хотя 1/8 выборки отличается в 10 раз.
    """

    values = [Decimal("100")] * 7 + [Decimal("1000")]
    profile = robust_price_dispersion(values)
    assert profile.sample_size == 8
    assert profile.all_scales_zero is True
    assert profile.robust_cv == Decimal("0")
    assert sorted(profile.zero_scale_methods) == ["iqr", "mad", "qn", "sn"]


def test_audit_var05c_partial_degeneracy_yields_none_relative_span() -> None:
    """Частичное вырождение шкал => cv_relative_span = None (не 0)."""

    values = [Decimal("100")] * 5 + [Decimal("101"), Decimal("102"), Decimal("103")]
    profile = robust_price_dispersion(values)
    assert sorted(profile.zero_scale_methods) == ["mad", "qn", "sn"]
    assert profile.all_scales_zero is False
    assert profile.partial_scale_degeneracy is True
    assert profile.cv_relative_span is None


# --- §4 вариация 6: значение ровно на пороге ------------------------------


def test_audit_var06_iqr_fence_boundary_is_inclusive_nowhere() -> None:
    """iqr_fences возвращает границы; строгость сравнения задаёт вызывающий."""

    values = [Decimal(str(v)) for v in (10, 20, 30, 40, 50)]
    low, high = iqr_fences(values)
    assert low == Decimal("-10.0")
    assert high == Decimal("70.0")


def test_audit_var06b_winsorize_boundaries() -> None:
    values = [Decimal(str(v)) for v in (1, 2, 3, 4, 100)]
    result = winsorize(values, lower=Decimal("0.1"), upper=Decimal("0.9"))
    assert result == (
        Decimal("1.4"),
        Decimal("2"),
        Decimal("3"),
        Decimal("4"),
        Decimal("61.6"),
    )
    with pytest.raises(ValueError):
        winsorize(values, lower=Decimal("0.5"), upper=Decimal("0.5"))


# --- §4 вариация 7: отрицательная и нулевая цена --------------------------


def test_audit_var07_non_positive_prices_rejected() -> None:
    with pytest.raises(ValueError):
        robust_price_dispersion([Decimal("0"), Decimal("10")])
    with pytest.raises(ValueError):
        robust_price_dispersion([Decimal("-1"), Decimal("10")])
    # median/percentile отрицательные значения принимают молча
    assert median([Decimal("-5"), Decimal("5")]) == Decimal("0")


# --- §4 вариация 8: None / пустая строка в идентификаторе -----------------


def test_audit_var08_identifier_none_and_empty() -> None:
    assert norm_oem(None) == ""
    assert norm_oem("") == ""
    assert norm_oem("   ") == ""
    assert normalize_oe(None) is None
    # normalize_oe отбрасывает короткие идентификаторы, norm_oem — нет
    assert normalize_oe("AB") is None
    assert norm_oem("AB") == "AB"
    assert normalize_brand(None) == ""
    assert norm_text(None) == " "


# --- §4 вариация 9: ведущие нули ------------------------------------------


def test_audit_var09_leading_zeros_are_not_stripped() -> None:
    """ФАКТ: ведущие нули сохраняются, '0986424815' != '986424815'."""

    assert norm_oem("0986424815") == "0986424815"
    assert norm_oem("986424815") == "986424815"
    assert norm_oem("0986424815") != norm_oem("986424815")
    assert normalize_oe("0986424815") == "0986424815"
    assert normalize_oe("00A0001") == "00A0001"


# --- §4 вариация 10: кириллица, латиница, гомоглифы -----------------------


def test_audit_var10_oe_normalizers_converge_on_cyrillic_homoglyphs() -> None:
    """Исправлено: все OE-пути сворачивают безопасные омоглифы одинаково."""

    cyrillic_oe = "АВС123"  # АВС123 кириллицей
    assert norm_oem(cyrillic_oe) == "ABC123"
    assert normalize_oe(cyrillic_oe) == "ABC123"


def test_audit_var10b_homoglyph_brand_abstains() -> None:
    """Mixed-script unknown brands fail closed instead of becoming noise."""

    # 'ВОSСН': В,О,С,Н — кириллица, S — латиница
    homoglyph = "ВОSСН"
    assert normalize_brand(homoglyph) == ""
    assert normalize_brand("BOSCH") == "BOSCH"
    assert normalize_brand(homoglyph) != normalize_brand("BOSCH")


def test_audit_var10c_kemp_text_marker_conflicts_with_brand_rule() -> None:
    """A text marker cannot override an explicit conflicting brand rule."""

    rules = {"BOSCH": ProductTier.OES}
    result = classify_tier(
        brand="BOSCH",
        title="Brake pad set",
        description="Analogue of KEMP part number 123",
        brand_tiers=rules,
    )
    assert result.tier is ProductTier.UNKNOWN
    assert result.is_kemp is False
    assert result.confidence == Decimal("0.20")
    assert result.exclusion_reason == "TIER_CONFLICT"
    assert result.reasons == ("KEMP_TEXT_BRAND_CONFLICT",)


# --- Детерминизм / float в scoring ----------------------------------------


def test_confidence_transcendentals_follow_versioned_precision_profile() -> None:
    """Approximate confidence math is rounded by an explicit replay contract."""

    value = geometric_mean(
        {"a": Decimal("0.7"), "b": Decimal("0.3"), "c": Decimal("0.9")}
    )
    coverage = log_coverage(Decimal("5"), 12)

    assert value == Decimal("0.573879354831")
    assert coverage == Decimal("0.698555495460")
    assert value.as_tuple().exponent == -12
    assert coverage.as_tuple().exponent == -12


def test_audit_domain_functions_are_deterministic_across_repeats() -> None:
    sample = [Decimal(str(v)) for v in (101, 99, 250, 100, 98, 102, 97, 400)]
    first = robust_price_dispersion(sample)
    second = robust_price_dispersion(list(reversed(sample)))
    assert first.selected_scale == second.selected_scale
    assert first.robust_cv == second.robust_cv
