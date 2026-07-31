"""Extract product data from prom.ua's embedded Apollo cache."""

from __future__ import annotations

import json
import re

from .exceptions import ParseError, ParserSchemaChanged
from marko.services.parser_models import (
    ListingPage,
    MotorsContext,
    MotorsVehicle,
    Product,
    SeedInfo,
    get_nested,
)

# window.ApolloCacheState = {...}; - extract balanced JSON object after '='.
_APOLLO_RE = re.compile(r"window\.ApolloCacheState\s*=\s*(\{)", re.DOTALL)
# Keys in _FAST_CACHE that hold the data we parse (matched by prefix).
_LISTING_KEY_PREFIX = "CompanyListingQuery"  # a single seller's catalog
_SEARCH_KEY_PREFIX = "SearchListingQuery"  # site-wide search (many sellers)
_PRODUCT_KEY_PREFIX = "ProductCardPageQuery"  # a single product card (seed)
# prom.ua's automotive vertical: every seller's offer filed under one
# normalized part code.  Same listing shape as search, so the same parser and
# the same schema-change guards apply.
_OE_LISTING_KEY_PREFIX = "MotorsOENumberListingQuery"


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
    raw_products = page.get("products")
    if not isinstance(raw_products, list):
        raise ParserSchemaChanged("Apollo listing.page.products is not a list")
    products: list[Product] = []
    for index, item in enumerate(raw_products):
        if not isinstance(item, dict) or not isinstance(item.get("product"), dict):
            raise ParserSchemaChanged(
                f"Apollo listing.page.products[{index}].product is invalid"
            )
        products.append(Product.from_raw(item["product"], lang))
    return products


def _parse_products(html: str, key_prefix: str, lang: str) -> ListingPage:
    """Shared parser for both seller listings and search results."""
    cache = _extract_apollo_state(html)
    record = _find_cache_record(cache, key_prefix)
    if record is None:
        raise ParserSchemaChanged(f"Expected Apollo record {key_prefix} is absent")
    page = get_nested(record, "result.listing.page")
    if not isinstance(page, dict):
        raise ParserSchemaChanged("Apollo result.listing.page is absent or invalid")
    products = _products_from_page(page, lang)
    total = page.get("total")
    if total is not None and (not isinstance(total, int) or isinstance(total, bool)):
        raise ParserSchemaChanged("Apollo listing.page.total is not an integer")
    if products and total is not None and total < len(products):
        raise ParserSchemaChanged(
            "Apollo listing.page.total contradicts the returned products"
        )
    if not products:
        if page.get("products") != [] or total != 0:
            raise ParserSchemaChanged(
                "Apollo empty products contradict the recognized empty-result contract"
            )
        return ListingPage(
            products=[],
            total=total,
            lang=lang,
            outcome="EMPTY_SEARCH_RESULT",
        )
    return ListingPage(
        products=products,
        total=total,
        lang=lang,
        outcome="RESULTS",
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


def parse_oe_listing(html: str, lang: str = "ua") -> ListingPage:
    """Parse an /auto/oen/ page: offers from many sellers under one part code."""

    return _parse_products(html, _OE_LISTING_KEY_PREFIX, lang)


def _motors_vehicles(raw: object) -> tuple[MotorsVehicle, ...]:
    if not isinstance(raw, list):
        return ()
    vehicles: list[MotorsVehicle] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        manufacturer = (item.get("manufacturer") or {}).get("name")
        model = (item.get("model") or {}).get("name")
        if not manufacturer or not model:
            # A vehicle without a make or a model identifies nothing; keeping it
            # would pad the applicability list with rows nobody can match on.
            continue
        vehicles.append(
            MotorsVehicle(
                manufacturer=str(manufacturer),
                model=str(model),
                engine=_text_or_none(item.get("name")),
                horsepower=item.get("hp") if isinstance(item.get("hp"), int) else None,
                fuel_type=_text_or_none(item.get("fuelType")),
                drive_type=_text_or_none(item.get("driveType")),
                date_from=_text_or_none((item.get("model") or {}).get("dateFrom")),
                date_to=_text_or_none((item.get("model") or {}).get("dateTo")),
            )
        )
    return tuple(vehicles)


def _text_or_none(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def parse_motors_context(html: str, lang: str = "ua") -> MotorsContext | None:
    """Read the automotive-vertical block of a product card, if it has one.

    Returns nothing rather than raising when the block is absent: a product
    outside the automotive vertical is an ordinary state, not a broken page.
    """

    del lang
    cache = _extract_apollo_state(html)
    record = _find_cache_record(cache, _PRODUCT_KEY_PREFIX)
    if record is None:
        raise ParserSchemaChanged("Expected Apollo record ProductCardPageQuery is absent")
    motors = get_nested(record, "result.motorsProductPage")
    if not isinstance(motors, dict):
        return None

    normalized = _text_or_none(motors.get("normalizedPartCode"))
    numbers: list[str] = []
    page_id: int | None = None
    alias: str | None = None
    for entry in motors.get("compatibleOENumbers") or []:
        if not isinstance(entry, dict):
            continue
        number = _text_or_none(entry.get("oeNumberNormalized"))
        if number:
            numbers.append(number)
        page = entry.get("oeNumberPage")
        # The listing to consult is the one for *our* code.  A superseding
        # number's page is a different market and would silently widen the
        # comparison to a part we do not sell.
        if (
            isinstance(page, dict)
            and page_id is None
            and (normalized is None or number == normalized)
        ):
            candidate_id = page.get("id")
            candidate_alias = _text_or_none(page.get("alias"))
            if isinstance(candidate_id, int) and candidate_alias:
                page_id, alias = candidate_id, candidate_alias

    product = get_nested(record, "result.product") or {}
    images = tuple(
        image
        for image in (product.get("images") or [])
        if isinstance(image, str) and image
    )
    group = motors.get("partGroupId")
    return MotorsContext(
        normalized_part_code=normalized,
        part_group_id=group if isinstance(group, int) else None,
        oe_page_id=page_id,
        oe_page_alias=alias,
        compatible_oe_numbers=tuple(dict.fromkeys(numbers)),
        compatible_vehicles=_motors_vehicles(motors.get("compatibleVehicles")),
        images=images,
    )
