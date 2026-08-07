"""PROMPT_15_015 M-001..M-025 and hard-gate metamorphic checks."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import itertools
from pathlib import Path
import random

import re

import pytest

from metis.pricing import (
    CoefficientModel,
    CompetitorOffer,
    DimensionEvidence,
    EvidenceState,
    HardGateResult,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    TierCoefficient,
    category_comparability_rule,
    evaluate_comparison_evidence,
    recommend_price,
    verified_comparison_evidence,
)
from metis.pricing.candidate_selection import load_candidate_selection_config
from metis.pricing.comparability import (
    _CATEGORICAL_STEMS,
    normalized_categorical_dimension,
)
from marko.services.semantic_candidate_features import (
    _POSITION_PATTERNS,
    _SIDE_PATTERNS,
)


ABSTAIN = {
    RecommendationAction.MANUAL_REVIEW,
    RecommendationAction.INSUFFICIENT_DATA,
}
AUTOMATIC = {
    RecommendationAction.RAISE,
    RecommendationAction.HOLD,
    RecommendationAction.LOWER,
}
RETRIEVAL_KINDS = ("fuzzy", "sku", "model")
CATEGORY = "brakes"


def test_workspace_ownership_is_not_seeded_with_tenant_ids_in_shared_policy() -> None:
    config = load_candidate_selection_config(
        Path(__file__).resolve().parents[1] / "config" / "comparability.yaml"
    )

    assert config.own_seller_ids == frozenset()


def _coefficients() -> dict[tuple[str, ProductTier], TierCoefficient]:
    return {
        (CATEGORY, ProductTier.BUDGET): TierCoefficient(
            category=CATEGORY,
            tier=ProductTier.BUDGET,
            multiplier=Decimal("1"),
            model=CoefficientModel.SHRINKAGE,
            method_version="comparability-contract-v2",
            coefficient_version="comparability-contract-v2:synthetic",
            sample_size=20,
            effective_sample_size=Decimal("18"),
            confidence=Decimal("0.95"),
            validated=True,
            log_effect=Decimal("0"),
            interval_low=Decimal("0.9"),
            interval_high=Decimal("1.1"),
            dataset_hash="a" * 64,
        )
    }


def _context() -> ProductPricingContext:
    return ProductPricingContext(
        sku="COMPARABILITY-1", category=CATEGORY, current_price=Decimal("80")
    )


def _evidence(
    index: int,
    *,
    seller_id: str | None = None,
    retrieval_kind: str = "fuzzy",
    dimension: str | None = None,
    state: EvidenceState = EvidenceState.MATCH,
):
    stable = seller_id if seller_id is not None else f"seller-{index}"
    overrides = (
        {dimension: DimensionEvidence(state=state)} if dimension is not None else None
    )
    return verified_comparison_evidence(
        stable_seller_id=stable,
        source_record_id=f"obs-{index}",
        retrieval_kind=retrieval_kind,
        dimension_overrides=overrides,
    )


def _offer(
    index: int,
    *,
    seller_id: str | None = None,
    seller_name: str | None = None,
    currency: str | None = "UAH",
    currency_raw: str | None = "UAH",
    evidence=...,
) -> CompetitorOffer:
    stable = seller_id if seller_id is not None else f"seller-{index}"
    comparison = _evidence(index, seller_id=stable) if evidence is ... else evidence
    return CompetitorOffer(
        observation_id=f"obs-{index}",
        seller_id=stable,
        seller_name=seller_name or f"Seller {index}",
        price=Decimal(100 + index * 5),
        currency=currency,
        currency_raw=currency_raw,
        is_available=True,
        age_hours=Decimal("0"),
        match_confidence=Decimal("0.99"),
        tier=ProductTier.BUDGET,
        tier_confidence=Decimal("0.99"),
        source_confidence=Decimal("1"),
        semantic_gate_current=True,
        automatic_eligible=True,
        comparison_evidence=comparison,
    )


def _market(**kwargs) -> list[CompetitorOffer]:
    return [_offer(index, **kwargs) for index in range(5)]


def test_competitor_offer_defaults_are_fail_closed() -> None:
    offer = CompetitorOffer(
        observation_id="unadmitted-observation",
        seller_id="seller-unadmitted",
        seller_name="Seller",
        price=Decimal("100"),
        currency="UAH",
        currency_raw="UAH",
        is_available=True,
        age_hours=Decimal("0"),
        match_confidence=Decimal("0.99"),
        tier=ProductTier.BUDGET,
        tier_confidence=Decimal("0.99"),
        source_confidence=Decimal("1"),
        comparison_evidence=verified_comparison_evidence(
            stable_seller_id="seller-unadmitted",
            source_record_id="unadmitted-observation",
        ),
    )

    assert offer.automatic_eligible is False
    assert offer.semantic_gate_current is False


def test_padded_normalized_currency_passes_the_currency_hard_gate() -> None:
    decision = evaluate_comparison_evidence(
        _evidence(0),
        seller_id="seller-0",
        currency_raw=" UAH ",
        currency_normalized=" uah ",
        required_currency="UAH",
        category=CATEGORY,
    )

    assert decision.hard_gate_result is HardGateResult.PASS
    assert decision.hard_gate_results["currency_matches"] == 1


@pytest.mark.parametrize("retrieval_kind", RETRIEVAL_KINDS)
@pytest.mark.parametrize(
    ("case_id", "dimension", "state"),
    (
        ("M-001", "oe_reference", EvidenceState.UNKNOWN),
        ("M-002", "oe_reference", EvidenceState.UNKNOWN),
        ("M-003", "oe_reference", EvidenceState.CONFLICT),
        ("M-007", "vehicle_generation", EvidenceState.CONFLICT),
        ("M-008", "year_interval", EvidenceState.CONFLICT),
        ("M-010", "side", EvidenceState.CONFLICT),
        ("M-011", "position", EvidenceState.CONFLICT),
        ("M-012", "condition", EvidenceState.CONFLICT),
        ("M-013", "package_quantity", EvidenceState.CONFLICT),
    ),
)
def test_m001_m013_hard_dimensions_never_auto(
    case_id: str,
    dimension: str,
    state: EvidenceState,
    retrieval_kind: str,
) -> None:
    del case_id
    offers = [
        _offer(
            index,
            evidence=_evidence(
                index,
                retrieval_kind=retrieval_kind,
                dimension=dimension,
                state=state,
            ),
        )
        for index in range(5)
    ]
    result = recommend_price(_context(), offers, _coefficients())
    assert result.action in ABSTAIN
    assert result.recommended_price is None
    if state == EvidenceState.CONFLICT:
        assert any("REJECTED_" in item.reason for item in result.excluded)


@pytest.mark.parametrize("state", (EvidenceState.UNKNOWN, EvidenceState.CONFLICT))
def test_brand_is_informational_after_oe_identity(state: EvidenceState) -> None:
    offers = [
        _offer(
            index,
            evidence=_evidence(index, dimension="brand_manufacturer", state=state),
        )
        for index in range(5)
    ]
    result = recommend_price(_context(), offers, _coefficients())
    assert result.action in AUTOMATIC
    assert result.automatic_eligible


@pytest.mark.parametrize("dimension", ("fitment", "side"))
def test_category_conditional_unknown_does_not_become_a_global_hard_gate(
    dimension: str,
) -> None:
    offers = [
        _offer(
            index,
            evidence=_evidence(index, dimension=dimension, state=EvidenceState.UNKNOWN),
        )
        for index in range(5)
    ]
    result = recommend_price(_context(), offers, _coefficients())
    assert result.action in AUTOMATIC


@pytest.mark.parametrize("retrieval_kind", RETRIEVAL_KINDS)
def test_m014_unknown_source_cannot_be_faked_by_confidence(
    retrieval_kind: str,
) -> None:
    offers = []
    for index in range(5):
        evidence = _evidence(index, retrieval_kind=retrieval_kind)
        evidence = replace(
            evidence,
            provenance=replace(evidence.provenance, source_type="unknown"),
        )
        offers.append(_offer(index, evidence=evidence))
    result = recommend_price(_context(), offers, _coefficients())
    assert result.action in ABSTAIN
    assert result.recommended_price is None
    assert "MANUAL_MISSING_SOURCE_PROVENANCE" in result.reasons


def test_m015_missing_source_hash_abstains() -> None:
    offers = []
    for index in range(5):
        evidence = _evidence(index)
        offers.append(
            _offer(
                index,
                evidence=replace(
                    evidence,
                    provenance=replace(evidence.provenance, raw_evidence_sha256=None),
                ),
            )
        )
    result = recommend_price(_context(), offers, _coefficients())
    assert result.action in ABSTAIN
    assert result.recommended_price is None


def test_m016_blank_seller_ids_are_not_independent() -> None:
    offers = []
    for index in range(5):
        evidence = _evidence(index)
        evidence = replace(
            evidence,
            seller_identity=replace(
                evidence.seller_identity, stable_seller_id=None, verified=False
            ),
        )
        offers.append(
            _offer(
                index, seller_id="", seller_name=f"Unique {index}", evidence=evidence
            )
        )
    result = recommend_price(_context(), offers, _coefficients())
    assert result.action in ABSTAIN
    assert result.unique_seller_count == 0
    assert result.recommended_price is None


@pytest.mark.parametrize(
    ("stable_seller_id", "caller_seller_id"),
    (("", ""), ("seller-a", "seller-b")),
)
def test_blank_or_mismatched_seller_identity_fails_direct_gate(
    stable_seller_id: str,
    caller_seller_id: str,
) -> None:
    evidence = _evidence(1, seller_id=stable_seller_id)
    decision = evaluate_comparison_evidence(
        evidence,
        seller_id=caller_seller_id,
        currency_raw="UAH",
        currency_normalized="UAH",
        required_currency="UAH",
    )
    assert not decision.automatic_eligible
    assert "MANUAL_MISSING_STABLE_SELLER_ID" in decision.reason_codes


def test_m017_same_verified_seller_multiple_names_deduplicates() -> None:
    offers = []
    for index in range(5):
        evidence = _evidence(index, seller_id="seller-one")
        offers.append(
            _offer(
                index,
                seller_id="seller-one",
                seller_name=f"Alias {index}",
                evidence=evidence,
            )
        )
    result = recommend_price(_context(), offers, _coefficients())
    assert result.unique_seller_count == 1
    assert result.action in ABSTAIN


@pytest.mark.parametrize("currency_raw", (None, "", "   "))
def test_m018_missing_raw_currency_does_not_default_to_uah(
    currency_raw: str | None,
) -> None:
    result = recommend_price(
        _context(), _market(currency="UAH", currency_raw=currency_raw), _coefficients()
    )
    assert result.action in ABSTAIN
    assert result.recommended_price is None
    assert "MANUAL_MISSING_RAW_CURRENCY" in result.reasons


def test_m019_currency_conflict_rejects() -> None:
    result = recommend_price(
        _context(),
        _market(currency="USD", currency_raw="USD"),
        _coefficients(),
    )
    assert result.action in ABSTAIN
    assert result.recommended_price is None
    assert any("REJECTED_" in item.reason for item in result.excluded)


def test_m020_all_verified_can_reach_automatic_gate() -> None:
    result = recommend_price(_context(), _market(), _coefficients())
    assert result.action in AUTOMATIC
    assert result.automatic_eligible is True
    assert result.verified_seller_count == 5


def test_m021_removing_any_required_dimension_revokes_automatic() -> None:
    baseline = recommend_price(_context(), _market(), _coefficients())
    assert baseline.action in AUTOMATIC
    dimensions = tuple(category_comparability_rule(CATEGORY).hard_required)
    for dimension in dimensions:
        offers = [
            _offer(
                index,
                evidence=_evidence(
                    index, dimension=dimension, state=EvidenceState.UNKNOWN
                ),
            )
            for index in range(5)
        ]
        result = recommend_price(_context(), offers, _coefficients())
        assert result.action in ABSTAIN, dimension
        assert result.recommended_price is None, dimension


def test_m022_adding_any_conflict_revokes_automatic() -> None:
    for dimension in tuple(
        name for name in _evidence(0).dimensions if name != "brand_manufacturer"
    ):
        offers = [
            _offer(
                index,
                evidence=_evidence(
                    index, dimension=dimension, state=EvidenceState.CONFLICT
                ),
            )
            for index in range(5)
        ]
        result = recommend_price(_context(), offers, _coefficients())
        assert result.action in ABSTAIN, dimension
        assert result.recommended_price is None, dimension


def _canonical(result) -> tuple:
    return (
        result.action,
        result.recommended_price,
        result.fair_price,
        result.unique_seller_count,
        tuple(sorted(result.reasons)),
        tuple(item.observation_id for item in result.evidence),
    )


def test_m023_permutation_is_canonical() -> None:
    offers = _market()
    expected = _canonical(recommend_price(_context(), offers, _coefficients()))
    rng = random.Random(15015)
    for _ in range(12):
        shuffled = list(offers)
        rng.shuffle(shuffled)
        assert (
            _canonical(recommend_price(_context(), shuffled, _coefficients()))
            == expected
        )


def test_m024_duplicate_evidence_does_not_increase_count() -> None:
    offers = _market()
    duplicate = replace(offers[0], observation_id="obs-duplicate", price=Decimal("999"))
    result = recommend_price(_context(), [*offers, duplicate], _coefficients())
    assert result.unique_seller_count == 5
    assert any(item.reason == "SELLER_DUPLICATE" for item in result.excluded)


def test_m025_original_raise_920_payload_is_killed() -> None:
    deficient = [
        replace(_offer(index), comparison_evidence=None, currency_raw=None)
        for index in range(5)
    ]
    result = recommend_price(
        ProductPricingContext(
            sku="OLD-RAISE-920", category="brakes", current_price=Decimal("800")
        ),
        [
            replace(item, price=Decimal(1000 + index * 50))
            for index, item in enumerate(deficient)
        ],
        _coefficients(),
    )
    assert result.action in ABSTAIN
    assert result.recommended_price is None


def test_property_evidence_removal_or_conflict_never_increases_eligibility() -> None:
    hard_required = tuple(category_comparability_rule(CATEGORY).hard_required)
    conflict_dimensions = tuple(
        name for name in _evidence(0).dimensions if name != "brand_manufacturer"
    )
    cases = tuple(
        itertools.chain(
            itertools.product((EvidenceState.UNKNOWN,), hard_required),
            itertools.product((EvidenceState.CONFLICT,), conflict_dimensions),
        )
    )
    for state, dimension in cases:
        offers = [
            _offer(
                index,
                evidence=_evidence(index, dimension=dimension, state=state),
            )
            for index in range(5)
        ]
        result = recommend_price(_context(), offers, _coefficients())
        assert result.action in ABSTAIN
        assert not result.automatic_eligible
    (TierCoefficient,)
    (category_comparability_rule,)


@pytest.mark.parametrize(
    ("dimension", "left", "right", "expected"),
    (
        ("side", "Лівий", "Передній лівий", EvidenceState.MATCH),
        ("side", "Лівий", "Передній правий", EvidenceState.CONFLICT),
        ("side", "лев", "левая сторона", EvidenceState.MATCH),
        ("position", "Передній", "Передній лівий", EvidenceState.MATCH),
        ("position", "Передній", "Задній лівий", EvidenceState.CONFLICT),
        ("position", "front", "пер.", EvidenceState.MATCH),
    ),
)
def test_a_compound_side_or_position_phrase_is_read_not_abandoned(
    dimension: str,
    left: str,
    right: str,
    expected: EvidenceState,
) -> None:
    """One fact, two vocabularies, and only the poorer one gated pricing.

    The semantic extractor reads ``передній лівий`` as front + left from word
    stems. The comparability layer looked its values up in an exact table of
    18 side and 20 position tokens, so the same phrase came back UNKNOWN and
    the candidate was held as ``MANUAL_MISSING_SIDE_OR_POSITION`` — a wording
    gap recorded as missing evidence.
    """

    evidence = normalized_categorical_dimension(dimension, left, right)

    assert evidence.state is expected


@pytest.mark.parametrize(
    ("dimension", "value"),
    (
        ("side", "лівий/правий"),
        ("side", "левый или правый"),
        ("position", "передній та задній"),
    ),
)
def test_a_phrase_naming_both_values_stays_unknown(
    dimension: str,
    value: str,
) -> None:
    """Reading a stem must not become guessing which of two it meant."""

    canonical = "лівий" if dimension == "side" else "передній"
    evidence = normalized_categorical_dimension(dimension, canonical, value)

    assert evidence.state is EvidenceState.UNKNOWN


def test_an_unrelated_phrase_is_still_unknown_rather_than_a_conflict() -> None:
    evidence = normalized_categorical_dimension("side", "Лівий", "Комплект")

    assert evidence.state is EvidenceState.UNKNOWN


def test_the_two_side_and_position_vocabularies_stay_in_sync() -> None:
    """One fact, deliberately spelled twice, held equal by this test.

    ``metis`` does not import ``marko``, so the comparability layer cannot
    reuse the semantic extractor's patterns and carries its own copy. Only the
    test suite sees both packages; without this, the copies drift and the
    poorer one silently gates pricing again.
    """

    extractor = {
        "side": _SIDE_PATTERNS,
        "position": _POSITION_PATTERNS,
    }
    for dimension, patterns in extractor.items():
        mirrored = {
            canonical
            for _pattern, canonical in _CATEGORICAL_STEMS[dimension]
        }
        assert mirrored == set(patterns), dimension

    for dimension, phrases in (
        ("side", ("лівий", "левая сторона", "left", "правий", "right")),
        ("position", ("передній", "задня вісь", "front", "rear")),
    ):
        for phrase in phrases:
            extracted = {
                canonical
                for canonical, regexes in extractor[dimension].items()
                if any(re.search(regex, phrase, re.IGNORECASE) for regex in regexes)
            }
            mirrored = {
                canonical
                for pattern, canonical in _CATEGORICAL_STEMS[dimension]
                if pattern.search(phrase)
            }
            assert extracted == mirrored, (dimension, phrase)
