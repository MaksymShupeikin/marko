"""Один вопрос модели на один разный товар, а не на каждое объявление.

Сбор по карточке `2141006` 22.08.2026 дал 99 объявлений. Разных товаров среди
них — единицы: продавцы размножают одну и ту же позицию. Замер по реальным
данным того сбора:

    объявлений                              99
    по названию                             74 группы
    по артикулу, иначе названию             39 групп
    по бренду + артикулу, иначе названию    42 группы   ← выбрано

Взят третий ключ: он на три группы дороже второго, зато не склеивает детали
разных производителей, случайно совпавшие артикулом. Владелец 22.08 выбрал
«сгруппировать и судить группами» именно ради этого сокращения.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

from marko.services.candidate_offer_grouping import (
    group_candidate_offers,
    grouping_summary,
)


def _offer(
    *,
    title: str,
    price: str,
    sku: str | None = None,
    brand: str | None = None,
    seller: str = "seller-a",
    selection_status: str = "SELECTED",
    selection_reason: str | None = None,
    offer_id: UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=offer_id or uuid4(),
        title=title,
        sku=sku,
        brand=brand,
        seller_id=seller,
        seller_name=seller,
        sale_price=Decimal(price),
        currency="UAH",
        selection_status=selection_status,
        selection_reason=selection_reason,
    )


def test_the_same_part_from_two_sellers_is_one_question() -> None:
    groups = group_candidate_offers(
        [
            _offer(title="Шпилька ступиці", sku="N 910 105 016", brand="Mercedes", price="120", seller="a"),
            _offer(title="Шпилька ступицы", sku="N910105016", brand="MERCEDES", price="99", seller="b"),
        ]
    )

    assert len(groups) == 1
    group = groups[0]
    assert len(group.offer_ids) == 2
    assert set(group.seller_ids) == {"a", "b"}
    assert group.lowest_price == Decimal("99")
    assert group.highest_price == Decimal("120")


def test_the_same_article_from_different_makers_stays_two_questions() -> None:
    groups = group_candidate_offers(
        [
            _offer(title="Шпилька", sku="12345", brand="Mercedes", price="120"),
            _offer(title="Крышка", sku="12345", brand="BMW", price="250"),
        ]
    )

    assert len(groups) == 2


def test_offers_without_an_article_group_by_their_title() -> None:
    groups = group_candidate_offers(
        [
            _offer(title="Кришка горловини (E36/E46)", price="207", seller="a"),
            _offer(title="кришка горловини e36 e46", price="222", seller="b"),
            _offer(title="Зовсім інша деталь", price="300", seller="c"),
        ]
    )

    assert len(groups) == 2
    merged = next(g for g in groups if len(g.offer_ids) == 2)
    assert merged.lowest_price == Decimal("207")


def test_representative_is_the_cheapest_offer_because_the_estimate_uses_it() -> None:
    """Оценка считается от минимальной сопоставимой цены — судить надо её."""

    cheap = uuid4()
    groups = group_candidate_offers(
        [
            _offer(title="Шпилька", sku="A1", price="500", offer_id=uuid4()),
            _offer(title="Шпилька", sku="A1", price="120", offer_id=cheap),
            _offer(title="Шпилька", sku="A1", price="300", offer_id=uuid4()),
        ]
    )

    assert groups[0].representative_id == cheap


def test_why_the_free_gates_refused_the_group_travels_with_it() -> None:
    """Луна пересматривает отказ, а не судит вслепую — решение владельца."""

    groups = group_candidate_offers(
        [
            _offer(
                title="Крышка BMW",
                sku="B1",
                price="250",
                selection_status="REJECTED",
                selection_reason="OEM_CONFLICT",
                seller="a",
            ),
            _offer(
                title="Крышка BMW",
                sku="B1",
                price="270",
                selection_status="REJECTED",
                selection_reason="USED",
                seller="b",
            ),
        ]
    )

    assert groups[0].rejected_reasons == ("OEM_CONFLICT", "USED")
    assert groups[0].was_rejected_by_gates is True


def test_a_group_the_gates_admitted_is_not_marked_rejected() -> None:
    groups = group_candidate_offers(
        [_offer(title="Шпилька", sku="A1", price="120", selection_status="SELECTED")]
    )

    assert groups[0].rejected_reasons == ()
    assert groups[0].was_rejected_by_gates is False


def test_group_order_is_deterministic_and_cheapest_first() -> None:
    offers = [
        _offer(title="Третий", sku="C", price="300"),
        _offer(title="Первый", sku="A", price="100"),
        _offer(title="Второй", sku="B", price="200"),
    ]

    prices = [group.lowest_price for group in group_candidate_offers(offers)]
    assert prices == [Decimal("100"), Decimal("200"), Decimal("300")]
    assert [g.key for g in group_candidate_offers(offers)] == [
        g.key for g in group_candidate_offers(list(reversed(offers)))
    ]


def test_summary_states_the_saving_in_numbers() -> None:
    offers = [
        _offer(title="Шпилька", sku="A1", price="120", seller="a"),
        _offer(title="Шпилька", sku="A1", price="130", seller="b"),
        _offer(title="Крышка", sku="B1", price="250", seller="c"),
    ]

    summary = grouping_summary(group_candidate_offers(offers), offer_count=len(offers))

    assert summary["offers"] == 3
    assert summary["groups"] == 2
    assert summary["calls_saved"] == 1


def test_no_offers_is_not_an_error() -> None:
    assert group_candidate_offers([]) == ()
    assert grouping_summary((), offer_count=0)["groups"] == 0
