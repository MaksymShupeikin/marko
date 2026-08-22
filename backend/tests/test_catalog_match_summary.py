"""Новая оценка товара после двух кнопок.

Владелец 22.08 выбрал правило «минимальная сопоставимая − 5 %» — ровно то,
что уже действует в больших прогонах (`market_collection.py:509`). Цифра с
карточки и цифра из прогона обязаны совпадать, иначе покупателю на демо
показывают два разных ответа на один вопрос.

Считается она только по группам, которые модель признала сопоставимыми.
Отклонённое и недоказанное в цену не входит.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from marko.services.catalog_match import summarize_catalog_match


def _group(price: str, *, key: str, currency: str = "UAH") -> SimpleNamespace:
    return SimpleNamespace(
        key=key,
        lowest_price=Decimal(price),
        currency=currency,
    )


def test_estimate_is_five_percent_under_the_cheapest_comparable() -> None:
    groups = [_group("690", key="a"), _group("810", key="b")]
    verdicts = {"a": "MATCH", "b": "MATCH"}

    outcome = summarize_catalog_match(
        groups,
        verdicts,
        minimum_discount=Decimal("0.05"),
        price_tick=Decimal("1"),
    )

    assert outcome.minimum_comparable_price == Decimal("690")
    # 690 * 0.95 = 655.5 -> вниз по шагу цены
    assert outcome.advisory_price == Decimal("655")
    assert outcome.comparable_group_count == 2
    assert outcome.currency == "UAH"


def test_a_cheaper_group_the_model_refused_does_not_pull_the_price_down() -> None:
    groups = [_group("120", key="junk"), _group("690", key="real")]
    verdicts = {"junk": "NO_MATCH", "real": "MATCH"}

    outcome = summarize_catalog_match(
        groups,
        verdicts,
        minimum_discount=Decimal("0.05"),
        price_tick=Decimal("1"),
    )

    assert outcome.minimum_comparable_price == Decimal("690")
    assert outcome.comparable_group_count == 1


def test_insufficient_evidence_is_not_a_comparable() -> None:
    groups = [_group("500", key="maybe")]
    verdicts = {"maybe": "INSUFFICIENT_EVIDENCE"}

    outcome = summarize_catalog_match(
        groups,
        verdicts,
        minimum_discount=Decimal("0.05"),
        price_tick=Decimal("1"),
    )

    assert outcome.minimum_comparable_price is None
    assert outcome.advisory_price is None
    assert outcome.comparable_group_count == 0


def test_nothing_comparable_yields_no_number_rather_than_zero() -> None:
    outcome = summarize_catalog_match(
        [_group("120", key="a")],
        {"a": "NO_MATCH"},
        minimum_discount=Decimal("0.05"),
        price_tick=Decimal("1"),
    )

    assert outcome.advisory_price is None
    assert outcome.minimum_comparable_price is None


def test_a_group_without_a_price_cannot_set_the_floor() -> None:
    priceless = SimpleNamespace(key="a", lowest_price=None, currency="UAH")
    outcome = summarize_catalog_match(
        [priceless, _group("690", key="b")],
        {"a": "MATCH", "b": "MATCH"},
        minimum_discount=Decimal("0.05"),
        price_tick=Decimal("1"),
    )

    assert outcome.minimum_comparable_price == Decimal("690")


def test_price_tick_of_ten_rounds_down_not_nearest() -> None:
    outcome = summarize_catalog_match(
        [_group("690", key="a")],
        {"a": "MATCH"},
        minimum_discount=Decimal("0.05"),
        price_tick=Decimal("10"),
    )

    # 655.5 -> 650, вниз: политика заказчика — встать НИЖЕ минимума, а не рядом
    assert outcome.advisory_price == Decimal("650")


def test_the_card_and_the_run_use_the_same_arithmetic() -> None:
    """Сверка с формулой прогонов: minimum * (1 - discount), затем вниз по шагу."""

    from metis.pricing.statistics import round_down_to_tick

    minimum = Decimal("739")
    expected = round_down_to_tick(
        minimum * (Decimal("1") - Decimal("0.05")), Decimal("1")
    )

    outcome = summarize_catalog_match(
        [_group("739", key="a")],
        {"a": "MATCH"},
        minimum_discount=Decimal("0.05"),
        price_tick=Decimal("1"),
    )

    assert outcome.advisory_price == expected
