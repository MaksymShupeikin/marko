"""Extract part suggestions and seller offers from avto.pro responses."""
from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

from marko.parsers.prom.exceptions import ParseError

# Offer rows in the server-rendered feed table (part page and continuation
# fragments share the same markup).
_ROW_RE = re.compile(
    r'<tr\b[^>]*data-interactive-feed-item-element="true"[^>]*>.*?</tr>', re.S
)
# "Показать ещё" button carries the continuation token (Descriptor + Skip).
_TOKEN_RE = re.compile(r'data-token="([^"]+)"')
_TAG_RE = re.compile(r"<[^>]+>")

_CURRENCY_BY_SYMBOL = {"грн": "UAH", "$": "USD", "€": "EUR"}


@dataclass(frozen=True)
class PartSuggestion:
    """One brand+number interpretation of a search query."""
    title: str
    brand: str | None
    brand_path: str | None
    is_original: bool
    part_uri: str  # /part-<number>-<BRAND>-<id>/


@dataclass(frozen=True)
class Offer:
    """A single seller warehouse offer from the feed table."""
    maker: str | None
    code: str | None
    part_uri: str | None
    description: str | None
    city: str | None
    availability: str | None
    price: float
    currency: str
    warehouse_id: str | None  # raw data-wh-id, stable seller/warehouse key
    boosted: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "maker": self.maker,
            "code": self.code,
            "part_uri": self.part_uri,
            "description": self.description,
            "city": self.city,
            "availability": self.availability,
            "price": self.price,
            "currency": self.currency,
            "warehouse_id": self.warehouse_id,
            "boosted": self.boosted,
        }


@dataclass(frozen=True)
class FeedPage:
    """Offers from one feed page plus the token for the next one."""
    offers: list[Offer]
    continuation_token: str | None


def parse_search_suggestions(payload: dict) -> list[PartSuggestion]:
    """Part-page suggestions from PUT /api/v1/search/query response JSON."""
    suggestions: list[PartSuggestion] = []
    for item in payload.get("Suggestions") or []:
        uri = item.get("Uri") or ""
        target = parse_qs(urlsplit(uri).query).get("uri", [""])[0]
        if not target.startswith("/part-"):
            continue  # category/listing suggestions have no offer feed
        part = (item.get("FoundPart") or {}).get("Part") or {}
        brand = part.get("Brand") or {}
        suggestions.append(
            PartSuggestion(
                title=item.get("Title") or "",
                brand=brand.get("Name"),
                brand_path=brand.get("Path"),
                is_original=bool(brand.get("IsOriginal")),
                part_uri=target,
            )
        )
    return suggestions


def _attr(source: str, name: str) -> str | None:
    match = re.search(rf'{name}="([^"]*)"', source)
    return htmllib.unescape(match.group(1)) if match else None


def _td(row: str, cell_type: str) -> str | None:
    match = re.search(rf'<td[^>]*data-type="{cell_type}"[^>]*>.*?</td>', row, re.S)
    return match.group(0) if match else None


def _text(fragment: str | None) -> str | None:
    if fragment is None:
        return None
    text = " ".join(htmllib.unescape(_TAG_RE.sub(" ", fragment)).split())
    return text or None


def _parse_row(row: str) -> Offer | None:
    price_cell = _td(row, "price")
    try:
        price = float(_attr(price_cell or "", "data-value") or 0)
    except ValueError:
        price = 0.0
    if price <= 0:
        return None  # "цена по запросу" is useless for comparison

    code_cell = _td(row, "code") or ""
    delivery_cell = _td(row, "delivery") or ""
    # Currency renders as <b data-type="currency">грн</b> inside the price cell.
    symbol_match = re.search(r'data-type="currency">\s*([^<\s]+)', price_cell or "")
    symbol = htmllib.unescape(symbol_match.group(1)) if symbol_match else ""
    return Offer(
        maker=_text(_td(row, "maker")),
        code=_attr(code_cell, "title"),
        part_uri=_attr(code_cell, "href"),
        description=_descr(row),
        city=_attr(delivery_cell, "data-city"),
        availability=_attr(delivery_cell, "data-tooltip-content"),
        price=price,
        currency=_CURRENCY_BY_SYMBOL.get(symbol, "UAH"),
        warehouse_id=_attr(row, "data-wh-id"),
        boosted=_attr(row, "data-is-boost-position") == "1",
    )


def _descr(row: str) -> str | None:
    match = re.search(
        r'<td[^>]*title="([^"]*)"[^>]*>\s*<span class="ap-feed__table__descr', row
    )
    return htmllib.unescape(match.group(1)) if match else None


def parse_feed(html: str) -> FeedPage:
    """Offers and continuation token from a part page or feed fragment."""
    rows = _ROW_RE.findall(html)
    if not rows and "ap-feed" not in html:
        raise ParseError(
            "Не знайдено таблицю пропозицій avto.pro — можливо, спрацював "
            "антибот-захист або змінилась структура сторінки."
        )
    token_match = _TOKEN_RE.search(html)
    token = htmllib.unescape(token_match.group(1)) if token_match else None
    offers = [offer for offer in map(_parse_row, rows) if offer is not None]
    return FeedPage(offers=offers, continuation_token=token)
