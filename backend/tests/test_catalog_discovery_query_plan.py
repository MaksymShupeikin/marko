"""Чем система ищет конкурентов и что этот поиск вправе доказать.

Карточка `2141006` («шпилька ступиці Mercedes 509») 22.08.2026 собрала 99
объявлений, и все 99 отклонены воротами: `OEM_CONFLICT` 87, `USED` 5,
`BRAND_MISMATCH` 4, `OEM_NOT_FOUND` 2, `CATEGORY_NOT_AUTOPARTS` 1. Приехали
противоскользящая накладка для ступеней бассейна Emaux и каскад маслозаливних
кришок BMW — всё, что содержит то же число.

Ворота отработали правильно; неверен был запрос. У карточки нет ни OE, ни
MPN, поэтому поиск уходил голым `sku` — внутренним артикулом магазина.
Артикул продавца ничего не утверждает о детали: это его собственное поле, а
не номер производителя.

План поиска строится **после** разрешения приватного кода
(`_resolve_private_catalog_discovery_query`), поэтому получает уже готовый
`resolved_query` и не подменяет ту логику.
"""

from __future__ import annotations

import pytest

from marko.services.catalog_discovery import (
    CATALOG_DISCOVERY_QUERY_MPN,
    CATALOG_DISCOVERY_QUERY_OE,
    CATALOG_DISCOVERY_QUERY_SELLER_ARTICLE,
    CATALOG_DISCOVERY_QUERY_TITLE_BRAND,
    CatalogDiscoveryError,
    catalog_discovery_search_plan,
)


_TITLE = "(6шт) Шпилька \\ болт передньої ступиці (колісна) Mercedes 509"


def test_oe_stays_both_the_identity_and_the_search() -> None:
    plan = catalog_discovery_search_plan(
        resolved_query="93818439",
        sku="2141006",
        oe="93818439",
        mpn=None,
        title=_TITLE,
        brand="Mercedes-Benz",
    )

    assert plan.kind == CATALOG_DISCOVERY_QUERY_OE
    assert plan.search_query == "93818439"
    assert plan.identity_query == "93818439"
    assert plan.identity_bearing is True
    assert plan.discovery_queries == ()


def test_mpn_keeps_its_existing_status() -> None:
    """11 689 карточек магазина живут на MPN — их поведение не меняется."""

    plan = catalog_discovery_search_plan(
        resolved_query="BKOBM008",
        sku="2141006",
        oe=None,
        mpn="BKO-BM-008",
        title=_TITLE,
        brand="NTY",
    )

    assert plan.kind == CATALOG_DISCOVERY_QUERY_MPN
    assert plan.search_query == "BKOBM008"
    assert plan.identity_query == "BKOBM008"
    assert plan.identity_bearing is True


def test_private_code_resolved_to_a_public_number_keeps_its_identity() -> None:
    """Разрешение приватного кода в публичный номер не трогается планом."""

    plan = catalog_discovery_search_plan(
        resolved_query="357905851D",
        sku="776414",
        oe=None,
        mpn=None,
        title=_TITLE,
        brand="Volkswagen",
    )

    assert plan.search_query == "357905851D"
    assert plan.identity_query == "357905851D"
    assert plan.identity_bearing is True


def test_seller_article_is_replaced_by_the_title_and_brand() -> None:
    plan = catalog_discovery_search_plan(
        resolved_query="2141006",
        sku="2141006",
        oe=None,
        mpn=None,
        title=_TITLE,
        brand="Mercedes-Benz",
    )

    assert plan.kind == CATALOG_DISCOVERY_QUERY_TITLE_BRAND
    assert "Шпилька" in plan.search_query
    assert "Mercedes-Benz" in plan.search_query
    assert plan.search_query != "2141006"
    # Артикул продавца ничего не доказывает: поиск по нему не может объявить
    # кандидата подтверждённым.
    assert plan.identity_query == ""
    assert plan.identity_bearing is False
    # Искать по нему всё ещё полезно — иногда это настоящий номер поставщика.
    # Он идёт отдельной дорожкой «только retrieval», которая не даёт цены.
    assert plan.discovery_queries == ("2141006",)


def test_seller_article_survives_as_last_resort_and_still_proves_nothing() -> None:
    plan = catalog_discovery_search_plan(
        resolved_query="2141006",
        sku="2141006",
        oe=None,
        mpn=None,
        title=None,
        brand=None,
    )

    assert plan.kind == CATALOG_DISCOVERY_QUERY_SELLER_ARTICLE
    assert plan.search_query == "2141006"
    assert plan.identity_query == ""
    assert plan.identity_bearing is False


def test_private_kemp_code_never_reaches_a_public_query() -> None:
    plan = catalog_discovery_search_plan(
        resolved_query="2141006",
        sku="776414",
        oe=None,
        mpn=None,
        title=_TITLE,
        brand="Mercedes-Benz",
    )

    assert "776414" not in plan.search_query
    assert plan.discovery_queries == ()


def test_private_kemp_code_is_stripped_out_of_the_title_phrase() -> None:
    plan = catalog_discovery_search_plan(
        resolved_query="1153724217",
        sku="1153724217",
        oe=None,
        mpn=None,
        title="Шрус Audi-100 776427 A6 91-97",
        brand="Audi",
    )

    assert "776427" not in plan.search_query
    assert "Шрус" in plan.search_query


def test_empty_resolution_is_refused() -> None:
    with pytest.raises(CatalogDiscoveryError) as excinfo:
        catalog_discovery_search_plan(
            resolved_query="", sku=None, oe=None, mpn=None, title=None, brand=None
        )

    assert excinfo.value.code == "CATALOG_DISCOVERY_IDENTIFIER_REQUIRED"


def test_packaging_and_synonym_noise_is_stripped_from_the_phrase() -> None:
    """«(6шт) … \\ болт … (колісна)» уводил поиск на колісні проставки."""

    plan = catalog_discovery_search_plan(
        resolved_query="2141006",
        sku="2141006",
        oe=None,
        mpn=None,
        title=_TITLE,
        brand="Mercedes-Benz",
    )

    assert "6шт" not in plan.search_query
    assert "(" not in plan.search_query
    assert "\\" not in plan.search_query
    assert "колісна" not in plan.search_query
    assert "Шпилька" in plan.search_query
    assert "ступиці" in plan.search_query
    assert "Mercedes 509" in plan.search_query


def test_search_phrase_stays_bounded() -> None:
    plan = catalog_discovery_search_plan(
        resolved_query="2141006",
        sku="2141006",
        oe=None,
        mpn=None,
        title="деталь " * 200,
        brand="Mercedes-Benz",
    )

    assert len(plan.search_query) <= 255
