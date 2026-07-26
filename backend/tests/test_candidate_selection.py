from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from metis.pricing.candidate_selection import (
    CandidateItem,
    CandidateSelectionConfigError,
    CandidateStatus,
    ReferenceItem,
    build_category_domain_context,
    check_candidate,
    load_candidate_selection_config,
    norm_oem,
    norm_text,
    verdict_histogram,
)
from metis.pricing.types import ProductTier


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_candidate_selection_config(BACKEND_ROOT / "config" / "comparability.yaml")
APPROVED_POLCAR = {
    "POLCAR": ProductTier.AFTERMARKET_B,
    "KEMP": ProductTier.KEMP,
}


def _reference(**overrides) -> ReferenceItem:
    values = {
        "oem": "7E5 827 505 A",
        "title": "VW Transporter T5 T6 замок задней крышки",
        "price": Decimal("1800"),
        "brand": "KEMP",
        "category": "body_lock",
        "tier": ProductTier.KEMP,
    }
    values.update(overrides)
    return ReferenceItem(**values)


def _candidate(**overrides) -> CandidateItem:
    values = {
        "seller_id": "3823617",
        "seller_name": "АвтоМаркет",
        "title": ("7E5827505A Замок кришки багажника Фольксваген Транспортер T5 T6"),
        "description": None,
        "article_field": "9568ZC-5F",
        "brand": "Polcar",
        "price": Decimal("400"),
        "condition": None,
    }
    values.update(overrides)
    return CandidateItem(**values)


def test_normalizers_preserve_words_and_canonicalize_oem() -> None:
    assert norm_text("Б/У буфер") == " б у буфер "
    assert norm_oem("7E5 827-505 A") == "7E5827505A"


def test_norm_text_replaces_each_supported_ukrainian_character_position() -> None:
    assert norm_text("Ёжик під'їжджає, Єнот") == " ежик пид ижджае енот "


def test_owned_seller_stops_at_first_gate() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(seller_id="2847093"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == "OWN_SELLER"
    assert verdict.passed_gates == ()


@pytest.mark.parametrize(
    ("seller_name", "expected"),
    [
        ('интернет магазин "Avtorazborka24"', "DISMANTLER_SELLER"),
        ("Razborka.club", "DISMANTLER_SELLER"),
        ("Авторозбірка Мікроавтобусів", "DISMANTLER_SELLER"),
    ],
)
def test_dismantler_seller_is_detected_before_condition(
    seller_name: str,
    expected: str,
) -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(seller_name=seller_name),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == expected
    assert verdict.passed_gates == ("own_seller",)


def test_used_marker_does_not_match_inside_buffer_word() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(
            title="7E5827505A буфер замка VW Transporter T5",
            brand="Polcar",
        ),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE


def test_used_and_new_conflict_goes_to_review() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(title="Новий замок 7E5827505A, знято з нової машини"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REVIEW
    assert verdict.reason == "CONDITION_CONFLICT"
    assert verdict.details["stopped_gate"] == "condition"


def test_used_and_remanufactured_are_distinct_early_exit_reasons() -> None:
    used = check_candidate(
        _reference(),
        _candidate(title="Б/У замок 7E5827505A VW Transporter T5"),
        CONFIG,
    )
    reman = check_candidate(
        _reference(),
        _candidate(title="Відновлений замок 7E5827505A VW Transporter T5"),
        CONFIG,
    )

    assert (used.status, used.reason) == (CandidateStatus.SKIP, "USED")
    assert (reman.status, reman.reason) == (
        CandidateStatus.SKIP,
        "REMANUFACTURED",
    )


@pytest.mark.parametrize(
    ("article", "title", "description", "crosses", "evidence"),
    [
        ("7E5 827 505 A", "Замок", None, frozenset(), "ARTICLE_FIELD"),
        ("OTHER", "Замок 7E5827505A", None, frozenset(), "TITLE"),
        ("OTHER", "Замок", "OE: 7E5 827 505 A", frozenset(), "DESCRIPTION"),
        ("9568ZC-5F", "Замок", None, frozenset({"9568ZC5F"}), "CROSS_TABLE"),
    ],
)
def test_oem_evidence_precedence(
    article: str,
    title: str,
    description: str | None,
    crosses: frozenset[str],
    evidence: str,
) -> None:
    verdict = check_candidate(
        _reference(title="Замок"),
        _candidate(
            article_field=article,
            title=title,
            description=description,
        ),
        CONFIG,
        confirmed_cross_oems=crosses,
    )

    assert verdict.details["gates"]["oem_identity"]["evidence"] == evidence


def test_missing_oem_stops_before_variant_and_tier() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(
            title="Замок кришки багажника VW Transporter T5",
            article_field="9568ZC-5F",
        ),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == "OEM_NOT_FOUND"
    assert "variant" not in verdict.passed_gates


def test_oem_stuffing_is_a_flag_not_a_skip() -> None:
    verdict = check_candidate(
        _reference(title="Замок"),
        _candidate(
            article_field="OTHER",
            title=("7E5827505A 7E5827505B 31827011 16SKV510 замок VW Transporter T5"),
        ),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE
    assert "OEM_STUFFED" in verdict.flags
    assert verdict.details["gates"]["oem_stuffing"]["token_count"] == (
        CONFIG.max_oem_in_title + 1
    )


def test_explicit_side_mismatch_is_skipped() -> None:
    verdict = check_candidate(
        _reference(title="Амортизатор задний правый Toyota Camry V40"),
        _candidate(title="Амортизатор задний левый Toyota Camry V40 7E5827505A"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == "VARIANT_MISMATCH:side"


def test_matching_explicit_side_is_not_skipped() -> None:
    verdict = check_candidate(
        _reference(title="Амортизатор задний правый Toyota Camry V40"),
        _candidate(title=("Амортизатор задний правый Toyota Camry V40 7E5827505A")),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE
    assert verdict.reason == "OK"


def test_one_sided_variant_knowledge_remains_fail_closed_without_skip() -> None:
    verdict = check_candidate(
        _reference(title="Амортизатор задний правый Toyota Camry V40"),
        _candidate(title="Амортизатор задний Toyota Camry V40 7E5827505A"),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE
    assert verdict.reason == "OK"


def test_all_ambiguous_variant_axes_are_preserved_as_flags() -> None:
    verdict = check_candidate(
        _reference(
            title=("Амортизатор левый правый передний задний VW Transporter T5")
        ),
        _candidate(
            title=(
                "7E5827505A амортизатор левый правый передний задний VW Transporter T5"
            )
        ),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE
    assert "VARIANT_AMBIGUOUS:side" in verdict.flags
    assert "VARIANT_AMBIGUOUS:axle" in verdict.flags


def test_pack_mismatch_is_skipped() -> None:
    verdict = check_candidate(
        _reference(title="Комплект 2 шт замков VW Transporter T5"),
        _candidate(title="Замок VW Transporter T5 7E5827505A"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == "PACK_MISMATCH"


def test_same_platform_is_retained_with_soft_flag() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(
            title="7E5827505A Замок Volkswagen Multivan T5 T6",
        ),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE
    assert "SAME_PLATFORM" in verdict.flags


def test_different_vehicle_brand_is_skipped() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(title="7E5827505A Замок Toyota Camry V40"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == "BRAND_MISMATCH"


def test_unknown_applicability_is_a_soft_flag() -> None:
    verdict = check_candidate(
        _reference(title="Замок 7E5827505A"),
        _candidate(title="Замок 7E5827505A"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REVIEW
    assert verdict.reason == "TIER_UNKNOWN"
    assert "APPLICABILITY_UNKNOWN" in verdict.flags


def test_missing_reference_generation_does_not_create_false_mismatch() -> None:
    verdict = check_candidate(
        _reference(title="Замок VW Transporter"),
        _candidate(title="Замок VW Transporter T6 7E5827505A"),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE
    assert "APPLICABILITY_UNKNOWN" in verdict.flags


def test_unknown_tier_is_review_after_all_identity_gates() -> None:
    verdict = check_candidate(_reference(), _candidate(), CONFIG)

    assert verdict.status is CandidateStatus.REVIEW
    assert verdict.reason == "TIER_UNKNOWN"
    assert verdict.details["stopped_gate"] == "tier"
    assert verdict.passed_gates[-1] == "applicability"


def test_price_anomaly_is_a_flag_and_never_a_skip() -> None:
    verdict = check_candidate(
        _reference(price=Decimal("1800")),
        _candidate(price=Decimal("400")),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE
    assert verdict.reason == "OK"
    assert "PRICE_ANOMALY" in verdict.flags
    assert verdict.passed_gates[-1] == "price_anomaly"


@pytest.mark.parametrize("candidate_price", [Decimal("35"), Decimal("300")])
def test_price_anomaly_boundaries_are_inclusive(candidate_price: Decimal) -> None:
    verdict = check_candidate(
        _reference(price=Decimal("100")),
        _candidate(price=candidate_price),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
    )

    assert verdict.status is CandidateStatus.COMPARABLE
    assert "PRICE_ANOMALY" not in verdict.flags


def test_empty_reference_and_candidate_oem_fields_fail_closed() -> None:
    verdict = check_candidate(
        _reference(oem=None, title="Замок VW Transporter T5"),
        _candidate(
            title="Замок VW Transporter T5",
            article_field=None,
        ),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == "OEM_NOT_FOUND"


def test_mixed_script_brand_does_not_gain_an_unverified_tier() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(brand="КEМP"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REVIEW
    assert verdict.reason == "TIER_UNKNOWN"


def test_histogram_preserves_review_semantics() -> None:
    verdicts = [
        check_candidate(_reference(), _candidate(), CONFIG),
        check_candidate(
            _reference(),
            _candidate(seller_name="Avtorazborka24"),
            CONFIG,
        ),
    ]

    assert verdict_histogram(verdicts) == {
        "DISMANTLER_SELLER": 1,
        "TIER_UNKNOWN (REVIEW)": 1,
    }


def test_config_loader_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(CandidateSelectionConfigError):
        load_candidate_selection_config(tmp_path / "missing.yaml")


# --- Ворота категорийного домена: матрица вариаций ---------------------------
#
# Пути ниже взяты из захваченной выдачи Prom (2026-07-26, N=137 карточек),
# а не придуманы: [0, 13, 1808, 180803] — бассейновая накладка Emaux,
# [0, 55, 5502, 341529, 341550] — замок багажника VW.

POOL_PATH = (0, 13, 1808, 180803)
AUTOPART_PATH = (0, 55, 5502, 341529, 341550)


def _domain_config(**overrides):
    policy = replace(CONFIG.category_domain, **overrides)
    return replace(CONFIG, category_domain=policy)


def test_category_gate_skips_proven_non_automotive_domain() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(category_id=180803, category_path=POOL_PATH),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == "CATEGORY_NOT_AUTOPARTS"
    details = verdict.details["gates"]["category_domain"]
    assert details["mode"] == "BLOCKLIST"
    assert details["matched_ancestor"] == [0, 13, 1808]


def test_category_gate_passes_automotive_domain() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(category_id=341550, category_path=AUTOPART_PATH),
        CONFIG,
    )

    assert verdict.reason != "CATEGORY_NOT_AUTOPARTS"
    assert "category_domain" in verdict.passed_gates


def test_category_gate_fails_open_without_category_data() -> None:
    """Вариация 1: отсутствие данных не наказывается."""

    verdict = check_candidate(_reference(), _candidate(), CONFIG)

    assert verdict.reason != "CATEGORY_NOT_AUTOPARTS"
    assert "CATEGORY_UNKNOWN" in verdict.flags


def test_category_ancestor_match_is_integerwise_not_textual() -> None:
    """Предок 20 не должен поглощать несвязанную категорию 208.

    Строковое сравнение путей дало бы ложный SKIP настоящей автозапчасти
    NTY KOREK OLEJU, наблюдавшейся по пути [0, 18, 208, 20808].
    """

    verdict = check_candidate(
        _reference(),
        _candidate(category_id=20808, category_path=(0, 18, 208, 20808)),
        CONFIG,
    )

    assert verdict.reason != "CATEGORY_NOT_AUTOPARTS"


def test_category_gate_disabled_is_inert() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(category_id=180803, category_path=POOL_PATH),
        _domain_config(enabled=False),
    )

    assert verdict.reason != "CATEGORY_NOT_AUTOPARTS"
    assert verdict.details["gates"]["category_domain"]["mode"] == "DISABLED"


def test_category_gate_runs_after_cheaper_seller_gates() -> None:
    """Вариация 10: порядок цепочки не нарушен новыми воротами."""

    verdict = check_candidate(
        _reference(),
        _candidate(
            seller_name="Avtorazborka24",
            category_id=180803,
            category_path=POOL_PATH,
        ),
        CONFIG,
    )

    assert verdict.reason == "DISMANTLER_SELLER"
    assert "category_domain" not in verdict.passed_gates


def test_majority_vote_stays_inert_below_minimum_sample() -> None:
    """Вариация 3: N < N_min — голосование не проводится."""

    config = _domain_config(majority_vote_enabled=True, blocked_ancestors=())
    context = build_category_domain_context([AUTOPART_PATH] * 4, config.category_domain)

    assert context.mode_prefix is None
    verdict = check_candidate(
        _reference(),
        _candidate(category_id=180803, category_path=POOL_PATH),
        config,
        category_context=context,
    )
    assert verdict.reason != "CATEGORY_OUTLIER_MAJORITY_VOTE"


def test_majority_vote_requires_a_conclusive_share() -> None:
    """Вариация 2: доля строго ниже порога делает ворота no-op."""

    config = _domain_config(majority_vote_enabled=True, blocked_ancestors=())
    scattered = [AUTOPART_PATH] * 3 + [POOL_PATH] * 3
    context = build_category_domain_context(scattered, config.category_domain)

    assert context.mode_prefix is None
    assert context.majority_share == Decimal("0.500000")


def test_majority_vote_boundary_share_is_inclusive() -> None:
    """Вариация 2: доля ровно на пороге считается достаточной."""

    config = _domain_config(majority_vote_enabled=True, blocked_ancestors=())
    paths = [AUTOPART_PATH] * 6 + [POOL_PATH] * 4
    context = build_category_domain_context(paths, config.category_domain)

    assert context.majority_share == Decimal("0.600000")
    assert context.mode_prefix == (0, 55, 5502)

    verdict = check_candidate(
        _reference(),
        _candidate(category_id=180803, category_path=POOL_PATH),
        config,
        category_context=context,
    )
    assert verdict.status is CandidateStatus.SKIP
    assert verdict.reason == "CATEGORY_OUTLIER_MAJORITY_VOTE"


def test_majority_vote_ignores_candidates_without_category_data() -> None:
    config = _domain_config(majority_vote_enabled=True, blocked_ancestors=())
    context = build_category_domain_context(
        [AUTOPART_PATH] * 5 + [()] * 20, config.category_domain
    )

    assert context.candidate_count == 5
    assert context.mode_prefix == (0, 55, 5502)


def test_enforced_allowlist_rejects_everything_outside_the_list() -> None:
    config = _domain_config(
        blocked_ancestors=(),
        allowed_ancestors=((0, 55, 5502),),
        allowlist_enforced=True,
    )

    allowed = check_candidate(
        _reference(),
        _candidate(category_id=341550, category_path=AUTOPART_PATH),
        config,
    )
    rejected = check_candidate(
        _reference(),
        _candidate(category_id=20808, category_path=(0, 18, 208, 20808)),
        config,
    )

    assert allowed.reason != "CATEGORY_NOT_AUTOPARTS"
    assert rejected.status is CandidateStatus.SKIP
    assert rejected.reason == "CATEGORY_NOT_AUTOPARTS"


def test_shipped_policy_keeps_allowlist_disabled() -> None:
    """Строгий allowlist остаётся выключенным до утверждения владельцем."""

    assert CONFIG.category_domain.enabled is True
    assert CONFIG.category_domain.allowlist_enforced is False
    assert CONFIG.category_domain.majority_vote_enabled is False
    assert CONFIG.category_domain.blocked_ancestors


def test_config_rejects_ancestor_listed_as_both_blocked_and_allowed(
    tmp_path: Path,
) -> None:
    source = Path(CONFIG.source_path).read_text(encoding="utf-8")
    broken = source.replace(
        "  allowed_ancestors: []",
        '  allowed_ancestors:\n    - path: [0, 13, 1808]\n      label: "Конфликт"',
    )
    target = tmp_path / "comparability.yaml"
    target.write_text(broken, encoding="utf-8")

    with pytest.raises(CandidateSelectionConfigError):
        load_candidate_selection_config(target)


def test_config_rejects_unlabelled_ancestor(tmp_path: Path) -> None:
    source = Path(CONFIG.source_path).read_text(encoding="utf-8")
    broken = source.replace(
        '    - path: [0, 13, 1808]\n      label: "Басейни та аксесуари"',
        "    - path: [0, 13, 1808]",
    )
    target = tmp_path / "comparability.yaml"
    target.write_text(broken, encoding="utf-8")

    with pytest.raises(CandidateSelectionConfigError):
        load_candidate_selection_config(target)
