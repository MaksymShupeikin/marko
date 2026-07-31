"""Candidate selection under the customer's 2026-07-30 tier-agnostic decision.

The owner priced himself out of the tier model: his segment is budget, so the
target is the cheapest comparable offer regardless of the competitor's level,
and if only originals are on the market the cheapest original is the target.

That removes the reason the two tier gates exist, and only those two.  Every
gate that answers "is this the same part" keeps its full force here, because
under a minimum-based target a single wrong match is no longer averaged away by
the median — it *becomes* the recommendation.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from marko.core.config import Settings
from marko.services.catalog_discovery import (
    CatalogDiscoveryError,
    tier_agnostic_pricing,
)
from metis.pricing.candidate_selection import (
    CandidateItem,
    CandidateStatus,
    ReferenceItem,
    check_candidate,
    load_candidate_selection_config,
)
from metis.pricing.types import ProductTier


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_candidate_selection_config(BACKEND_ROOT / "config" / "comparability.yaml")

# Polcar is an approved level; the reference is our own KEMP part.  The two
# differ, so the pair reaches the calibration gate instead of passing through
# ``SAME_TIER_IDENTITY``.
APPROVED_POLCAR = {"POLCAR": ProductTier.AFTERMARKET_B, "KEMP": ProductTier.KEMP}


def _reference(**overrides) -> ReferenceItem:
    values = {
        "oem": "7E5 827 505 A",
        "title": "VW Transporter T5 T6 замок задней крышки",
        "price": Decimal("1800"),
        "brand": "KEMP",
        "category": "body_lock",
        "tier": ProductTier.KEMP,
    }
    values.update(overrides)
    return ReferenceItem(**values)


def _candidate(**overrides) -> CandidateItem:
    values = {
        "seller_id": "3823617",
        "seller_name": "АвтоМаркет",
        "title": "7E5827505A Замок кришки багажника Фольксваген Транспортер T5 T6",
        "description": None,
        "article_field": "9568ZC-5F",
        "brand": "Polcar",
        "price": Decimal("1600"),
        "condition": None,
    }
    values.update(overrides)
    return CandidateItem(**values)


def _check(*, tier_agnostic: bool, brand_tiers=None, premiums=None, **candidate_kwargs):
    return check_candidate(
        _reference(),
        _candidate(**candidate_kwargs),
        CONFIG,
        brand_tiers=brand_tiers,
        calibrated_premiums=premiums,
        tier_agnostic=tier_agnostic,
    )


# --------------------------------------------------------- the decision itself


def test_unknown_tier_becomes_evidence_when_the_owner_ignores_tiers() -> None:
    """The 8320-offer bucket: comparable in every respect but the brand level."""

    blocked = _check(tier_agnostic=False, brand_tiers=None)
    admitted = _check(tier_agnostic=True, brand_tiers=None)

    assert blocked.status is CandidateStatus.REFERENCE_ONLY
    assert blocked.reason == "TIER_UNKNOWN"

    assert admitted.status is CandidateStatus.PRICING_EVIDENCE
    assert admitted.reason == "OK"
    assert admitted.predicted_tier is ProductTier.UNKNOWN
    assert "TIER_UNKNOWN_ACCEPTED" in admitted.flags


def test_uncalibrated_premium_becomes_evidence_when_the_owner_ignores_tiers() -> None:
    """The 92-offer bucket: level known, no validated coefficient to convert it."""

    blocked = _check(tier_agnostic=False, brand_tiers=APPROVED_POLCAR, premiums={})
    admitted = _check(tier_agnostic=True, brand_tiers=APPROVED_POLCAR, premiums={})

    assert blocked.status is CandidateStatus.REFERENCE_ONLY
    assert blocked.reason == "PREMIUM_NOT_CALIBRATED"

    assert admitted.status is CandidateStatus.PRICING_EVIDENCE
    assert admitted.predicted_tier is ProductTier.AFTERMARKET_B
    assert "TIER_AGNOSTIC_PRICING" in admitted.flags
    premium = admitted.details["gates"]["premium_calibration"]
    assert premium["premium"] == "1"
    assert premium["source"] == "TIER_AGNOSTIC_OWNER_POLICY"


def test_an_original_is_admitted_rather_than_converted() -> None:
    """"Если кроме оригинала ничего нет — берём самый дешёвый оригинал."""

    admitted = _check(
        tier_agnostic=True,
        brand_tiers={"VAG": ProductTier.OEM, "KEMP": ProductTier.KEMP},
        premiums={},
        brand="VAG",
        price=Decimal("2400"),
    )

    assert admitted.status is CandidateStatus.PRICING_EVIDENCE
    assert admitted.predicted_tier is ProductTier.OEM


def test_the_default_still_demands_a_tier_and_a_coefficient() -> None:
    """Another tenant may well be a premium seller; the old path must survive."""

    assert _check(tier_agnostic=False, brand_tiers=None).reason == "TIER_UNKNOWN"
    assert (
        _check(tier_agnostic=False, brand_tiers=APPROVED_POLCAR, premiums={}).reason
        == "PREMIUM_NOT_CALIBRATED"
    )


# ------------------------------------------------------------- what must not go


def test_price_sanity_survives_the_unknown_tier() -> None:
    """The guard is keyed on a tier premium, and ``unknown`` has none.

    Admitting the unknown-tier bucket without pinning the premium to 1 would
    silently switch the check off for precisely the 8320 offers being let in:
    ``premiums.get(UNKNOWN)`` is ``None``, which reports ``checked: False``.
    """

    assert CONFIG.price_anomaly.default_tier_premiums.get(ProductTier.UNKNOWN) is None

    verdict = _check(tier_agnostic=True, brand_tiers=None, price=Decimal("40"))
    anomaly = verdict.details["gates"]["price_anomaly"]

    assert anomaly["checked"] is True
    assert anomaly["tier_premium"] == "1"
    assert "PRICE_ANOMALY" in verdict.flags


def test_a_plausible_price_is_not_flagged() -> None:
    verdict = _check(tier_agnostic=True, brand_tiers=None, price=Decimal("1600"))

    assert verdict.details["gates"]["price_anomaly"]["checked"] is True
    assert "PRICE_ANOMALY" not in verdict.flags


@pytest.mark.parametrize(
    ("kwargs", "expected_reason"),
    [
        ({"title": "Б/У 7E5827505A замок кришки багажника"}, "USED"),
        ({"seller_name": "Авторазборка Львов"}, "DISMANTLER_SELLER"),
        ({"title": "Комплект 2 шт 7E5827505A замок кришки"}, "PACK_MISMATCH"),
        ({"title": "Шнек для мясорубки Zelmer 86.3130"}, "OEM_NOT_FOUND"),
    ],
)
def test_identity_gates_keep_their_force(kwargs, expected_reason) -> None:
    """Ignoring the level is not ignoring whether it is the same part."""

    verdict = _check(tier_agnostic=True, brand_tiers=None, **kwargs)

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == expected_reason


def test_our_own_brand_is_still_held_back() -> None:
    """A shop reselling KEMP prices our product, not the market we price against."""

    verdict = _check(
        tier_agnostic=True,
        brand_tiers=APPROVED_POLCAR,
        brand="KEMP",
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "OWN_BRAND"


# ------------------------------------------------------- reading the decision


def test_the_shipped_strategy_turns_the_decision_on() -> None:
    """The collector must agree with the deployed pricing strategy, not guess."""

    assert tier_agnostic_pricing(Settings()) is True


def test_no_configured_strategy_keeps_the_conservative_path() -> None:
    assert tier_agnostic_pricing(Settings(pricing_raise_policy_path="  ")) is False


def test_an_unreadable_strategy_stops_the_run(tmp_path) -> None:
    """Neither default is safe to assume, so a broken file refuses to collect."""

    broken = tmp_path / "raise_policy.yaml"
    broken.write_text("schema_version: wrong-version\n", encoding="utf-8")

    with pytest.raises(CatalogDiscoveryError) as excinfo:
        tier_agnostic_pricing(Settings(pricing_raise_policy_path=str(broken)))

    assert excinfo.value.code == "CATALOG_DISCOVERY_RAISE_POLICY_INVALID"
