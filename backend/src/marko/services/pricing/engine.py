"""Price suggestion for one product: the contract, and today's implementation.

Формула живе за інтерфейсом навмисно. Сьогодні це «мінімум ринку мінус 6%»,
завтра — робастна квантильна оцінка; вікно переоцінки не має про це знати.

Модуль чистий: ні мережі, ні бази, ні LLM. Вхід — готовий звіт по конкурентах
у тому вигляді, в якому його віддає ``CompetitorPriceReport.as_json()``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

# Дубль порога з ``competitor_prices._MIN_STATS_CONFIDENCE``: тягнути сюди
# модуль із redis/httpx заради однієї константи дорожче, ніж тримати копію.
# Розбіжність ловить test_pricing_engine.test_confidence_threshold_matches_source.
MIN_STATS_CONFIDENCE = 0.7

# Крок за один прогін. Рекомендація, що вимагає більшого стрибка, не
# відкидається — вона обрізається до межі, а обрізання видно в доказах.
MAX_STEP_PERCENT = Decimal("15")

# Різниця менша за гривню — це не переоцінка, а шум округлення.
UNCHANGED_EPSILON = Decimal("1")

# Ціна, нижча за 40% медіани, майже завжди тримається на смітті парсингу
# (склеєні цифри, платіж розстрочки, б/в). Той самий множник, що й
# ``_SUSPICIOUS_LOW_FACTOR`` у пошуку конкурентів.
SUSPICIOUS_LOW_FACTOR = Decimal("2.5")

CHANGED = "changed"
UNCHANGED = "unchanged"
NO_RECOMMENDATION = "no_recommendation"


@dataclass(frozen=True)
class PriceSuggestion:
    """What to do with one product's price, and why."""

    outcome: str
    method: str
    new_price: Decimal | None = None
    reason: str | None = None
    zone: str | None = None
    tier: str | None = None
    confidence: Decimal | None = None
    offers_total: int = 0
    evidence: dict[str, Any] = field(default_factory=dict)


class PricingEngine(Protocol):
    """Every engine answers the same question about one product."""

    name: str

    def suggest(
        self,
        *,
        current_price: Decimal | None,
        report: dict[str, Any],
        policy: str,
    ) -> PriceSuggestion:
        ...


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def confident_prices(report: dict[str, Any]) -> list[Decimal]:
    """Ціни, що мають право описувати ринок: слабкі збіги — не гроші."""
    prices: list[Decimal] = []
    for source in report.get("sources") or []:
        for offer in source.get("offers") or []:
            if float(offer.get("confidence") or 0) < MIN_STATS_CONFIDENCE:
                continue
            price = _decimal(offer.get("price"))
            if price is not None and price > 0:
                prices.append(price)
    return sorted(prices)


def price_zone(current_price: Decimal, prices: list[Decimal]) -> str | None:
    """Де наша ціна на шкалі ринку — за емпіричною функцією розподілу.

    Це опис позиції, а не вирок: товар у зоні ``premium`` може бути і
    переоціненим, і єдиним оригіналом серед підробок. Розрізняє їх лише
    сегментація за якістю, якої в цьому рушії ще немає.
    """
    if not prices:
        return None
    below = sum(1 for price in prices if price < current_price)
    equal = sum(1 for price in prices if price == current_price)
    # Середній ранг: ціна, що збігається з чужою, не отримує переваги.
    percentile = (below + equal / 2) / len(prices) * 100
    if percentile < 10:
        return "underpriced"
    if percentile < 35:
        return "value"
    if percentile < 65:
        return "mainstream"
    if percentile < 90:
        return "premium"
    return "outlier_high"


def _clamp_to_step(current: Decimal, target: Decimal) -> tuple[Decimal, bool]:
    """Не даємо ціні стрибнути далі, ніж на MAX_STEP_PERCENT за прогін."""
    limit = current * MAX_STEP_PERCENT / Decimal("100")
    if target < current - limit:
        return (current - limit).quantize(Decimal("1")), True
    if target > current + limit:
        return (current + limit).quantize(Decimal("1")), True
    return target, False


class LegacyMinusPercentEngine:
    """Today's rule: a few percent under the cheapest confident competitor.

    Рушій свідомо слабкий — він успадковує головну ваду: ``min`` тримається
    на одному спостереженні, і кожна помилка парсингу тягне його вниз. Тому
    тут живуть обмеження: без них масовий прогін тиражував би цю ваду.
    """

    name = "legacy_min_minus"

    def suggest(
        self,
        *,
        current_price: Decimal | None,
        report: dict[str, Any],
        policy: str,
    ) -> PriceSuggestion:
        stats = report.get("stats") or {}
        offers_total = int(stats.get("offers_total") or 0)
        prices = confident_prices(report)
        median = _decimal(stats.get("median_price"))
        evidence: dict[str, Any] = {
            "engine": self.name,
            "policy": policy,
            "min_price": stats.get("min_price"),
            "median_price": stats.get("median_price"),
            "max_price": stats.get("max_price"),
            "confident_offers": len(prices),
            "anchor": "min_price",
            "discount_percent": stats.get("recommended_discount_percent"),
        }

        def refuse(reason: str) -> PriceSuggestion:
            return PriceSuggestion(
                outcome=NO_RECOMMENDATION,
                method=self.name,
                reason=reason,
                offers_total=offers_total,
                zone=(
                    price_zone(current_price, prices)
                    if current_price and current_price > 0
                    else None
                ),
                evidence=evidence,
            )

        if current_price is None or current_price <= 0:
            return refuse("У товару немає власної ціни, від якої рахувати")
        if stats.get("thin_market"):
            return refuse("Тонкий ринок: менше трьох підтверджених цін")

        target = _decimal(stats.get("recommended_price"))
        if target is None or target <= 0:
            return refuse("Ринкових даних недостатньо для точної рекомендації")

        # Запобіжник проти хибного мінімуму: рекомендація, що провалилася
        # під 40% медіани, майже напевно тримається на смітті парсингу.
        if median is not None and median > 0 and target < median / SUSPICIOUS_LOW_FACTOR:
            evidence["guard"] = "below_suspicious_low_fence"
            return refuse(
                "Рекомендація нижча за 40% медіани ринку — схоже на хибний мінімум"
            )

        clamped_target, clamped = _clamp_to_step(current_price, target)
        evidence["clamped_to_max_step"] = clamped
        if clamped:
            evidence["unclamped_price"] = str(target)

        zone = price_zone(current_price, prices)
        if abs(clamped_target - current_price) < UNCHANGED_EPSILON:
            return PriceSuggestion(
                outcome=UNCHANGED,
                method=self.name,
                new_price=current_price,
                zone=zone,
                offers_total=offers_total,
                evidence=evidence,
            )

        return PriceSuggestion(
            outcome=CHANGED,
            method=self.name,
            new_price=clamped_target,
            zone=zone,
            offers_total=offers_total,
            evidence=evidence,
        )


_ENGINES: dict[str, PricingEngine] = {
    LegacyMinusPercentEngine.name: LegacyMinusPercentEngine(),
}

DEFAULT_ENGINE = LegacyMinusPercentEngine.name


def get_engine(name: str | None = None) -> PricingEngine:
    return _ENGINES[name or DEFAULT_ENGINE]
