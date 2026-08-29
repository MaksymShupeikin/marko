"""Aggregate competitor prices from public auto-parts marketplaces."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from statistics import median
from typing import Any, Callable, Iterable, Iterator, Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

import marko.repositories.stores as stores_repo
from marko.core.config import get_settings
from marko.infrastructure.db.models import CompetitorSellerExclusion, Listing
from marko.parsers.avtopro import AvtoproGateway, default_config as avtopro_config
from marko.parsers.avtopro.gateway import BASE_URL as AVTOPRO_BASE_URL
from marko.parsers.prom.client import AsyncHttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.parser import parse_product_page, parse_search
from marko.parsers.prom_export import (
    normalize_oem,
    parse_price,
    seller_from_export_url,
)
from marko.repositories.listings import (
    get_workspace_listing,
    set_listing_oem_numbers,
)
from marko.services import exchange_rates, llm_filter, offer_gates
from marko.services.matching import (
    brands_compatible,
    laterality_conflict,
    normalize_tokens,
    token_similarity,
)

log = logging.getLogger(__name__)

PROM_BASE_URL = "https://prom.ua"

# (стадія, підпис для користувача) — синхронний виклик, щоб класти в чергу SSE.
ProgressCallback = Callable[[str, str], None]

_MIN_SUBSTRING_OEM_LENGTH = 6  # коротший номер трапляється в чужих назвах випадково
_MIN_SELF_SUFFICIENT_DIGITS = 8  # коротший цифровий номер сам по собі нічого не доводить
_MIN_STEM = 4  # довжина кореня для звірки теми назви
_MIN_STATS_CONFIDENCE = 0.7  # слабкі збіги не мають задавати мін/медіану/макс
# Викиди: ціна, що відрізняється від медіани впевнених збігів у 8+ разів, —
# майже напевно сміття парсингу (склеєні цифри, «0 грн» доставки), не ринок.
# Замовник підрізає найдешевшого конкурента на 6% — це його основний запит.
_RECOMMENDED_DISCOUNT = Decimal("0.94")

_OUTLIER_FACTOR = Decimal("8")
_OUTLIER_MIN_OFFERS = 4  # менше — нема статистики, викид не відрізнити від ринку
# Другий прохід моделі по цінах, що формують звіт.
_SUSPICIOUS_LOW_FACTOR = Decimal("2.5")  # дешевше за 40% медіани — точно перевірити
_VERIFY_MIN_CONFIDENT = 3  # медіана з двох цін — не якір
_VERIFY_MAX_OFFERS = 40  # стеля на звіт; скільки не влізло — у лог
_UNVERIFIED_CONFIDENCE = 0.5  # видно у списку, але поза статистикою
_MIN_STATS_SAMPLE = 3  # менше — це вже не ринок, а випадкові дві ціни
_MIN_NAME_SIMILARITY = 0.7  # нижче — це вже інша деталь, а не конкурент
_STRONG_NAME_SIMILARITY = 0.8  # від цього збіг за назвою рахується у статистику
_OEM_HIT_SCORE = 0.9  # знайдено за номером — це та сама деталь, не аналог
# Аналог — та сама деталь на ту саму машину від іншого виробника; деталь на
# іншу машину модель відсіює вердиктом "no" ще до цього місця. Товар під
# власною маркою (KEMP) точного збігу за брендом не має в принципі, тож без
# аналогів у статистику потрапляли б лише наші ж магазини — а їх ми виключаємо.
_ANALOG_CONFIDENCE = 0.75  # вище порога статистики, нижче за підтверджений збіг
_LLM_SAME_CONFIDENCE = 0.95  # модель підтвердила: та сама деталь
# Ширший невід: точність тепер тримає LLM-фільтр, а не обрізання джерела.
_PROM_MAX_OFFERS = 60
_AVTOPRO_MAX_OFFERS = 40
_MAX_OEM_TERMS = 2  # другий номер приводить інших продавців, ніж перший
_MAX_NAME_TOKENS = 8

SERPER_URL = "https://google.serper.dev/search"
_SERP_RESULTS_PER_TERM = 20
_GOOGLE_MAX_OFFERS = 20
# Сторінок докачуємо небагато: більшість цін уже в сніпетах, а кожен GET —
# чужий сайт зі своїм часом відповіді.
_SERP_MAX_PAGE_FETCHES = 12
_SERP_TIMEOUT = 6.0
# Ці маркетплейси вже є окремими джерелами — з Google вони лише дублюють.
_SERP_COVERED_DOMAINS = ("prom.ua", "avto.pro")
# Ринок — український: російські й білоруські магазини не конкуренти,
# а їхні ціни в рублях лише засмічують порівняння.
# Замовник продає лише в Україні — закордонний магазин не конкурує з його
# покупцем, а його ціна (нехай і чесно сконвертована) лише каламутить звіт.
# Тому білий список замість чорного: gl=ua у Serper — побажання, не гарантія,
# і американські чи китайські майданчики все одно просочувались у видачу.
_SERP_ALLOWED_TLD = ".ua"

_NON_ALNUM_RE = re.compile(r"[^0-9A-ZА-ЯІЇЄЁ]+", re.I)
_PROM_PRODUCT_ID_RE = re.compile(r"/(?:[a-z]{2}/)?p(?P<id>\d+)-", re.I)
_PROM_SELLER_HOST_ID_RE = re.compile(r"-cs(?P<id>\d+)(?:\.|$)", re.I)

# These sellers belong to the Marko installation, not to the competitive
# market. Prom's numeric company id is the durable identity; slug is a fallback
# for search payloads that omit it.
# Власна торгова марка магазину, а не виробник деталі. 41 120 із 47 785
# карток каталогу йдуть під нею, і саме тому вона отруювала звірку: збіг за
# справжнім номером анулювався, бо конкурент продає ту саму деталь під Sachs
# чи VAG. Тримаємо у вже нормалізованому вигляді — порівнюємо casefold.
GLOBAL_OWN_BRANDS: tuple[str, ...] = ("kemp",)

# Власні сайти поза маркетплейсами: у конкуренти вони потрапляли через Google
# і на «Ford Sierra» ставали найдешевшою пропозицією — рекомендація підрізала
# замовника ним самим. Дилери, що перепродають KEMP, конкурентами лишаються.
GLOBAL_OWN_DOMAINS: tuple[str, ...] = ("kemp.ua",)

GLOBAL_OWN_PROM_SELLERS: tuple[tuple[str, str], ...] = (
    ("2847093", "kemp"),
    ("4015921", "avtobust"),
    ("3325174", "profparts"),
    ("3912822", "parts-avto"),
)


@dataclass(frozen=True)
class PartSearchQuery:
    """Search context for one catalog listing."""

    listing_id: str
    oem_numbers: tuple[str, ...]
    brand: str | None
    name: str
    source_url: str
    owner_seller_ids: tuple[str, ...] = ()
    owner_seller_slugs: tuple[str, ...] = ()
    # Ручний пошук: марку ввела людина, і вона ж бачить, що підібралось.
    manual: bool = False

    @property
    def primary_term(self) -> str:
        if self.oem_numbers:
            return self.oem_numbers[0]
        return " ".join(value for value in (self.brand, self.name) if value)[:160]

    def as_json(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "oem_numbers": self.oem_numbers,
            "brand": self.brand,
            "name": self.name,
            "source_url": self.source_url,
        }


@dataclass(frozen=True)
class MarketOffer:
    """A normalized competitor offer from any source."""

    source: str
    title: str
    price: Decimal
    currency: str
    url: str
    seller: str | None = None
    city: str | None = None
    availability: str | None = None
    condition: str | None = None
    image_url: str | None = None
    confidence: float = 1.0
    # Не той самий номер: інший виробник робить те саме — ціна для порівняння.
    is_analog: bool = False

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["price"] = str(self.price)
        return data


@dataclass(frozen=True)
class SourceResult:
    """Offers and status for one marketplace source."""

    source: str
    label: str
    status: str
    offers: tuple[MarketOffer, ...] = ()
    error: str | None = None

    @property
    def prices(self) -> list[Decimal]:
        return _stats_prices(self.offers)

    @property
    def min_price(self) -> Decimal | None:
        return min(self.prices) if self.offers else None

    @property
    def median_price(self) -> Decimal | None:
        values = self.prices
        return Decimal(str(median(values))).quantize(Decimal("0.01")) if values else None

    @property
    def max_price(self) -> Decimal | None:
        return max(self.prices) if self.offers else None

    def as_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "label": self.label,
            "status": self.status,
            "error": self.error,
            "offers_total": len(self.offers),
            "min_price": _decimal_json(self.min_price),
            "median_price": _decimal_json(self.median_price),
            "max_price": _decimal_json(self.max_price),
            "offers": [offer.as_json() for offer in self.offers],
        }


@dataclass(frozen=True)
class CompetitorPriceReport:
    """Full cached response for one listing."""

    query: PartSearchQuery
    sources: tuple[SourceResult, ...]
    observed_at: datetime
    cached: bool = False

    @property
    def offers(self) -> list[MarketOffer]:
        return [offer for source in self.sources for offer in source.offers]

    @property
    def prices(self) -> list[Decimal]:
        return _stats_prices(self.offers)

    def as_json(self) -> dict[str, Any]:
        prices = self.prices
        return {
            "query": self.query.as_json(),
            "cached": self.cached,
            "observed_at": self.observed_at.isoformat(),
            "stats": {
                "offers_total": len(self.offers),
                "sources_total": len(self.sources),
                "min_price": _decimal_json(min(prices) if prices else None),
                "median_price": _decimal_json(
                    Decimal(str(median(prices))).quantize(Decimal("0.01"))
                    if prices
                    else None
                ),
                "max_price": _decimal_json(max(prices) if prices else None),
                "recommended_price": _decimal_json(
                    _recommended_price(prices) if prices else None
                ),
            },
            "sources": [source.as_json() for source in self.sources],
        }


class PriceSource(Protocol):
    source: str
    label: str

    async def search(self, query: PartSearchQuery) -> SourceResult:
        ...


class _RedisCacheClient(Protocol):
    async def get(self, key: str) -> bytes | str | None:
        ...

    async def set(self, key: str, value: str, *, ex: int) -> Any:
        ...


class CompetitorPriceCache:
    """Shared Redis TTL cache with one independent key per catalog listing."""

    def __init__(
        self,
        redis_url: str,
        *,
        client: _RedisCacheClient | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._client = client

    def _redis(self) -> _RedisCacheClient:
        if self._client is None:
            self._client = Redis.from_url(self._redis_url, decode_responses=True)
        return self._client

    async def get(self, key: str) -> dict[str, Any] | None:
        raw = await self._redis().get(key)
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            log.warning("Invalid competitor price cache payload for %s", key)
            return None
        if not isinstance(payload, dict):
            return None
        return {**payload, "cached": True}

    async def set(self, key: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        serialized = json.dumps(
            {**payload, "cached": False},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        await self._redis().set(key, serialized, ex=ttl_seconds)


_cache = CompetitorPriceCache(get_settings().competitor_price_cache_url)

# ponytail: ліміт на процес; якщо інстансів стане багато і джерела почнуть
# банити — переносити ліміт у Redis-семафор.
_collect_slots = asyncio.Semaphore(get_settings().competitor_report_concurrency)


async def listing_search_query(
    session: AsyncSession,
    workspace_id,
    listing_id,
) -> PartSearchQuery:
    """Все, що потребує бази — окремо: далі йде лише мережа, вже без сесії."""
    listing = await get_workspace_listing(session, workspace_id, listing_id)
    if listing is None:
        raise LookupError("Product was not found in this workspace")

    seller_exclusions = await stores_repo.list_competitor_seller_exclusions(
        session, workspace_id
    )
    query = _query_from_listing(listing, seller_exclusions)
    raw = listing.raw_data if isinstance(listing.raw_data, dict) else {}
    if raw.get("oem_numbers"):
        return query
    # У картці лише внутрішній артикул — за ним конкурентів не знайти.
    return await _numbers_from_product_page(session, listing, query)


async def _numbers_from_product_page(
    session: AsyncSession, listing: Any, query: PartSearchQuery
) -> PartSearchQuery:
    """Дочитує каталожний номер зі сторінки товару й запам'ятовує його.

    Товар, доданий посиланням, приходить без номера — лишався пошук за
    назвою. Один GET на картку, далі номер живе в raw_data, тож наступні
    звіти безкоштовні. Антибот чи змінена розмітка — не привід валити звіт:
    працюємо за назвою, як і до цього.
    """
    try:
        async with AsyncHttpClient(_source_config()) as client:
            html = await client.get_html(listing.url)
        numbers = parse_product_page(html).product.oem_numbers
    except Exception as exc:  # сторінка недоступна — звіт усе одно потрібен
        log.info("Не вдалось дочитати номер зі сторінки %s: %s", listing.url, exc)
        return query
    if not numbers:
        return query
    await set_listing_oem_numbers(session, listing.id, list(numbers))
    await session.commit()
    log.info("Дочитано номери для %s: %s", listing.id, numbers)
    # Артикул лишається кандидатом для звірки, але вже після справжніх номерів.
    return replace(
        query, oem_numbers=tuple(dict.fromkeys((*numbers, *query.oem_numbers)))
    )


def manual_search_query(
    oem: str,
    brand: str | None = None,
    name: str | None = None,
    seller_exclusions: Iterable[CompetitorSellerExclusion] = (),
) -> PartSearchQuery:
    """Запит із форми ручного пошуку: жодного товару в каталозі за ним немає."""
    number = normalize_oem(oem)
    numbers = (number,) if number else ()
    owner_ids, owner_slugs = _owner_identity(seller_exclusions)
    return PartSearchQuery(
        # Свій ключ кешу на кожну комбінацію — саме її і бачить користувач.
        listing_id=f"manual:{_norm_code(oem)}",
        oem_numbers=numbers,
        brand=(brand or "").strip() or None,
        # Без номера шукати все одно є що: назвою за Prom.
        name=(name or "").strip() or oem.strip(),
        source_url="",
        owner_seller_ids=owner_ids,
        owner_seller_slugs=owner_slugs,
        manual=True,
    )


def _owner_identity(
    seller_exclusions: Iterable[CompetitorSellerExclusion],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Ідентичність власних Prom-магазинів: їхні пропозиції — не конкуренти."""
    prom_exclusions = [
        seller
        for seller in seller_exclusions
        if seller.marketplace.casefold() == "prom"
    ]
    ids = tuple(
        sorted(
            {
                *(external_id for external_id, _ in GLOBAL_OWN_PROM_SELLERS),
                *(
                    value
                    for value in (
                        _text_value(seller.external_id)
                        for seller in prom_exclusions
                    )
                    if value
                ),
            }
        )
    )
    slugs = tuple(
        sorted(
            {
                *(slug for _, slug in GLOBAL_OWN_PROM_SELLERS),
                *(
                    value
                    for value in (
                        _normalized_slug(seller.slug)
                        for seller in prom_exclusions
                    )
                    if value
                ),
            }
        )
    )
    return ids, slugs


async def competitor_prices_for_query(
    query: PartSearchQuery,
    *,
    refresh: bool = False,
    on_event: ProgressCallback | None = None,
) -> dict[str, Any]:
    cache_key = _cache_key(query)
    settings = get_settings()
    if not refresh:
        cached = await _cache.get(cache_key)
        if cached is not None:
            return cached

    async with _collect_slots:
        # Поки чекали на слот, той самий звіт міг зібрати хтось інший.
        if not refresh:
            cached = await _cache.get(cache_key)
            if cached is not None:
                return cached
        report = await _collect(query, on_event)
        payload = report.as_json()
        # Запис у кеш ще під слотом: наступний у черзі має його вже побачити.
        await _cache.set(
            cache_key, payload, settings.competitor_price_cache_ttl_seconds
        )
    return payload


async def competitor_prices_for_listing(
    session: AsyncSession,
    workspace_id,
    listing_id,
    *,
    refresh: bool = False,
) -> dict[str, Any]:
    query = await listing_search_query(session, workspace_id, listing_id)
    return await competitor_prices_for_query(query, refresh=refresh)


async def _collect(
    query: PartSearchQuery, on_event: ProgressCallback | None = None
) -> CompetitorPriceReport:
    emit = on_event or (lambda stage, message: None)
    sources: tuple[PriceSource, ...] = (
        AvtoproPriceSource(),
        PromPriceSource(),
        GooglePriceSource(),
    )
    emit("start", "Готуємо пошукові запити")
    timeout = get_settings().competitor_price_source_timeout_seconds
    # Кожне джерело фільтрується моделлю одразу, як віддало пропозиції, —
    # LLM працює, поки найповільніше джерело ще збирає. Це половина часу звіту.
    results = await asyncio.gather(
        *(_refined_source(source, query, timeout, emit) for source in sources)
    )
    refined = await _to_uah(tuple(results))
    sane = _drop_implausible(_single_currency(refined))
    return CompetitorPriceReport(
        query=query,
        sources=await _verify_offers(query, sane, emit),
        observed_at=datetime.now(UTC),
    )


async def _refined_source(
    source: PriceSource,
    query: PartSearchQuery,
    timeout: float,
    emit: ProgressCallback,
) -> SourceResult:
    return await _refine_source(
        query, await _run_source(source, query, timeout, emit), emit
    )


async def _refine_source(
    query: PartSearchQuery,
    result: SourceResult,
    emit: ProgressCallback,
) -> SourceResult:
    """Пропустити зібране крізь дешеву модель: вона бачить те, чого не бачать токени."""
    if not result.offers or not llm_filter.is_enabled():
        return result

    emit("filter", f"{result.label}: звіряємо {len(result.offers)} варіантів")
    verdicts = await llm_filter.classify(
        name=query.name,
        brand=_market_brand(query.brand),
        oem_numbers=query.oem_numbers,
        titles=[offer.title for offer in result.offers],
    )
    if not verdicts:
        return result

    kept: list[MarketOffer] = []
    for index, offer in enumerate(result.offers):
        match verdicts.get(index):
            case "no":
                continue
            case "same":
                offer = replace(
                    offer,
                    confidence=max(offer.confidence, _LLM_SAME_CONFIDENCE),
                    is_analog=False,
                )
            case "analog":
                offer = replace(offer, confidence=_ANALOG_CONFIDENCE, is_analog=True)
        kept.append(offer)

    dropped = len(result.offers) - len(kept)
    if dropped:
        emit("filter", f"{result.label}: відсіяли {dropped} чужих позицій")
    return replace(
        result,
        offers=tuple(kept),
        status="empty" if not kept and result.status == "ok" else result.status,
    )


async def _verify_offers(
    query: PartSearchQuery,
    sources: tuple[SourceResult, ...],
    emit: ProgressCallback,
) -> tuple[SourceResult, ...]:
    """Другий прохід моделі по цінах, з яких рахується звіт.

    Перший фільтр бачить лише назви — ціну оцінити нічим, бо медіана ринку
    зʼявляється аж коли відповіли всі джерела. Тут модель отримує ціну,
    продавця, наявність і стан, а ми діємо так: підтверджене лишається,
    відкинуте зникає, а все неперевірене падає нижче порога статистики —
    підозріло дешева пропозиція не задасть рекомендовану ціну навіть тоді,
    коли модель недоступна.
    """
    if not get_settings().competitor_verify_enabled or not llm_filter.is_enabled():
        return sources

    indexed = [
        (source_index, offer_index, offer)
        for source_index, source in enumerate(sources)
        for offer_index, offer in enumerate(source.offers)
    ]
    strong = [
        offer.price
        for _, _, offer in indexed
        if offer.confidence >= _MIN_STATS_CONFIDENCE
    ]
    if len(strong) < _VERIFY_MIN_CONFIDENT:
        return sources
    anchor = Decimal(str(median(strong)))

    def worth_checking(offer: MarketOffer) -> bool:
        # Все, що йде в статистику, плюс підозріло дешеві поза нею.
        return (
            offer.confidence >= _MIN_STATS_CONFIDENCE
            or offer.price < anchor / _SUSPICIOUS_LOW_FACTOR
        )

    # Найдешевші перші: саме вони задають рекомендацію, і саме вони найчастіше
    # виявляються не тим товаром.
    picked = sorted(
        (item for item in indexed if worth_checking(item[2])),
        key=lambda item: item[2].price,
    )
    if not picked:
        return sources
    if len(picked) > _VERIFY_MAX_OFFERS:
        log.info(
            "Перевірка цін: %d пропозицій понад стелю %d лишились неперевіреними",
            len(picked) - _VERIFY_MAX_OFFERS,
            _VERIFY_MAX_OFFERS,
        )
        picked = picked[:_VERIFY_MAX_OFFERS]

    emit("filter", f"Перевіряємо ціни: {len(picked)} пропозицій")
    verdicts = await llm_filter.verify_offers(
        name=query.name,
        brand=_market_brand(query.brand),
        oem_numbers=query.oem_numbers,
        market_summary=f"Медіана ринку: {anchor} {_report_currency(sources)}",
        offers=[_offer_facts(offer) for _, _, offer in picked],
    )

    updates: dict[tuple[int, int], MarketOffer | None] = {}
    for position, (source_index, offer_index, offer) in enumerate(picked):
        match verdicts.get(position):
            case "ok":
                continue
            case "drop":
                updates[(source_index, offer_index)] = None
            case _:
                # «Не знаю» — не доказ поганої пропозиції. Понижуємо лише
                # підозріло дешеві: саме вони здатні збити рекомендацію
                # сміттєвою ціною. Решту лишаємо в статистиці, інакше модель
                # мовчки вирізає чесний дешевий ринок і радить підняти ціну —
                # так на реальній картці з 29 пропозицій у розрахунок пройшли
                # дві, а рекомендація вийшла втричі вища за ринок.
                if offer.price >= anchor / _SUSPICIOUS_LOW_FACTOR:
                    continue
                updates[(source_index, offer_index)] = replace(
                    offer,
                    confidence=min(offer.confidence, _UNVERIFIED_CONFIDENCE),
                )
    if not updates:
        return sources

    dropped = sum(1 for value in updates.values() if value is None)
    if dropped:
        emit("filter", f"Відсіяли {dropped} сумнівних цін")
    log.info(
        "Перевірка цін: відкинуто %d, знижено %d із %d",
        dropped,
        len(updates) - dropped,
        len(picked),
    )
    return tuple(
        replace(
            source,
            offers=tuple(
                updates.get((source_index, offer_index), offer)
                for offer_index, offer in enumerate(source.offers)
                if updates.get((source_index, offer_index), offer) is not None
            ),
        )
        for source_index, source in enumerate(sources)
    )


def _offer_facts(offer: MarketOffer) -> llm_filter.OfferFacts:
    return llm_filter.OfferFacts(
        title=offer.title,
        price=f"{offer.price} {offer.currency}",
        seller=offer.seller,
        availability=offer.availability,
        condition=offer.condition,
    )


def _report_currency(sources: tuple[SourceResult, ...]) -> str:
    return next(
        (offer.currency for source in sources for offer in source.offers), "UAH"
    )


async def _to_uah(sources: tuple[SourceResult, ...]) -> tuple[SourceResult, ...]:
    """Перерахувати доларові та єврові пропозиції в гривню за курсом НБУ.

    Курси беруться лише коли іноземна валюта справді зустрілась; недоступний
    НБУ — пропозиції лишаються як є і їх зніме _single_currency, як раніше.
    """
    foreign = {
        offer.currency
        for source in sources
        for offer in source.offers
        if offer.currency != "UAH"
    }
    if not foreign:
        return sources
    rates = await exchange_rates.uah_rates()
    if not rates:
        return sources
    converted: list[SourceResult] = []
    for source in sources:
        offers = tuple(
            replace(
                offer,
                price=(offer.price * rates[offer.currency]).quantize(Decimal("0.01")),
                currency="UAH",
            )
            if offer.currency in rates
            else offer
            for offer in source.offers
        )
        converted.append(replace(source, offers=offers))
    return tuple(converted)


def _drop_implausible(sources: tuple[SourceResult, ...]) -> tuple[SourceResult, ...]:
    """Прибрати цінове сміття: нулі та дикі викиди відносно медіани.

    Історія: сніпет Google віддавав «доставка 0 грн» як ціну 0 і склеєні
    цифри як мільйони — обидва випадки доїжджали до клієнта. Нуль — не ціна
    ніколи; викид ловимо лише коли є з чим порівняти (медіана впевнених
    збігів і не менше чотирьох пропозицій), щоб не зачепити чесний розкид.
    """
    positive = tuple(
        replace(
            source,
            offers=tuple(offer for offer in source.offers if offer.price > 0),
        )
        for source in sources
    )
    offers = [offer for source in positive for offer in source.offers]
    strong = [
        offer.price for offer in offers if offer.confidence >= _MIN_STATS_CONFIDENCE
    ]
    if len(offers) < _OUTLIER_MIN_OFFERS or not strong:
        return positive
    anchor = Decimal(str(median(strong)))
    if anchor <= 0:
        return positive

    def plausible(offer: MarketOffer) -> bool:
        return anchor / _OUTLIER_FACTOR <= offer.price <= anchor * _OUTLIER_FACTOR

    dropped = sum(1 for offer in offers if not plausible(offer))
    if dropped:
        log.info(
            "Ціни конкурентів: відкинуто %d викид(ів) за медіаною %s", dropped, anchor
        )
    return tuple(
        replace(source, offers=tuple(filter(plausible, source.offers)))
        for source in positive
    )


def _single_currency(sources: tuple[SourceResult, ...]) -> tuple[SourceResult, ...]:
    """Drop offers priced in a foreign currency — 50 USD is not below 200 UAH.

    Without exchange rates the only honest comparison is within one currency.
    The catalog is priced in UAH, so any UAH offers win even as a minority;
    only a report with no UAH at all falls back to the most common currency.
    """
    counts = Counter(
        offer.currency for source in sources for offer in source.offers
    )
    if len(counts) < 2:
        return sources
    main = "UAH" if counts.get("UAH") else counts.most_common(1)[0][0]
    log.info(
        "Competitor prices: kept %s, dropped %d offer(s) in other currencies",
        main,
        sum(count for currency, count in counts.items() if currency != main),
    )
    kept: list[SourceResult] = []
    for source in sources:
        offers = tuple(offer for offer in source.offers if offer.currency == main)
        status = "empty" if not offers and source.status == "ok" else source.status
        kept.append(replace(source, offers=offers, status=status))
    return tuple(kept)


async def _run_source(
    source: PriceSource,
    query: PartSearchQuery,
    timeout: float,
    emit: ProgressCallback,
) -> SourceResult:
    emit("source", f"Збираємо пропозиції: {source.label}")
    try:
        result = await asyncio.wait_for(source.search(query), timeout=timeout)
    except Exception as exc:  # source failures must not hide the whole report
        log.warning("Competitor source %s failed: %s", source.source, exc)
        emit("source", f"{source.label}: джерело не відповіло")
        return SourceResult(
            source=source.source,
            label=source.label,
            status="error",
            error=str(exc),
        )
    emit("source", f"{source.label}: знайдено {len(result.offers)}")
    return result


class AvtoproPriceSource:
    source = "avtopro"
    label = "Avto.pro"

    async def search(self, query: PartSearchQuery) -> SourceResult:
        if not query.oem_numbers:
            return SourceResult(self.source, self.label, "skipped", error="No OEM number")

        def fetch() -> SourceResult:
            # Дефолтний ScrapeConfig — 30 с таймаут і 4 ретраї: один завислий
            # запит з'їдав увесь бюджет джерела. Стрічка й так рветься
            # антиботом — швидше здатися і віддати зібране.
            gateway = AvtoproGateway(
                replace(
                    avtopro_config(),
                    max_search_pages=4,
                    timeout=8.0,
                    max_retries=2,
                )
            )
            exact_codes = {_norm_code(number) for number in query.oem_numbers}
            for oem in query.oem_numbers[:3]:
                result = gateway.offers(
                    oem,
                    brand=query.brand,
                    name=query.name,
                    fallback_to_first=query.manual,
                )
                if result is None:
                    continue
                # Стрічка деталі — це сама деталь плюс аналоги інших виробників,
                # підібрані каталогом avto.pro. Аналоги лишаємо: саме вони
                # показують, за скільки продається те саме по суті.
                # Один артикул лежить на десятку складів — це той самий товар,
                # і десять рядків про нього лише забивають список та зсувають
                # медіану. Лишаємо найдешевшу пропозицію на артикул.
                # Відсів до дедупу, а не після: вживана деталь дешевша за нову,
                # і найдешевшим на артикул виявився б саме мотлох.
                unique = _cheapest_by_key(
                    (
                        offer
                        for offer in result.offers
                        # offer.used — машинний прапорець рядка (data-bu,
                        # розборка). Текст його не замінює: з пʼяти вживаних
                        # пропозицій на реальній сторінці слово «б/у» стояло
                        # лише в одній, а решта йшли як звичайні — зокрема та,
                        # що ставала мінімумом ринку.
                        if not offer.used
                        and not offer_gates.is_junk(
                            _avtopro_text(offer), offer.availability
                        )
                    ),
                    key=lambda offer: f"{offer.maker}|{_norm_code(offer.code)}",
                )
                offers = sorted(
                    (
                        MarketOffer(
                            source=self.source,
                            title=_avtopro_text(offer) or result.suggestion.title,
                            price=Decimal(str(offer.price)).quantize(Decimal("0.01")),
                            currency=offer.currency,
                            url=AVTOPRO_BASE_URL
                            + (offer.part_uri or result.suggestion.part_uri),
                            city=offer.city,
                            availability=offer.availability,
                            # Вживані сюди вже не доходять — прапорець рядка
                            # відсіяв їх до дедупу, тож «нове» тут факт.
                            condition=offer_gates.condition_of(
                                _avtopro_text(offer), offer.availability
                            )
                            or "new",
                            confidence=(
                                0.98
                                if _norm_code(offer.code) in exact_codes
                                else _ANALOG_CONFIDENCE
                            ),
                            is_analog=_norm_code(offer.code) not in exact_codes,
                        )
                        for offer in unique
                    ),
                    key=_by_confidence_then_price,
                )[:_AVTOPRO_MAX_OFFERS]
                if not offers:
                    continue
                return SourceResult(
                    self.source,
                    self.label,
                    "ok",
                    tuple(sorted(offers, key=_by_price)),
                )
            return SourceResult(self.source, self.label, "empty")

        return await asyncio.to_thread(fetch)


class PromPriceSource:
    source = "prom"
    label = "Prom.ua"

    async def search(self, query: PartSearchQuery) -> SourceResult:
        config = _source_config()
        async with AsyncHttpClient(config) as client:
            # Термів лише 2–3, а клієнт і так тримає спільний rate-limit:
            # паралельно — це ціна найповільнішого терму, а не сума всіх.
            batches = await asyncio.gather(
                *(
                    self._term_offers(client, query, term, config)
                    for term in _search_terms(query)
                )
            )
        offers = [offer for batch in batches for offer in batch]

        unique = _cheapest_by_key(offers, key=lambda offer: offer.seller or offer.url)
        # Обрізаємо найслабші збіги, а показуємо за ціною: так видно ринок,
        # а не наш рейтинг схожості.
        kept = sorted(unique, key=_by_confidence_then_price)[:_PROM_MAX_OFFERS]
        return SourceResult(
            self.source,
            self.label,
            "ok" if kept else "empty",
            tuple(sorted(kept, key=_by_price)),
        )

    async def _term_offers(
        self,
        client: AsyncHttpClient,
        query: PartSearchQuery,
        term: str,
        config: ScrapeConfig,
    ) -> list[MarketOffer]:
        """One term across all configured pages — fetched in parallel, not in turn."""
        pages = await asyncio.gather(
            *(
                self._page_products(client, term, number)
                for number in range(1, max(1, config.max_search_pages) + 1)
            )
        )
        return [
            offer
            for products in pages
            for offer in self._offers_from(query, products, term)
        ]

    async def _page_products(
        self, client: AsyncHttpClient, term: str, number: int
    ) -> list[Any]:
        """Одна сторінка, що не відповіла, не має забирати з собою решту:
        сторінок тепер десяток, і збій будь-якої лишав звіт зовсім без Prom."""
        params: dict[str, Any] = {"search_term": term}
        if number > 1:
            params["page"] = number
        try:
            html = await client.get_html(f"{PROM_BASE_URL}/ua/search", params)
            return parse_search(html, "ua").products
        except Exception as exc:
            log.info("Prom: сторінка %d для %r не відповіла: %s", number, term, exc)
            return []

    def _offers_from(
        self, query: PartSearchQuery, products: Iterable[Any], term: str
    ) -> Iterator[MarketOffer]:
        for product in products:
            score = _match_score(
                query,
                product.name,
                product.sku,
                name=product.name,
                brand=product.brand,
            )
            if not score or _is_own_prom_product(query, product):
                continue
            # Вживане й «ціна за запитом» відпадають до дедупу за продавцем:
            # інакше найдешевшим у продавця став би саме мотлох.
            if offer_gates.is_junk(product.name, product.presence):
                log.info("Ціни конкурентів: відсіяно %r", product.name)
                continue
            price = parse_price(product.effective_price)
            if price is None or not product.url:
                continue
            yield MarketOffer(
                source=self.source,
                title=product.name or product.sku or term,
                price=price,
                currency=product.currency or "UAH",
                url=product.url,
                seller=product.seller_name,
                availability=product.presence,
                condition=offer_gates.condition_of(product.name),
                image_url=product.image,
                confidence=score,
                # Номер не збігся — знайшли за назвою, тобто аналог.
                is_analog=score < _OEM_HIT_SCORE,
            )


class GooglePriceSource:
    """Serper.dev: незалежні магазини, які не живуть на маркетплейсах.

    Ціна — з тексту сніпета видачі; нема в сніпеті — один GET сторінки і
    structured data (JSON-LD, microdata, og:price). Окремих LLM-викликів
    джерело не робить: зібрані тайтли фільтрує спільний llm_filter далі.
    """

    source = "google"
    label = "Google"

    async def search(self, query: PartSearchQuery) -> SourceResult:
        api_key = get_settings().serper_api_key
        if not api_key:
            return SourceResult(self.source, self.label, "skipped", error="No API key")

        async with httpx.AsyncClient(
            timeout=_SERP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        ) as client:
            batches = await asyncio.gather(
                *(self._serp(client, api_key, term) for term in _search_terms(query))
            )
            candidates = self._candidates(query, batches)
            offers = await self._priced_offers(client, candidates)

        unique = _cheapest_by_key(offers, key=lambda offer: offer.seller or offer.url)
        kept = sorted(unique, key=_by_confidence_then_price)[:_GOOGLE_MAX_OFFERS]
        return SourceResult(
            self.source,
            self.label,
            "ok" if kept else "empty",
            tuple(sorted(kept, key=_by_price)),
        )

    async def _serp(
        self, client: httpx.AsyncClient, api_key: str, term: str
    ) -> list[dict]:
        response = await client.post(
            SERPER_URL,
            json={"q": term, "gl": "ua", "hl": "uk", "num": _SERP_RESULTS_PER_TERM},
            headers={"X-API-KEY": api_key},
        )
        response.raise_for_status()
        return response.json().get("organic") or []

    def _candidates(
        self, query: PartSearchQuery, batches: Iterable[list[dict]]
    ) -> list[tuple[dict, str, float]]:
        own_domain = _serp_domain(query.source_url)
        seen: set[str] = set()
        picked: list[tuple[dict, str, float]] = []
        for item in (entry for batch in batches for entry in batch):
            url = item.get("link") or ""
            domain = _serp_domain(url)
            if not domain or url in seen:
                continue
            if domain == own_domain or _covered_elsewhere(domain):
                continue
            if _is_own_domain(domain):
                continue
            if not domain.endswith(_SERP_ALLOWED_TLD):
                continue
            # Лише за назвою: сніпет збирає й інші оголошення сторінки, тож
            # магазин, який поруч торгує розборкою, вилітав би дарма.
            # Заразом бережемо слоти докачки сторінок для справжніх кандидатів.
            if offer_gates.is_junk(item.get("title")):
                continue
            seen.add(url)
            score = _match_score(
                query,
                item.get("title"),
                item.get("snippet"),
                name=item.get("title"),
            )
            if score:
                picked.append((item, domain, score))
        return picked

    async def _priced_offers(
        self,
        client: httpx.AsyncClient,
        candidates: list[tuple[dict, str, float]],
    ) -> list[MarketOffer]:
        # Сторінка надійніша за сніпет: регулярка по тексту ловила «доставка
        # 0 грн» і склеєні цифри. Тому спершу читаємо сторінку (структурні
        # дані), і лише коли вона не віддала ціну — беремо сніпет як резерв.
        offers: list[MarketOffer] = []
        fetched = candidates[:_SERP_MAX_PAGE_FETCHES]
        priced_pages = await asyncio.gather(
            *(
                self._page_price(client, item.get("link") or "")
                for item, _, _ in fetched
            )
        )
        leftovers: list[tuple[dict, str, float]] = list(
            candidates[_SERP_MAX_PAGE_FETCHES:]
        )
        for (item, domain, score), priced in zip(fetched, priced_pages):
            if priced is not None:
                offers.append(self._offer(item, domain, score, *priced))
            else:
                leftovers.append((item, domain, score))
        for item, domain, score in leftovers:
            snippet = f"{item.get('title') or ''} {item.get('snippet') or ''}"
            price = _price_from_text(snippet)
            if price is not None:
                offers.append(self._offer(item, domain, score, price, "UAH"))
        return offers

    async def _page_price(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[Decimal, str] | None:
        """Чужий сайт, що не відповів — просто без ціни, а не без джерела."""
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return None
            return _structured_price(response.text)
        except Exception as exc:
            log.info("Google: сторінка %r без ціни: %s", url, exc)
            return None

    def _offer(
        self, item: dict, domain: str, score: float, price: Decimal, currency: str
    ) -> MarketOffer:
        return MarketOffer(
            source=self.source,
            title=item.get("title") or item.get("link") or "",
            price=price,
            currency=_norm_currency(currency),
            url=item.get("link") or "",
            seller=domain,
            confidence=score,
            is_analog=score < _OEM_HIT_SCORE,
        )


_TEXT_PRICE_RE = re.compile(
    r"(\d[\d\s ]{0,9}(?:[.,]\d{1,2})?)\s*(?:грн|₴|uah)", re.I
)
_LD_JSON_RE = re.compile(
    r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.I | re.S
)


def _price_from_text(text: str) -> Decimal | None:
    match = _TEXT_PRICE_RE.search(text)
    return parse_price(match.group(1)) if match else None


def _structured_price(html: str) -> tuple[Decimal, str] | None:
    """Ціна з розмітки сторінки: JSON-LD, потім microdata, потім OpenGraph."""
    for block in _LD_JSON_RE.findall(html):
        try:
            found = _ld_price(json.loads(block.strip()))
        except ValueError:
            continue
        if found:
            return found
    flat = re.sub(r"\s+", " ", html)
    for pattern in (
        r'<[^>]*itemprop="price"[^>]*>',
        r"<meta[^>]*og:price:amount[^>]*>",
    ):
        for match in re.finditer(pattern, flat, re.I):
            tag = match.group(0)
            content = re.search(r'content="([^"]*)"', tag)
            raw = (
                content.group(1)
                if content
                else flat[match.end() : match.end() + 40].split("<", 1)[0]
            )
            price = parse_price(raw)
            if price is not None:
                # Валюти в microdata поруч може й не бути; ринок — гривневий.
                return price, "UAH"
    return None


def _ld_price(node: Any) -> tuple[Decimal, str] | None:
    if isinstance(node, list):
        return next(filter(None, map(_ld_price, node)), None)
    if not isinstance(node, dict):
        return None
    if node.get("@type") in ("Offer", "AggregateOffer"):
        price = parse_price(node.get("price") or node.get("lowPrice"))
        if price is not None:
            return price, _norm_currency(str(node.get("priceCurrency") or ""))
    return next(
        filter(
            None,
            (
                _ld_price(value)
                for value in node.values()
                if isinstance(value, (dict, list))
            ),
        ),
        None,
    )


def _norm_currency(value: str | None) -> str:
    text = (value or "").strip().upper()
    return "UAH" if text in ("", "ГРН", "ГРН.", "₴") else text


def _serp_domain(url: str | None) -> str:
    return (urlsplit(url or "").hostname or "").lower().removeprefix("www.")


def _is_own_domain(domain: str) -> bool:
    """Власний сайт замовника — не конкурент, разом із піддоменами."""
    return any(
        domain == own or domain.endswith("." + own) for own in GLOBAL_OWN_DOMAINS
    )


def _covered_elsewhere(domain: str) -> bool:
    return any(
        domain == covered or domain.endswith("." + covered)
        for covered in _SERP_COVERED_DOMAINS
    )


def _source_config() -> ScrapeConfig:
    return ScrapeConfig(
        delay=0.05,
        delay_jitter=0.03,
        timeout=6.0,
        max_retries=2,
        # Сторінки одного терміну йдуть паралельно, тож глибина коштує майже
        # стільки ж часу, скільки одна сторінка.
        page_concurrency=6,
        max_search_pages=6,
        base_headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        },
    )


def _query_from_listing(
    listing: Listing,
    seller_exclusions: Iterable[CompetitorSellerExclusion] = (),
) -> PartSearchQuery:
    raw = listing.raw_data if isinstance(listing.raw_data, dict) else {}
    raw_numbers = raw.get("oem_numbers") or []
    candidates = [*raw_numbers, listing.sku]
    numbers = tuple(
        dict.fromkeys(filter(None, (normalize_oem(value) for value in candidates)))
    )
    export_seller = seller_from_export_url(listing.url)
    store_ids, store_slugs = _owner_identity(seller_exclusions)
    owner_seller_ids = tuple(
        sorted(
            {
                value
                for value in (
                    *store_ids,
                    _text_value(raw.get("seller_id")),
                    export_seller.company_id if export_seller else None,
                )
                if value
            }
        )
    )
    owner_seller_slugs = tuple(
        sorted(
            {
                value
                for value in (
                    *store_slugs,
                    _normalized_slug(raw.get("seller_slug")),
                    export_seller.slug if export_seller else None,
                )
                if value
            }
        )
    )
    return PartSearchQuery(
        listing_id=str(listing.id),
        oem_numbers=numbers,
        brand=listing.brand,
        name=listing.name,
        source_url=listing.url,
        owner_seller_ids=owner_seller_ids,
        owner_seller_slugs=owner_seller_slugs,
    )


def _market_brand(brand: str | None) -> str | None:
    """Марка виробника деталі; власна торгова марка нею не вважається.

    Порожня марка нікого не відсіює (`brands_compatible` пропускає невідоме),
    тож звірка за номером починає працювати, а в промт моделі не йде рядок
    «Виробник: KEMP», який схиляв її до вердикту «аналог». Для справжніх марок
    каталогу (VAG, Bosch, Opel) усе лишається як було.

    У самому запиті марку лишаємо: avto.pro шукає деталь у каталозі за
    виробником, і там KEMP — справжній ключ. Знімаємо її лише там, де вона
    видає себе за виробника деталі: звірка бренду та промти моделі.
    """
    return None if (brand or "").strip().casefold() in GLOBAL_OWN_BRANDS else brand


def _search_terms(query: PartSearchQuery) -> list[str]:
    """The number, then the name — they find different halves of the market.

    A catalog number is often the shop's own article, so searching by it turns
    up only its own dealers; the name is what surfaces actual competitors. The
    brand is deliberately left out: it is usually our own, and it would bias
    the search back towards our own goods.
    """
    terms = list(query.oem_numbers[:_MAX_OEM_TERMS])
    tokens = normalize_tokens(query.name)[:_MAX_NAME_TOKENS]
    if tokens:
        terms.append(" ".join(tokens))
    return [term for term in dict.fromkeys(terms) if term]


def _matchable_oem_codes(query: PartSearchQuery) -> list[str]:
    """OEM numbers long enough that a substring hit is not a coincidence."""
    return [
        code
        for code in map(_norm_code, query.oem_numbers)
        if len(code) >= _MIN_SUBSTRING_OEM_LENGTH
    ]


def _is_ambiguous_code(code: str) -> bool:
    """Short and all digits — such a number is somebody's own article too."""
    return code.isdigit() and len(code) < _MIN_SELF_SUFFICIENT_DIGITS


def _topic_overlap(seed_name: str, text: str) -> bool:
    """A word shared with the catalog name, endings ignored (бігун/бігунок)."""
    stems = {
        token[:_MIN_STEM]
        for token in normalize_tokens(seed_name)
        if len(token) >= _MIN_STEM
    }
    return any(
        token[:_MIN_STEM] in stems
        for token in normalize_tokens(text)
        if len(token) >= _MIN_STEM
    )


def _match_score(
    query: PartSearchQuery,
    *values: str | None,
    name: str | None = None,
    brand: str | None = None,
) -> float:
    """Confidence that these fields describe our part; 0.0 when they do not.

    The number is looked for across every field, but similarity is scored
    against `name` alone — a foreign article number mixed into the text only
    dilutes it.
    """
    text = " ".join(value or "" for value in values)
    if laterality_conflict(normalize_tokens(query.name), normalize_tokens(text)):
        return 0.0

    haystack = _norm_code(text)
    hits = [code for code in _matchable_oem_codes(query) if code in haystack]
    # Бренд звіряємо лише для збігу за номером: той самий номер під чужою
    # маркою — інша деталь. Для пошуку за назвою бренд навпаки заважає — він
    # майже завжди наш власний, а конкурент продає ту саму річ під своїм.
    if hits and not brands_compatible(_market_brand(query.brand), brand):
        hits = []
    if hits:
        # Суто цифровий короткий номер — це ще й чийсь внутрішній артикул
        # («Пакети для сміття … 1300115», «Шафа ВРА-03 13-00115»), тож самого
        # номера мало: назва має бути хоч про ту саму річ.
        if not all(_is_ambiguous_code(code) for code in hits):
            return _OEM_HIT_SCORE
        if _topic_overlap(query.name, text):
            return _OEM_HIT_SCORE

    # Номер у каталозі часто внутрішній артикул: по ньому знаходяться лише
    # власні дилери. Схожа назва — це і є справжні конкуренти.
    similarity = token_similarity(
        set(normalize_tokens(query.name)),
        set(normalize_tokens(text if name is None else name)),
    )
    if similarity >= _STRONG_NAME_SIMILARITY:
        return 0.7
    if similarity >= _MIN_NAME_SIMILARITY:
        return 0.55
    return 0.0


def _product_matches(
    query: PartSearchQuery,
    *values: str | None,
    name: str | None = None,
    brand: str | None = None,
) -> bool:
    return _match_score(query, *values, name=name, brand=brand) > 0.0


def _is_own_prom_product(query: PartSearchQuery, product: Any) -> bool:
    """Identify the owned Prom offer without relying on a mutable product title."""
    seller_id = _text_value(getattr(product, "seller_id", None))
    if seller_id and seller_id in query.owner_seller_ids:
        return True

    seller_slug = _normalized_slug(getattr(product, "seller_slug", None))
    if seller_slug and seller_slug in query.owner_seller_slugs:
        return True

    url_seller_id = _prom_seller_id_from_url(getattr(product, "url", None))
    if url_seller_id and url_seller_id in query.owner_seller_ids:
        return True

    return _same_marketplace_product(query.source_url, getattr(product, "url", None))


def _prom_seller_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    hostname = (urlsplit(url.strip()).hostname or "").casefold()
    match = _PROM_SELLER_HOST_ID_RE.search(hostname)
    return match.group("id") if match else None


def _same_marketplace_product(source_url: str | None, offer_url: str | None) -> bool:
    if not source_url or not offer_url:
        return False

    source_id = _prom_product_id(source_url)
    offer_id = _prom_product_id(offer_url)
    if source_id and offer_id:
        return source_id == offer_id

    return _normalized_url(source_url) == _normalized_url(offer_url)


def _prom_product_id(url: str) -> str | None:
    match = _PROM_PRODUCT_ID_RE.search(urlsplit(url).path)
    return match.group("id") if match else None


def _normalized_url(url: str) -> tuple[str, str]:
    parsed = urlsplit(url.strip())
    path = re.sub(r"^/[a-z]{2}/", "/", parsed.path.rstrip("/"), flags=re.I)
    return (parsed.hostname or "").lower().removeprefix("www."), path.lower()


def _normalized_slug(value: Any) -> str | None:
    text = _text_value(value)
    return text.casefold() if text else None


def _text_value(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _avtopro_text(offer: Any) -> str:
    """Текст рядка avto.pro: виробник, код і опис в один рядок для відсівів."""
    return " ".join(
        part for part in (offer.maker, offer.code, offer.description) if part
    )


def _norm_code(value: str | None) -> str:
    return _NON_ALNUM_RE.sub("", (value or "").upper())


def _recommended_price(prices: list[Decimal]) -> Decimal:
    """Конкретна сума до виставлення: на 6% нижче мінімуму впевнених збігів.

    ponytail: наївне правило "трохи дешевше за найдешевшого"; коли з'явиться
    маржа/собівартість — рахувати від неї, а не лише від ринку.
    """
    # Копійчані ціни округлення до гривні здатне обнулити — нуль не рекомендація.
    return max(
        (min(prices) * _RECOMMENDED_DISCOUNT).quantize(Decimal("1")), Decimal("1")
    )


def _stats_prices(offers: Iterable[MarketOffer]) -> list[Decimal]:
    """Ціни впевнених збігів; коли їх замало — усі, що пройшли гейти.

    Дві випадкові ціни не описують ринок. Якщо після перевірки впевнених
    лишилась жменя, а пропозицій було помітно більше, вужча вибірка
    систематично зміщена вгору: модель сумнівається саме в дешевих аналогах.
    Ширша вибірка з позначкою краща за впевнено неправильну рекомендацію.
    """
    offers = list(offers)
    strong = [
        offer.price for offer in offers if offer.confidence >= _MIN_STATS_CONFIDENCE
    ]
    if len(strong) >= _MIN_STATS_SAMPLE or len(offers) < _MIN_STATS_SAMPLE:
        return strong or [offer.price for offer in offers]
    # Пропозицій вистачало, а впевнених лишилась жменя — вибірка зміщена.
    return [offer.price for offer in offers]


def _by_confidence_then_price(offer: MarketOffer) -> tuple[float, Decimal]:
    """Trim order: when the list does not fit, the weakest matches go first."""
    return (-offer.confidence, offer.price)


def _by_price(offer: MarketOffer) -> Decimal:
    """Display order: one price ladder, cheapest first, analogues included."""
    return offer.price


def _cheapest_by_key(offers: Iterable[Any], *, key) -> list[Any]:
    cheapest: dict[str, Any] = {}
    for offer in offers:
        marker = key(offer)
        current = cheapest.get(marker)
        if current is None or offer.price < current.price:
            cheapest[marker] = offer
    return list(cheapest.values())


def _decimal_json(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _cache_key(query: PartSearchQuery) -> str:
    payload = "|".join(
        [
            *query.oem_numbers,
            query.brand or "",
            query.name,
            *query.owner_seller_ids,
            *query.owner_seller_slugs,
        ]
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    # v8: відсіви вживаного й перевірка цін другим проходом — інакше шість
    # годин TTL показували б старі звіти з розборкою і фальшивим "new".
    return f"competitor-prices:v10:{query.listing_id}:{digest}"
