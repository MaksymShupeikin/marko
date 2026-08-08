"""Аномалия на ребре не есть аномалия на якоре.

Ворота, пускающие номер в колонку OE, до сих пор смотрели на `graph.anomalies`
— множество, собранное по **всему** графу. Из-за этого позиция, у которой
справочник уверенно назвал оригинал, оставалась `MPN_ONLY` только потому, что
где-то сбоку висел кросс с общим артикулом. Артикул поставщика, принадлежащий
нескольким нашим кодам, ничего не говорит о том, верен ли оригинал.

Здесь проверяется разделение: `anomalies` по-прежнему перечисляет всё (позиция
не исчезает из ручного разбора), а `canonical_anomalies` — только то, что
ставит под сомнение сам якорь.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from marko.services.catalog_identity_reparse import SourceIndex, plan_identity
from metis.pricing.identity_graph import (
    Anomaly,
    SourceNumbers,
    build_identity_graph,
    load_identity_graph_config,
)
from metis.pricing.kemp_site import load_kemp_site_tokens

BACKEND = Path(__file__).resolve().parents[1]
CONFIG = load_identity_graph_config(BACKEND / "config/identity_graph.yaml")
TOKENS = load_kemp_site_tokens(BACKEND / "config/kemp_site_tokens.yaml")

MAP = "KEMP_REFERENCE_MAP_V2"
MAP_OLD = "KEMP_REFERENCE_MAP_V1"
ARTICLE = "KEMP_REFERENCE_ARTICLE"
OWN = "OWN_EXPORT_CHARACTERISTIC"

ANCHOR = "1K0413031BK"
CROSS = "606554"


def _graph(*, shared=frozenset(), fanout=frozenset(), semantic=False, **by_source):
    return build_identity_graph(
        own_code="77641229",
        sources=[
            SourceNumbers(name, tuple(numbers), f"{name} context")
            for name, numbers in by_source.items()
        ],
        config=CONFIG,
        shared_article_numbers=shared,
        public_number_semantic_fanout=fanout,
        source_semantic_conflict=semantic,
    )


def _plan(*, shared=frozenset(), **by_source):
    index = SourceIndex(
        by_code={
            "77641229": tuple(
                SourceNumbers(name, tuple(numbers), f"{name} context")
                for name, numbers in by_source.items()
            )
        },
        shared_articles=shared,
        loaded_sources=tuple(by_source),
    )
    return plan_identity(
        own_code="77641229",
        part_numbers_raw=(),
        current_oe_norm="",
        index=index,
        config=CONFIG,
        tokens=TOKENS,
    )


# --- граф -------------------------------------------------------------------


def test_a_shared_article_on_an_edge_leaves_the_anchor_clean() -> None:
    graph = _graph(shared=frozenset({CROSS}), **{MAP: (ANCHOR,), OWN: (CROSS,)})

    assert graph.canonical == ANCHOR
    assert graph.anomalies == (Anomaly.SHARED_ARTICLE_FANOUT.value,)
    assert graph.canonical_anomalies == ()


def test_a_shared_anchor_is_an_anomaly_on_the_anchor() -> None:
    graph = _graph(shared=frozenset({ANCHOR}), **{MAP: (ANCHOR,), OWN: (CROSS,)})

    assert graph.canonical_anomalies == (Anomaly.SHARED_ARTICLE_FANOUT.value,)


def test_a_public_fanout_on_another_number_leaves_the_anchor_clean() -> None:
    graph = _graph(fanout=frozenset({CROSS}), **{MAP: (ANCHOR,), OWN: (CROSS,)})

    assert Anomaly.PUBLIC_NUMBER_SEMANTIC_FANOUT.value in graph.anomalies
    assert graph.canonical_anomalies == ()


def test_a_public_fanout_on_the_anchor_taints_it() -> None:
    graph = _graph(fanout=frozenset({ANCHOR}), **{MAP: (ANCHOR,), OWN: (CROSS,)})

    assert graph.canonical_anomalies == (
        Anomaly.PUBLIC_NUMBER_SEMANTIC_FANOUT.value,
    )


def test_a_semantic_conflict_taints_the_anchor_because_the_key_is_in_doubt() -> None:
    """Две строки под одним внутренним кодом описывают разные детали. Тогда
    неизвестно, чья вообще эта позиция, и якорь ничем не лучше рёбер."""

    graph = _graph(semantic=True, **{MAP: (ANCHOR,), OWN: (CROSS,)})

    assert graph.canonical_anomalies == (Anomaly.SOURCE_SEMANTIC_CONFLICT.value,)


def test_sources_disagreeing_about_the_oe_taint_the_anchor() -> None:
    """Спор идёт ровно о том, какой номер оригинальный. Якорь — одна из сторон
    спора, и пускать его нельзя."""

    graph = _graph(**{MAP: (ANCHOR,), "KEMP_SITE": ("8D0698151",)})

    assert Anomaly.OE_SOURCE_CONFLICT.value in graph.anomalies
    assert Anomaly.OE_SOURCE_CONFLICT.value in graph.canonical_anomalies


def test_the_newer_edition_wins_the_anchor_so_supersession_never_reaches_it() -> None:
    graph = _graph(**{MAP_OLD: (ANCHOR,), MAP: ("1K0413031BM",)})

    assert graph.canonical == "1K0413031BM"
    assert graph.canonical_anomalies == ()


def test_the_anchor_never_carries_a_reason_the_graph_itself_hides() -> None:
    """Инвариант: это поле сужает ворота и нигде их не ужесточает.

    Пример ниже — известная дыра, а не замысел. У графа без рёбер аномалия
    «общий артикул» не выставляется вообще: она добавляется только в цикле по
    рёбрам, а цикл пуст. Позиция при этом уходит в цены с номером, который
    принадлежит нескольким нашим кодам. Чинить это надо отдельно: на живом
    каталоге такая правка снимает OE со 163 позиций, и решение о них — не
    побочный эффект другой задачи.
    """

    graph = _graph(shared=frozenset({ANCHOR}), **{MAP: (ANCHOR,)})

    assert graph.links == ()
    assert graph.anomalies == ()
    assert graph.canonical_anomalies == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"shared": frozenset({ANCHOR})},
        {"shared": frozenset({CROSS})},
        {"fanout": frozenset({ANCHOR})},
        {"fanout": frozenset({CROSS})},
        {"semantic": True},
        {},
    ],
)
def test_the_anchor_set_is_always_a_subset_of_the_graph_set(kwargs) -> None:
    graph = _graph(**kwargs, **{MAP: (ANCHOR,), OWN: (CROSS,), "KEMP_SITE": ("8D0698151",)})

    assert set(graph.canonical_anomalies) <= set(graph.anomalies)


# --- что из этого следует для позиции ---------------------------------------


def test_an_edge_anomaly_no_longer_blocks_a_confidently_named_oe() -> None:
    plan = _plan(shared=frozenset({CROSS}), **{MAP: (ANCHOR,), OWN: (CROSS,)})

    assert plan.identity_status == "OE_CONFIRMED"
    assert plan.fill_oe_norm == ANCHOR
    # Позиция всё равно остаётся в ручном разборе: аномалия никуда не делась.
    assert plan.graph.anomalies == (Anomaly.SHARED_ARTICLE_FANOUT.value,)


def test_an_anomaly_on_the_anchor_still_blocks_it() -> None:
    plan = _plan(shared=frozenset({ANCHOR}), **{MAP: (ANCHOR,), OWN: (CROSS,)})

    assert plan.identity_status == "MPN_ONLY"
    assert plan.fill_oe_norm == ""


def test_on_the_shipped_catalogue_the_gate_only_opens(monkeypatch) -> None:
    """Замер на живых файлах: сужение ворот не должно закрыть ни одной позиции.

    Дефект +276 родился ровно из ослабления такого правила, поэтому число
    закрывшихся здесь важнее числа открывшихся.
    """

    import dataclasses

    import marko.services.catalog_identity_reparse as reparse
    from marko.services.catalog_discovery import resolve_backend_path
    from metis.pricing.kemp_reference import load_article_brand_kinds

    kinds = load_article_brand_kinds(resolve_backend_path("config/article_brand_kinds.yaml"))
    index = reparse.build_source_index(
        config=CONFIG,
        kinds=kinds,
        tokens=TOKENS,
        reference_paths=[
            resolve_backend_path("data/kemp_reference_map.csv"),
            resolve_backend_path("data/kemp_oe_map.csv"),
        ],
        site_path=resolve_backend_path("data/kemp_site_numbers.csv"),
        spareto_paths=[resolve_backend_path("data/spareto_oe_confirmations.csv")],
    )

    def statuses() -> dict[str, str]:
        return {
            code: plan_identity(
                own_code=code, part_numbers_raw=(), current_oe_norm="",
                index=index, config=CONFIG, tokens=TOKENS,
            ).identity_status
            for code in index.by_code
        }

    after = statuses()

    real = reparse.build_identity_graph
    monkeypatch.setattr(
        reparse,
        "build_identity_graph",
        lambda **kw: (lambda g: dataclasses.replace(g, canonical_anomalies=g.anomalies))(real(**kw)),
    )
    before = statuses()

    opened = {c for c in before if before[c] != "OE_CONFIRMED" and after[c] == "OE_CONFIRMED"}
    closed = {c for c in before if before[c] == "OE_CONFIRMED" and after[c] != "OE_CONFIRMED"}

    # «Ни одной закрывшейся» — главное здесь, и от состава данных не зависит.
    assert not closed, sorted(closed)[:20]
    # Нижняя граница считана на наборе с 355 подтверждениями spareto (замер
    # 2026-08-08: открылось 331, без spareto — 333). Если датасет пересобрали и
    # число уехало, двигать границу можно, но только вместе с новым замером.
    assert len(opened) >= 300
