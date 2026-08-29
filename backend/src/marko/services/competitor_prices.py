"""Aggregate competitor prices from public auto-parts marketplaces."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from html import unescape
from statistics import median
from typing import Any, Callable, Iterable, Iterator, Protocol
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from marko.core.config import get_settings
from marko.infrastructure.db.models import Listing, MarketplaceStore
from marko.parsers.avtopro import (
    AvtoproGateway,
    default_config as avtopro_config,
    parse_feed,
)
from marko.parsers.avtopro.gateway import BASE_URL as AVTOPRO_BASE_URL
from marko.parsers.prom.client import AsyncHttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.parser import parse_product_page, parse_search
from marko.parsers.prom_export import (
    normalize_oem,
    parse_price,
    seller_from_export_url,
)
from marko.repositories.listings import get_workspace_listing
from marko.services import llm_filter
from marko.services.exchange_rates import KYIV, NbuExchangeRateProvider
from marko.services.matching import (
    brands_compatible,
    laterality_conflict,
    normalize_tokens,
    token_similarity,
)
from marko.services.parser_models import Seller
from marko.services.seller_exclusions import (
    SellerExclusion,
    load_prom_seller_exclusions,
)

log = logging.getLogger(__name__)

PROM_BASE_URL = "https://prom.ua"

# (стадія, підпис для користувача) — синхронний виклик, щоб класти в чергу SSE.
ProgressCallback = Callable[[str, str], None]

_MIN_SUBSTRING_OEM_LENGTH = 6  # коротший номер трапляється в чужих назвах випадково
_MIN_SELF_SUFFICIENT_DIGITS = 8  # коротший цифровий номер сам по собі нічого не доводить
_MIN_STEM = 4  # довжина кореня для звірки теми назви
_MIN_STATS_CONFIDENCE = 0.7  # слабкі збіги не мають задавати мін/медіану/макс
_MIN_NAME_SIMILARITY = 0.7  # нижче — це вже інша деталь, а не конкурент
_STRONG_NAME_SIMILARITY = 0.8  # від цього збіг за назвою рахується у статистику
_OEM_HIT_SCORE = 0.9  # знайдено за номером — це та сама деталь, не аналог
_ANALOG_CONFIDENCE = 0.6  # аналог іншого виробника: показуємо, але не в статистиці
_LLM_SAME_CONFIDENCE = 0.95  # модель підтвердила: та сама деталь
_VERIFIED_CONFIDENCE = 0.99  # друга перевірка сторінки підтвердила товар і ціну
_MIN_RECOMMENDATION_OFFERS = 2
_LOW_PRICE_RATIO = Decimal("0.50")
_HIGH_PRICE_RATIO = Decimal("2")
_MODIFIED_Z_LIMIT = Decimal("3.5")
_MAX_VERIFICATION_OFFERS = 120
_VERIFICATION_TIMEOUT = 8.0
_PAGE_EVIDENCE_CHARS = 6000
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
_SERP_COVERED_DOMAINS = ("prom.ua", "avto.pro", "exist.ua")
# Ринок — український: російські й білоруські магазини не конкуренти,
# а їхні ціни в рублях лише засмічують порівняння.
_SERP_BLOCKED_TLDS = (".ru", ".su", ".by", ".рф", ".xn--p1ai")

_NON_ALNUM_RE = re.compile(r"[^0-9A-ZА-ЯІЇЄЁ]+", re.I)
_PROM_PRODUCT_ID_RE = re.compile(r"/(?:[a-z]{2}/)?p(?P<id>\d+)-", re.I)
_USED_RE = re.compile(
    r"(?:"
    r"(?<![\w])б\s*[/.‐‑‒–—-]?\s*[ув](?![\w])|"
    r"\b(?:used|refurbished|remanufactured)\b|"
    r"вживан|бывш\w*\s+в\s+употреблен|відновлен|восстановлен|"
    r"авторозбір|авторазбор|автошрот"
    r")",
    re.I,
)
_NON_FIXED_PRICE_RE = re.compile(
    r"(?:"
    r"(?:ціна|цена).{0,35}(?:за\s+запитом|по\s+запросу|уточн|договірн|договорн|пізніше|позже|напиш|пишіт|сообщим|повідомим)|"
    r"(?:за\s+запитом|по\s+запросу|уточн|напиш|пишіт|сообщим|повідомим).{0,35}(?:ціна|цену|цена)|"
    r"price\s+on\s+request"
    r")",
    re.I,
)
_UNAVAILABLE_RE = re.compile(
    r"(?:немає\s+в\s+наявності|нет\s+в\s+наличии|не\s+в\s+наявності|закінчився|out\s+of\s+stock|неактуальн)",
    re.I,
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
    # Ціна впливає на статистику лише після повторної перевірки сторінки.
    verified: bool = False
    original_price: Decimal | None = None
    original_currency: str | None = None
    exchange_rate: Decimal | None = None
    exchange_rate_date: str | None = None
    verified_at: datetime | None = None
    price_changed_on_page: bool = False
    # Source-specific identity is internal and never leaves the public API.
    source_offer_id: str | None = field(default=None, repr=False, compare=False)
    source_code: str | None = field(default=None, repr=False, compare=False)
    # Сніпет пошуку допомагає гейтам, але не є частиною публічного API.
    evidence_text: str | None = field(default=None, repr=False, compare=False)

    def as_json(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("evidence_text", None)
        data.pop("source_offer_id", None)
        data.pop("source_code", None)
        data["price"] = str(self.price)
        for key in ("original_price", "exchange_rate"):
            if data[key] is not None:
                data[key] = str(data[key])
        if data["verified_at"] is not None:
            data["verified_at"] = data["verified_at"].isoformat()
        return data


@dataclass(frozen=True)
class VerifiedPageSnapshot:
    """Deterministic facts extracted from the freshly fetched product page."""

    url: str
    title: str
    code: str | None
    brand: str | None
    price: Decimal
    currency: str
    availability: str | None
    condition: str | None
    verified_at: datetime
    evidence_text: str


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
        values = self.prices
        return min(values) if values else None

    @property
    def median_price(self) -> Decimal | None:
        values = self.prices
        return Decimal(str(median(values))).quantize(Decimal("0.01")) if values else None

    @property
    def max_price(self) -> Decimal | None:
        values = self.prices
        return max(values) if values else None

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
    pricing_status: str | None = None

    @property
    def offers(self) -> list[MarketOffer]:
        return [offer for source in self.sources for offer in source.offers]

    @property
    def prices(self) -> list[Decimal]:
        return _stats_prices(self.offers)

    def as_json(self) -> dict[str, Any]:
        prices = self.prices
        eligible_offers_total = len(prices)
        pricing_status = self.pricing_status or (
            "reliable"
            if eligible_offers_total >= _MIN_RECOMMENDATION_OFFERS
            else "insufficient"
        )
        reliable = pricing_status == "reliable"
        return {
            "query": self.query.as_json(),
            "cached": self.cached,
            "observed_at": self.observed_at.isoformat(),
            "stats": {
                "offers_total": len(self.offers),
                "eligible_offers_total": eligible_offers_total,
                "sources_total": len(self.sources),
                "min_price": _decimal_json(min(prices) if prices else None),
                "median_price": _decimal_json(
                    Decimal(str(median(prices))).quantize(Decimal("0.01"))
                    if prices
                    else None
                ),
                "max_price": _decimal_json(max(prices) if prices else None),
                "recommended_price": _decimal_json(
                    _discounted_market_price(prices, Decimal("6")) if reliable else None
                ),
                "recommended_price_from": _decimal_json(
                    _discounted_market_price(prices, Decimal("7")) if reliable else None
                ),
                "recommended_price_to": _decimal_json(
                    _discounted_market_price(prices, Decimal("5")) if reliable else None
                ),
                "recommended_discount_percent": 6,
                "recommended_discount_min_percent": 5,
                "recommended_discount_max_percent": 7,
                "slider_discount_min_percent": 1,
                "slider_discount_max_percent": 30,
                "pricing_status": pricing_status,
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
_nbu_rates = NbuExchangeRateProvider(get_settings().competitor_price_cache_url)

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

    exclusions = await load_prom_seller_exclusions(session, workspace_id)
    return _query_from_listing(listing, exclusions)


def manual_search_query(
    oem: str,
    brand: str | None = None,
    name: str | None = None,
    owned_stores: Iterable[MarketplaceStore] = (),
    *,
    seller_exclusions: Iterable[SellerExclusion] = (),
) -> PartSearchQuery:
    """Запит із форми ручного пошуку: жодного товару в каталозі за ним немає."""
    number = normalize_oem(oem)
    numbers = (number,) if number else ()
    owner_ids, owner_slugs = _owner_identity(
        [*owned_stores, *seller_exclusions]
    )
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
    owned_stores: Iterable[MarketplaceStore | SellerExclusion],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Ідентичність власних Prom-магазинів: їхні пропозиції — не конкуренти."""
    prom_stores = [
        store for store in owned_stores if store.marketplace.casefold() == "prom"
    ]
    ids = tuple(
        sorted({v for v in (_text_value(s.external_id) for s in prom_stores) if v})
    )
    slugs = tuple(
        sorted(
            {
                value
                for value in (
                    _normalized_slug(
                        getattr(store, "slug", None) or getattr(store, "name", None)
                    )
                    for store in prom_stores
                )
                if value
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
        ExistPriceSource(),
        GooglePriceSource(),
    )
    emit("start", "Готуємо пошукові запити")
    timeout = get_settings().competitor_price_source_timeout_seconds
    # Кожне джерело фільтрується моделлю одразу, як віддало пропозиції, —
    # LLM працює, поки найповільніше джерело ще збирає. Це половина часу звіту.
    results = await asyncio.gather(
        *(_refined_source(source, query, timeout, emit) for source in sources)
    )
    checked_sources = await _verify_pricing_offers(query, tuple(results), emit)
    normalized_sources = await _normalize_currencies(checked_sources, emit)
    deduplicated_sources = _deduplicate_verified_sellers(normalized_sources)
    clean_sources, pricing_status = await _apply_anomaly_gates(
        query, deduplicated_sources, emit
    )
    return CompetitorPriceReport(
        query=query,
        sources=clean_sources,
        observed_at=datetime.now(UTC),
        pricing_status=pricing_status,
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
    """Жорсткі гейти, потім семантичне звірення дешевою моделлю."""
    if not result.offers:
        return result

    gated, rejected = _hard_gate_offers(result.offers)
    if rejected:
        emit("filter", f"{result.label}: відхилили {rejected} непридатних оголошень")
    result = replace(
        result,
        offers=gated,
        status="empty" if not gated and result.status == "ok" else result.status,
    )
    if not gated or not llm_filter.is_enabled():
        return result

    emit("filter", f"{result.label}: звіряємо {len(gated)} варіантів")
    verdicts = await llm_filter.classify(
        name=query.name,
        brand=query.brand,
        oem_numbers=query.oem_numbers,
        titles=[offer.title for offer in gated],
        details=[_offer_llm_details(offer) for offer in gated],
    )
    if not verdicts:
        # Помилка моделі не є дозволом використовувати неперевірені ціни.
        emit("filter", f"{result.label}: модель не підтвердила пропозиції")
        return replace(result, offers=(), status="empty")

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


async def _verify_pricing_offers(
    query: PartSearchQuery,
    sources: tuple[SourceResult, ...],
    emit: ProgressCallback,
) -> tuple[SourceResult, ...]:
    """Replace search prices with fresh product-page facts, then ask Nano.

    Every displayed offer, including an analogue, must survive a deterministic
    page parse and the semantic availability/state check. Search snippets never
    become market prices directly.
    """
    candidates = [
        offer
        for source in sources
        for offer in source.offers
    ]
    if not candidates:
        return sources

    if not llm_filter.is_enabled():
        emit("verify", "Перевірка недоступна: пропозиції не допущені до звіту")
        return tuple(
            replace(
                source,
                offers=(),
                status="empty" if source.status == "ok" else source.status,
            )
            for source in sources
        )

    selected = candidates[:_MAX_VERIFICATION_OFFERS]
    candidate_keys = {_offer_key(offer) for offer in candidates}
    selected_keys = {_offer_key(offer) for offer in selected}
    emit("verify", f"Перевіряємо {len(selected)} сторінок з товарами")

    snapshots = await _fetch_verified_snapshots(query, selected)
    reviewable: list[tuple[MarketOffer, VerifiedPageSnapshot]] = []
    review_payloads: list[dict[str, str]] = []
    for offer, snapshot in zip(selected, snapshots):
        if snapshot is None:
            continue
        page_offer = replace(
            offer,
            title=snapshot.title or offer.title,
            price=snapshot.price,
            currency=snapshot.currency,
            availability=snapshot.availability or offer.availability,
            condition=snapshot.condition or offer.condition,
            evidence_text=snapshot.evidence_text,
        )
        if _offer_rejection_reason(page_offer) is not None:
            continue
        reviewable.append((offer, snapshot))
        review_payloads.append(
            {
                "title": snapshot.title or offer.title,
                "seller": offer.seller or "",
                "price": str(snapshot.price),
                "currency": snapshot.currency,
                "availability": snapshot.availability or "",
                "source_condition": snapshot.condition or "",
                "candidate_match_type": "analog" if offer.is_analog else "same",
                "url": offer.url,
                "page_evidence": snapshot.evidence_text,
            }
        )

    verdicts = await llm_filter.verify_pricing_offers(
        name=query.name,
        brand=query.brand,
        oem_numbers=query.oem_numbers,
        candidates=review_payloads,
    )
    accepted_keys = {
        _offer_key(offer)
        for index, (offer, _) in enumerate(reviewable)
        if verdicts.get(index) is True
    }
    snapshot_by_key = {
        _offer_key(offer): snapshot for offer, snapshot in reviewable
    }

    verified_sources: list[SourceResult] = []
    rejected = 0
    for source in sources:
        kept: list[MarketOffer] = []
        for offer in source.offers:
            key = _offer_key(offer)
            if key not in candidate_keys:
                kept.append(offer)
            elif key in selected_keys and key in accepted_keys:
                snapshot = snapshot_by_key[key]
                kept.append(
                    replace(
                        offer,
                        title=snapshot.title or offer.title,
                        price=snapshot.price,
                        currency=snapshot.currency,
                        availability=snapshot.availability or offer.availability,
                        confidence=max(offer.confidence, _VERIFIED_CONFIDENCE),
                        condition="new",
                        verified=True,
                        # Preserve the authoritative page amount before any
                        # NBU conversion, never the preliminary search value.
                        original_price=snapshot.price,
                        original_currency=snapshot.currency,
                        verified_at=snapshot.verified_at,
                        price_changed_on_page=(
                            snapshot.price != offer.price
                            or snapshot.currency != _norm_currency(offer.currency)
                        ),
                        evidence_text=snapshot.evidence_text,
                    )
                )
            else:
                rejected += 1
        verified_sources.append(
            replace(
                source,
                offers=tuple(kept),
                status="empty" if not kept and source.status == "ok" else source.status,
            )
        )

    if rejected:
        emit("verify", f"Не допустили {rejected} неперевірених пропозицій")
    return tuple(verified_sources)


async def _fetch_verified_snapshots(
    query: PartSearchQuery, offers: list[MarketOffer]
) -> list[VerifiedPageSnapshot | None]:
    async with httpx.AsyncClient(
        timeout=_VERIFICATION_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
    ) as client:
        return list(
            await asyncio.gather(
                *(_fetch_verified_snapshot(client, query, offer) for offer in offers)
            )
        )


async def _fetch_verified_snapshot(
    client: httpx.AsyncClient,
    query: PartSearchQuery,
    offer: MarketOffer,
) -> VerifiedPageSnapshot | None:
    try:
        response = await client.get(offer.url)
        if response.status_code != 200:
            return None
        return _snapshot_from_html(query, offer, response.text)
    except Exception as exc:
        log.info("Offer verification page %r failed: %s", offer.url, exc)
        return None


def _snapshot_from_html(
    query: PartSearchQuery, offer: MarketOffer, html: str
) -> VerifiedPageSnapshot | None:
    evidence = _page_evidence(html)
    if not evidence:
        return None
    checked_at = datetime.now(UTC)

    if offer.source == "prom":
        try:
            product = parse_product_page(html, "ua").product
        except Exception:
            return None
        price = parse_price(product.effective_price)
        if price is None or price <= 0:
            return None
        return VerifiedPageSnapshot(
            url=offer.url,
            title=product.name or offer.title,
            code=product.sku,
            brand=product.brand,
            price=price,
            currency=_norm_currency(product.currency),
            availability=product.presence,
            condition=None,
            verified_at=checked_at,
            evidence_text=evidence,
        )

    if offer.source == "avtopro":
        try:
            feed = parse_feed(html)
        except Exception:
            return None
        matching = [
            row
            for row in feed.offers
            if (not offer.source_offer_id or row.warehouse_id == offer.source_offer_id)
            and (not offer.source_code or _norm_code(row.code) == _norm_code(offer.source_code))
        ]
        if len(matching) != 1:
            return None
        row = matching[0]
        return VerifiedPageSnapshot(
            url=offer.url,
            title=" ".join(filter(None, (row.maker, row.code, row.description))),
            code=row.code,
            brand=row.maker,
            price=Decimal(str(row.price)).quantize(Decimal("0.01")),
            currency=_norm_currency(row.currency),
            availability=row.availability,
            condition=None,
            verified_at=checked_at,
            evidence_text=evidence,
        )

    product = _primary_structured_product(html, query, offer)
    if product is None:
        return None
    title, code, brand, price, currency, availability, condition = product
    return VerifiedPageSnapshot(
        url=offer.url,
        title=title or offer.title,
        code=code,
        brand=brand,
        price=price,
        currency=currency,
        availability=availability,
        condition=condition,
        verified_at=checked_at,
        evidence_text=evidence,
    )


def _page_evidence(html: str) -> str | None:
    """Compact untrusted page data for the second verification pass."""
    structured = "\n".join(_LD_JSON_RE.findall(html))[: _PAGE_EVIDENCE_CHARS // 2]
    visible = re.sub(r"<script\b[^>]*>.*?</script>", " ", html, flags=re.I | re.S)
    visible = re.sub(r"<style\b[^>]*>.*?</style>", " ", visible, flags=re.I | re.S)
    visible = unescape(re.sub(r"<[^>]+>", " ", visible))
    visible = re.sub(r"\s+", " ", visible).strip()
    combined = f"{structured}\n{visible}".strip()[:_PAGE_EVIDENCE_CHARS]
    return combined or None


async def _normalize_currencies(
    sources: tuple[SourceResult, ...], emit: ProgressCallback
) -> tuple[SourceResult, ...]:
    currencies = {
        _norm_currency(offer.currency)
        for source in sources
        for offer in source.offers
        if _norm_currency(offer.currency) != "UAH"
    }
    rates = await _nbu_rates.rates_for(currencies)
    dropped = 0
    normalized: list[SourceResult] = []
    for source in sources:
        offers: list[MarketOffer] = []
        for offer in source.offers:
            currency = _norm_currency(offer.currency)
            original_price = offer.original_price or offer.price
            original_currency = offer.original_currency or currency
            if currency == "UAH":
                offers.append(
                    replace(
                        offer,
                        currency="UAH",
                        original_price=original_price,
                        original_currency=original_currency,
                    )
                )
                continue
            rate = rates.get(currency)
            if rate is None:
                dropped += 1
                continue
            offers.append(
                replace(
                    offer,
                    price=(offer.price * rate.rate).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    ),
                    currency="UAH",
                    original_price=original_price,
                    original_currency=original_currency,
                    exchange_rate=rate.rate,
                    exchange_rate_date=rate.exchange_date,
                )
            )
        normalized.append(
            replace(
                source,
                offers=tuple(offers),
                status="empty" if not offers and source.status == "ok" else source.status,
            )
        )
    if dropped:
        emit("verify", f"Без курсу НБУ відхилили {dropped} валютних пропозицій")
    return tuple(normalized)


def _deduplicate_verified_sellers(
    sources: tuple[SourceResult, ...],
) -> tuple[SourceResult, ...]:
    """One seller/warehouse contributes at most one verified market price."""
    best: dict[str, MarketOffer] = {}
    unverified: list[MarketOffer] = []
    for source in sources:
        for offer in source.offers:
            if not offer.verified:
                unverified.append(offer)
                continue
            identity = "|".join(
                (
                    offer.source,
                    offer.source_offer_id
                    or offer.seller
                    or _serp_domain(offer.url)
                    or offer.url,
                )
            )
            current = best.get(identity)
            if current is None or offer.price < current.price:
                best[identity] = offer
    allowed = {_offer_key(offer) for offer in (*best.values(), *unverified)}
    return tuple(
        replace(
            source,
            offers=tuple(o for o in source.offers if _offer_key(o) in allowed),
        )
        for source in sources
    )


async def _apply_anomaly_gates(
    query: PartSearchQuery,
    sources: tuple[SourceResult, ...],
    emit: ProgressCallback,
) -> tuple[tuple[SourceResult, ...], str]:
    market = [
        offer
        for source in sources
        for offer in source.offers
        if offer.verified
    ]
    if len(market) < 2:
        return sources, "insufficient"

    if len(market) == 2:
        if max(o.price for o in market) / min(o.price for o in market) <= _HIGH_PRICE_RATIO:
            return sources, "reliable"
        refreshed = await _refresh_anomalous_prices(query, market)
        if len(refreshed) != 2 or max(o.price for o in refreshed) / min(
            o.price for o in refreshed
        ) > _HIGH_PRICE_RATIO:
            emit("verify", "Дві підтверджені ціни суперечать одна одній")
            conflict = {_offer_key(offer) for offer in market}
            return (
                tuple(
                    replace(
                        source,
                        offers=tuple(
                            replace(o, verified=False)
                            if _offer_key(o) in conflict
                            else o
                            for o in source.offers
                        ),
                    )
                    for source in sources
                ),
                "conflict",
            )
        sources = _replace_offers(sources, refreshed)
        return sources, "reliable"

    suspicious = _statistical_outliers(market)
    if not suspicious:
        return sources, "reliable"
    refreshed = await _refresh_anomalous_prices(query, suspicious)
    sources = _replace_offers(sources, refreshed)
    refreshed_by_key = {_offer_key(offer): offer for offer in refreshed}
    all_market = [
        refreshed_by_key.get(_offer_key(offer), offer) for offer in market
    ]
    rejected = {_offer_key(offer) for offer in _statistical_outliers(all_market)}
    if rejected:
        emit("verify", f"Відхилили {len(rejected)} стійких аномальних цін")
        sources = _remove_offer_keys(sources, rejected)
    status = "reliable" if len(_stats_prices(o for s in sources for o in s.offers)) >= 2 else "insufficient"
    return sources, status


def _statistical_outliers(offers: list[MarketOffer]) -> list[MarketOffer]:
    if len(offers) < 3:
        return []
    center = Decimal(str(median(o.price for o in offers)))
    deviations = [abs(o.price - center) for o in offers]
    mad = Decimal(str(median(deviations)))
    result: list[MarketOffer] = []
    for offer in offers:
        fail_safe = offer.price < center * _LOW_PRICE_RATIO or offer.price > center * _HIGH_PRICE_RATIO
        z_outlier = (
            mad > 0
            and (Decimal("0.6745") * abs(offer.price - center) / mad)
            > _MODIFIED_Z_LIMIT
        )
        if fail_safe or z_outlier:
            result.append(offer)
    return result


async def _refresh_anomalous_prices(
    query: PartSearchQuery, offers: list[MarketOffer]
) -> list[MarketOffer]:
    snapshots = await _fetch_verified_snapshots(query, offers)
    refreshed: list[MarketOffer] = []
    for offer, snapshot in zip(offers, snapshots):
        if snapshot is None or snapshot.price <= 0:
            continue
        currency = _norm_currency(snapshot.currency)
        if currency == "UAH":
            price = snapshot.price
        elif offer.exchange_rate is not None and currency == offer.original_currency:
            price = (snapshot.price * offer.exchange_rate).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        else:
            continue
        refreshed.append(
            replace(
                offer,
                price=price,
                original_price=snapshot.price,
                original_currency=currency,
                verified_at=snapshot.verified_at,
                price_changed_on_page=True,
                evidence_text=snapshot.evidence_text,
            )
        )
    return refreshed


def _replace_offers(
    sources: tuple[SourceResult, ...], replacements: list[MarketOffer]
) -> tuple[SourceResult, ...]:
    by_key = {_offer_key(offer): offer for offer in replacements}
    return tuple(
        replace(
            source,
            offers=tuple(by_key.get(_offer_key(offer), offer) for offer in source.offers),
        )
        for source in sources
    )


def _remove_offer_keys(
    sources: tuple[SourceResult, ...], rejected: set[tuple[str, str, str]]
) -> tuple[SourceResult, ...]:
    cleaned: list[SourceResult] = []
    for source in sources:
        offers = tuple(o for o in source.offers if _offer_key(o) not in rejected)
        cleaned.append(
            replace(
                source,
                offers=offers,
                status="empty" if not offers and source.status == "ok" else source.status,
            )
        )
    return tuple(cleaned)


def _hard_gate_offers(
    offers: Iterable[MarketOffer],
) -> tuple[tuple[MarketOffer, ...], int]:
    candidates = tuple(offers)
    kept = tuple(
        offer for offer in candidates if _offer_rejection_reason(offer) is None
    )
    return kept, len(candidates) - len(kept)


def _offer_rejection_reason(offer: MarketOffer) -> str | None:
    # A zero search-snippet price is allowed only until the fresh page parse.
    if offer.verified and offer.price <= 0:
        return "non_positive_price"
    text = " ".join(
        value
        for value in (
            offer.title,
            offer.seller,
            offer.availability,
            offer.condition,
            offer.evidence_text,
        )
        if value
    )
    if _USED_RE.search(text):
        return "not_new"
    if _NON_FIXED_PRICE_RE.search(text):
        return "non_fixed_price"
    if _UNAVAILABLE_RE.search(offer.availability or ""):
        return "unavailable"
    return None


def _offer_llm_details(offer: MarketOffer) -> str:
    return " | ".join(
        value
        for value in (
            f"ціна={offer.price} {offer.currency}",
            f"продавець={offer.seller}" if offer.seller else None,
            f"наявність={offer.availability}" if offer.availability else None,
            f"стан={offer.condition}" if offer.condition else None,
            offer.evidence_text,
        )
        if value
    )


def _offer_key(offer: MarketOffer) -> tuple[str, str, str]:
    return offer.source, offer.url, offer.source_offer_id or ""


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
                unique = _cheapest_by_key(
                    result.offers,
                    key=lambda offer: f"{offer.maker}|{_norm_code(offer.code)}",
                )
                offers = sorted(
                    (
                        MarketOffer(
                            source=self.source,
                            title=" ".join(
                                part
                                for part in (offer.maker, offer.code, offer.description)
                                if part
                            )
                            or result.suggestion.title,
                            price=Decimal(str(offer.price)).quantize(Decimal("0.01")),
                            currency=offer.currency,
                            url=AVTOPRO_BASE_URL
                            + (offer.part_uri or result.suggestion.part_uri),
                            city=offer.city,
                            availability=offer.availability,
                            confidence=(
                                0.98
                                if _norm_code(offer.code) in exact_codes
                                else _ANALOG_CONFIDENCE
                            ),
                            is_analog=_norm_code(offer.code) not in exact_codes,
                            source_offer_id=offer.warehouse_id,
                            source_code=offer.code,
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
                image_url=product.image,
                confidence=score,
                # Номер не збігся — знайшли за назвою, тобто аналог.
                is_analog=score < _OEM_HIT_SCORE,
                source_code=product.sku,
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
            if domain.endswith(_SERP_BLOCKED_TLDS):
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
        offers: list[MarketOffer] = []
        pending: list[tuple[dict, str, float]] = []
        for item, domain, score in candidates:
            snippet = f"{item.get('title') or ''} {item.get('snippet') or ''}"
            price = _price_from_text(snippet)
            if price is not None:
                offers.append(self._offer(item, domain, score, price, "UAH"))
            else:
                pending.append((item, domain, score))

        priced_pages = await asyncio.gather(
            *(
                self._page_price(client, item.get("link") or "")
                for item, _, _ in pending[:_SERP_MAX_PAGE_FETCHES]
            )
        )
        for (item, domain, score), priced in zip(pending, priced_pages):
            if priced is not None:
                offers.append(self._offer(item, domain, score, *priced))
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
            evidence_text=f"{item.get('title') or ''} {item.get('snippet') or ''}",
        )


class ExistPriceSource(GooglePriceSource):
    """First-class Exist.ua source, isolated from the generic Google source."""

    source = "exist"
    label = "Exist.ua"

    async def search(self, query: PartSearchQuery) -> SourceResult:
        api_key = get_settings().serper_api_key
        if not api_key:
            return SourceResult(self.source, self.label, "skipped", error="No API key")
        if not query.oem_numbers:
            return SourceResult(
                self.source, self.label, "skipped", error="No OEM number"
            )
        terms = [
            " ".join(
                value
                for value in ("site:exist.ua", query.brand, oem)
                if value
            )
            for oem in query.oem_numbers[:_MAX_OEM_TERMS]
        ]
        async with httpx.AsyncClient(
            timeout=_SERP_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        ) as client:
            batches = await asyncio.gather(
                *(self._serp(client, api_key, term) for term in terms)
            )
            candidates = self._exist_candidates(query, batches)
            offers = await self._priced_offers(client, candidates)
        unique = _cheapest_by_key(offers, key=lambda offer: offer.url)
        kept = sorted(unique, key=_by_confidence_then_price)[:_GOOGLE_MAX_OFFERS]
        return SourceResult(
            self.source,
            self.label,
            "ok" if kept else "empty",
            tuple(sorted(kept, key=_by_price)),
        )

    def _exist_candidates(
        self, query: PartSearchQuery, batches: Iterable[list[dict]]
    ) -> list[tuple[dict, str, float]]:
        seen: set[str] = set()
        result: list[tuple[dict, str, float]] = []
        for item in (entry for batch in batches for entry in batch):
            url = item.get("link") or ""
            domain = _serp_domain(url)
            if domain != "exist.ua" and not domain.endswith(".exist.ua"):
                continue
            if url in seen:
                continue
            seen.add(url)
            score = _match_score(
                query,
                item.get("title"),
                item.get("snippet"),
                name=item.get("title"),
                brand=query.brand,
            )
            if score:
                result.append((item, domain, score))
        return result

    def _offer(
        self, item: dict, domain: str, score: float, price: Decimal, currency: str
    ) -> MarketOffer:
        offer = super()._offer(item, domain, score, price, currency)
        return replace(offer, source_code=_first_code_in_text(item.get("title") or ""))


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


def _primary_structured_product(
    html: str,
    query: PartSearchQuery,
    offer: MarketOffer,
) -> tuple[
    str | None,
    str | None,
    str | None,
    Decimal,
    str,
    str | None,
    str | None,
] | None:
    """Extract exactly one main-card price; related-product prices are ignored."""
    products: list[dict[str, Any]] = []
    for block in _LD_JSON_RE.findall(html):
        try:
            payload = json.loads(block.strip())
        except ValueError:
            continue
        products.extend(_json_ld_products(payload))

    target_codes = {
        _norm_code(value)
        for value in (*query.oem_numbers, offer.source_code)
        if value
    }
    exact = [
        product
        for product in products
        if target_codes
        and any(
            code and code in _norm_code(str(product.get(field) or ""))
            for code in target_codes
            for field in ("sku", "mpn", "productID", "name")
        )
    ]
    candidates = exact or (products if len(products) == 1 else [])
    parsed = [_parsed_product_node(product) for product in candidates]
    parsed = [value for value in parsed if value is not None]
    # Multiple candidate cards or multiple distinct prices are ambiguous.
    unique = {
        (value[3], value[4]): value
        for value in parsed
    }
    if len(unique) == 1:
        return next(iter(unique.values()))

    # Other sites may expose only Offer/microdata/OpenGraph without Product.
    if products:
        return None
    price = _unambiguous_structured_price(html)
    if price is None:
        return None
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = (
        unescape(re.sub(r"<[^>]+>", " ", title_match.group(1))).strip()
        if title_match
        else offer.title
    )
    return title, offer.source_code, None, price[0], price[1], None, None


def _json_ld_products(node: Any) -> list[dict[str, Any]]:
    if isinstance(node, list):
        return [item for value in node for item in _json_ld_products(value)]
    if not isinstance(node, dict):
        return []
    value_type = node.get("@type")
    types = value_type if isinstance(value_type, list) else [value_type]
    found = [node] if "Product" in types else []
    for key, value in node.items():
        if key == "offers":
            continue
        if isinstance(value, (dict, list)):
            found.extend(_json_ld_products(value))
    return found


def _parsed_product_node(
    product: dict[str, Any],
) -> tuple[
    str | None,
    str | None,
    str | None,
    Decimal,
    str,
    str | None,
    str | None,
] | None:
    prices = _direct_offer_prices(product.get("offers"))
    unique = {(price, currency) for price, currency in prices if price > 0}
    if len(unique) != 1:
        return None
    price, currency = next(iter(unique))
    brand_value = product.get("brand")
    brand = (
        str(brand_value.get("name") or "").strip() or None
        if isinstance(brand_value, dict)
        else str(brand_value or "").strip() or None
    )
    offer_node = product.get("offers")
    if isinstance(offer_node, list):
        offer_node = offer_node[0] if len(offer_node) == 1 else {}
    if not isinstance(offer_node, dict):
        offer_node = {}
    return (
        str(product.get("name") or "").strip() or None,
        str(product.get("sku") or product.get("mpn") or product.get("productID") or "").strip()
        or None,
        brand,
        price,
        currency,
        str(offer_node.get("availability") or "").strip() or None,
        str(offer_node.get("itemCondition") or "").strip() or None,
    )


def _direct_offer_prices(node: Any) -> list[tuple[Decimal, str]]:
    if isinstance(node, list):
        return [value for item in node for value in _direct_offer_prices(item)]
    if not isinstance(node, dict):
        return []
    node_type = node.get("@type")
    if node_type == "AggregateOffer":
        low = parse_price(node.get("lowPrice"))
        high = parse_price(node.get("highPrice"))
        if low is None or (high is not None and high != low):
            return []
        return [(low, _norm_currency(str(node.get("priceCurrency") or "")))]
    if node_type == "Offer" or "price" in node:
        price = parse_price(node.get("price"))
        return (
            [(price, _norm_currency(str(node.get("priceCurrency") or "")))]
            if price is not None
            else []
        )
    return []


def _unambiguous_structured_price(html: str) -> tuple[Decimal, str] | None:
    prices: list[tuple[Decimal, str]] = []
    for block in _LD_JSON_RE.findall(html):
        try:
            payload = json.loads(block.strip())
        except ValueError:
            continue
        prices.extend(_all_offer_prices(payload))
    if not prices:
        flat = re.sub(r"\s+", " ", html)
        for match in re.finditer(
            r'<(?:meta|[^>]+)[^>]*(?:itemprop="price"|property="og:price:amount")[^>]*>',
            flat,
            re.I,
        ):
            content = re.search(r'content="([^"]*)"', match.group(0), re.I)
            price = parse_price(content.group(1)) if content else None
            if price is not None:
                prices.append((price, "UAH"))
    unique = {(price, currency) for price, currency in prices if price > 0}
    return next(iter(unique)) if len(unique) == 1 else None


def _all_offer_prices(node: Any) -> list[tuple[Decimal, str]]:
    if isinstance(node, list):
        return [value for item in node for value in _all_offer_prices(item)]
    if not isinstance(node, dict):
        return []
    own = _direct_offer_prices(node)
    if own:
        return own
    return [
        value
        for child in node.values()
        if isinstance(child, (dict, list))
        for value in _all_offer_prices(child)
    ]


def _first_code_in_text(text: str) -> str | None:
    match = re.search(r"(?=[A-Z0-9 -]{6,})(?=[A-Z0-9 -]*\d)[A-Z0-9][A-Z0-9 -]{4,}[A-Z0-9]", text, re.I)
    return re.sub(r"\s+", "", match.group(0)) if match else None


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
    owned_stores: Iterable[MarketplaceStore | SellerExclusion] = (),
) -> PartSearchQuery:
    raw = listing.raw_data if isinstance(listing.raw_data, dict) else {}
    raw_numbers = raw.get("oem_numbers") or []
    candidates = [*raw_numbers, listing.sku]
    numbers = tuple(
        dict.fromkeys(filter(None, (normalize_oem(value) for value in candidates)))
    )
    export_seller = seller_from_export_url(listing.url)
    store_ids, store_slugs = _owner_identity(owned_stores)
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
    if hits and not brands_compatible(query.brand, brand):
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
    """Identify an excluded Prom seller by ID, then slug, then URL identity."""
    seller_id = _text_value(getattr(product, "seller_id", None))
    if seller_id:
        return seller_id in query.owner_seller_ids

    seller_slug = _normalized_slug(getattr(product, "seller_slug", None))
    if seller_slug:
        return seller_slug in query.owner_seller_slugs

    url_seller = _prom_seller_from_url(getattr(product, "url", None))
    if url_seller is not None:
        if url_seller.company_id in query.owner_seller_ids:
            return True
        if url_seller.slug.casefold() in query.owner_seller_slugs:
            return True

    return _same_marketplace_product(query.source_url, getattr(product, "url", None))


def _prom_seller_from_url(url: str | None) -> Seller | None:
    """Seller page path or ``slug-cs<ID>.prom.ua`` host as a final fallback."""
    if not url:
        return None
    try:
        return Seller.from_url(url)
    except ValueError:
        return seller_from_export_url(url)


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


def _norm_code(value: str | None) -> str:
    return _NON_ALNUM_RE.sub("", (value or "").upper())


def _discounted_market_price(
    prices: list[Decimal], discount_percent: Decimal
) -> Decimal:
    """One deterministic half-up rounding policy for every recommended amount."""
    multiplier = Decimal("1") - discount_percent / Decimal("100")
    return (min(prices) * multiplier).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )


def _recommended_price(prices: list[Decimal]) -> Decimal:
    """Backward-compatible helper: the central policy is now market minimum −6%."""
    return _discounted_market_price(prices, Decimal("6"))


def _stats_prices(offers: Iterable[MarketOffer]) -> list[Decimal]:
    """Page-verified same-part and compatible-analogue offers form the market."""
    return [
        offer.price
        for offer in offers
        if offer.verified
        and offer.confidence >= _MIN_STATS_CONFIDENCE
    ]


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
    payload = json.dumps(
        {
            "oem_numbers": query.oem_numbers,
            "brand": query.brand,
            "name": query.name,
            "owner_seller_ids": sorted(set(query.owner_seller_ids)),
            "owner_seller_slugs": sorted(set(query.owner_seller_slugs)),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()
    kyiv_date = datetime.now(KYIV).date().isoformat()
    return f"competitor-prices:v8:{kyiv_date}:{query.listing_id}:{digest}"
