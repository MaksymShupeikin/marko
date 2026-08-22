"""Collapse a discovery run's offers into one question per distinct product.

Sellers replicate the same part many times over. The collection for card
``2141006`` on 2026-08-22 returned 99 offers that were, by article and maker,
42 distinct products. Asking the paid reviewer once per offer would buy the
same answer 2.4 times over.

Grouping key, chosen by measurement on that run rather than by taste:

===============================  =======
by title alone                   74
by article, else title           39
by maker + article, else title   42  <- used
===============================  =======

The middle key is cheaper by three calls and wrong more often: two makers'
parts can share a short article string, and merging them would let one
verdict speak for both. Three calls is a small price for not doing that.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
import re
import unicodedata
from typing import Any
from uuid import UUID


CANDIDATE_OFFER_GROUPING_VERSION = "candidate-offer-grouping-v1"

_NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Zа-яА-ЯіїєґІЇЄҐ]+")


@dataclass(frozen=True, slots=True)
class CandidateOfferGroup:
    """One distinct product, and every offer of it this run found."""

    key: str
    representative_id: UUID
    offer_ids: tuple[UUID, ...]
    seller_ids: tuple[str, ...]
    title: str
    brand: str | None
    sku: str | None
    lowest_price: Decimal | None
    highest_price: Decimal | None
    currency: str | None
    rejected_reasons: tuple[str, ...]

    @property
    def was_rejected_by_gates(self) -> bool:
        """Whether the free deterministic gates refused every offer here.

        The owner asked on 2026-08-22 for these to be reviewed rather than
        dropped: a gate can be wrong, and the reviewer is told *why* it
        refused instead of judging blind.
        """

        return bool(self.rejected_reasons)


def _normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return _NON_ALNUM_RE.sub("", text)


def _price(offer: Any) -> Decimal | None:
    value = getattr(offer, "sale_price", None)
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _group_key(offer: Any) -> str:
    article = _normalize(getattr(offer, "sku", None))
    identity = article or _normalize(getattr(offer, "title", None))
    return f"{_normalize(getattr(offer, 'brand', None))}|{identity}"


def group_candidate_offers(
    offers: Sequence[Any],
) -> tuple[CandidateOfferGroup, ...]:
    """Group ``offers`` by distinct product, cheapest group first.

    The representative is the cheapest offer of its group because the
    customer's estimate is built from the minimum comparable price: that is
    the offer whose comparability actually decides the number.
    """

    buckets: dict[str, list[Any]] = {}
    for offer in offers:
        buckets.setdefault(_group_key(offer), []).append(offer)

    groups: list[CandidateOfferGroup] = []
    for key, members in buckets.items():
        priced = [(_price(member), member) for member in members]
        # A missing price must not win the representative slot by sorting
        # first, and must not crash the comparison either.
        ordered = sorted(
            priced,
            key=lambda pair: (
                pair[0] is None,
                pair[0] if pair[0] is not None else Decimal(0),
                str(pair[1].id),
            ),
        )
        prices = [value for value, _ in ordered if value is not None]
        representative = ordered[0][1]
        reasons = {
            str(getattr(member, "selection_reason", "") or "").strip()
            for member in members
            if str(getattr(member, "selection_status", "") or "").upper() == "REJECTED"
        }
        reasons.discard("")
        groups.append(
            CandidateOfferGroup(
                key=key,
                representative_id=representative.id,
                offer_ids=tuple(member.id for _, member in ordered),
                seller_ids=tuple(
                    dict.fromkeys(
                        str(getattr(member, "seller_id", "") or "").strip()
                        for _, member in ordered
                        if str(getattr(member, "seller_id", "") or "").strip()
                    )
                ),
                title=str(getattr(representative, "title", "") or ""),
                brand=str(getattr(representative, "brand", "") or "") or None,
                sku=str(getattr(representative, "sku", "") or "") or None,
                lowest_price=min(prices) if prices else None,
                highest_price=max(prices) if prices else None,
                currency=str(getattr(representative, "currency", "") or "") or None,
                rejected_reasons=tuple(sorted(reasons)),
            )
        )

    groups.sort(
        key=lambda group: (
            group.lowest_price is None,
            group.lowest_price if group.lowest_price is not None else Decimal(0),
            group.key,
        )
    )
    return tuple(groups)


def grouping_summary(
    groups: Sequence[CandidateOfferGroup], *, offer_count: int
) -> dict[str, Any]:
    """State the saving as a number, so a report can never imply a bigger one."""

    return {
        "version": CANDIDATE_OFFER_GROUPING_VERSION,
        "offers": offer_count,
        "groups": len(groups),
        "calls_saved": max(0, offer_count - len(groups)),
        "gate_rejected_groups": sum(
            1 for group in groups if group.was_rejected_by_gates
        ),
    }


__all__ = [
    "CANDIDATE_OFFER_GROUPING_VERSION",
    "CandidateOfferGroup",
    "group_candidate_offers",
    "grouping_summary",
]
