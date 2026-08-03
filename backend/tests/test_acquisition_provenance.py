"""Провенанс приобретения обязан пережить границу обработки предложения.

Ревью 2026-08-01 (второй проход): ``AcceptedCandidate`` нёс только
``retrieval_kind``, поэтому номер, по которому взят рынок, терялся на самой
границе — ``market_collection`` читал ``via_oe_number`` и всегда получал
``None``. Расширенный кросс при этом объявлялся подтверждённым, не называя, чем
он подтверждён.
"""

from __future__ import annotations

from decimal import Decimal

from factories import product
from marko.parsers.prom.gateway import MOTORS_IDENTITY_SOURCE
from marko.services.matching import ComparisonParams, build_comparison
from marko.services.offer_processing import AcceptedCandidate, process_offer_candidate
from marko.services.parser_models import SeedInfo
from marko.services.scraper_contract import ScrapeInput, ScrapeOutput


def _record(*, via_oe_number: str | None, is_widened: bool, drop_block: bool = False):
    """Запись оффера ровно в том виде, в каком её отдаёт замороженная граница."""

    seed = SeedInfo(
        product=product(
            id=1, name="Радиатор VW", price="5163", company={"id": 111, "name": "KEMP"}
        ),
        seller_count=2,
        min_price=None,
        max_price=None,
    )
    comparison = build_comparison(
        seed,
        [
            product(
                id=200,
                name="Радиатор VW",
                price="1100",
                urlText="radiator",
                company={"id": 900001, "name": "Магазин"},
            )
        ],
        ComparisonParams(
            query="7L6121253",
            threshold=0.3,
            max_sellers=10,
            identity_source=MOTORS_IDENTITY_SOURCE,
            via_oe_number=via_oe_number,
            is_widened=is_widened,
        ),
    )
    scrape_input = ScrapeInput.build(
        "https://prom.ua/ua/p1153738393-radiator.html", "7L6121253"
    )
    record = dict(
        ScrapeOutput.from_comparison(scrape_input, comparison).payload["output"][
            "records"
        ][0]
    )
    if drop_block:
        record.pop("acquisition", None)
    return record


def test_the_candidate_keeps_the_number_the_market_was_taken_by() -> None:
    candidate = process_offer_candidate(
        _record(via_oe_number="7L6121253C", is_widened=True), fallback_index=0
    )

    assert isinstance(candidate, AcceptedCandidate)
    assert candidate.via_oe_number == "7L6121253C"
    assert candidate.is_widened is True


def test_an_unwidened_listing_carries_no_via_number() -> None:
    candidate = process_offer_candidate(
        _record(via_oe_number=None, is_widened=False), fallback_index=0
    )

    assert isinstance(candidate, AcceptedCandidate)
    assert candidate.via_oe_number is None
    assert candidate.is_widened is False


def test_a_widened_claim_without_a_via_number_is_not_widened() -> None:
    """Расширение без названного номера — заявление без содержания.

    Пропустить его значит объявить кросс, не сказав, к чему он относится.
    """

    record = _record(via_oe_number="7L6121253C", is_widened=True)
    record["acquisition"] = dict(record["acquisition"], via_oe_number="   ")
    candidate = process_offer_candidate(record, fallback_index=0)

    assert isinstance(candidate, AcceptedCandidate)
    assert candidate.via_oe_number is None
    assert candidate.is_widened is False


def test_a_missing_acquisition_block_is_not_an_error() -> None:
    candidate = process_offer_candidate(
        _record(via_oe_number=None, is_widened=False, drop_block=True),
        fallback_index=0,
    )

    assert isinstance(candidate, AcceptedCandidate)
    assert candidate.via_oe_number is None
    assert candidate.is_widened is False
    assert candidate.price == Decimal("1100")
