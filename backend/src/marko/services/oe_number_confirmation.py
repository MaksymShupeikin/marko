"""Confirm a proposed manufacturer number against an independent source.

A card with no OE and no MPN cannot be searched honestly: its only identifier
is the shop's own shelf number, which Prom reuses across unrelated domains.
Article ``2141006`` retrieved a pool-stair pad and a cascade of BMW oil caps.

Asking a model for the number is the obvious next move and the dangerous one:
a model asked to name a part number will always name one, including when it
does not know. So proposing and confirming are separate steps here, and only a
confirmed number is ever written into ``oe_norm`` or sent to a public search.

The confirmation rule is not invented in this module. It is the one already
trusted by ``catalog_identity_reparse`` for the offline spareto export that
produced +178 confirmed codes: the page at ``https://spareto.com/oe/<number>``
counts only when its headline reads ``<number> - <types> OE number by<makes>``.
A "Search results for …" page is the source answering "I do not know this
original number", which is evidence of absence, not of identity.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from marko.core.config import Settings
from marko.services.catalog_identity_safety import is_internal_catalog_code
from metis.pricing.crosses import normalize_cross_oem


SPARETO_CONFIRMATION_VERSION = "spareto-oe-confirmation-v1"

_SPARETO_HOST = "https://spareto.com"

#: ``<номер> - <типы> OE number by<МАРКИ>`` -- the block that asserts identity.
_HEADLINE = re.compile(
    r"^\s*(?P<num>[0-9A-Za-z][0-9A-Za-z .\-/]*?)\s*-\s*.+?\s*OE number by",
    re.S,
)


@dataclass(frozen=True, slots=True)
class OeNumberConfirmation:
    """One number, and what an independent source says about it."""

    number: str
    confirmed: bool
    source_url: str
    headline: str


def spareto_oe_url(number: str) -> str:
    """Address of the page that would confirm ``number``.

    Refuses a private KEMP shelf code outright: it is a join key, and asking a
    public catalogue about it would publish it.
    """

    candidate = str(number or "").strip()
    if not candidate:
        raise ValueError("OE confirmation needs a number")
    if is_internal_catalog_code(candidate):
        raise ValueError(
            "private KEMP codes are join keys and never leave for a public source"
        )
    return f"{_SPARETO_HOST}/oe/{candidate}"


def headline_confirms_number(headline: str | None, number: str) -> bool:
    """Whether this page headline asserts that ``number`` is an OE number.

    Comparison is on the normalized form because the source prints the same
    number with its own spacing: ``3579 05 851 d`` and ``357905851D`` are the
    same claim, and treating them as different would throw away real evidence.
    """

    match = _HEADLINE.match(str(headline or ""))
    if match is None:
        return False
    return normalize_cross_oem(match.group("num")) == normalize_cross_oem(number)


def confirm_oe_number(
    number: str,
    *,
    settings: Settings,
    fetch_headline: object | None = None,
) -> OeNumberConfirmation:
    """Ask the source about ``number`` and report exactly what it answered.

    ``fetch_headline`` is injectable so the decision can be exercised without a
    network. A failure to reach the source is *not* a confirmation: it returns
    unconfirmed, because "we could not check" and "the source says yes" must
    never collapse into the same outcome.
    """

    url = spareto_oe_url(number)
    reader = fetch_headline or _fetch_spareto_headline
    try:
        headline = reader(url, settings)  # type: ignore[operator]
    except Exception:
        headline = ""
    return OeNumberConfirmation(
        number=str(number).strip(),
        confirmed=headline_confirms_number(headline, number),
        source_url=url,
        headline=str(headline or ""),
    )


def _fetch_spareto_headline(url: str, settings: Settings) -> str:
    """Read the page's first heading. Free: an ordinary public GET."""

    import requests

    response = requests.get(
        url,
        timeout=max(5, settings.pricing_scraper_http_timeout_seconds),
        headers={"User-Agent": "Mozilla/5.0 (compatible; MarkoIdentity/1.0)"},
    )
    if response.status_code != 200:
        return ""
    match = re.search(
        r"<h1[^>]*>(?P<text>.*?)</h1>", response.text, re.S | re.IGNORECASE
    )
    if match is None:
        return ""
    return re.sub(r"<[^>]+>", " ", match.group("text")).strip()


__all__ = [
    "SPARETO_CONFIRMATION_VERSION",
    "OeNumberConfirmation",
    "confirm_oe_number",
    "headline_confirms_number",
    "spareto_oe_url",
]
