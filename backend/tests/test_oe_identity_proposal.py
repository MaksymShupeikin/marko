"""Цепочка «предложить — подтвердить — использовать» для карточки без номера.

Связка каталогов 22.08 закрыла 1 015 карточек бесплатно, но все они в одном
магазине из четырёх. У оставшихся 25 671 кодов запчастей нет вовсе, и модель —
единственный оставшийся источник. Она же и самый опасный: спрошенная про номер
детали, она назовёт его всегда.

Поэтому предложение здесь ничего не решает само: пока независимый источник не
подтвердил номер, карточка остаётся такой, какой была, и ищет по названию.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from marko.core.config import Settings
from marko.services.oe_identity_proposal import (
    MAX_PROPOSED_NUMBERS,
    build_oe_proposal_input,
    resolve_card_identity,
    sanitize_proposed_numbers,
)


def _settings() -> Settings:
    return Settings(_env_file=None)


_CARD = {
    "sku": "2141006",
    "name": "(6шт) Шпилька \\ болт передньої ступиці (колісна) Mercedes 509",
    "brand": "Mercedes-Benz",
    "characteristics_raw": {"Стан": "Вживаний", "Тип запчастини": "Оригінал"},
    "current_price": "720.00",
    "cost": "410.00",
    "recommended_price": "655",
}


def test_the_question_never_shows_the_model_our_money() -> None:
    payload = build_oe_proposal_input(_CARD)

    serialized = str(payload)
    assert "720.00" not in serialized
    assert "410.00" not in serialized
    assert "655" not in serialized
    assert payload["our_product"]["brand"] == "Mercedes-Benz"
    assert payload["our_product"]["characteristics_raw"]["Стан"] == "Вживаний"


def test_the_shop_article_travels_labelled_as_unproven() -> None:
    payload = build_oe_proposal_input(_CARD)

    assert payload["our_product"]["seller_article_unverified"] == "2141006"
    assert "sku" not in payload["our_product"]


def test_a_private_kemp_code_is_not_even_shown_as_a_hint() -> None:
    payload = build_oe_proposal_input({**_CARD, "sku": "776414"})

    assert "776414" not in str(payload)


def test_the_question_invites_an_empty_answer() -> None:
    """Иначе модель предпочтёт правдоподобную догадку молчанию."""

    payload = build_oe_proposal_input(_CARD)

    assert "empty list" in payload["question"]


def test_private_codes_and_stubs_are_refused_before_the_source_is_asked() -> None:
    kept, refused = sanitize_proposed_numbers(["776414", "12", "357905851D", ""])

    assert kept == ("357905851D",)
    assert refused == (("776414", "PRIVATE_KEMP_CODE"), ("12", "TOO_SHORT_TO_BE_A_PART_NUMBER"))


def test_duplicates_collapse_and_the_list_is_bounded() -> None:
    kept, _ = sanitize_proposed_numbers(
        ["A1234", "a1234", "B1234", "C1234", "D1234", "E1234", "F1234"]
    )

    assert kept[0] == "A1234"
    assert len(kept) == MAX_PROPOSED_NUMBERS


def _confirmation(number: str, confirmed: bool) -> SimpleNamespace:
    return SimpleNamespace(
        number=number,
        confirmed=confirmed,
        source_url=f"https://spareto.com/oe/{number}",
        headline="",
    )


@pytest.mark.asyncio
async def test_an_unconfirmed_proposal_never_becomes_identity() -> None:
    async def _propose(_payload: dict) -> list[str]:
        return ["A0009901411", "1234567"]

    outcome = await resolve_card_identity(
        _CARD,
        settings=_settings(),
        propose=_propose,
        confirm=lambda number, **_: _confirmation(number, False),
    )

    assert outcome.confirmed_number is None
    assert outcome.is_usable is False
    assert len(outcome.confirmations) == 2


@pytest.mark.asyncio
async def test_the_first_confirmed_number_settles_it_and_stops_the_asking() -> None:
    async def _propose(_payload: dict) -> list[str]:
        return ["WRONG123", "93818439", "ALSO456"]

    asked: list[str] = []

    def _confirm(number: str, **_: object) -> SimpleNamespace:
        asked.append(number)
        return _confirmation(number, number == "93818439")

    outcome = await resolve_card_identity(
        _CARD, settings=_settings(), propose=_propose, confirm=_confirm
    )

    assert outcome.confirmed_number == "93818439"
    assert outcome.is_usable is True
    # Третий номер не спрашивали: один доказанный номер — это идентичность.
    assert asked == ["WRONG123", "93818439"]


@pytest.mark.asyncio
async def test_a_silent_model_leaves_the_card_exactly_as_it_was() -> None:
    async def _propose(_payload: dict) -> list[str]:
        return []

    outcome = await resolve_card_identity(
        _CARD,
        settings=_settings(),
        propose=_propose,
        confirm=lambda number, **_: _confirmation(number, True),
    )

    assert outcome.proposed == ()
    assert outcome.confirmed_number is None
