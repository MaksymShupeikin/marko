from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from metis.pricing.types import CohortRole
from marko.services.offer_identity import ConfirmedCross
from marko.services.offer_processing import EvidenceAccountingError
from marko.services.market_collection import (
    _catalog_semantic_reference_payload,
    _initial_cohort_role,
    _offer_search_identity,
)


def _classification(
    *,
    exclusion_reason: str | None = None,
    is_used: bool = False,
    is_kemp: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        exclusion_reason=exclusion_reason,
        is_used=is_used,
        is_kemp=is_kemp,
    )


def test_semantic_reference_does_not_expose_private_kemp_code_as_oe() -> None:
    item = SimpleNamespace(
        identity_status="MPN_ONLY",
        oe_norm="77641360",
        mpn_norm="115",
        part_numbers_norm=["115070"],
        sku="77641360",
        name="Part",
        description=None,
        brand="KEMP",
        category="Filters",
        applicability_brands=[],
        applicability_models=[],
        characteristics_raw={},
        raw_row={},
    )

    payload = _catalog_semantic_reference_payload(item)

    assert payload["oe"] is None
    assert payload["mpn"] == "115"
    assert payload["search_identity"] == "115070"
    assert payload["identity_status"] == "MPN_ONLY"


def test_semantic_reference_keeps_asserted_vehicle_oe() -> None:
    item = SimpleNamespace(
        identity_status="OE_CONFIRMED",
        oe_norm="31211128157",
        mpn_norm="77641360",
        part_numbers_norm=[],
        sku="KEMP-1",
        name="Part",
        description=None,
        brand="KEMP",
        category="Filters",
        applicability_brands=[],
        applicability_models=[],
        characteristics_raw={},
        raw_row={},
    )

    payload = _catalog_semantic_reference_payload(item)

    assert payload["oe"] == "31211128157"
    assert payload["mpn"] is None
    assert payload["search_identity"] == "31211128157"
    assert payload["identity_status"] == "OE_CONFIRMED"


def test_the_gate_is_told_which_unit_the_seed_is_priced_in() -> None:
    # A bounded run hands the collector a frozen row with no ``raw_row``, so the
    # unit has to arrive as its own field or the gate reports unit_basis and
    # package_quantity missing on every candidate.
    item = SimpleNamespace(
        identity_status="OE_CONFIRMED",
        oe_norm="31211128157",
        mpn_norm=None,
        part_numbers_norm=[],
        sku="KEMP-1",
        name="Part",
        description=None,
        brand="KEMP",
        category="Filters",
        applicability_brands=[],
        applicability_models=[],
        characteristics_raw={},
        measure_unit="шт.",
    )

    payload = _catalog_semantic_reference_payload(item)

    assert payload["measure_unit"] == "шт."


def test_a_seed_with_no_resolvable_unit_asserts_none() -> None:
    item = SimpleNamespace(
        identity_status="OE_CONFIRMED",
        oe_norm="31211128157",
        mpn_norm=None,
        part_numbers_norm=[],
        sku="KEMP-1",
        name="Part",
        description=None,
        brand="KEMP",
        category="Filters",
        applicability_brands=[],
        applicability_models=[],
        characteristics_raw={},
        measure_unit=None,
        raw_row={},
    )

    payload = _catalog_semantic_reference_payload(item)

    assert "measure_unit" not in payload


def test_an_unreadable_brand_level_no_longer_parks_a_tier_blind_offer() -> None:
    # Owner decision of 2026-07-30: the price is the cheapest comparable offer
    # whatever level it sits at, so UNKNOWN_TIER stops withholding the offer.
    role = _initial_cohort_role(
        _classification(exclusion_reason="UNKNOWN_TIER"),
        is_owned=False,
        tier_agnostic=True,
    )

    assert role is CohortRole.TARGET_MARKET


def test_the_same_offer_is_still_parked_when_the_policy_prices_by_tier() -> None:
    role = _initial_cohort_role(
        _classification(exclusion_reason="UNKNOWN_TIER"),
        is_owned=False,
        tier_agnostic=False,
    )

    assert role is CohortRole.MANUAL_REVIEW


def test_tier_blindness_releases_only_the_tier_and_nothing_else() -> None:
    role = _initial_cohort_role(
        _classification(exclusion_reason="TIER_CONFLICT"),
        is_owned=False,
        tier_agnostic=True,
    )

    assert role is CohortRole.MANUAL_REVIEW


@pytest.mark.parametrize(
    ("classification", "is_owned", "expected"),
    [
        (_classification(is_used=True), False, CohortRole.USED_REJECTED),
        (_classification(is_kemp=True), False, CohortRole.KEMP_REFERENCE),
        (_classification(), True, CohortRole.OWNED_STORE),
    ],
)
def test_tier_blindness_does_not_touch_the_other_partitions(
    classification: SimpleNamespace,
    is_owned: bool,
    expected: CohortRole,
) -> None:
    role = _initial_cohort_role(
        classification,
        is_owned=is_owned,
        tier_agnostic=True,
    )

    assert role is expected


def test_a_widened_row_is_verified_against_the_number_that_found_it() -> None:
    crosses = (
        ConfirmedCross(
            search_oe_norm="31211128157",
            candidate_oe_norm="1K0412249",
            canonical_identity_key="key",
            confidence=Decimal("0.95"),
            cross_link_id="link-1",
        ),
    )

    assert (
        _offer_search_identity(
            {"found_by_query": "1k0412249"},
            primary="31211128157",
            confirmed_crosses=crosses,
        )
        == "1K0412249"
    )


def test_an_undeclared_cross_cannot_be_claimed_after_the_fact() -> None:
    """The run freezes its confirmed crosses at start; a payload cannot add one."""

    with pytest.raises(EvidenceAccountingError) as error:
        _offer_search_identity(
            {"found_by_query": "9999999"},
            primary="31211128157",
            confirmed_crosses=(),
        )

    assert "ACQUISITION_WIDENING_BINDING_ERROR" in str(error.value)


def test_a_cross_frozen_for_another_catalog_row_is_not_ours() -> None:
    crosses = (
        ConfirmedCross(
            search_oe_norm="7E5827505A",
            candidate_oe_norm="1K0412249",
            canonical_identity_key="key",
            confidence=Decimal("0.95"),
            cross_link_id="link-1",
        ),
    )

    with pytest.raises(EvidenceAccountingError):
        _offer_search_identity(
            {"found_by_query": "1K0412249"},
            primary="31211128157",
            confirmed_crosses=crosses,
        )


@pytest.mark.parametrize("detail", [None, {}, {"found_by_query": "  "}, "not-a-map"])
def test_a_row_without_a_widening_keeps_the_primary_identity(detail: object) -> None:
    assert (
        _offer_search_identity(
            detail,
            primary="31211128157",
            confirmed_crosses=(),
        )
        == "31211128157"
    )


def test_a_discovery_key_retrieves_without_ever_widening_the_identity() -> None:
    """A retrieval-only key found the row; it did not identify it.

    The customer's namespace rule: the original vehicle OE is the market
    identity, and only a cross with confirmed source and provenance may widen
    it. A public MPN carries no such claim, so the row is still checked
    against the primary — it earns its evidence off the card or it goes to
    review. What must not happen is the run refusing the row outright: the
    number was declared, so the acquisition is legitimate.
    """

    assert (
        _offer_search_identity(
            {"found_by_query": "606554"},
            primary="31211128157",
            confirmed_crosses=(),
            discovery_queries=("606554",),
        )
        == "31211128157"
    )


def test_a_confirmed_cross_still_wins_over_the_weaker_declaration() -> None:
    crosses = (
        ConfirmedCross(
            search_oe_norm="31211128157",
            candidate_oe_norm="1K0412249",
            canonical_identity_key="key",
            confidence=Decimal("0.95"),
            cross_link_id="link-1",
        ),
    )

    assert (
        _offer_search_identity(
            {"found_by_query": "1K0412249"},
            primary="31211128157",
            confirmed_crosses=crosses,
            discovery_queries=("1K0412249",),
        )
        == "1K0412249"
    )


def test_a_number_in_neither_frozen_list_still_stops_the_run() -> None:
    """Opening a second tier must not open an unbounded third one."""

    with pytest.raises(EvidenceAccountingError) as error:
        _offer_search_identity(
            {"found_by_query": "9999999"},
            primary="31211128157",
            confirmed_crosses=(),
            discovery_queries=("606554",),
        )

    assert "ACQUISITION_WIDENING_BINDING_ERROR" in str(error.value)
