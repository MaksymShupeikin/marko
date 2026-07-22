"""Orchestrates catalog scraping and cross-seller price comparison."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from math import ceil
import re
from typing import Any, AsyncIterator, Iterator

from .config import BASE_URL, ScrapeConfig
from .exceptions import ParseError, RequestFailed
from marko.services.matching import (
    ComparisonParams,
    PriceComparison,
    build_comparison,
    build_search_query,
)
from marko.services.parser_models import ListingPage, Product, SeedInfo, Seller

from .client import AsyncHttpClient, HttpClient
from .parser import (
    parse_listing,
    parse_product_group_ids,
    parse_product_page,
    parse_search,
)

log = logging.getLogger(__name__)

_PRODUCT_URL_RE = re.compile(
    r"prom\.ua/(?:(?P<lang>[a-z]{2})/)?p(?P<product_id>\d+)-(?P<word>[\w-]+)\.html", re.I
)


@dataclass(frozen=True)
class _ListingRequest:
    seller: Seller
    page_number: int
    product_group: str | None = None

    @property
    def params(self) -> dict[str, int | str] | None:
        params: dict[str, int | str] = {}
        if self.page_number > 1:
            params["page"] = self.page_number
        if self.product_group is not None:
            params["product_group"] = self.product_group
        return params or None

    @property
    def label(self) -> str:
        return self.product_group or "all"


@dataclass(frozen=True)
class _FetchedListing:
    request: _ListingRequest
    page: ListingPage
    html: str


class PromGateway:
    """Access seller catalogs and comparable offers on prom.ua."""

    def __init__(self, config: ScrapeConfig | None = None) -> None:
        self._config = config or ScrapeConfig()

    def scrape(self, seller_url: str, *, strict: bool = False) -> Iterator[Product]:
        """Return unique seller products for synchronous CLI callers."""
        return iter(asyncio.run(self._collect_products(seller_url, strict)))

    async def scrape_async(self, seller_url: str) -> AsyncIterator[Product]:
        """Yield unique products, stopping cleanly if a public page becomes unavailable."""
        try:
            async for product in self._scrape_seller(seller_url):
                yield product
        except (ParseError, RequestFailed) as exc:
            log.error("Імпорт каталогу зупинено: %s", exc)

    async def scrape_strict_async(self, seller_url: str) -> AsyncIterator[Product]:
        """Yield unique products and propagate source or parsing failures."""
        async for product in self._scrape_seller(seller_url):
            yield product

    async def _collect_products(self, seller_url: str, strict: bool) -> list[Product]:
        stream = (
            self.scrape_strict_async(seller_url)
            if strict
            else self.scrape_async(seller_url)
        )
        return [product async for product in stream]

    async def _scrape_seller(self, seller_url: str) -> AsyncIterator[Product]:
        seller = Seller.from_url(seller_url)
        log.info("Продавець: company_id=%s slug=%s lang=%s",
                 seller.company_id, seller.slug, seller.lang)

        seen_ids: set[int | None] = set()
        first_request = _ListingRequest(seller, self._config.start_page)
        async with AsyncHttpClient(self._config) as client:
            first_listing = await self._fetch_listing(client, first_request)
            if first_listing.page.is_empty:
                log.info("Каталог продавця порожній.")
                return
            async for page in self._iter_catalog_pages(client, first_listing):
                for product in page.products:
                    if product.id in seen_ids:
                        continue
                    seen_ids.add(product.id)
                    yield product

        log.info("Готово. Унікальних товарів: %d", len(seen_ids))

    async def _iter_catalog_pages(
        self,
        client: AsyncHttpClient,
        first_listing: _FetchedListing,
    ) -> AsyncIterator[ListingPage]:
        self._log_listing(first_listing)
        yield first_listing.page
        async for page in self._iter_remaining_pages(client, first_listing):
            yield page

        group_ids = self._product_groups_to_expand(first_listing)
        if not group_ids:
            return

        log.info("Ліміт Prom досягнуто; додатково обходимо %d груп.", len(group_ids))
        async for page in self._iter_product_group_pages(
            client,
            first_listing,
            group_ids,
        ):
            yield page

    async def _iter_product_group_pages(
        self,
        client: AsyncHttpClient,
        catalog_listing: _FetchedListing,
        group_ids: tuple[str, ...],
    ) -> AsyncIterator[ListingPage]:
        first_requests = [
            _ListingRequest(catalog_listing.request.seller, 1, group_id)
            for group_id in group_ids
        ]
        group_listings: list[_FetchedListing] = []
        async for group_listing in self._iter_fetched_requests(
            client,
            first_requests,
        ):
            if group_listing.page.is_empty:
                continue
            group_listings.append(group_listing)
            self._log_listing(group_listing)
            yield group_listing.page
            if self._is_capped(group_listing.page):
                log.warning(
                    "Група %s теж досягла ліміту %d; публічна видача може бути неповною.",
                    group_listing.request.product_group,
                    self._config.catalog_result_limit,
                )

        remaining_requests = self._interleaved_group_requests(group_listings)
        async for listing in self._iter_fetched_requests(
            client,
            remaining_requests,
        ):
            if listing.page.is_empty:
                continue
            self._log_listing(listing)
            yield listing.page

        for listing in group_listings:
            if self._known_final_page(listing) is not None:
                continue
            async for page in self._iter_unknown_pages(client, listing):
                yield page

    async def _iter_remaining_pages(
        self,
        client: AsyncHttpClient,
        first_listing: _FetchedListing,
    ) -> AsyncIterator[ListingPage]:
        final_page = self._known_final_page(first_listing)
        if final_page is None:
            async for page in self._iter_unknown_pages(client, first_listing):
                yield page
            return

        requests = self._remaining_page_requests(first_listing, final_page)
        async for listing in self._iter_fetched_requests(client, requests):
            if listing.page.is_empty:
                return
            self._log_listing(listing)
            yield listing.page

    async def _iter_fetched_requests(
        self,
        client: AsyncHttpClient,
        requests: list[_ListingRequest],
    ) -> AsyncIterator[_FetchedListing]:
        concurrency = max(1, self._config.page_concurrency)
        for batch_start in range(0, len(requests), concurrency):
            batch = requests[batch_start : batch_start + concurrency]
            listings = await asyncio.gather(
                *(self._fetch_listing(client, request) for request in batch)
            )
            for listing in listings:
                yield listing

    @staticmethod
    def _remaining_page_requests(
        listing: _FetchedListing,
        final_page: int,
    ) -> list[_ListingRequest]:
        return [
            _ListingRequest(
                seller=listing.request.seller,
                page_number=page_number,
                product_group=listing.request.product_group,
            )
            for page_number in range(
                listing.request.page_number + 1,
                final_page + 1,
            )
        ]

    def _interleaved_group_requests(
        self,
        listings: list[_FetchedListing],
    ) -> list[_ListingRequest]:
        requests_by_group = []
        for listing in listings:
            final_page = self._known_final_page(listing)
            if final_page is None:
                continue
            requests_by_group.append(
                self._remaining_page_requests(listing, final_page)
            )
        longest_group = max(
            (len(requests) for requests in requests_by_group),
            default=0,
        )
        return [
            requests[page_index]
            for page_index in range(longest_group)
            for requests in requests_by_group
            if page_index < len(requests)
        ]

    async def _iter_unknown_pages(
        self,
        client: AsyncHttpClient,
        first_listing: _FetchedListing,
    ) -> AsyncIterator[ListingPage]:
        seen_signatures = {self._page_signature(first_listing.page)}
        page_number = first_listing.request.page_number + 1
        while not self._page_limit_reached(first_listing.request.page_number, page_number):
            request = _ListingRequest(
                seller=first_listing.request.seller,
                page_number=page_number,
                product_group=first_listing.request.product_group,
            )
            listing = await self._fetch_listing(client, request)
            signature = self._page_signature(listing.page)
            if listing.page.is_empty or signature in seen_signatures:
                return
            seen_signatures.add(signature)
            self._log_listing(listing)
            yield listing.page
            page_number += 1

    async def _fetch_listing(
        self,
        client: AsyncHttpClient,
        request: _ListingRequest,
    ) -> _FetchedListing:
        html = await client.get_html(request.seller.listing_url, params=request.params)
        page = parse_listing(html, request.seller.lang)
        return _FetchedListing(request=request, page=page, html=html)

    def _known_final_page(self, listing: _FetchedListing) -> int | None:
        product_count = len(listing.page.products)
        if listing.page.total is None or product_count == 0:
            return None
        if self._config.max_pages:
            configured_final_page = (
                listing.request.page_number + self._config.max_pages - 1
            )
            if listing.request.page_number > 1:
                return configured_final_page
            return min(
                ceil(listing.page.total / product_count),
                configured_final_page,
            )
        if listing.request.page_number > 1:
            return None
        return ceil(listing.page.total / product_count)

    def _product_groups_to_expand(self, listing: _FetchedListing) -> tuple[str, ...]:
        can_expand = (
            self._config.expand_product_groups
            and not self._config.max_pages
            and listing.request.page_number == 1
            and self._is_capped(listing.page)
        )
        return parse_product_group_ids(listing.html) if can_expand else ()

    def _is_capped(self, page: ListingPage) -> bool:
        return bool(
            page.total is not None
            and page.total >= self._config.catalog_result_limit
        )

    def _page_limit_reached(self, first_page: int, current_page: int) -> bool:
        return bool(
            self._config.max_pages
            and current_page >= first_page + self._config.max_pages
        )

    @staticmethod
    def _page_signature(page: ListingPage) -> tuple[int | None, ...]:
        return tuple(product.id for product in page.products)

    @staticmethod
    def _log_listing(listing: _FetchedListing) -> None:
        log.info(
            "Група %s, сторінка %d: %d товарів (total: %s)",
            listing.request.label,
            listing.request.page_number,
            len(listing.page.products),
            listing.page.total,
        )

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
