"""The price suggestion contract, measured against a real saved market report.

Фікстура ``report-407a92e8.json`` — справжній звіт аудиту 31 серпня:
51 пропозиція, медіана 2550 ₴. На ній видно і те, що рушій робить правильно,
і те, чому нинішню формулу доведеться замінити.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from marko.services import competitor_prices as cp
from marko.services.competitor_prices import (
    CompetitorPriceReport,
    MarketOffer,
    PartSearchQuery,
    SourceResult,
)
from marko.services.pricing import engine as pricing

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "audit" / "redis" / "report-407a92e8.json"
)


def _report_from(offers_by_source: dict[str, list[MarketOffer]]) -> dict:
    """Справжній об'єкт звіту, а не саморобний словник.

    Статистику рахує той самий код, що й у продакшні, тож тест не може
    розійтися з ним через копіпасту порогів.
    """
    from datetime import UTC, datetime

    query = PartSearchQuery(
        listing_id="listing-1",
        oem_numbers=("1234567",),
        brand="Mann",
        name="Амортизатор передній",
        source_url="https://example.prom.ua/p1.html",
    )
    sources = tuple(
        SourceResult(source, source, "ok", tuple(offers))
        for source, offers in offers_by_source.items()
    )
    return CompetitorPriceReport(
        query=query, sources=sources, observed_at=datetime.now(UTC)
    ).as_json()


def _saved_offers() -> dict[str, list[MarketOffer]]:
    saved = json.loads(_FIXTURE.read_text())
    result: dict[str, list[MarketOffer]] = {}
    for source in saved["sources"]:
        result[source["source"]] = [
            MarketOffer(
                source=offer["source"],
                title=offer["title"],
                price=Decimal(offer["price"]),
                currency=offer["currency"],
                url=offer["url"],
                seller=offer.get("seller"),
                availability=offer.get("availability"),
                condition=offer.get("condition"),
                confidence=offer.get("confidence", 1.0),
                is_analog=offer.get("is_analog", False),
            )
            for offer in source["offers"]
        ]
    return result


def test_confidence_threshold_matches_competitor_prices():
    """Поріг продубльовано навмисно — розбіжність має падати тут, а не в грошах."""
    assert pricing.MIN_STATS_CONFIDENCE == cp._MIN_STATS_CONFIDENCE


def test_real_report_keeps_the_legacy_recommendation():
    report = _report_from(_saved_offers())
    suggestion = pricing.LegacyMinusPercentEngine().suggest(
        current_price=Decimal("1200"), report=report, policy="balanced"
    )
    assert suggestion.outcome == pricing.CHANGED
    # Мінімум 1162.66 → мінус 6% → 1093. Крок від 1200 — менш ніж 15%.
    assert suggestion.new_price == Decimal("1093")
    assert suggestion.evidence["clamped_to_max_step"] is False


def test_one_garbage_offer_destroys_the_legacy_anchor():
    """Доказ дефекту, а не перевірка рушія: ``min`` тримається на одній ціні.

    Саме тому масовий прогін не можна запускати на цій формулі без
    обмежень — одна помилка парсингу з'їдає третину ціни.
    """
    offers = _saved_offers()
    clean = _report_from(offers)
    offers["prom"] = offers["prom"] + [
        MarketOffer(
            source="prom",
            title="Амортизатор передній, б/в з розборки",
            price=Decimal("765.00"),  # 30% медіани — типовий вигляд сміття
            currency="UAH",
            url="https://prom.ua/p-garbage.html",
            confidence=0.95,
        )
    ]
    poisoned = _report_from(offers)

    clean_anchor = Decimal(clean["stats"]["recommended_price"])
    poisoned_anchor = Decimal(poisoned["stats"]["recommended_price"])
    drop = (clean_anchor - poisoned_anchor) / clean_anchor
    assert drop > Decimal("0.3"), "одна ціна має зрушити якір на десятки відсотків"


def test_the_guard_refuses_a_poisoned_anchor_instead_of_pricing_it():
    """Обмеження не робить формулу розумною — воно не дає їй нашкодити."""
    offers = _saved_offers()
    offers["prom"] = offers["prom"] + [
        MarketOffer(
            source="prom",
            title="Амортизатор передній, б/в",
            price=Decimal("765.00"),
            currency="UAH",
            url="https://prom.ua/p-garbage.html",
            confidence=0.95,
        )
    ]
    suggestion = pricing.LegacyMinusPercentEngine().suggest(
        current_price=Decimal("1200"),
        report=_report_from(offers),
        policy="balanced",
    )
    assert suggestion.outcome == pricing.NO_RECOMMENDATION
    assert suggestion.new_price is None
    assert suggestion.reason
    assert suggestion.evidence["guard"] == "below_suspicious_low_fence"


def test_thin_market_never_gets_a_price():
    offers = {
        "prom": [
            MarketOffer(
                source="prom",
                title="Амортизатор",
                price=Decimal("2000"),
                currency="UAH",
                url="https://prom.ua/p1.html",
                confidence=0.95,
            )
        ]
    }
    suggestion = pricing.LegacyMinusPercentEngine().suggest(
        current_price=Decimal("2500"), report=_report_from(offers), policy="balanced"
    )
    assert suggestion.outcome == pricing.NO_RECOMMENDATION
    assert "Тонкий ринок" in suggestion.reason


def test_large_drop_is_clamped_to_the_step_and_says_so():
    report = _report_from(_saved_offers())
    # Своя ціна вдвічі вища за ринок: рекомендація вимагала б −45% за раз.
    suggestion = pricing.LegacyMinusPercentEngine().suggest(
        current_price=Decimal("2000"), report=report, policy="balanced"
    )
    assert suggestion.outcome == pricing.CHANGED
    assert suggestion.new_price == Decimal("1700")  # рівно −15%
    assert suggestion.evidence["clamped_to_max_step"] is True
    assert suggestion.evidence["unclamped_price"] == "1093"


def test_price_already_at_the_recommendation_is_unchanged_not_silent():
    report = _report_from(_saved_offers())
    suggestion = pricing.LegacyMinusPercentEngine().suggest(
        current_price=Decimal("1093"), report=report, policy="balanced"
    )
    assert suggestion.outcome == pricing.UNCHANGED
    assert suggestion.new_price == Decimal("1093")
    assert suggestion.reason is None


def test_product_without_its_own_price_is_refused_with_a_reason():
    suggestion = pricing.LegacyMinusPercentEngine().suggest(
        current_price=None, report=_report_from(_saved_offers()), policy="balanced"
    )
    assert suggestion.outcome == pricing.NO_RECOMMENDATION
    assert "власної ціни" in suggestion.reason


@pytest.mark.parametrize(
    ("price", "zone"),
    [
        (Decimal("900"), "underpriced"),
        (Decimal("2550"), "mainstream"),
        (Decimal("9999"), "outlier_high"),
    ],
)
def test_zone_describes_where_we_stand_on_the_market_scale(price, zone):
    report = _report_from(_saved_offers())
    prices = pricing.confident_prices(report)
    assert pricing.price_zone(price, prices) == zone


def test_zone_is_unknown_without_a_market():
    assert pricing.price_zone(Decimal("100"), []) is None


def test_every_refusal_carries_a_reason():
    """«Не пораховано» без причини — це брехня користувачу, а не результат."""
    engine = pricing.LegacyMinusPercentEngine()
    refusals = [
        engine.suggest(
            current_price=None, report=_report_from(_saved_offers()), policy="balanced"
        ),
        engine.suggest(
            current_price=Decimal("100"),
            report=_report_from({"prom": []}),
            policy="balanced",
        ),
    ]
    for suggestion in refusals:
        assert suggestion.outcome == pricing.NO_RECOMMENDATION
        assert suggestion.reason
