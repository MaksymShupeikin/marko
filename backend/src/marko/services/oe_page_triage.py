"""Decide whether a saved catalogue page may be read for OE numbers at all.

The OE harvest is offline-first: somebody saves catalogue pages, a parser reads
them. That removes invented numbers but not *misattributed* ones, and two
outsourced rounds failed on exactly that. Both delivered pages that were the
catalogue's **search by OE number** view rather than an article card, and that
view prints the query back as a finding::

    All spare parts in the list below are equivalent to OEM number 68789:
    68789 (original number of VOLVO)
    68789 (original number of NISSAN)

``68789`` is a Nissens radiator article. Read as a cross list, that page hands
two vehicle makers to a part neither of them ever built, in the same shape a
real cross list has. The number is unrecoverable afterwards: it looks exactly
like data.

So the page is classified before anything is read off it, and the classifier
fails closed. A page we cannot positively identify as an article card for the
expected article is refused, because the alternative — treating it as a part
with no crosses — is an absence the catalogue never stated.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

__all__ = ["PageVerdict", "TriageResult", "triage_page"]


class PageVerdict(str, Enum):
    """What kind of page was saved."""

    ARTICLE_CARD = "ARTICLE_CARD"
    #: The catalogue's lookup-by-OE view. Echoes the query as an OE number.
    SEARCH_BY_NUMBER = "SEARCH_BY_NUMBER"
    NOTHING_FOUND = "NOTHING_FOUND"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class TriageResult:
    verdict: PageVerdict
    reason: str
    #: ``None`` when nothing was expected, so "not checked" stays distinct from
    #: "checked and wrong" — only the latter is a defect worth reporting.
    article_matches: bool | None = None
    brand_matches: bool | None = None

    @property
    def usable(self) -> bool:
        return (
            self.verdict is PageVerdict.ARTICLE_CARD
            and self.article_matches is not False
            and self.brand_matches is not False
        )


#: Sentences the lookup-by-OE view prints about its own result. Matched on the
#: page text rather than on markup: the wording survives a redesign, the markup
#: does not, and a stale check here fails open.
_SEARCH_MARKERS = (
    "equivalent to oem number",
    "an oem number is a unique code",
    "original number of",
    "эквивалентны oem",
    "оригинальный номер производителя",
)

#: Only phrases about the *article* result. "Sorry, no matches were found for
#: your query" reads like one but belongs to the car-selector widget, which
#: sits on every page — it marked four of the five pilot pages as empty when
#: they were merely the wrong view. A marker that fires everywhere hides the
#: distinction it was added to draw.
_NOTHING_MARKERS = (
    "no spare parts corresponding to your request",
    "ничего не найдено по вашему запросу",
    "нічого не знайдено за вашим запитом",
)

_BLOCKED_MARKERS = (
    "attention required",
    "verify you are a human",
    "too many requests",
    "checking your browser",
    "cf-error",
    "captcha",
    "проверка браузера",
)

#: Only an article card carries the manufacturer's own cross list, and every
#: catalogue labels it. Absent all of them, the page is not a card.
_CARD_MARKERS = (
    "oem numbers of the product",
    "reference number oem",
    "oe number",
    "oem number:",
    "vergleichsnummer",
    "оригинальные номера",
    "оригінальні номери",
    "замінює",
    "заменяет",
)


def _fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _text(html: str) -> str:
    """Visible text, with script and style bodies dropped.

    Markers are matched here rather than in the raw markup so that a phrase
    sitting in a JSON blob or a tracking script cannot pass a page.
    """

    stripped = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    stripped = re.sub(r"(?s)<[^>]+>", " ", stripped)
    return re.sub(r"\s+", " ", stripped)


def _normalize_number(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


def triage_page(
    html: str,
    *,
    url: str,
    expected_article: str = "",
    expected_brand: str = "",
) -> TriageResult:
    """Classify one saved page, refusing everything not positively a card.

    ``expected_article`` and ``expected_brand`` come from the harvest manifest.
    Checking them here is what catches the neighbouring-article save: two of the
    five pilot pages were cards for a nearby number, which parse perfectly and
    attribute their numbers to the wrong catalogue row.
    """

    text = _text(html)
    folded = _fold(text)
    folded_url = _fold(url)

    for marker in _BLOCKED_MARKERS:
        if marker in folded:
            return TriageResult(PageVerdict.BLOCKED, f"страница-заглушка: {marker!r}")

    # "The catalogue was asked and said it has no such article" is the more
    # actionable of the two refusals, so it is read before the page-type check.
    # Both refuse, so ordering cannot let a page through either way.
    for marker in _NOTHING_MARKERS:
        if marker in folded:
            return TriageResult(PageVerdict.NOTHING_FOUND, "каталог ничего не нашёл")

    for marker in _SEARCH_MARKERS:
        if marker in folded:
            return TriageResult(
                PageVerdict.SEARCH_BY_NUMBER,
                f"поиск по номеру, а не карточка: {marker!r}",
            )

    # The URL catches what the wording misses. A catalogue's article card never
    # lives under an OE-lookup path, so a page saved from one is the wrong view
    # even when its markup happens to carry card-like labels.
    if "/oem/" in folded_url:
        return TriageResult(
            PageVerdict.SEARCH_BY_NUMBER, "адрес содержит /oem/ — это поиск по номеру"
        )

    if not any(marker in folded for marker in _CARD_MARKERS):
        return TriageResult(
            PageVerdict.UNKNOWN, "не найден блок оригинальных номеров"
        )

    article_matches: bool | None = None
    if expected_article:
        article_matches = _normalize_number(expected_article) in _normalize_number(text)
    brand_matches: bool | None = None
    if expected_brand:
        brand_matches = _fold(expected_brand) in folded

    reasons: list[str] = []
    if article_matches is False:
        reasons.append(f"артикула {expected_article!r} на странице нет")
    if brand_matches is False:
        reasons.append(f"бренда {expected_brand!r} на странице нет")

    return TriageResult(
        PageVerdict.ARTICLE_CARD,
        "; ".join(reasons) or "карточка артикула",
        article_matches=article_matches,
        brand_matches=brand_matches,
    )
