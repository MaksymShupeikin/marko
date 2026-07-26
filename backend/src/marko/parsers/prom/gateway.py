"""Orchestrates catalog scraping and cross-seller price comparison."""

from __future__ import annotations

import logging
import re
from typing import Any, Iterator

from .config import BASE_URL, ScrapeConfig
from .exceptions import ParseError, RequestFailed
from marko.services.matching import (
    ComparisonParams,
    PriceComparison,
    build_comparison,
    build_search_query,
)
from marko.services.parser_models import ListingPage, Product, SeedInfo, Seller

from .client import HttpClient
from .parser import parse_listing, parse_product_page, parse_search

log = logging.getLogger(__name__)

_PRODUCT_URL_RE = re.compile(
    r"prom\.ua/(?:(?P<lang>[a-z]{2})/)?p(?P<product_id>\d+)-(?P<word>[\w-]+)\.html",
    re.I,
)


def _is_pagination_end(exc: RequestFailed, page_num: int) -> bool:
    """Tell "there is no such page" apart from "the fetch broke".

    Prom's reported result total can exceed what it actually serves — measured
    on 2026-07-26, query ``8E0121251L`` reported 67 but served 66 across three
    pages. The next page then answers ``301`` to the canonical search URL.
    Treating that as a failure discarded every product already collected, which
    cost 2 of 30 measured positions. A redirect on the first page is *not*
    covered here: with no page fetched there is nothing to salvage, and a moved
    or blocked endpoint must still surface as an error.
    """

    return page_num > 1 and exc.is_redirect


class PromGateway:
    """Access seller catalogs and comparable offers on prom.ua."""

    def __init__(self, config: ScrapeConfig | None = None) -> None:
        self._config = config or ScrapeConfig()

    def scrape(self, seller_url: str, *, strict: bool = False) -> Iterator[Product]:
        """Lazily yield unique seller products, page by page."""
        seller = Seller.from_url(seller_url)
        log.info(
            "Продавець: company_id=%s slug=%s lang=%s",
            seller.company_id,
            seller.slug,
            seller.lang,
        )

        seen_products: set[tuple[str, str]] = set()
        with HttpClient(self._config) as client:
            for page in self._iter_pages(client, seller, strict=strict):
                new_on_page = 0
                for product in page.products:
                    identity = (
                        ("id", str(product.id))
                        if product.id is not None
                        else (
                            "fallback",
                            product.url
                            or "|".join(
                                (
                                    product.name or "",
                                    product.sku or "",
                                    product.seller_name or "",
                                )
                            ),
                        )
                    )
                    if identity in seen_products:
                        continue
                    seen_products.add(identity)
                    new_on_page += 1
                    yield product
                if page.products and new_on_page == 0:
                    log.info("Нових товарів немає — зупиняюсь (кінець каталогу).")
                    break

        log.info("Готово. Унікальних товарів: %d", len(seen_products))

    def _iter_pages(
        self, client: HttpClient, seller: Seller, *, strict: bool = False
    ) -> Iterator[ListingPage]:
        page_num = self._config.start_page
        fetched = 0
        while True:
            if self._config.max_pages and fetched >= self._config.max_pages:
                log.info("Досягнуто max_pages=%d.", self._config.max_pages)
                return

            page = self._fetch_page(client, seller, page_num, strict=strict)
            if page is None:
                return
            if page.is_empty:
                log.info("Сторінка %d порожня — кінець.", page_num)
                return

            log.info(
                "Сторінка %d: %d товарів (total за сайтом: %s)",
                page_num,
                len(page.products),
                page.total,
            )
            yield page
            fetched += 1
            page_num += 1

    def _fetch_page(
        self,
        client: HttpClient,
        seller: Seller,
        page_num: int,
        *,
        strict: bool = False,
    ) -> ListingPage | None:
        params = {"page": page_num} if page_num > 1 else None
        try:
            html = client.get_html(seller.listing_url, params=params)
            return parse_listing(html, seller.lang)
        except RequestFailed as exc:
            if _is_pagination_end(exc, page_num):
                log.info(
                    "Сторінка %d відсутня (HTTP %s) — кінець лістингу.",
                    page_num,
                    exc.status_code,
                )
                return None
            log.error("Сторінку %d не завантажено: %s", page_num, exc)
            if strict:
                raise
            return None
        except ParseError as exc:
            log.error("Сторінку %d не розібрано: %s", page_num, exc)
            if strict:
                raise
            return None

    # -- Cross-seller price comparison --

    def search(
        self,
        query: str,
        *,
        lang: str = "ua",
        strict: bool = False,
    ) -> Iterator[Product]:
        """Yield raw Prom search results without inventing comparability.

        This is an extraction-boundary operation for discovery/replay.  It
        deliberately does not call ``build_comparison`` and therefore cannot
        by itself authorize a price recommendation.
        """

        normalized_query = query.strip()
        normalized_lang = lang.strip().casefold()
        if not normalized_query:
            raise ValueError("Prom search query must not be empty")
        if not re.fullmatch(r"[a-z]{2}", normalized_lang):
            raise ValueError(f"Unsupported Prom language: {lang!r}")
        with HttpClient(self._config) as client:
            yield from self._collect_candidates(
                client,
                normalized_query,
                normalized_lang,
                strict=strict,
            )

    def compare(
        self,
        seed_url: str,
        query: str | None = None,
        *,
        strict: bool = False,
    ) -> PriceComparison:
        """Compare a seed product against similar offers from other sellers."""
        match = _PRODUCT_URL_RE.search(seed_url)
        if not match:
            raise ValueError(
                f"Не схоже на URL товару prom.ua: {seed_url!r}\n"
                "Очікую щось на кшталт https://prom.ua/ua/p1483068331-slug.html"
            )
        lang = (match.group("lang") or "ua").lower()

        with HttpClient(self._config) as client:
            seed = self._fetch_seed(client, seed_url, lang)
            search_query = query or build_search_query(seed.product)
            log.info(
                "Seed: %s | бренд=%s | model_id=%s | buyBox=%s продавців (%s–%s)",
                seed.product.name,
                seed.product.brand,
                seed.product.model_id,
                seed.seller_count,
                seed.min_price,
                seed.max_price,
            )
            log.info("Пошуковий запит: %r", search_query)

            candidates = self._collect_candidates(
                client,
                search_query,
                lang,
                strict=strict,
            )
            comparison = build_comparison(
                seed,
                candidates,
                ComparisonParams(
                    query=search_query,
                    threshold=self._config.similarity_threshold,
                    max_sellers=self._config.max_sellers,
                ),
            )

        log.info(
            "Порівняно продавців: %d (переглянуто кандидатів: %d)",
            len(comparison.offers),
            comparison.candidates_scanned,
        )
        return comparison

    def _fetch_seed(self, client: HttpClient, seed_url: str, lang: str) -> SeedInfo:
        html = client.get_html(seed_url)
        return parse_product_page(html, lang)

    def _collect_candidates(
        self,
        client: HttpClient,
        query: str,
        lang: str,
        *,
        strict: bool = False,
    ) -> Iterator[Product]:
        """Yield unique search products until total, exhaustion, or safety cap."""
        search_url = f"{BASE_URL}/{lang}/search"
        seen_products: set[tuple[str, str]] = set()
        reported_total: int | None = None
        for page_num in range(1, self._config.max_search_pages + 1):
            params: dict[str, Any] = {"search_term": query}
            if page_num > 1:
                params["page"] = page_num
            try:
                html = client.get_html(search_url, params=params)
                page = parse_search(html, lang)
            except RequestFailed as exc:
                if _is_pagination_end(exc, page_num):
                    log.info(
                        "Пошукова сторінка %d відсутня (HTTP %s) — кінець вибірки, "
                        "зібране збережено.",
                        page_num,
                        exc.status_code,
                    )
                    return
                log.error("Пошукову сторінку %d не завантажено: %s", page_num, exc)
                if strict:
                    raise
                return
            except ParseError as exc:
                log.error("Пошукову сторінку %d не розібрано: %s", page_num, exc)
                if strict:
                    raise
                return
            if page.is_empty:
                log.info("Пошукова сторінка %d порожня — кінець.", page_num)
                return
            if page.total is not None:
                reported_total = max(reported_total or 0, page.total)
            log.info(
                "Пошук, стор. %d: %d кандидатів (total: %s)",
                page_num,
                len(page.products),
                page.total,
            )
            new_on_page = 0
            for product in page.products:
                identity = (
                    ("id", str(product.id))
                    if product.id is not None
                    else (
                        "fallback",
                        product.url
                        or "|".join(
                            (
                                product.name or "",
                                product.sku or "",
                                product.seller_name or "",
                            )
                        ),
                    )
                )
                if identity in seen_products:
                    continue
                seen_products.add(identity)
                new_on_page += 1
                yield product
            if page.products and new_on_page == 0:
                log.info(
                    "Пошукова сторінка %d повторює вже зібрані товари — зупиняюсь.",
                    page_num,
                )
                return
            if reported_total is not None and len(seen_products) >= reported_total:
                log.info(
                    "Зібрано повідомлений Prom total=%d за %d сторінок.",
                    reported_total,
                    page_num,
                )
                return
