"""Competitor offers from prom.ua's own automotive catalogue.

Every earlier attempt to find comparable offers searched the marketplace for our
OE number and hoped the results were the same part.  Measured on 2026-07-31 that
hope was misplaced: for one Touareg radiator the search returned 22 "comparable"
offers priced 1087 to 12968, and reading them showed the matching was *correct*
— they really are Touareg radiators, of four different sizes and classes.  The
engine then took the minimum of that and proposed cutting our price 79%.

prom.ua already answers the question we were reconstructing.  A product card in
the automotive vertical carries a normalized part code, the OE numbers that
supersede it, the vehicles it fits, and a link to the listing of every seller's
offer filed under that code — 114 of them for the same radiator.

This module reads that, applies the deterministic gates, and hands the survivors
over cheapest-first.  It decides nothing about comparability: that is the
model's job in ``llm_comparability``, and the order here exists so the model is
asked about the offers that can actually set a price.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import math

from marko.parsers.prom.client import HttpClient
from marko.parsers.prom.parser import parse_motors_context, parse_oe_listing
from marko.services.parser_models import MotorsContext, Product
from metis.pricing.candidate_selection import (
    CandidateItem,
    CandidateSelectionConfig,
    CandidateStatus,
    CandidateVerdict,
    ReferenceItem,
    check_candidate,
)

#: Recorded on every verdict this module produces, so a link built from one of
#: these offers says which marketplace grouping asserted the identity.
MOTORS_IDENTITY_SOURCE = "PROM_OE_PAGE"

#: prom.ua returns 30 products per listing page and ignores the sort parameters
#: tried on 2026-07-31 (``sort=price_asc``, ``sort=1``, ``order=price_asc`` all
#: returned the same order), so the cheap end can only be found after fetching
#: the pages.  The cap exists because some codes carry hundreds of offers and
#: the tail is not worth the requests.
OFFERS_PER_PAGE = 30
DEFAULT_MAX_PAGES = 4


class PromMotorsError(RuntimeError):
    """The automotive source cannot answer for this product."""


@dataclass(frozen=True, slots=True)
class MotorsCandidate:
    """One competitor offer, priced, with the verdict of the deterministic gates."""

    product: Product
    price: Decimal
    verdict: CandidateVerdict

    @property
    def seller_id(self) -> str:
        return str(self.product.seller_id or "")


@dataclass(frozen=True, slots=True)
class MotorsHarvest:
    """Everything the automotive source had to say about one of our products."""

    context: MotorsContext | None
    oe_page_url: str | None
    total_reported: int = 0
    fetched: int = 0
    pages_fetched: int = 0
    truncated: bool = False
    #: Gate survivors, cheapest first.  Ordering is the whole economy of the
    #: design: the owner's rule needs the bottom of the distribution, so a model
    #: asked in this order can stop long before the list runs out.
    accepted: tuple[MotorsCandidate, ...] = ()
    rejected: Mapping[str, int] = field(default_factory=dict)

    @property
    def has_offers(self) -> bool:
        return bool(self.accepted)

    def cheapest(self, limit: int) -> tuple[MotorsCandidate, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return self.accepted[:limit]

    def as_dict(self) -> dict[str, object]:
        return {
            "oe_page_url": self.oe_page_url,
            "normalized_part_code": (
                None if self.context is None else self.context.normalized_part_code
            ),
            "total_reported": self.total_reported,
            "fetched": self.fetched,
            "pages_fetched": self.pages_fetched,
            "truncated": self.truncated,
            "accepted": len(self.accepted),
            "rejected": dict(sorted(self.rejected.items())),
        }


def _price_of(product: Product) -> Decimal | None:
    for raw in (product.price, product.price_original):
        if raw in (None, ""):
            continue
        try:
            value = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if value.is_finite() and value > 0:
            return value
    return None


def as_candidate_item(product: Product) -> CandidateItem:
    """Shape a listing product for the gate chain.

    ``article_field`` is left as the seller wrote it.  The identity of these
    offers is asserted by the source they came from and is passed to
    ``check_candidate`` explicitly, rather than smuggled in through a field that
    means something else.
    """

    return CandidateItem(
        seller_id=str(product.seller_id or ""),
        seller_name=str(product.seller_name or ""),
        title=str(product.name or ""),
        description=product.description,
        article_field=product.sku,
        brand=product.brand,
        price=_price_of(product) or Decimal("0"),
        condition=product.condition,
        category_id=product.category_id,
        category_path=tuple(product.category_ids or ()),
    )


def collect_offers(
    html_pages: Sequence[str],
    *,
    reference: ReferenceItem,
    config: CandidateSelectionConfig,
    owned_seller_ids: frozenset[str] = frozenset(),
    lang: str = "ua",
) -> tuple[tuple[MotorsCandidate, ...], dict[str, int], int, int]:
    """Run already-fetched listing pages through the gates. Pure, so testable.

    Offers without a usable price are dropped before the gates rather than
    priced at zero: a zero would sort to the front and become the market floor.
    """

    seen: dict[int, Product] = {}
    total = 0
    for html in html_pages:
        page = parse_oe_listing(html, lang)
        total = max(total, page.total or 0)
        for product in page.products:
            if product.id is not None:
                seen.setdefault(product.id, product)

    accepted: list[MotorsCandidate] = []
    rejected: dict[str, int] = {}
    for product in seen.values():
        price = _price_of(product)
        if price is None:
            rejected["NO_USABLE_PRICE"] = rejected.get("NO_USABLE_PRICE", 0) + 1
            continue
        verdict = check_candidate(
            reference,
            as_candidate_item(product),
            config,
            owned_seller_ids=owned_seller_ids,
            tier_agnostic=True,
            identity_source=MOTORS_IDENTITY_SOURCE,
        )
        if verdict.status is CandidateStatus.REJECTED:
            rejected[verdict.reason] = rejected.get(verdict.reason, 0) + 1
            continue
        accepted.append(MotorsCandidate(product=product, price=price, verdict=verdict))

    accepted.sort(key=lambda candidate: (candidate.price, candidate.product.id or 0))
    return tuple(accepted), rejected, len(seen), total


def harvest(
    client: HttpClient,
    *,
    product_url: str,
    reference: ReferenceItem,
    config: CandidateSelectionConfig,
    owned_seller_ids: frozenset[str] = frozenset(),
    max_pages: int = DEFAULT_MAX_PAGES,
    lang: str = "ua",
) -> MotorsHarvest:
    """Read our card, then the cross-seller listing prom.ua files it under.

    A product with no automotive page comes back empty rather than raising:
    measured on 2026-07-31, 12 of 40 catalogue positions have none, so absence
    is an ordinary state the caller has to handle anyway.
    """

    if max_pages <= 0:
        raise ValueError("max_pages must be positive")
    context = parse_motors_context(client.get_html(product_url), lang)
    if context is None or not context.has_oe_page:
        return MotorsHarvest(context=context, oe_page_url=None)

    base = context.oe_page_url(lang)
    assert base is not None  # has_oe_page
    first = client.get_html(base)
    pages = [first]
    reported = parse_oe_listing(first, lang).total or 0
    wanted = max(1, math.ceil(reported / OFFERS_PER_PAGE))
    for number in range(2, min(max_pages, wanted) + 1):
        pages.append(client.get_html(f"{base}?page={number}"))

    accepted, rejected, fetched, total = collect_offers(
        pages,
        reference=reference,
        config=config,
        owned_seller_ids=owned_seller_ids,
        lang=lang,
    )
    return MotorsHarvest(
        context=context,
        oe_page_url=base,
        total_reported=total,
        fetched=fetched,
        pages_fetched=len(pages),
        truncated=wanted > len(pages),
        accepted=accepted,
        rejected=rejected,
    )


__all__ = [
    "DEFAULT_MAX_PAGES",
    "MOTORS_IDENTITY_SOURCE",
    "OFFERS_PER_PAGE",
    "MotorsCandidate",
    "MotorsHarvest",
    "PromMotorsError",
    "as_candidate_item",
    "collect_offers",
    "harvest",
]
