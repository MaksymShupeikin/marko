"""Провенанс ринку, з якого взято пропозицію, і стеля оцінки для розширення.

prom.ua групує пропозиції за нормалізованим кодом деталі.  Коли нашого коду
там немає, парсер бере лістинг спорідненого номера з ланцюга заміщень —
``MotorsContext.via_oe_number`` фіксує, чий саме це ринок, а ``is_widened``
каже, що він не наш.  Виміряно 2026-07-31: сторінка коду існує для 28 із 40
позицій каталогу, тож розширення — звичайна, а не крайова ситуація.

Що перевіряється тут: сигнал доходить від шлюзу до збереженого спостереження і
до оцінювача, і пропозиція з ринку СПОРІДНЕНОГО номера ніколи не отримує
``EXACT``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from factories import product

from marko.infrastructure.db.models import MarketObservation, OfferProcessingOutcome
from marko.parsers.prom.gateway import MOTORS_IDENTITY_SOURCE, PromGateway
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.market_collection import (
    _domain_offer,
    _persist_payload_observations,
    _semantic_review_required_for_observation,
)
from marko.services.matching import ComparisonParams, build_comparison
from marko.services.parser_models import MotorsContext, SeedInfo
from marko.services.pricing_runs import policy_from_dict, policy_to_dict
from marko.services.scraper_contract import (
    PROM_ADAPTER_VERSION,
    RETRIEVAL_KIND_PROM_OE_PAGE,
    RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
    ScrapeInput,
    ScrapeOutput,
)
from marko.services.semantic_candidate_features import SEMANTIC_FEATURE_EXTRACTOR_VERSION
from marko.services.semantic_candidate_gate import SEMANTIC_PRICING_GATE_VERSION
from metis.pricing import (
    CohortRole,
    ProductTier,
    comparison_evidence_from_dict,
    comparison_evidence_to_dict,
)

SEED_URL = "https://prom.ua/ua/p1153738393-radiator-folksvagen-tuareg.html"


# -- Спільні будівельники ----------------------------------------------------


def _seed(**overrides) -> SeedInfo:
    base = {
        "id": 1,
        "name": "Радіатор VW Touareg 2.5 TDI 710*549",
        "price": "5163",
        "company": {"id": 2847093, "name": "KEMP"},
    }
    base.update(overrides)
    return SeedInfo(
        product=product(**base), seller_count=2, min_price=None, max_price=None
    )


def _context(**overrides) -> MotorsContext:
    base = {
        "normalized_part_code": "7L6121253",
        "part_group_id": 109790,
        "oe_page_id": 1146851,
        "oe_page_alias": "7l6121253",
    }
    base.update(overrides)
    return MotorsContext(**base)


def _offer_product(index: int, price: str, **overrides):
    base = {
        "id": 100 + index,
        "name": "Радіатор охолодження Touareg",
        "price": price,
        "urlText": "radiator",
        "company": {"id": 300 + index, "name": f"Продавець {index}"},
    }
    base.update(overrides)
    return product(**base)


def _install(monkeypatch, *, context, candidates):
    monkeypatch.setattr(
        PromGateway,
        "_fetch_seed_with_motors",
        lambda self, client, url, lang: (_seed(), context),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_oe_candidates",
        lambda self, client, ctx, lang: iter(candidates),
    )
    monkeypatch.setattr(
        PromGateway,
        "_collect_candidates",
        lambda self, client, query, lang, *, strict=False: iter(()),
    )


def _oe_comparison(*, via_oe_number: str | None, is_widened: bool):
    return build_comparison(
        _seed(),
        [_offer_product(1, "1100"), _offer_product(2, "900")],
        ComparisonParams(
            query="7L6121253",
            threshold=0.55,
            max_sellers=10,
            identity_source=MOTORS_IDENTITY_SOURCE,
            via_oe_number=via_oe_number,
            is_widened=is_widened,
        ),
    )


# -- FINDING 4: шлюз -> порівняння ------------------------------------------


def test_the_gateway_marks_a_comparison_taken_from_a_related_number(
    monkeypatch,
) -> None:
    """Наш код без лістингу; ринок узято за 7L6121253C з ланцюга заміщень."""

    _install(
        monkeypatch,
        context=_context(via_oe_number="7L6121253C"),
        candidates=[_offer_product(1, "1100")],
    )

    comparison = PromGateway().compare(SEED_URL)

    assert comparison.source == MOTORS_IDENTITY_SOURCE
    assert comparison.via_oe_number == "7L6121253C"
    assert comparison.is_widened is True


def test_the_gateway_does_not_invent_a_widening_for_our_own_number(
    monkeypatch,
) -> None:
    _install(
        monkeypatch,
        context=_context(via_oe_number="7L6121253"),
        candidates=[_offer_product(1, "1100")],
    )

    comparison = PromGateway().compare(SEED_URL)

    assert comparison.via_oe_number == "7L6121253"
    assert comparison.is_widened is False


# -- FINDING 4: порівняння -> серіалізація -----------------------------------


def test_the_serialized_comparison_states_where_the_market_came_from() -> None:
    comparison = _oe_comparison(via_oe_number="7L6121253C", is_widened=True)

    payload = comparison.as_dict()

    assert payload["source"] == MOTORS_IDENTITY_SOURCE
    assert payload["acquisition"] == {
        "source": MOTORS_IDENTITY_SOURCE,
        "via_oe_number": "7L6121253C",
        "is_widened": True,
    }


def test_a_text_search_serializes_as_an_unwidened_search() -> None:
    comparison = build_comparison(
        _seed(),
        [_offer_product(1, "1100")],
        ComparisonParams(query="7L6121253", threshold=0.0, max_sellers=10),
    )

    payload = comparison.as_dict()

    assert payload["source"] == "SEARCH"
    assert payload["acquisition"] == {
        "source": "SEARCH",
        "via_oe_number": None,
        "is_widened": False,
    }


# -- FINDING 4: заморожена межа ----------------------------------------------


def test_the_frozen_boundary_no_longer_overwrites_the_prom_oe_page_origin() -> None:
    scrape_input = ScrapeInput.build(SEED_URL, "7L6121253")
    comparison = _oe_comparison(via_oe_number="7L6121253C", is_widened=True)

    output = ScrapeOutput.from_comparison(scrape_input, comparison)

    assert output.payload["output"]["acquisition"] == {
        "source": MOTORS_IDENTITY_SOURCE,
        "method": "OE_PAGE_LISTING",
        # Номер, по которому страница ЗАПРОШЕНА, приезжает от приобретения, а
        # не восстанавливается из каталога ниже по течению (F6).
        "queried_oe_norm": "7L6121253",
        "via_oe_number": "7L6121253C",
        "is_widened": True,
        "source_url": SEED_URL,
        "input_hash": ScrapeInput.build(SEED_URL, "7L6121253").input_hash,
    }
    records = output.payload["output"]["records"]
    assert records
    for record in records:
        assert record["retrieval_kind"] == RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED
        assert record["acquisition"]["via_oe_number"] == "7L6121253C"
        assert record["acquisition"]["is_widened"] is True


def test_an_unwidened_part_code_listing_keeps_its_own_retrieval_kind() -> None:
    scrape_input = ScrapeInput.build(SEED_URL, "7L6121253")
    comparison = _oe_comparison(via_oe_number="7L6121253", is_widened=False)

    output = ScrapeOutput.from_comparison(scrape_input, comparison)

    for record in output.payload["output"]["records"]:
        assert record["retrieval_kind"] == RETRIEVAL_KIND_PROM_OE_PAGE


def test_a_search_comparison_keeps_the_historical_retrieval_kind() -> None:
    """Ретенція: збережені payload-и пошуку не повинні змінити зміст."""

    scrape_input = ScrapeInput.build(SEED_URL, "7L6121253")
    comparison = build_comparison(
        _seed(),
        [_offer_product(1, "1100")],
        ComparisonParams(query="7L6121253", threshold=0.0, max_sellers=10),
    )

    output = ScrapeOutput.from_comparison(scrape_input, comparison)

    for record in output.payload["output"]["records"]:
        assert record["retrieval_kind"] == "product_seed_comparison"
        assert record["acquisition"]["is_widened"] is False


# -- FINDING 4: збереження на спостереженні ----------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        for value in self.added:
            if isinstance(value, MarketObservation) and value.id is None:
                value.id = uuid4()

    def begin_nested(self):
        session = self

        class _Nested:
            async def __aenter__(self) -> _FakeSession:
                return session

            async def __aexit__(self, *_exc: object) -> None:
                return None

        return _Nested()


def _record(*, retrieval_kind: str, acquisition: dict | None, product_id: int = 42):
    return {
        "raw_offer_index": 0,
        "retrieval_kind": retrieval_kind,
        "retrieval_score": None,
        "acquisition": acquisition,
        "product": {
            "product_id": product_id,
            "price": "100.00",
            "currency": "UAH",
            "seller_id": "seller-1",
            "name": "Радіатор охолодження Touareg",
            "is_available": True,
            "url": f"https://prom.ua/ua/p{product_id}-radiator.html",
            "oe_raw": "7L6 121 253 C",
        },
        "upstream_comparison_evidence": None,
    }


async def _persist(records) -> _FakeSession:
    raw_evidence = [
        {"logical_request_id": str(uuid4()), "raw_content_sha256": "a" * 64}
    ]
    session = _FakeSession()
    await _persist_payload_observations(
        session,
        run=SimpleNamespace(
            id=uuid4(),
            parser_version=PROM_ADAPTER_VERSION,
            policy_config=policy_to_dict(policy_from_dict(None)),
        ),
        run_item=SimpleNamespace(id=uuid4()),
        catalog_item=SimpleNamespace(
            id=uuid4(),
            category="cooling",
            oe_norm="7L6121253",
            mpn_norm="",
            identity_status="OE_CONFIRMED",
            part_numbers_norm=(),
        ),
        capture=SimpleNamespace(
            id=uuid4(),
            parser_version=PROM_ADAPTER_VERSION,
            content_sha256="c" * 64,
            payload={
                "raw_evidence": raw_evidence,
                "raw_manifest_sha256": canonical_sha256(raw_evidence),
            },
        ),
        offers=records,
        owned_sellers=set(),
        brand_tiers={},
        brand_confidence={},
        observed_at=datetime(2026, 7, 31, tzinfo=UTC),
        source_type="prom_public",
        acquisition_query="7L6121253",
    )
    return session


@pytest.mark.asyncio
async def test_a_widened_market_is_persisted_on_the_observation() -> None:
    session = await _persist(
        [
            _record(
                retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
                acquisition={
                    "source": MOTORS_IDENTITY_SOURCE,
                    "via_oe_number": "7L6121253C",
                    "is_widened": True,
                },
            )
        ]
    )

    observation = next(
        value for value in session.added if isinstance(value, MarketObservation)
    )
    assert (
        observation.comparison_evidence["retrieval_kind"]
        == RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED
    )
    outcome = next(
        value
        for value in session.added
        if isinstance(value, OfferProcessingOutcome) and value.stage == "persistence"
    )
    assert "ACQUIRED_VIA_WIDENED_OE" in outcome.reason_codes


@pytest.mark.asyncio
async def test_a_widened_acquisition_cannot_be_stored_as_an_ordinary_one() -> None:
    """Захист від payload-у, де блок провенансу і retrieval_kind розходяться."""

    session = await _persist(
        [
            _record(
                retrieval_kind="product_seed_comparison",
                acquisition={
                    "source": MOTORS_IDENTITY_SOURCE,
                    "via_oe_number": "7L6121253C",
                    "is_widened": True,
                },
            )
        ]
    )

    observation = next(
        value for value in session.added if isinstance(value, MarketObservation)
    )
    assert (
        observation.comparison_evidence["retrieval_kind"]
        == RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED
    )


@pytest.mark.asyncio
async def test_an_ordinary_acquisition_is_not_marked_as_widened() -> None:
    session = await _persist(
        [
            _record(
                retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE,
                acquisition={
                    "source": MOTORS_IDENTITY_SOURCE,
                    "via_oe_number": "7L6121253",
                    "is_widened": False,
                },
            )
        ]
    )

    observation = next(
        value for value in session.added if isinstance(value, MarketObservation)
    )
    assert (
        observation.comparison_evidence["retrieval_kind"] == RETRIEVAL_KIND_PROM_OE_PAGE
    )
    outcome = next(
        value
        for value in session.added
        if isinstance(value, OfferProcessingOutcome) and value.stage == "persistence"
    )
    assert "ACQUIRED_VIA_WIDENED_OE" not in outcome.reason_codes


def test_the_widened_flag_survives_the_re_enrichment_round_trip() -> None:
    """Чому прапорець живе саме в ``retrieval_kind``.

    ``oe_reenrichment`` перезаписує ``observation.comparison_evidence`` через
    ``from_dict``/``to_dict``.  Кодек знає лише свої поля, тож будь-який
    сусідній ключ тихо зникає — а ``retrieval_kind`` переживає.
    """

    stored = {
        "dimensions": {},
        "provenance": {},
        "seller_identity": {},
        "policy_id": "p",
        "policy_hash": "c" * 64,
        "retrieval_kind": RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
        "acquisition": {"is_widened": True, "via_oe_number": "7L6121253C"},
        "hard_gate_result": "MANUAL_REVIEW",
        "reason_codes": [],
    }

    round_tripped = comparison_evidence_to_dict(comparison_evidence_from_dict(stored))

    assert round_tripped is not None
    assert round_tripped["retrieval_kind"] == RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED
    assert "acquisition" not in round_tripped


# -- FINDING 4: стеля оцінки -------------------------------------------------


def _review(match_level: str):
    from marko.services.llm_comparability import (
        ComparabilityMatchLevel,
        ComparabilityVerdict,
        EffectiveComparabilityReview,
    )

    return EffectiveComparabilityReview(
        review_id=uuid4(),
        market_observation_id=uuid4(),
        input_hash="b" * 64,
        verdict=ComparabilityVerdict.COMPARABLE,
        match_level=ComparabilityMatchLevel(match_level),
        confidence=Decimal("0.9"),
        rationale="однакова деталь",
        dimension_findings=(),
        hard_stop_conflicts=(),
        decision_source="llm",
        status="succeeded",
        provider="openai",
        model_id="model",
        prompt_version="v1",
        reviewed_at=datetime(2026, 7, 31, tzinfo=UTC),
        cache_hit_review_id=None,
    )


def _observation(retrieval_kind: str) -> MarketObservation:
    return MarketObservation(
        id=uuid4(),
        pricing_run_item_id=uuid4(),
        catalog_item_id=uuid4(),
        raw_capture_id=uuid4(),
        source="prom_public",
        source_listing_id="42",
        seller_id="seller-1",
        seller_name="Продавець",
        url="https://prom.ua/ua/p42-radiator.html",
        url_absence_reason=None,
        title="Радіатор охолодження Touareg",
        description=None,
        description_available=False,
        condition_raw="Новий",
        condition_state="NEW",
        condition_reason_codes=[],
        cross_candidates=[],
        candidate_snapshot={},
        brand_raw="Nissens",
        search_oe_norm="7L6121253",
        extracted_oe_norms=[],
        oe_verification_status="UNKNOWN",
        oe_evidence=[],
        canonical_category_id="generic_unknown",
        price=Decimal("1100"),
        currency="UAH",
        currency_raw="грн",
        currency_inferred=False,
        is_available=True,
        match_confidence=Decimal("0.9"),
        source_confidence=Decimal("0.9"),
        source_confidence_factors={},
        parser_version=PROM_ADAPTER_VERSION,
        comparison_evidence={
            "dimensions": {},
            "provenance": {},
            "seller_identity": {},
            "policy_id": "p",
            "policy_hash": "c" * 64,
            "retrieval_kind": retrieval_kind,
            "hard_gate_result": "MANUAL_REVIEW",
            "reason_codes": [],
        },
        comparability_hard_gate_result="MANUAL_REVIEW",
        calibration_exclusion_codes=[],
        seller_identity_verified=True,
        source_provenance_verified=True,
        automatic_eligible=False,
        via_cross=False,
        observed_at=datetime(2026, 7, 31, tzinfo=UTC),
    )


def _classification():
    return SimpleNamespace(
        tier=ProductTier.AFTERMARKET_A.value,
        tier_confidence=Decimal("0.9"),
        is_used=False,
        is_kemp=False,
        is_owned=False,
        is_dumping=False,
        exclusion_reason=None,
        cohort_role=CohortRole.TARGET_MARKET.value,
    )


def test_an_offer_from_a_related_numbers_market_is_never_graded_exact() -> None:
    offer = _domain_offer(
        _observation(RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED),
        _classification(),
        datetime(2026, 7, 31, tzinfo=UTC),
        semantic_review=_review("EXACT"),
        semantic_review_required=True,
    )

    assert offer.semantic_review_match_level == "ACCEPTABLE_ANALOGUE"


def test_the_ceiling_holds_even_when_the_semantic_review_is_advisory() -> None:
    offer = _domain_offer(
        _observation(RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED),
        _classification(),
        datetime(2026, 7, 31, tzinfo=UTC),
        semantic_review=_review("EXACT"),
        semantic_review_required=False,
    )

    assert offer.semantic_review_match_level == "ACCEPTABLE_ANALOGUE"


def test_the_ceiling_never_promotes_a_worse_grade() -> None:
    offer = _domain_offer(
        _observation(RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED),
        _classification(),
        datetime(2026, 7, 31, tzinfo=UTC),
        semantic_review=_review("SUSPICIOUS"),
        semantic_review_required=True,
    )

    assert offer.semantic_review_match_level == "SUSPICIOUS"


def test_our_own_part_codes_market_still_reaches_exact() -> None:
    offer = _domain_offer(
        _observation(RETRIEVAL_KIND_PROM_OE_PAGE),
        _classification(),
        datetime(2026, 7, 31, tzinfo=UTC),
        semantic_review=_review("EXACT"),
        semantic_review_required=True,
    )

    assert offer.semantic_review_match_level == "EXACT"


def test_persisted_domain_offer_rejects_stale_semantic_snapshot() -> None:
    observation = _observation(RETRIEVAL_KIND_PROM_OE_PAGE)
    observation.candidate_snapshot = {
        "semantic_gate": {
            "status": "PRICING_EVIDENCE",
            "reason": "OK",
            "gate_version": "semantic-pricing-gate-v9-category-required-conflicts",
            "extractor_version": "semantic-features-v39",
        }
    }

    offer = _domain_offer(
        observation,
        _classification(),
        datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert offer.semantic_gate_current is False


def test_domain_offer_without_admission_field_fails_closed() -> None:
    """A legacy/replay adapter must not manufacture price eligibility."""

    observation = _observation(RETRIEVAL_KIND_PROM_OE_PAGE)
    del observation.automatic_eligible

    offer = _domain_offer(
        observation,
        _classification(),
        datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert offer.automatic_eligible is False


def test_domain_offer_does_not_trust_scalar_admission_without_identity_projection() -> None:
    """A stale/manual ``true`` flag cannot revive an unverified row."""

    observation = _observation(RETRIEVAL_KIND_PROM_OE_PAGE)
    observation.automatic_eligible = True

    offer = _domain_offer(
        observation,
        _classification(),
        datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert offer.automatic_eligible is False


def test_domain_offer_rechecks_all_persisted_admission_columns() -> None:
    """A copied scalar flag cannot bypass hard-gate or provenance columns."""

    observation = _observation(RETRIEVAL_KIND_PROM_OE_PAGE)
    observation.automatic_eligible = True
    observation.oe_verification_status = "VERIFIED_EXACT"
    observation.search_oe_norm = "93818439"
    observation.extracted_oe_norms = ["93818439"]
    observation.verified_matched_oe_norm = "93818439"
    observation.comparison_identity_key = "93818439"
    observation.comparability_hard_gate_result = "MANUAL_REVIEW"
    observation.candidate_snapshot = {
        "identity_admission": {"automatic_evidence_sufficient": True},
        "semantic_gate": {
            "status": "PRICING_EVIDENCE",
            "reason": "OK",
            "gate_version": SEMANTIC_PRICING_GATE_VERSION,
            "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
        },
    }

    offer = _domain_offer(
        observation,
        _classification(),
        datetime(2026, 7, 31, tzinfo=UTC),
    )

    assert offer.automatic_eligible is False


def test_verified_cross_requires_semantic_admission_even_in_optional_mode() -> None:
    observation = _observation(RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED)
    observation.oe_verification_status = "VERIFIED_CROSS"

    assert _semantic_review_required_for_observation(
        observation,
        global_required=False,
    )


def test_legacy_replay_trace_preserves_global_only_review_authority() -> None:
    observation = _observation(RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED)
    observation.oe_verification_status = "VERIFIED_CROSS"

    assert not _semantic_review_required_for_observation(
        observation,
        global_required=False,
        traced_required_observation_ids=frozenset(),
    )


def test_new_replay_trace_restores_per_observation_review_authority() -> None:
    observation = _observation(RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED)
    observation.oe_verification_status = "VERIFIED_CROSS"

    assert _semantic_review_required_for_observation(
        observation,
        global_required=False,
        traced_required_observation_ids=frozenset({str(observation.id)}),
    )
