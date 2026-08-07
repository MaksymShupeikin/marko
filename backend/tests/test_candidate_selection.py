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
# A validated coefficient for the reference category, so tests about identity
# gates and soft flags reach the end of the chain instead of stopping at
# ``PREMIUM_NOT_CALIBRATED``.  Calibration itself is covered separately.
CALIBRATED_PREMIUMS = {("body_lock", ProductTier.AFTERMARKET_B): Decimal("1.0")}


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
        owned_seller_ids=frozenset({"2847093"}),
    )

    assert verdict.status is CandidateStatus.REJECTED
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

    assert verdict.status is CandidateStatus.REJECTED
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
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE


def test_used_and_new_conflict_goes_to_review() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(title="Новий замок 7E5827505A, знято з нової машини"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
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

    assert (used.status, used.reason) == (CandidateStatus.REJECTED, "USED")
    assert (reman.status, reman.reason) == (
        CandidateStatus.REJECTED,
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


def test_exact_mpn_is_used_when_seller_sku_is_different() -> None:
    """An unrelated seller SKU must not hide an exact manufacturer number."""

    verdict = check_candidate(
        _reference(title="Замок"),
        _candidate(
            article_field="SELLER-SKU-OTHER",
            article_fields=(("MPN", "7E5 827 505 A"),),
            title="Замок кришки багажника",
        ),
        CONFIG,
        tier_agnostic=True,
    )

    identity = verdict.details["gates"]["oem_identity"]
    assert verdict.reason != "OEM_NOT_FOUND"
    assert identity["evidence"] == "MPN"
    assert {item["namespace"] for item in identity["structured_articles"]} == {
        "ARTICLE_FIELD",
        "MPN",
    }


def test_labelled_part_number_is_kept_as_separate_identity_namespace() -> None:
    verdict = check_candidate(
        _reference(oem="77646966", title="Радіатор"),
        _candidate(
            article_field="PRIVATE-SKU",
            article_fields=(("PART_NUMBER", "77646966"),),
            title="Радіатор охолодження",
        ),
        CONFIG,
        tier_agnostic=True,
    )

    identity = verdict.details["gates"]["oem_identity"]
    assert verdict.reason != "OEM_NOT_FOUND"
    assert identity["evidence"] == "PART_NUMBER"


def test_conflicting_native_mpn_overrides_copied_title_number() -> None:
    verdict = check_candidate(
        _reference(oem="7E5827505A", title="Замок кришки багажника"),
        _candidate(
            article_field="SELLER-SKU",
            article_fields=(("MPN", "7E5827505B"),),
            title="Замок кришки багажника 7E5827505A / 7E5827505B",
        ),
        CONFIG,
        tier_agnostic=True,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "OEM_CONFLICT"


def test_conflicting_native_mpn_overrides_matching_private_sku() -> None:
    """A copied seller SKU must not beat a contradictory native MPN."""

    verdict = check_candidate(
        _reference(oem="7E5827505A", title="Замок кришки багажника"),
        _candidate(
            article_field="7E5827505A",
            article_fields=(
                ("SKU", "7E5827505A"),
                ("MPN", "7E5827505B"),
            ),
            title="Замок кришки багажника 7E5827505A",
        ),
        CONFIG,
        tier_agnostic=True,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "OEM_CONFLICT"
    assert verdict.details["gates"]["oem_identity"]["conflicting_native"] == [
        {"namespace": "MPN", "normalized": "7E5827505B"}
    ]


def test_source_assertion_does_not_override_explicit_conflicting_native_oe() -> None:
    verdict = check_candidate(
        _reference(oem="93818439", title="Радіатор Iveco Daily"),
        _candidate(
            article_fields=(("OE", "93818440"),),
            title="Радіатор Iveco Daily",
        ),
        CONFIG,
        identity_source="PROM_OE_PAGE",
        tier_agnostic=True,
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "SOURCE_ASSERTION_OE_CONFLICT"
    assert verdict.details["gates"]["oem_identity"]["conflicting_native_oes"] == [
        "93818440"
    ]


def test_oem_title_match_supports_grouped_identifier_boundaries() -> None:
    verdict = check_candidate(
        _reference(title="Замок"),
        _candidate(
            title="Замок 7E5 827 505 A",
            article_field="OTHER",
        ),
        CONFIG,
        tier_agnostic=True,
    )

    assert verdict.details["gates"]["oem_identity"]["evidence"] == "TITLE"


def test_short_numeric_hash_label_is_strong_title_identity() -> None:
    verdict = check_candidate(
        _reference(
            oem="115159",
            title="Амортизатор передний VW Golf 115159",
        ),
        _candidate(title="Амортизатор передний VW Golf #115159"),
        CONFIG,
        tier_agnostic=True,
    )

    assert verdict.reason != "WEAK_NUMERIC_IDENTITY"
    assert verdict.details["gates"]["oem_identity"]["evidence"] == "TITLE"


def test_oem_substring_inside_longer_identifier_is_not_identity_evidence() -> None:
    verdict = check_candidate(
        _reference(title="Замок"),
        _candidate(
            title="Замок X7E5827505A9",
            article_field="OTHER",
        ),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "OEM_NOT_FOUND"


def test_missing_oem_stops_before_variant_and_tier() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(
            title="Замок кришки багажника VW Transporter T5",
            article_field="9568ZC-5F",
        ),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED
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
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
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

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "VARIANT_MISMATCH:side"


def test_matching_explicit_side_is_not_skipped() -> None:
    verdict = check_candidate(
        _reference(title="Амортизатор задний правый Toyota Camry V40"),
        _candidate(title=("Амортизатор задний правый Toyota Camry V40 7E5827505A")),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert verdict.reason == "OK"


def test_one_sided_variant_knowledge_remains_fail_closed_without_skip() -> None:
    verdict = check_candidate(
        _reference(title="Амортизатор задний правый Toyota Camry V40"),
        _candidate(title="Амортизатор задний Toyota Camry V40 7E5827505A"),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert verdict.reason == "OK"


@pytest.mark.parametrize(
    ("axis", "oem", "reference_title", "candidate_title"),
    [
        (
            "core_shape",
            "7H0121253G",
            "Радіатор охолодження 7H0121253G плоскі соти VW T5",
            "Радіатор охолодження 7H0121253G круглі соти VW T5",
        ),
        (
            "power_rating",
            "7D0959455M",
            "Радіатор охолодження 7D0959455M 350W VW T4",
            "Радіатор охолодження 7D0959455M 450W VW T4",
        ),
        (
            "connector_pins",
            "HIS25",
            "Замок запалювання HIS25 4 pin VW Golf",
            "Замок запалювання HIS25 6 pin VW Golf",
        ),
    ],
)
def test_explicit_physical_variant_conflict_is_rejected(
    axis: str,
    oem: str,
    reference_title: str,
    candidate_title: str,
) -> None:
    """Same article is not enough when both titles assert opposite hardware."""

    verdict = check_candidate(
        _reference(oem=oem, title=reference_title),
        _candidate(title=candidate_title),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == f"VARIANT_MISMATCH:{axis}"
    assert verdict.details["stopped_gate"] == "variant"


@pytest.mark.parametrize(
    ("oem", "reference_title", "candidate_title"),
    [
        (
            "7H0121253G",
            "Радіатор охолодження 7H0121253G VW T5",
            "Радіатор охолодження 7H0121253G плоскі соти VW T5",
        ),
        (
            "HIS25",
            "Замок запалювання HIS25 VW Golf",
            "Замок запалювання HIS25 6 pin VW Golf",
        ),
    ],
)
def test_missing_physical_variant_does_not_create_false_mismatch(
    oem: str,
    reference_title: str,
    candidate_title: str,
) -> None:
    """Unknown physical data remains reviewable instead of being guessed."""

    verdict = check_candidate(
        _reference(oem=oem, title=reference_title),
        _candidate(title=candidate_title),
        CONFIG,
    )

    assert verdict.reason != "VARIANT_MISMATCH:core_shape"
    assert verdict.reason != "VARIANT_MISMATCH:connector_pins"
    assert verdict.details["stopped_gate"] != "variant"


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
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert "VARIANT_AMBIGUOUS:side" in verdict.flags
    assert "VARIANT_AMBIGUOUS:axle" in verdict.flags


def test_pack_mismatch_is_skipped() -> None:
    verdict = check_candidate(
        _reference(title="Комплект 2 шт замков VW Transporter T5"),
        _candidate(title="Замок VW Transporter T5 7E5827505A"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "PACK_MISMATCH"


def test_same_platform_is_retained_with_soft_flag() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(
            title="7E5827505A Замок Volkswagen Multivan T5 T6",
        ),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert "SAME_PLATFORM" in verdict.flags


def test_different_vehicle_brand_is_skipped() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(title="7E5827505A Замок Toyota Camry V40"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "BRAND_MISMATCH"


def test_unknown_applicability_is_a_soft_flag() -> None:
    verdict = check_candidate(
        _reference(title="Замок 7E5827505A"),
        _candidate(title="Замок 7E5827505A"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "TIER_UNKNOWN"
    assert "APPLICABILITY_UNKNOWN" in verdict.flags


def test_missing_reference_generation_does_not_create_false_mismatch() -> None:
    verdict = check_candidate(
        _reference(title="Замок VW Transporter"),
        _candidate(title="Замок VW Transporter T6 7E5827505A"),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert "APPLICABILITY_UNKNOWN" in verdict.flags


def test_unknown_tier_is_reference_only_after_all_identity_gates() -> None:
    """An unapproved brand must cost the candidate its price vote, not its seat.

    This is the case that used to empty the whole result set: with only KEMP
    approved in the brand dictionary, every external brand lands here.
    """

    verdict = check_candidate(_reference(), _candidate(), CONFIG)

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "TIER_UNKNOWN"
    assert verdict.details["stopped_gate"] == "tier_known"
    assert verdict.passed_gates[-1] == "own_brand"
    assert "applicability" in verdict.passed_gates


def test_price_anomaly_is_a_flag_and_never_a_skip() -> None:
    verdict = check_candidate(
        _reference(price=Decimal("1800")),
        _candidate(price=Decimal("400")),
        CONFIG,
        brand_tiers=APPROVED_POLCAR,
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
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
        calibrated_premiums=CALIBRATED_PREMIUMS,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
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

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "OEM_NOT_FOUND"


def test_mixed_script_brand_does_not_gain_an_unverified_tier() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(brand="КEМP"),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "TIER_UNKNOWN"


def test_histogram_names_the_outcome_and_the_cause() -> None:
    verdicts = [
        check_candidate(_reference(), _candidate(), CONFIG),
        check_candidate(
            _reference(),
            _candidate(seller_name="Avtorazborka24"),
            CONFIG,
        ),
    ]

    assert verdict_histogram(verdicts) == {
        "REFERENCE_ONLY:TIER_UNKNOWN": 1,
        "REJECTED:DISMANTLER_SELLER": 1,
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

    assert verdict.status is CandidateStatus.REJECTED
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
    assert verdict.status is CandidateStatus.REJECTED
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
    assert rejected.status is CandidateStatus.REJECTED
    assert rejected.reason == "CATEGORY_NOT_AUTOPARTS"


def test_shipped_policy_keeps_allowlist_disabled() -> None:
    """Строгий allowlist остаётся выключенным до утверждения владельцем."""

    assert CONFIG.category_domain.enabled is True
    assert CONFIG.category_domain.allowlist_enforced is False
    assert CONFIG.category_domain.majority_vote_enabled is False
    assert CONFIG.category_domain.blocked_ancestors
    assert CONFIG.category_domain.trusted_automotive_ancestors == ((0, 55),)
    assert CONFIG.category_domain.require_semantic_for_unknown is True
    assert CONFIG.category_domain.automotive_markers.prefixes
    assert CONFIG.category_domain.non_automotive_markers.prefixes


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


# Измеренная на 8563 офферах контаминация категорий (2026-07-29)


def test_household_appliance_parts_are_rejected_by_category() -> None:
    """Шнек для мясорубки Zelmer 86.3130 сталкивался с позицией KEMP 863130.

    До правки блок-листа режим гейта был ``NO_ACTIVE_POLICY``, и эти офферы
    доходили до конца цепочки: 402 в корзине TIER_UNKNOWN и 9 среди 39 строк,
    которые конвейер считал пригодной ценовой уликой.
    """
    verdict = check_candidate(
        _reference(oem="86.3130", title="Шнек 863130"),
        _candidate(
            title="12000133 Шнек для м'ясорубок Zelmer NR8 86.3130",
            brand="Zelmer",
            category_id=64421,
            category_path=(0, 50, 5006, 644, 64421),
        ),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "CATEGORY_NOT_AUTOPARTS"
    details = verdict.details["gates"]["category_domain"]
    assert details["mode"] == "BLOCKLIST"
    assert details["matched_ancestor"] == [0, 50, 5006]


def test_kitchen_appliance_branch_is_rejected_by_category() -> None:
    verdict = check_candidate(
        _reference(oem="86.3130", title="Шнек 863130"),
        _candidate(
            title="Кухонна техніка -> Шнек( z24) 86.3130 OEM",
            brand="Zelmer",
            category_id=341550,
            category_path=(0, 34, 3415, 341550),
        ),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "CATEGORY_NOT_AUTOPARTS"


@pytest.mark.parametrize(
    ("label", "path"),
    [
        ("маникюрная лампа", (0, 16, 1618, 161801)),
        ("компьютерный стол", (0, 15, 1503, 150301)),
        ("зоотовары", (0, 27, 2702, 270201)),
        ("одежда", (0, 3, 354, 3541)),
        ("военная амуниция", (0, 69, 6901, 690101)),
        ("жидкие обои", (0, 81, 1303, 130301)),
        ("медицинский зажим", (0, 40, 1611, 161101)),
    ],
)
def test_measured_non_automotive_branches_are_rejected(label, path) -> None:
    verdict = check_candidate(_reference(), _candidate(category_path=path), CONFIG)

    assert verdict.status is CandidateStatus.REJECTED, label
    assert verdict.reason == "CATEGORY_NOT_AUTOPARTS", label


@pytest.mark.parametrize(
    ("label", "path"),
    [
        ("болт VW вне автоветви", (0, 81, 4205, 420501)),
        ("крышка маслозаливная BMW", (0, 509, 71906, 7190601)),
        ("крышка NTY", (0, 18, 208, 20808)),
        ("прокладка ELRING", (0, 29, 2905, 290501)),
        ("колесо Loncin: решение владельца, не блокируем", (0, 18, 1821, 182101)),
    ],
)
def test_genuine_parts_outside_the_automotive_branch_still_pass(label, path) -> None:
    """Блок-лист не должен превращаться в allowlist по верхней ветви.

    Настоящие автозапчасти измеримо живут вне [0, 55]; блокировка ветви целиком
    срезала бы их.
    """
    verdict = check_candidate(_reference(), _candidate(category_path=path), CONFIG)

    assert verdict.reason != "CATEGORY_NOT_AUTOPARTS", label


@pytest.mark.parametrize(
    ("label", "title", "path"),
    [
        (
            "vitamin numeric collision",
            "NOW Vitamin B-12 1000 мкг (67367)",
            (0, 16, 1636, 23005),
        ),
        (
            "knife numeric collision",
            "Ніж сегментний HAISSER (94646)",
            (0, 1420, 142003, 14200306),
        ),
        (
            "photo backdrop numeric collision",
            "Квадратний вініловий фотофон (132703)",
            (0, 50, 5004, 500406, 500411),
        ),
        (
            "well pump numeric collision",
            "Насос глибинний для свердловини 1850055",
            (0, 81, 8101, 132414, 13241401),
        ),
    ],
)
def test_semantic_domain_guard_rejects_measured_non_automotive_collisions(
    label: str,
    title: str,
    path: tuple[int, ...],
) -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(title=title, category_path=path),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED, label
    assert verdict.reason == "CATEGORY_NOT_AUTOPARTS", label
    details = verdict.details["gates"]["category_domain"]
    assert details["mode"] == "SEMANTIC_NON_AUTOMOTIVE", label
    assert details["semantic_text_markers"]["non_automotive"], label


def test_semantic_domain_guard_rejects_non_automotive_text_under_auto_branch() -> None:
    verdict = check_candidate(
        _reference(),
        _candidate(
            title="Vitamin B-12 67367",
            category_path=AUTOPART_PATH,
        ),
        CONFIG,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "CATEGORY_NOT_AUTOPARTS"
    assert verdict.details["gates"]["category_domain"]["mode"] == (
        "SEMANTIC_NON_AUTOMOTIVE"
    )


def test_unknown_or_unapproved_category_without_auto_semantics_stays_nonterminal_until_adapter_gate() -> (
    None
):
    verdict = check_candidate(
        _reference(),
        _candidate(
            title="Generic article 123456",
            article_field="7E5 827 505 A",
            category_path=(0, 9999, 999901),
        ),
        CONFIG,
        tier_agnostic=True,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert verdict.reason == "OK"
    assert "CATEGORY_DOMAIN_UNCONFIRMED" in verdict.flags


def test_nonstandard_category_with_explicit_auto_part_text_remains_eligible_for_later_gates() -> (
    None
):
    verdict = check_candidate(
        _reference(),
        _candidate(
            title="Кришка маслозаливна BMW",
            category_path=(0, 509, 71906, 7190601),
        ),
        CONFIG,
    )

    assert verdict.reason != "CATEGORY_NOT_AUTOPARTS"
    assert verdict.details["gates"]["category_domain"]["mode"] == (
        "SEMANTIC_AUTOMOTIVE_TEXT"
    )
