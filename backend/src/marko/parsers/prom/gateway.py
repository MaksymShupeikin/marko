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
    r"prom\.ua/(?:(?P<lang>[a-z]{2})/)?p(?P<product_id>\d+)-(?P<word>[\w-]+)\.html", re.I
)


class PromGateway:
    """Access seller catalogs and comparable offers on prom.ua."""

    def __init__(self, config: ScrapeConfig | None = None) -> None:
        self._config = config or ScrapeConfig()

    def scrape(self, seller_url: str, *, strict: bool = False) -> Iterator[Product]:
        """Lazily yield unique seller products, page by page."""
        seller = Seller.from_url(seller_url)
        log.info("Продавець: company_id=%s slug=%s lang=%s",
                 seller.company_id, seller.slug, seller.lang)

        seen_ids: set[int] = set()
        with HttpClient(self._config) as client:
            for page in self._iter_pages(client, seller, strict=strict):
                new_on_page = 0
                for product in page.products:
                    if product.id in seen_ids:
                        continue
                    seen_ids.add(product.id)
                    new_on_page += 1
                    yield product
                if page.products and new_on_page == 0:
                    log.info("Нових товарів немає — зупиняюсь (кінець каталогу).")
                    break

        log.info("Готово. Унікальних товарів: %d", len(seen_ids))

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

            log.info("Сторінка %d: %d товарів (total за сайтом: %s)",
                     page_num, len(page.products), page.total)
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

    def compare(self, seed_url: str, query: str | None = None) -> PriceComparison:
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
            log.info("Seed: %s | бренд=%s | model_id=%s | buyBox=%s продавців (%s–%s)",
                     seed.product.name, seed.product.brand, seed.product.model_id,
                     seed.seller_count, seed.min_price, seed.max_price)
            log.info("Пошуковий запит: %r", search_query)

            candidates = self._collect_candidates(client, search_query, lang)
            comparison = build_comparison(
                seed,
                candidates,
                ComparisonParams(
                    query=search_query,
                    threshold=self._config.similarity_threshold,
                    max_sellers=self._config.max_sellers,
                ),
            )

        log.info("Порівняно продавців: %d (переглянуто кандидатів: %d)",
                 len(comparison.offers), comparison.candidates_scanned)
        return comparison

    def _fetch_seed(self, client: HttpClient, seed_url: str, lang: str) -> SeedInfo:
        html = client.get_html(seed_url)
        return parse_product_page(html, lang)

    def _collect_candidates(
        self, client: HttpClient, query: str, lang: str
    ) -> Iterator[Product]:
        """Yield search-result products across up to max_search_pages pages."""
        search_url = f"{BASE_URL}/{lang}/search"
        for page_num in range(1, self._config.max_search_pages + 1):
            params: dict[str, Any] = {"search_term": query}
            if page_num > 1:
                params["page"] = page_num
            try:
                html = client.get_html(search_url, params=params)
                page = parse_search(html, lang)
            except RequestFailed as exc:
                log.error("Пошукову сторінку %d не завантажено: %s", page_num, exc)
                return
            except ParseError as exc:
                log.error("Пошукову сторінку %d не розібрано: %s", page_num, exc)
                return
            if page.is_empty:
                log.info("Пошукова сторінка %d порожня — кінець.", page_num)
                return
            log.info("Пошук, стор. %d: %d кандидатів (total: %s)",
                     page_num, len(page.products), page.total)
            yield from page.products
