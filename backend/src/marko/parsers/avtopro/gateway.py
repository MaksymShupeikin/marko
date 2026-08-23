"""Find competitor offers for an OEM number on avto.pro."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlencode

from marko.parsers.prom.client import HttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import ParseError, RequestFailed

from .parser import FeedPage, Offer, PartSuggestion, parse_feed, parse_search_suggestions

log = logging.getLogger(__name__)

BASE_URL = "https://avto.pro"
SEARCH_URL = f"{BASE_URL}/api/v1/search/query"
CONTINUATION_URL = f"{BASE_URL}/FeedPages/Continuation/"

# Без Accept-Language і Referer Azure WAF віддає JS-челлендж замість сторінки.
DEFAULT_HEADERS: dict[str, str] = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en;q=0.7",
    # Не заявляти br: requests без пакета brotli не розпакує таку відповідь.
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Referer": f"{BASE_URL}/",
}

_NORMALIZE_RE = re.compile(r"[^a-z0-9а-яіїєё]+")
_WORD_RE = re.compile(r"[a-zа-яіїєё]{2,}")


def _norm(value: str | None) -> str:
    return _NORMALIZE_RE.sub("", (value or "").lower())


def _words(*values: str | None) -> set[str]:
    """Слова-марки: шматки з цифрами відкидаємо, щоб номер не давав збігів."""
    chunks = (
        chunk
        for value in values
        for chunk in (value or "").lower().split()
        if not any(char.isdigit() for char in chunk)
    )
    return {word for chunk in chunks for word in _WORD_RE.findall(chunk)}


def pick_suggestion(
    suggestions: list[PartSuggestion],
    brand: str | None,
    name: str | None = None,
    *,
    fallback_to_first: bool = False,
) -> PartSuggestion | None:
    """The suggestion matching the brand, then the make named in `name`, else None.

    `fallback_to_first` — для ручного пошуку: людина сама бачить, яку марку
    підібрано (вона в title), тож топ-1 корисніший за «нічого не знайдено».
    """
    if not suggestions:
        return None
    if brand:
        wanted = _norm(brand)
        for suggestion in suggestions:
            # Марки в каталозі збірні («VAG/VW/Skoda/Seat/Audi»), тож окрім
            # рівності перевіряємо і входження: «vw» знайдеться, «iveco» теж.
            if wanted in (_norm(suggestion.brand), _norm(suggestion.brand_path)) or (
                wanted in _norm(suggestion.title)
            ):
                return suggestion
    # Один номер часто висить на кількох марках, і топ-1 avto.pro регулярно
    # віддає чужу («China», «BENTLEY»). Назва товару зазвичай містить потрібну.
    if name:
        wanted_words = _words(name)
        for suggestion in suggestions:
            # Title потрібен окремо: збірні марки лежать лише там
            # («VAG/VW/Skoda/Seat/Audi» при brand == «VAG»).
            if wanted_words & _words(
                suggestion.brand, suggestion.brand_path, suggestion.title
            ):
                return suggestion
    # Є з чим звіряти, але жодна підказка не збіглася. В автозвірці каталогу
    # краще нічого, ніж чужа марка; у ручному пошуку — навпаки.
    if brand or name:
        return suggestions[0] if fallback_to_first else None
    return suggestions[0]


@dataclass(frozen=True)
class PartOffers:
    """All collected competitor offers for one resolved part number."""
    suggestion: PartSuggestion
    offers: list[Offer]
    pages_fetched: int


def default_config() -> ScrapeConfig:
    return ScrapeConfig(base_headers=dict(DEFAULT_HEADERS))


class AvtoproGateway:
    """Search offers by OEM: suggestion -> part page -> feed continuations."""

    def __init__(self, config: ScrapeConfig | None = None) -> None:
        self._config = config or default_config()

    def search(self, oem: str) -> list[PartSuggestion]:
        with HttpClient(self._config) as client:
            return self._search(client, oem)

    def offers(
        self,
        oem: str,
        brand: str | None = None,
        name: str | None = None,
        *,
        fallback_to_first: bool = False,
    ) -> PartOffers | None:
        """Collect priced offers for the OEM, or None when nothing matched."""
        with HttpClient(self._config) as client:
            suggestion = pick_suggestion(
                self._search(client, oem),
                brand,
                name,
                fallback_to_first=fallback_to_first,
            )
            if suggestion is None:
                log.info("avto.pro: нічого не знайдено для %r", oem)
                return None
            page = parse_feed(client.get_html(BASE_URL + suggestion.part_uri))
            offers = list(page.offers)
            pages = 1
            max_pages = max(1, self._config.max_search_pages)
            while page.continuation_token and pages < max_pages:
                try:
                    page = self._continuation(client, page.continuation_token)
                except (RequestFailed, ParseError) as exc:
                    # Продовження стрічки регулярно ловить 401 або антибот.
                    # Перша сторінка вже зібрана — віддати її краще, ніж нічого.
                    log.info("avto.pro: стрічку обірвано на сторінці %d: %s", pages + 1, exc)
                    break
                offers.extend(page.offers)
                pages += 1
            return PartOffers(suggestion=suggestion, offers=offers, pages_fetched=pages)

    def _search(self, client: HttpClient, oem: str) -> list[PartSuggestion]:
        payload = client.put_json(SEARCH_URL, {"Query": oem})
        return parse_search_suggestions(payload)

    def _continuation(self, client: HttpClient, token: str) -> FeedPage:
        # The token is the button's JSON verbatim; compact it before sending.
        compact = json.dumps(json.loads(token), separators=(",", ":"), ensure_ascii=False)
        query = urlencode({"autopartsListContinuationToken": compact})
        return parse_feed(client.get_html(f"{CONTINUATION_URL}?{query}"))
