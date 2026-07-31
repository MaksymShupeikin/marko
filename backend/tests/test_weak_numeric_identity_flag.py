"""A short all-numeric OE found only in free text is flagged, never rejected.

This is the failure that put 115 meat-grinder augers into the observation set.
KEMP position 77646363 is a cylinder-head gasket whose OE is ``863130`` — Elring
prints it ``863.130``.  Zelmer prints an auger ``86.3130``.  Both normalize to
``863130``, so the auger listings matched on an exact string and passed the
identity gate on a title substring.

The category blocklist now rejects those two Prom branches by path, which is
correct and was measured, but it is retrospective: the next collision lands in a
branch nobody has listed yet.  The flag here marks the shape that produces them
so the class stays countable, and it deliberately stops at marking.  Rejecting a
candidate on the length of a number would need the golden set to show what the
rule costs in real candidates, and that set does not exist.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from metis.pricing.candidate_selection import (
    WEAK_NUMERIC_IDENTITY_MAX_DIGITS,
    CandidateItem,
    CandidateStatus,
    ReferenceItem,
    check_candidate,
    load_candidate_selection_config,
)
from metis.pricing.types import ProductTier

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_candidate_selection_config(BACKEND_ROOT / "config" / "comparability.yaml")
APPROVED = {"ZELMER": ProductTier.AFTERMARKET_B, "KEMP": ProductTier.KEMP}
CALIBRATED = {("gasket", ProductTier.AFTERMARKET_B): Decimal("1.0")}


def _gasket(oem: str = "863130") -> ReferenceItem:
    return ReferenceItem(
        oem=oem,
        title="Прокладка ГБЦ 1,5мм Jumper/Ducato/Movano/Boxer 2.8",
        price=Decimal("900"),
        brand="KEMP",
        category="gasket",
        tier=ProductTier.KEMP,
    )


def _auger(**overrides) -> CandidateItem:
    values = {
        "seller_id": "9001",
        "seller_name": "Побутова техніка",
        "title": "12000133 Шнек для м'ясорубок Zelmer NR8 86.3130",
        "description": None,
        "article_field": "12000133",
        "brand": "Zelmer",
        "price": Decimal("560"),
        "condition": None,
    }
    values.update(overrides)
    return CandidateItem(**values)


def _check(reference: ReferenceItem, candidate: CandidateItem):
    return check_candidate(
        reference,
        candidate,
        CONFIG,
        brand_tiers=APPROVED,
        calibrated_premiums=CALIBRATED,
    )


def test_the_real_collision_is_flagged() -> None:
    verdict = _check(_gasket(), _auger())

    assert "WEAK_NUMERIC_IDENTITY" in verdict.flags


def test_the_flag_does_not_reject_the_candidate() -> None:
    """Marking is the whole claim: the number really is there, in the title."""

    verdict = _check(_gasket(), _auger())

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert verdict.reason == "OK"
    identity = verdict.details["gates"]["oem_identity"]
    assert identity["evidence"] == "TITLE"
    assert identity["weak_numeric_identity"] is True


def test_an_exact_article_field_match_is_not_weak() -> None:
    """A structured field is not free text, so no collision can enter through it."""

    verdict = _check(_gasket(), _auger(article_field="863130"))

    assert verdict.details["gates"]["oem_identity"]["evidence"] == "ARTICLE_FIELD"
    assert "WEAK_NUMERIC_IDENTITY" not in verdict.flags


def test_a_long_oem_in_a_title_is_not_weak() -> None:
    """Length is the whole point: ten digits is not a space you collide in."""

    long_oem = "1" * (WEAK_NUMERIC_IDENTITY_MAX_DIGITS + 4)
    verdict = _check(
        _gasket(oem=long_oem),
        _auger(title=f"Шнек {long_oem} Zelmer"),
    )

    assert verdict.details["gates"]["oem_identity"]["evidence"] == "TITLE"
    assert "WEAK_NUMERIC_IDENTITY" not in verdict.flags


def test_a_short_oem_with_letters_is_not_weak() -> None:
    """Letters restore the space; only all-digit numbers are cheap to collide with."""

    verdict = _check(
        _gasket(oem="8A3130"),
        _auger(title="Шнек 8A3130 Zelmer"),
    )

    assert verdict.details["gates"]["oem_identity"]["evidence"] == "TITLE"
    assert "WEAK_NUMERIC_IDENTITY" not in verdict.flags


@pytest.mark.parametrize("digits", (3, 4, 5, 6))
def test_every_length_up_to_the_threshold_is_flagged(digits: int) -> None:
    oem = "8" * digits
    verdict = _check(_gasket(oem=oem), _auger(title=f"Шнек {oem} Zelmer"))

    assert "WEAK_NUMERIC_IDENTITY" in verdict.flags


def test_the_threshold_is_the_measured_one() -> None:
    """Recorded so a change of the number is a deliberate change of the claim.

    Measured on the 2026-07-29 reference map: 938 of 7687 positions carry an
    all-numeric OE of six digits or fewer, 682 of them exactly six.
    """

    assert WEAK_NUMERIC_IDENTITY_MAX_DIGITS == 6
