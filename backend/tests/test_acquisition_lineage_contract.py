"""F6: типизированная родословная приобретения и заявление, которое её переживает.

Ревью round 2 (независимый валидатор) воспроизвело четыре вещи:

1. граница принимала ``retrieval_kind=prom_oe_page`` вместе с
   ``acquisition.source=SEARCH`` и без единой улики об OE;
2. такая запись сохранялась как ``VERIFIED_EXACT``, потому что запрошенный
   номер заявления восстанавливался из ``CatalogItem.oe_norm`` — то есть из
   нашего собственного намерения, а не из того, что сделала площадка;
3. проверенный манифест привязывался только к хешу блоба, но не к
   подготовленному URL и не к идентичности запроса;
4. повторное обогащение вызывало проверяющего БЕЗ восстановленного заявления и
   роняло уже подтверждённую идентичность в ``UNKNOWN``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from factories import product

from marko.infrastructure.db.models import MarketObservation, OfferProcessingOutcome
from marko.parsers.prom.gateway import MOTORS_IDENTITY_SOURCE
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.market_collection import (
    ACQUISITION_LINEAGE_COLUMNS,
    _acquisition_capture_binding,
    _persist_payload_observations,
)
from marko.services.matching import ComparisonParams, build_comparison
from marko.services.oe_reenrichment import (
    OeReenrichmentDataError,
    build_reenrichment_patch,
)
from marko.services.offer_identity import (
    ConfirmedCross,
    OeVerificationStatus,
    SourceAssertion,
    canonical_cross_identity_key,
)
from marko.services.offer_processing import (
    ACQUISITION_METHOD_OE_PAGE_LISTING,
    ACQUISITION_METHOD_TEXT_SEARCH,
    ACQUISITION_SOURCE_OE_PAGE,
    ACQUISITION_SOURCE_SEARCH,
    AcceptedCandidate,
    AcquisitionContractError,
    AcquisitionLineage,
    EvidenceAccountingError,
    process_offer_candidate,
)
from marko.services.parser_models import SeedInfo
from marko.services.pricing_runs import policy_from_dict, policy_to_dict
from marko.services.scraper_contract import (
    PROM_ADAPTER_VERSION,
    PROM_OUTPUT_SCHEMA_VERSION,
    RETRIEVAL_KIND_PROM_OE_PAGE,
    RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
    ScrapeInput,
    ScrapeOutput,
    ScraperBoundaryError,
    ScraperErrorCode,
)
from metis.pricing import (
    comparison_evidence_to_dict,
    verified_comparison_evidence,
)

OUR_OE = "1K0615301"
VIA_OE = "1K0615302"
SEED_URL = "https://prom.ua/ua/p1153738393-radiator-folksvagen-tuareg.html"


def _frozen_item(oe: str = OUR_OE):
    return SimpleNamespace(
        category="cooling",
        oe_norm=oe,
        mpn_norm="",
        identity_status="OE_CONFIRMED",
        part_numbers_norm=(),
    )


# --------------------------------------------------------------------------
# Строители
# --------------------------------------------------------------------------


def _seed() -> SeedInfo:
    return SeedInfo(
        product=product(
            id=1, name="Радиатор VW", price="5163", company={"id": 111, "name": "KEMP"}
        ),
        seller_count=2,
        min_price=None,
        max_price=None,
    )


def _offer(index: int = 1, *, title: str = "Радиатор охлаждения", **overrides):
    base = {
        "id": 200 + index,
        "name": title,
        "price": "1100",
        "urlText": "radiator",
        "company": {"id": 900000 + index, "name": f"Магазин {index}"},
    }
    base.update(overrides)
    return product(**base)


def _payload(
    *,
    query: str = OUR_OE,
    identity_source: str | None = MOTORS_IDENTITY_SOURCE,
    via_oe_number: str | None = None,
    is_widened: bool = False,
    seed_url: str = SEED_URL,
    title: str = "Радиатор охлаждения",
) -> dict:
    """Payload ровно в том виде, в каком его отдаёт замороженная граница."""

    comparison = build_comparison(
        _seed(),
        [_offer(title=title)],
        ComparisonParams(
            query=query,
            threshold=0.3,
            max_sellers=10,
            identity_source=identity_source,
            via_oe_number=via_oe_number,
            is_widened=is_widened,
        ),
    )
    scrape_input = ScrapeInput.build(seed_url, query)
    return ScrapeOutput.from_comparison(scrape_input, comparison).payload


# --------------------------------------------------------------------------
# F6.1 — закрытый контракт на границе
# --------------------------------------------------------------------------


def test_a_part_code_retrieval_kind_cannot_arrive_from_a_search() -> None:
    """Воспроизведение дефекта: ``prom_oe_page`` с ``source=SEARCH``.

    Именно эта пара доезжала до персистентности и становилась
    ``VERIFIED_EXACT``: способ извлечения утверждал страницу конкретного
    номера, а происхождение говорило, что это обычный поиск.
    """

    payload = _payload()
    record = payload["output"]["records"][0]
    record["acquisition"]["source"] = ACQUISITION_SOURCE_SEARCH
    record["acquisition"]["method"] = ACQUISITION_METHOD_TEXT_SEARCH

    with pytest.raises(ScraperBoundaryError) as excinfo:
        ScrapeOutput.from_payload(payload)

    assert excinfo.value.code is ScraperErrorCode.ACQUISITION_CONTRACT
    assert "ACQUISITION_SOURCE_CONFLICT" in str(excinfo.value)


def test_an_inconsistent_payload_is_distinct_from_an_empty_market() -> None:
    """Пустой рынок — правдивый ответ; противоречивая запись — не ответ вовсе.

    Раньше и то и другое сводилось к одному коду ``serialization`` или молча
    проходило дальше, и оператор не мог их различить.
    """

    empty = ScrapeOutput.from_payload(
        {
            "schema_version": PROM_OUTPUT_SCHEMA_VERSION,
            "adapter_version": PROM_ADAPTER_VERSION,
            "input": ScrapeInput.build(SEED_URL, OUR_OE).as_dict(),
            "output": {
                "acquisition_outcome": "EMPTY_SEARCH_RESULT",
                "candidates_scanned": 0,
                "records": [],
            },
        }
    )
    assert empty.payload["output"]["acquisition_outcome"] == "EMPTY_SEARCH_RESULT"

    payload = _payload()
    payload["output"]["records"][0]["acquisition"]["source"] = ACQUISITION_SOURCE_SEARCH
    with pytest.raises(ScraperBoundaryError) as excinfo:
        ScrapeOutput.from_payload(payload)

    assert excinfo.value.code is ScraperErrorCode.ACQUISITION_CONTRACT
    assert excinfo.value.code is not ScraperErrorCode.SERIALIZATION


def _mutate_url(record: dict) -> None:
    record["acquisition"]["source_url"] = "https://prom.ua/ua/p999-other.html"


def _mutate_widened_flag_only(record: dict) -> None:
    record["acquisition"]["is_widened"] = True


def _mutate_via_without_widening(record: dict) -> None:
    record["acquisition"]["via_oe_number"] = VIA_OE


def _mutate_input_hash(record: dict) -> None:
    record["acquisition"]["input_hash"] = "f" * 64


def _mutate_retrieval_kind_hides_the_widening(record: dict) -> None:
    record["retrieval_kind"] = RETRIEVAL_KIND_PROM_OE_PAGE


@pytest.mark.parametrize(
    ("mutate", "expected", "widened_payload"),
    (
        (_mutate_url, "ACQUISITION_SOURCE_URL_MISMATCH", False),
        (_mutate_widened_flag_only, "ACQUISITION_VIA_OE_MISSING", False),
        (_mutate_via_without_widening, "ACQUISITION_VIA_OE_NOT_WIDENED", False),
        (_mutate_input_hash, "ACQUISITION_INPUT_HASH_MISMATCH", False),
        (
            _mutate_retrieval_kind_hides_the_widening,
            "ACQUISITION_WIDENING_CONFLICT",
            True,
        ),
    ),
)
def test_the_boundary_refuses_each_inconsistent_combination(
    mutate, expected, widened_payload
) -> None:
    payload = (
        _payload(via_oe_number=VIA_OE, is_widened=True)
        if widened_payload
        else _payload()
    )
    record = payload["output"]["records"][0]
    mutate(record)
    if not widened_payload:
        # Блок уровня выхода приводится в соответствие, чтобы тест проверял
        # именно названную несогласованность, а не расхождение с конвертом.
        payload["output"]["acquisition"] = dict(record["acquisition"])

    with pytest.raises(ScraperBoundaryError) as excinfo:
        ScrapeOutput.from_payload(payload)

    assert excinfo.value.code is ScraperErrorCode.ACQUISITION_CONTRACT
    assert expected in str(excinfo.value)


def test_a_part_code_page_that_names_no_number_is_refused() -> None:
    """Запрошенный номер не восстанавливается ниоткуда, кроме приобретения."""

    with pytest.raises(AcquisitionContractError) as excinfo:
        AcquisitionLineage.validated(
            {
                "source": ACQUISITION_SOURCE_OE_PAGE,
                "method": ACQUISITION_METHOD_OE_PAGE_LISTING,
                "queried_oe_norm": None,
                "is_widened": False,
            },
            retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE,
        )

    assert excinfo.value.code == "ACQUISITION_QUERY_OE_MISSING"


def test_a_record_cannot_disagree_with_the_payloads_own_acquisition() -> None:
    payload = _payload(via_oe_number=VIA_OE, is_widened=True)
    # Запись объявляет наш собственный рынок, конверт — расширенный.
    payload["output"]["records"][0]["retrieval_kind"] = RETRIEVAL_KIND_PROM_OE_PAGE
    payload["output"]["records"][0]["acquisition"]["is_widened"] = False
    payload["output"]["records"][0]["acquisition"]["via_oe_number"] = None

    with pytest.raises(ScraperBoundaryError) as excinfo:
        ScrapeOutput.from_payload(payload)

    assert excinfo.value.code is ScraperErrorCode.ACQUISITION_CONTRACT


def test_the_input_query_cannot_change_without_changing_its_input_hash() -> None:
    payload = _payload()
    payload["input"]["query"] = "DIFFERENT-PART"

    with pytest.raises(ScraperBoundaryError) as excinfo:
        ScrapeOutput.from_payload(payload)

    assert excinfo.value.code is ScraperErrorCode.ACQUISITION_CONTRACT
    assert "input_hash" in str(excinfo.value)


def test_a_part_code_page_without_an_acquisition_block_is_refused() -> None:
    payload = _payload()
    payload["output"]["records"][0].pop("acquisition")
    payload["output"].pop("acquisition")

    with pytest.raises(ScraperBoundaryError) as excinfo:
        ScrapeOutput.from_payload(payload)

    assert "ACQUISITION_BLOCK_MISSING" in str(excinfo.value)


def test_a_valid_widened_acquisition_survives_the_boundary_whole() -> None:
    output = ScrapeOutput.from_payload(_payload(via_oe_number=VIA_OE, is_widened=True))

    candidate = process_offer_candidate(
        output.candidate_records[0],
        fallback_index=0,
        prepared_url=output.prepared_url,
        input_hash=output.input_hash,
        fallback_queried_oe=output.acquisition_query,
    )

    assert isinstance(candidate, AcceptedCandidate)
    assert candidate.acquisition_source == ACQUISITION_SOURCE_OE_PAGE
    assert candidate.acquisition_method == ACQUISITION_METHOD_OE_PAGE_LISTING
    assert candidate.queried_oe_norm == OUR_OE
    assert candidate.via_oe_number == VIA_OE
    assert candidate.is_widened is True
    assert candidate.source_url == SEED_URL
    assert candidate.acquisition_reason_codes == ()


def test_a_generic_search_carries_no_asserted_number() -> None:
    output = ScrapeOutput.from_payload(_payload(identity_source=None))

    candidate = process_offer_candidate(
        output.candidate_records[0],
        fallback_index=0,
        prepared_url=output.prepared_url,
        input_hash=output.input_hash,
        fallback_queried_oe=output.acquisition_query,
    )

    assert isinstance(candidate, AcceptedCandidate)
    assert candidate.acquisition_source == ACQUISITION_SOURCE_SEARCH
    assert candidate.queried_oe_norm is None
    assert candidate.acquisition.asserts_identity is False


# --------------------------------------------------------------------------
# F6.2 — заявление собирается только из родословной
# --------------------------------------------------------------------------


def test_a_source_assertion_is_never_built_from_a_search_lineage() -> None:
    """Способ приобретения решает, а не то, что рядом лежит номер.

    Родословная намеренно собрана вручную с заполненным ``queried_oe_norm``:
    именно так выглядит попытка выдать текстовый поиск за заявление площадки,
    и отказ обязан держаться на ``asserts_identity``, а не на пустом поле.
    """

    search_lineage = AcquisitionLineage(
        source=ACQUISITION_SOURCE_SEARCH,
        method=ACQUISITION_METHOD_TEXT_SEARCH,
        retrieval_kind="search_query",
        is_widened=False,
        queried_oe_norm=OUR_OE,
        via_oe_number=None,
        source_url=SEED_URL,
    )

    assert (
        SourceAssertion.from_lineage(
            search_lineage, capture_sha256="a" * 64, confidence=Decimal("0.9")
        )
        is None
    )

    # И то же самое для родословной, которую граница уже отвергла как
    # противоречивую: она деградирует до ``LEGACY_UNVERIFIED``.
    degraded, reasons = AcquisitionLineage.from_record(
        {
            "source": ACQUISITION_SOURCE_SEARCH,
            "method": ACQUISITION_METHOD_TEXT_SEARCH,
            "is_widened": False,
        },
        retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE,
    )

    assert reasons == ("ACQUISITION_SOURCE_CONFLICT",)
    assert degraded.asserts_identity is False
    assert (
        SourceAssertion.from_lineage(
            degraded, capture_sha256="a" * 64, confidence=Decimal("0.9")
        )
        is None
    )


def test_a_source_assertion_cannot_be_built_without_an_asserted_number() -> None:
    """Пустой ``queried_oe_norm`` — не повод подставить наш собственный номер."""

    lineage = AcquisitionLineage(
        source=ACQUISITION_SOURCE_OE_PAGE,
        method=ACQUISITION_METHOD_OE_PAGE_LISTING,
        retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE,
        is_widened=False,
        queried_oe_norm=None,
        via_oe_number=None,
        source_url=SEED_URL,
    )

    assert (
        SourceAssertion.from_lineage(
            lineage, capture_sha256="a" * 64, confidence=Decimal("0.9")
        )
        is None
    )


def test_a_stated_search_source_defeats_an_asserting_retrieval_kind() -> None:
    """Защита в глубину: даже собранное вручную заявление не авторитетно."""

    assertion = SourceAssertion(
        queried_oe_norm=OUR_OE,
        retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE,
        capture_sha256="a" * 64,
        confidence=Decimal("0.95"),
        acquisition_source=ACQUISITION_SOURCE_SEARCH,
        acquisition_method=ACQUISITION_METHOD_TEXT_SEARCH,
    )

    assert assertion.authoritative_for(OUR_OE) is False


# --------------------------------------------------------------------------
# F6.3 — привязка манифеста к запросу, а не только к байтам
# --------------------------------------------------------------------------


def _manifest(capture_id: str = "capture-1") -> dict[str, str]:
    return {
        "source_record_id": "listing-1",
        "raw_capture_id": capture_id,
        "raw_content_sha256": "b" * 64,
    }


def _lineage(**overrides) -> AcquisitionLineage:
    base = {
        "source": ACQUISITION_SOURCE_OE_PAGE,
        "method": ACQUISITION_METHOD_OE_PAGE_LISTING,
        "retrieval_kind": RETRIEVAL_KIND_PROM_OE_PAGE,
        "is_widened": False,
        "queried_oe_norm": OUR_OE,
        "via_oe_number": None,
        "source_url": SEED_URL,
        "input_hash": "c" * 64,
    }
    base.update(overrides)
    return AcquisitionLineage(**base)


@pytest.mark.parametrize(
    "difference",
    (
        {"source_url": "https://prom.ua/ua/p999-other.html"},
        {"queried_oe_norm": "9Z9999999"},
        {"input_hash": "d" * 64},
    ),
)
def test_the_capture_binding_names_the_request_not_only_the_bytes(difference) -> None:
    """Одинаковые байты плюс разный запрос обязаны давать разную привязку.

    Иначе заявление, законно полученное для одного приобретения, можно
    предъявить за другое: хеш блоба совпадёт.
    """

    same_bytes = _manifest()

    assert _acquisition_capture_binding(
        same_bytes, _lineage()
    ) != _acquisition_capture_binding(same_bytes, _lineage(**difference))


def test_the_capture_binding_is_empty_when_nothing_is_asserted() -> None:
    search = _lineage(
        source=ACQUISITION_SOURCE_SEARCH,
        method=ACQUISITION_METHOD_TEXT_SEARCH,
        retrieval_kind="search_query",
        queried_oe_norm=None,
    )

    assert _acquisition_capture_binding(_manifest(), search) == ""


def test_the_capture_binding_is_empty_without_verified_bytes() -> None:
    unverified = dict(_manifest(), raw_content_sha256="")

    assert _acquisition_capture_binding(unverified, _lineage()) == ""


# --------------------------------------------------------------------------
# F6.4 — персистентность
# --------------------------------------------------------------------------


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


async def _persist(
    payload: dict,
    *,
    catalog_oe: str = OUR_OE,
    catalog_mpn: str = "",
    identity_status: str = "OE_CONFIRMED",
    crosses=(),
):
    output = ScrapeOutput.from_payload(payload)
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
            oe_norm=catalog_oe,
            mpn_norm=catalog_mpn,
            identity_status=identity_status,
            part_numbers_norm=(),
        ),
        capture=SimpleNamespace(
            id=uuid4(),
            parser_version=PROM_ADAPTER_VERSION,
            content_sha256=output.content_sha256,
            payload={
                "raw_evidence": raw_evidence,
                "raw_manifest_sha256": canonical_sha256(raw_evidence),
            },
        ),
        offers=list(output.candidate_records),
        owned_sellers=set(),
        brand_tiers={},
        brand_confidence={},
        observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        source_type="prom_public",
        confirmed_crosses=crosses,
        prepared_url=output.prepared_url,
        acquisition_input_hash=output.input_hash,
        acquisition_query=output.acquisition_query,
        requested_query=output.requested_query,
    )
    return next(
        value for value in session.added if isinstance(value, MarketObservation)
    ), session


@pytest.mark.asyncio
async def test_an_oe_page_offer_is_verified_and_stores_its_whole_lineage() -> None:
    observation, _ = await _persist(_payload())

    assert (
        observation.oe_verification_status == OeVerificationStatus.VERIFIED_EXACT.value
    )
    assert observation.source_assertion_retrieval_kind == RETRIEVAL_KIND_PROM_OE_PAGE
    assert observation.source_assertion_capture_sha256
    assert observation.source_assertion_source == ACQUISITION_SOURCE_OE_PAGE
    assert observation.source_assertion_method == ACQUISITION_METHOD_OE_PAGE_LISTING
    assert observation.source_assertion_queried_oe_norm == OUR_OE
    assert observation.source_assertion_source_url == SEED_URL
    assert observation.source_assertion_input_hash


@pytest.mark.asyncio
async def test_public_identity_never_falls_back_to_private_catalog_code() -> None:
    observation, _ = await _persist(
        _payload(query=OUR_OE),
        catalog_oe="77641257",
        catalog_mpn=OUR_OE,
        identity_status="MPN_ONLY",
    )

    assert observation.search_oe_norm == OUR_OE
    assert (
        observation.oe_verification_status
        == OeVerificationStatus.VERIFIED_EXACT.value
    )
    assert observation.verified_matched_oe_norm == OUR_OE


@pytest.mark.asyncio
async def test_seed_motors_page_on_compatible_oe_does_not_fail_the_item() -> None:
    """Canary OE 578128: the owned card is grouped under a different Prom OE.

    The frozen catalog identity stays 578128. Prom's motors page on that
    listing is 4A0412249 (VAG). Persist used to compare the *page* number to
    the catalog and raise ACQUISITION_QUERY_BINDING_ERROR. The input query
    is still the frozen identity; the page number is retrieval.
    """

    catalog_oe = "578128"
    page_oe = "4A0412249"
    payload = _payload(query=catalog_oe)
    payload["output"]["acquisition"]["queried_oe_norm"] = page_oe
    for record in payload["output"]["records"]:
        record["acquisition"]["queried_oe_norm"] = page_oe
    summary = payload["output"].get("comparison_summary")
    if isinstance(summary, dict):
        summary["query"] = page_oe

    observation, _ = await _persist(payload, catalog_oe=catalog_oe)

    assert observation.search_oe_norm == catalog_oe
    assert (
        observation.source_assertion_queried_oe_norm == page_oe
        or observation.source_assertion_queried_oe_norm is None
    )


@pytest.mark.asyncio
async def test_persistence_refuses_query_not_bound_to_frozen_identity() -> None:
    with pytest.raises(
        EvidenceAccountingError,
        match="ACQUISITION_QUERY_BINDING_ERROR",
    ):
        await _persist(_payload(query=OUR_OE), catalog_oe="DIFFERENT-PART")


@pytest.mark.asyncio
async def test_the_asserted_query_is_never_taken_from_the_catalog() -> None:
    """Ключевой дефект F6: площадка спрашивалась про ДРУГОЙ номер.

    Раньше ``queried_oe_norm`` заявления брался из ``CatalogItem.oe_norm``,
    поэтому страница чужого кода объявляла нашу идентичность подтверждённой.
    """

    with pytest.raises(
        EvidenceAccountingError,
        match="ACQUISITION_QUERY_BINDING_ERROR",
    ):
        await _persist(_payload(query="9Z9999999"), catalog_oe=OUR_OE)


@pytest.mark.asyncio
async def test_a_generic_search_persists_every_assertion_field_null() -> None:
    observation, _ = await _persist(_payload(identity_source=None))

    assert observation.source_assertion_retrieval_kind is None
    assert observation.source_assertion_capture_sha256 is None
    assert observation.source_assertion_confidence is None
    assert observation.via_oe_number is None
    for column in ACQUISITION_LINEAGE_COLUMNS:
        assert getattr(observation, column) is None, column


@pytest.mark.asyncio
async def test_a_widened_market_needs_a_proven_relation_to_be_a_cross() -> None:
    without_proof, _ = await _persist(_payload(via_oe_number=VIA_OE, is_widened=True))

    assert without_proof.oe_verification_status == OeVerificationStatus.UNKNOWN.value

    cross_id = uuid4()
    with_proof, _ = await _persist(
        _payload(via_oe_number=VIA_OE, is_widened=True),
        crosses=(
            ConfirmedCross(
                search_oe_norm=OUR_OE,
                candidate_oe_norm=VIA_OE,
                canonical_identity_key=canonical_cross_identity_key(OUR_OE, VIA_OE),
                confidence=Decimal("0.94"),
                cross_link_id=str(cross_id),
            ),
        ),
    )

    assert (
        with_proof.oe_verification_status == OeVerificationStatus.VERIFIED_CROSS.value
    )
    assert with_proof.verified_matched_oe_norm == VIA_OE
    assert with_proof.via_oe_number == VIA_OE
    assert (
        with_proof.source_assertion_retrieval_kind
        == RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED
    )
    assert with_proof.cross_link_id == cross_id


@pytest.mark.asyncio
async def test_a_source_url_mismatch_loses_the_claim_but_keeps_the_market() -> None:
    """Родословная, не сходящаяся с подготовленным URL, не утверждает ничего."""

    payload = _payload()
    # Payload проходит границу, а затем URL записи расходится с конвертом —
    # ровно так выглядит смешение двух приобретений в одном хранилище.
    output_records = payload["output"]["records"]
    output_records[0]["acquisition"]["source_url"] = "https://prom.ua/ua/p1-other.html"
    observation, session = await _persist_mutated(payload)

    assert observation.source_assertion_retrieval_kind is None
    assert (
        observation.oe_verification_status != OeVerificationStatus.VERIFIED_EXACT.value
    )
    outcome = next(
        value
        for value in session.added
        if isinstance(value, OfferProcessingOutcome) and value.stage == "persistence"
    )
    assert "ACQUISITION_SOURCE_URL_MISMATCH" in outcome.reason_codes


async def _persist_mutated(payload: dict):
    """Персистентность записей, которые уже НЕ прошли бы границу.

    Существует потому, что защита обязана держаться и на втором рубеже: часть
    удержанных payload-ов старше контракта.
    """

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
            oe_norm=OUR_OE,
            mpn_norm="",
            identity_status="OE_CONFIRMED",
            part_numbers_norm=(),
        ),
        capture=SimpleNamespace(
            id=uuid4(),
            parser_version=PROM_ADAPTER_VERSION,
            content_sha256=canonical_sha256(payload),
            payload={
                "raw_evidence": raw_evidence,
                "raw_manifest_sha256": canonical_sha256(raw_evidence),
            },
        ),
        offers=list(payload["output"]["records"]),
        owned_sellers=set(),
        brand_tiers={},
        brand_confidence={},
        observed_at=datetime(2026, 8, 1, tzinfo=UTC),
        source_type="prom_public",
        prepared_url=SEED_URL,
        acquisition_input_hash=ScrapeInput.build(SEED_URL, OUR_OE).input_hash,
        acquisition_query=OUR_OE,
    )
    return next(
        value for value in session.added if isinstance(value, MarketObservation)
    ), session


# --------------------------------------------------------------------------
# F6.5 — повторное обогащение сохраняет идентичность
# --------------------------------------------------------------------------


def _reenrichment_inputs(payload: dict, observation_overrides: dict | None = None):
    raw_evidence = [{"logical_request_id": "request-1", "raw_content_sha256": "b" * 64}]
    structured = dict(payload)
    structured["raw_evidence"] = raw_evidence
    structured["raw_manifest_sha256"] = canonical_sha256(raw_evidence)
    capture = SimpleNamespace(id=uuid4(), payload=structured)
    manifest = {
        "source_record_id": "201",
        "raw_capture_id": str(capture.id),
        "raw_content_sha256": canonical_sha256(raw_evidence),
    }
    output = ScrapeOutput.from_payload(payload)
    candidate = process_offer_candidate(
        output.candidate_records[0],
        fallback_index=0,
        prepared_url=output.prepared_url,
        input_hash=output.input_hash,
        fallback_queried_oe=output.acquisition_query,
    )
    binding = _acquisition_capture_binding(manifest, candidate.acquisition)
    observation = SimpleNamespace(
        source_listing_id="201",
        search_oe_norm=OUR_OE,
        comparison_evidence=comparison_evidence_to_dict(
            verified_comparison_evidence(
                stable_seller_id="900001",
                source_record_id="201",
            )
        ),
        seller_id="900001",
        currency_raw="UAH",
        currency="UAH",
        seller_identity_verified=True,
        source_provenance_verified=True,
        source_confidence=Decimal("1"),
        source_assertion_retrieval_kind=candidate.acquisition.retrieval_kind,
        source_assertion_capture_sha256=binding,
        source_assertion_confidence=Decimal("0.90"),
        via_oe_number=candidate.via_oe_number,
    )
    for key, value in (observation_overrides or {}).items():
        setattr(observation, key, value)
    return observation, capture, structured


def test_re_enrichment_preserves_an_exact_identity_it_can_revalidate() -> None:
    """Дефект: проверяющий вызывался без заявления, и ``VERIFIED_EXACT`` падал."""

    observation, capture, structured = _reenrichment_inputs(_payload())

    patch = build_reenrichment_patch(
        observation=observation,
        frozen_item=_frozen_item(),
        capture=capture,
        run=SimpleNamespace(policy_config={}),
        structured_payload=structured,
    )

    assert patch.oe_verification_status == OeVerificationStatus.VERIFIED_EXACT.value
    assert patch.verified_matched_oe_norm == OUR_OE


def test_re_enrichment_preserves_a_widened_identity_with_its_proven_relation() -> None:
    payload = _payload(via_oe_number=VIA_OE, is_widened=True)
    observation, capture, structured = _reenrichment_inputs(payload)
    cross_id = uuid4()

    patch = build_reenrichment_patch(
        observation=observation,
        frozen_item=_frozen_item(),
        capture=capture,
        run=SimpleNamespace(policy_config={}),
        structured_payload=structured,
        confirmed_crosses=(
            ConfirmedCross(
                search_oe_norm=OUR_OE,
                candidate_oe_norm=VIA_OE,
                canonical_identity_key=canonical_cross_identity_key(OUR_OE, VIA_OE),
                confidence=Decimal("0.94"),
                cross_link_id=str(cross_id),
            ),
        ),
    )

    assert patch.oe_verification_status == OeVerificationStatus.VERIFIED_CROSS.value
    assert patch.verified_matched_oe_norm == VIA_OE
    assert patch.via_cross is True
    assert patch.cross_link_id == cross_id


def test_re_enrichment_never_promotes_a_row_that_carried_no_assertion() -> None:
    observation, capture, structured = _reenrichment_inputs(
        _payload(),
        {
            "source_assertion_retrieval_kind": None,
            "source_assertion_capture_sha256": None,
            "source_assertion_confidence": None,
        },
    )

    patch = build_reenrichment_patch(
        observation=observation,
        frozen_item=_frozen_item(),
        capture=capture,
        run=SimpleNamespace(policy_config={}),
        structured_payload=structured,
    )

    assert patch.oe_verification_status == OeVerificationStatus.UNKNOWN.value
    assert patch.automatic_eligible is False


@pytest.mark.parametrize(
    ("override", "code"),
    (
        (
            {"source_assertion_capture_sha256": "e" * 64},
            "REENRICHMENT_ASSERTION_CAPTURE_MISMATCH",
        ),
        (
            {"source_assertion_retrieval_kind": RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED},
            "REENRICHMENT_ASSERTION_CONFLICT",
        ),
        (
            {"source_assertion_confidence": None},
            "REENRICHMENT_ASSERTION_INCOMPLETE",
        ),
        ({"via_oe_number": "9Z9999999"}, "REENRICHMENT_ASSERTION_CONFLICT"),
    ),
)
def test_re_enrichment_fails_closed_on_a_conflicting_assertion(override, code) -> None:
    observation, capture, structured = _reenrichment_inputs(_payload(), override)

    with pytest.raises(OeReenrichmentDataError, match=code):
        build_reenrichment_patch(
            observation=observation,
            frozen_item=_frozen_item(),
            capture=capture,
            run=SimpleNamespace(policy_config={}),
            structured_payload=structured,
        )


def test_re_enrichment_refuses_a_frozen_position_naming_another_number() -> None:
    """F4: замороженная позиция и наблюдение обязаны говорить об одном номере."""

    observation, capture, structured = _reenrichment_inputs(_payload())

    with pytest.raises(
        OeReenrichmentDataError, match="REENRICHMENT_FROZEN_OE_CONFLICT"
    ):
        build_reenrichment_patch(
            observation=observation,
            frozen_item=_frozen_item("9Z9999999"),
            capture=capture,
            run=SimpleNamespace(policy_config={}),
            structured_payload=structured,
        )


def test_the_validated_lineage_refuses_a_widening_to_the_same_number() -> None:
    with pytest.raises(AcquisitionContractError) as excinfo:
        AcquisitionLineage.validated(
            {
                "source": ACQUISITION_SOURCE_OE_PAGE,
                "method": ACQUISITION_METHOD_OE_PAGE_LISTING,
                "queried_oe_norm": OUR_OE,
                "via_oe_number": OUR_OE,
                "is_widened": True,
            },
            retrieval_kind=RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
        )

    assert excinfo.value.code == "ACQUISITION_WIDENING_WITHOUT_A_DIFFERENT_NUMBER"
