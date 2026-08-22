"""Предложенный номер не становится фактом, пока его не подтвердил источник.

Модель, которую просят назвать номер детали, назовёт его всегда — в том числе
когда не знает. Поэтому у карточки без OE предложение и подтверждение — два
разных шага, и в `oe_norm` попадает только подтверждённое.

Правило подтверждения не выдумано здесь: оно уже принято в
`catalog_identity_reparse` для оффлайновой выгрузки spareto, которая дала
+178 подтверждённых кодов. Страница `https://spareto.com/oe/<номер>` считается
подтверждением, только если её заголовок имеет вид
``<номер> - <типы> OE number by<МАРКИ>``. Заголовок «Search results for …» —
это ответ «такого оригинального номера я не знаю».
"""

from __future__ import annotations

import pytest

from marko.services.oe_number_confirmation import (
    OeNumberConfirmation,
    headline_confirms_number,
    spareto_oe_url,
)


def test_url_is_built_from_the_number_and_nothing_else() -> None:
    assert spareto_oe_url("357905851D") == "https://spareto.com/oe/357905851D"


def test_a_private_kemp_code_is_never_asked_about() -> None:
    """Приватный код магазина не уходит во внешний запрос ни при каких условиях."""

    with pytest.raises(ValueError):
        spareto_oe_url("776414")


def test_an_empty_number_is_refused() -> None:
    with pytest.raises(ValueError):
        spareto_oe_url("   ")


def test_the_headline_block_confirms_the_number_it_names() -> None:
    headline = "357905851D - Ignition Lock Housing OE number by VW, AUDI, SEAT"

    assert headline_confirms_number(headline, "357905851D") is True


def test_spacing_and_case_do_not_break_the_binding() -> None:
    headline = "3579 05 851 d - Ignition Lock Housing OE number by VW"

    assert headline_confirms_number(headline, "357905851D") is True


def test_a_search_results_page_confirms_nothing() -> None:
    assert headline_confirms_number("Search results for 12345678", "12345678") is False


def test_a_headline_about_another_number_confirms_nothing() -> None:
    headline = "1K0615301AA - Brake Disc OE number by VW"

    assert headline_confirms_number(headline, "357905851D") is False


def test_an_empty_page_confirms_nothing() -> None:
    assert headline_confirms_number("", "357905851D") is False
    assert headline_confirms_number(None, "357905851D") is False


def test_confirmation_carries_its_own_evidence() -> None:
    confirmation = OeNumberConfirmation(
        number="357905851D",
        confirmed=True,
        source_url="https://spareto.com/oe/357905851D",
        headline="357905851D - Ignition Lock Housing OE number by VW",
    )

    assert confirmation.confirmed is True
    # Оператор и покупатель обязаны видеть, ЧЕМ подтверждено, а не только что.
    assert confirmation.source_url.endswith("/oe/357905851D")
    assert "OE number by" in confirmation.headline


def test_an_unconfirmed_number_says_so_plainly() -> None:
    confirmation = OeNumberConfirmation(
        number="99999999",
        confirmed=False,
        source_url="https://spareto.com/oe/99999999",
        headline="Search results for 99999999",
    )

    assert confirmation.confirmed is False
