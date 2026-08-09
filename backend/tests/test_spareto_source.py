"""spareto.com как источник: страница поиска по номеру, а не карточка товара.

Источник отвечает на один вопрос — «какая деталь носит этот номер» — и отвечает
заголовком вида ``<номер> - <тип детали> OE number by<МАРКИ>``. Номера внутри
блока марок это эхо нашего запроса, поэтому в граф попадает ровно один номер:
тот, о котором страница и была запрошена.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from marko.services.catalog_identity_reparse import (
    CatalogIdentityReparseError,
    build_source_index,
    load_spareto_source,
    plan_identity,
)
from marko.services.catalog_discovery import resolve_backend_path
from metis.pricing.identity_graph import load_identity_graph_config
from metis.pricing.kemp_reference import load_article_brand_kinds
from metis.pricing.kemp_site import load_kemp_site_tokens

HEADER = "mpn,number_raw,source_url,page_headline,checked_at\n"
_HEAD = "035103383J - Gasket OE number by AUDI, CUPRA, SEAT, SKODA, VW"


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "spareto.csv"
    path.write_text(HEADER + body, encoding="utf-8")
    return path


def test_a_confirmed_number_becomes_one_source_statement(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        f"776476,035103383J,https://spareto.com/oe/035103383j,{_HEAD},2026-08-08\n",
    )
    grouped, skipped = load_spareto_source(path)
    assert skipped == 0
    assert grouped["776476"].numbers == ("035103383J",)
    assert grouped["776476"].extraction_method == "SPARETO_OE_PAGE"


def test_the_url_must_be_the_page_for_that_very_number(tmp_path: Path) -> None:
    """Адрес, не совпадающий с номером, — не доказательство, а описка."""

    path = _write(
        tmp_path,
        f"776476,035103383J,https://spareto.com/oe/1603164,{_HEAD},2026-08-08\n",
    )
    with pytest.raises(CatalogIdentityReparseError, match="unbound"):
        load_spareto_source(path)


def test_a_foreign_host_is_refused(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        f"776476,035103383J,https://example.com/oe/035103383j,{_HEAD},2026-08-08\n",
    )
    with pytest.raises(CatalogIdentityReparseError, match="untrusted"):
        load_spareto_source(path)


def test_a_page_without_the_oe_block_is_not_a_confirmation(tmp_path: Path) -> None:
    """«Search results for …» — это «не знаю», а не «да»."""

    path = _write(
        tmp_path,
        "77648039,VKBA3624,https://spareto.com/oe/vkba3624,Search results for vkba3624,2026-08-08\n",
    )
    grouped, skipped = load_spareto_source(path)
    assert grouped == {}
    assert skipped == 1


def test_our_internal_code_is_never_admitted_as_an_oe(tmp_path: Path) -> None:
    head = "77641028 - Gasket OE number by VW"
    path = _write(
        tmp_path, f"77641028,77641028,https://spareto.com/oe/77641028,{head},2026-08-08\n"
    )
    grouped, skipped = load_spareto_source(path)
    assert grouped == {}
    assert skipped == 1


def test_the_shipped_dataset_loads_and_every_row_is_bound() -> None:
    grouped, skipped = load_spareto_source(
        resolve_backend_path("data/spareto_oe_confirmations.csv")
    )
    assert skipped == 0
    assert len(grouped) >= 340


def test_a_second_asserting_voice_opens_positions_that_one_voice_could_not() -> None:
    """Ради этого источник и заводится: правило «двух голосов» из графа."""

    config = load_identity_graph_config(resolve_backend_path("config/identity_graph.yaml"))
    kinds = load_article_brand_kinds(resolve_backend_path("config/article_brand_kinds.yaml"))
    tokens = load_kemp_site_tokens(resolve_backend_path("config/kemp_site_tokens.yaml"))
    refs = [
        resolve_backend_path("data/kemp_reference_map.csv"),
        resolve_backend_path("data/kemp_oe_map.csv"),
    ]
    site = resolve_backend_path("data/kemp_site_numbers.csv")
    spareto = resolve_backend_path("data/spareto_oe_confirmations.csv")

    def plans(**extra: object) -> dict[str, object]:
        index = build_source_index(
            config=config, kinds=kinds, tokens=tokens,
            reference_paths=refs, site_path=site, **extra,
        )
        return {
            code: plan_identity(
                own_code=code, part_numbers_raw=(), current_oe_norm="",
                index=index, config=config, tokens=tokens,
            )
            for code in index.by_code
        }

    before, after = plans(), plans(spareto_paths=[spareto])
    opened = {c for c in before if before[c].identity_status != "OE_CONFIRMED"
              and after[c].identity_status == "OE_CONFIRMED"}
    closed = {c for c in before if before[c].identity_status == "OE_CONFIRMED"
              and after[c].identity_status != "OE_CONFIRMED"}

    assert len(opened) >= 150  # 355 подтверждений давали 181; 443 дают больше

    # Закрыться позиция может, но только громко. Каждая закрывшаяся — половина
    # группы кодов, под которыми у заказчика заведён один и тот же товар:
    # «Ролик паразитный ремня ГРМ Audi 1.9-2.3 5цил (27.4*68.7*8)» под двумя
    # номерами, «Ролик паразитный ремня поликлинового MB Sprinter Vito 638» под
    # четырьмя. Подтверждение одного из группы навешивает общий публичный номер
    # на всех, и аномалия здесь права: разбирать дубликаты должен человек.
    # Молча, без аномалии, не должна закрываться ни одна.
    #
    # Граница поднята с 5 до 7 после этапа 7 (2026-08-09, +88 подтверждений):
    # две новые — из группы «Ролик паразитный MB Sprinter», тот же случай.
    # Двигать её дальше можно только так же: разобрав каждую новую поимённо.
    assert len(closed) <= 7, sorted(closed)
    for code in closed:
        assert "PUBLIC_NUMBER_SEMANTIC_FANOUT" in after[code].graph.anomalies


def test_every_confirmed_code_is_a_code_the_reference_book_knows() -> None:
    """Подтверждение, легшее на несуществующий код, не подтверждает ничего.

    Коды заказчика хранятся как написаны, и часть из них с пробелом:
    ``7764 7180``. Если записать подтверждение под ``77647180``, оно заведёт в
    индексе новый ключ и повиснет рядом с позицией, которую должно было
    открыть. Именно это и случилось на приёме этапа 7 — 21 строка из 88.
    """

    config = load_identity_graph_config(resolve_backend_path("config/identity_graph.yaml"))
    kinds = load_article_brand_kinds(resolve_backend_path("config/article_brand_kinds.yaml"))
    tokens = load_kemp_site_tokens(resolve_backend_path("config/kemp_site_tokens.yaml"))
    index = build_source_index(
        config=config,
        kinds=kinds,
        tokens=tokens,
        reference_paths=[
            resolve_backend_path("data/kemp_reference_map.csv"),
            resolve_backend_path("data/kemp_oe_map.csv"),
        ],
        site_path=resolve_backend_path("data/kemp_site_numbers.csv"),
    )
    known = set(index.by_code)

    with resolve_backend_path("data/spareto_oe_confirmations.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        codes = {row["mpn"] for row in csv.DictReader(handle)}

    assert codes <= known, sorted(codes - known)[:10]
