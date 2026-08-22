"""Propose a manufacturer number for a card that has none, then prove it.

This is the half of the identity problem that the catalogue link cannot reach.
Running ``rebuild_catalog_internal_code_links`` on 2026-08-22 connected 1 943
catalogue positions to storefront cards and gave 1 015 previously blind cards a
real number -- for free. Every one of those links landed in a single store,
``kemp``. The other three stores publish no part code at all, which leaves
25 671 cards whose only identifier is the shop's own shelf number.

For those, a model is the only remaining source, and the danger is exactly that
it is a good one: asked to name a part number, a model always names one. So the
chain here is deliberately two-sided.

    propose  ->  confirm  ->  use

``propose`` is a paid guess and is treated as such: it never reaches
``oe_norm`` and never reaches a public search on its own. ``confirm`` is the
independent source in ``oe_number_confirmation``. Only a number that survives
both is identity; everything else leaves the card exactly as it was, searching
by title and brand.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from marko.core.config import Settings
from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.oe_number_confirmation import (
    OeNumberConfirmation,
    confirm_oe_number,
)


OE_PROPOSAL_CONTRACT_VERSION = "oe-identity-proposal-v1"

#: Public fields a proposal may see. Prices are absent on purpose: what the
#: part costs says nothing about its number, and letting the model see our
#: price is how a "recommendation" starts quietly steering itself.
_PROPOSAL_FIELDS = (
    "name",
    "brand",
    "category",
    "description",
    "characteristics_raw",
    "applicability_brands",
    "applicability_models",
)

#: Never propose more numbers than a human would check by hand.
MAX_PROPOSED_NUMBERS = 5


@dataclass(frozen=True, slots=True)
class OeIdentityOutcome:
    """What the two steps concluded, and what may be used."""

    proposed: tuple[str, ...]
    confirmations: tuple[OeNumberConfirmation, ...]
    confirmed_number: str | None
    #: Numbers refused before the source was even asked, and why.
    refused: tuple[tuple[str, str], ...] = field(default=())

    @property
    def is_usable(self) -> bool:
        return self.confirmed_number is not None


def build_oe_proposal_input(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Public description of our own part, and nothing else.

    Deliberately excludes every price-shaped field and the private KEMP code.
    The model is being asked what the part *is*, not what it is worth.
    """

    product = {
        key: snapshot[key]
        for key in _PROPOSAL_FIELDS
        if snapshot.get(key) not in (None, "", {}, [])
    }
    sku = str(snapshot.get("sku") or "").strip()
    if sku and not is_internal_catalog_code(sku):
        # The shop's article may itself be a supplier number. It travels as a
        # hint, explicitly labelled as unproven, never as an answer.
        product["seller_article_unverified"] = sku
    return {
        "contract_version": OE_PROPOSAL_CONTRACT_VERSION,
        "our_product": product,
        "question": (
            "Name the vehicle manufacturer's original part numbers this part "
            "could carry. Answer with numbers only, at most "
            f"{MAX_PROPOSED_NUMBERS}, ordered by confidence. If you do not "
            "know, answer with an empty list rather than a plausible guess."
        ),
    }


def sanitize_proposed_numbers(numbers: Sequence[Any]) -> tuple[
    tuple[str, ...], tuple[tuple[str, str], ...]
]:
    """Drop what must never be asked about, keeping the reason for each drop."""

    kept: list[str] = []
    refused: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in numbers:
        candidate = " ".join(str(raw or "").split())
        if not candidate:
            continue
        if is_internal_catalog_code(candidate):
            refused.append((candidate, "PRIVATE_KEMP_CODE"))
            continue
        if len(candidate) < 4:
            refused.append((candidate, "TOO_SHORT_TO_BE_A_PART_NUMBER"))
            continue
        key = candidate.upper()
        if key in seen:
            continue
        seen.add(key)
        kept.append(candidate)
        if len(kept) == MAX_PROPOSED_NUMBERS:
            break
    return tuple(kept), tuple(refused)


async def resolve_card_identity(
    snapshot: Mapping[str, Any],
    *,
    settings: Settings,
    propose: Callable[[dict[str, Any]], Awaitable[Sequence[str]]],
    confirm: Callable[..., OeNumberConfirmation] | None = None,
) -> OeIdentityOutcome:
    """Ask for numbers, then let an independent source settle each one.

    Stops at the first confirmation: one proven number is identity, and paying
    to confirm the rest buys nothing the card can use.
    """

    proposal_input = build_oe_proposal_input(snapshot)
    raw_numbers = await propose(proposal_input)
    numbers, refused = sanitize_proposed_numbers(raw_numbers)
    checker = confirm or confirm_oe_number
    confirmations: list[OeNumberConfirmation] = []
    for number in numbers:
        outcome = checker(number, settings=settings)
        confirmations.append(outcome)
        if outcome.confirmed:
            return OeIdentityOutcome(
                proposed=numbers,
                confirmations=tuple(confirmations),
                confirmed_number=outcome.number,
                refused=refused,
            )
    return OeIdentityOutcome(
        proposed=numbers,
        confirmations=tuple(confirmations),
        confirmed_number=None,
        refused=refused,
    )


__all__ = [
    "MAX_PROPOSED_NUMBERS",
    "OE_PROPOSAL_CONTRACT_VERSION",
    "OeIdentityOutcome",
    "build_oe_proposal_input",
    "resolve_card_identity",
    "sanitize_proposed_numbers",
]
