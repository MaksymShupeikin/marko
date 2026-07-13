"""Extract product data from prom.ua's embedded Apollo cache."""
from __future__ import annotations

import json
import re

from .exceptions import ParseError
from marko.services.parser_models import ListingPage, Product, SeedInfo, get_nested

# window.ApolloCacheState = {...}; - extract balanced JSON object after '='.
_APOLLO_RE = re.compile(r"window\.ApolloCacheState\s*=\s*(\{)", re.DOTALL)
# Keys in _FAST_CACHE that hold the data we parse (matched by prefix).
_LISTING_KEY_PREFIX = "CompanyListingQuery"   # a single seller's catalog
_SEARCH_KEY_PREFIX = "SearchListingQuery"     # site-wide search (many sellers)
_PRODUCT_KEY_PREFIX = "ProductCardPageQuery"  # a single product card (seed)


def _slice_balanced_json(text: str, start: int) -> str:
    """Return the balanced ``{...}`` substring starting from ``{`` at ``start``."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
    raise ParseError("Незбалансований JSON у ApolloCacheState.")


def _extract_apollo_state(html: str) -> dict:
    """Extract and parse the window.ApolloCacheState object from HTML."""
    match = _APOLLO_RE.search(html)
    if not match:
        raise ParseError(
            "Не знайдено window.ApolloCacheState — можливо, спрацював антибот-захист "
            "або змінилась структура сторінки."
        )
    start = match.start(1)
    raw = _slice_balanced_json(html, start)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ParseError(f"Не вдалось розпарсити Apollo-стан: {exc}") from exc


def _find_cache_record(cache: dict, key_prefix: str) -> dict | None:
    """Find the first _FAST_CACHE record whose key starts with ``key_prefix``."""
    fast_cache = cache.get("_FAST_CACHE", cache)
    for key, value in fast_cache.items():
        if key.startswith(key_prefix) and isinstance(value, dict):
            return value
    return None


def _products_from_page(page: dict, lang: str) -> list[Product]:
    """Normalize the products[] array of a listing/search page node."""
    raw_products = page.get("products") or []
    return [
        Product.from_raw(item["product"], lang)
        for item in raw_products
        if isinstance(item, dict) and item.get("product")
    ]


def _parse_products(html: str, key_prefix: str, lang: str) -> ListingPage:
    """Shared parser for both seller listings and search results."""
    cache = _extract_apollo_state(html)
    record = _find_cache_record(cache, key_prefix)
    if record is None:
        return ListingPage(products=[], total=None, lang=lang)
    page = get_nested(record, "result.listing.page") or {}
    return ListingPage(
        products=_products_from_page(page, lang),
        total=page.get("total"),
        lang=lang,
    )


def parse_listing(html: str, lang: str = "ua") -> ListingPage:
    """Parse the HTML of a seller catalog page into a ListingPage."""
    return _parse_products(html, _LISTING_KEY_PREFIX, lang)


def parse_search(html: str, lang: str = "ua") -> ListingPage:
    """Parse a site-wide search page into a ListingPage (offers from many sellers)."""
    return _parse_products(html, _SEARCH_KEY_PREFIX, lang)


def parse_product_page(html: str, lang: str = "ua") -> SeedInfo:
    """Parse a product card page into a SeedInfo (the product + its buyBox summary)."""
    cache = _extract_apollo_state(html)
    record = _find_cache_record(cache, _PRODUCT_KEY_PREFIX)
    if record is None:
        raise ParseError(
            "Не знайдено ProductCardPageQuery — перевірте, що це URL картки товару "
            "(.../pXXXXXXX-slug.html)."
        )
    result = record.get("result", {})
    raw = result.get("product") or {}
    if not raw:
        raise ParseError("Картка товару без даних product у ApolloCacheState.")
    buybox = result.get("buyBox") or {}
    return SeedInfo(
        product=Product.from_raw(raw, lang),
        seller_count=buybox.get("companyCount"),
        min_price=buybox.get("minPrice"),
        max_price=buybox.get("maxPrice"),
    )
