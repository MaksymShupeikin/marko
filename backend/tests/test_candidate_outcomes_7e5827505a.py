"""Stop-gate for the three-outcome chain, replayed on the 7E5827505A run.

The 29 candidates are reconstructed from the recorded live run
(``docs/METIS_DETERMINISTIC_CANDIDATE_SELECTION_7E5827505A_2026-07-25.md``,
run ``aa621d41-646b-4875-bb0c-138423901a8a``): four named early exits plus the
25 listings that cleared every identity gate and stopped only at the tier gate.
The point of the replay is the *distribution*, which the document states in
full, not the individual titles.

Before this change the run produced 0 COMPARABLE, 25 REVIEW and 4 SKIP, and the
customer saw nothing.  The assertions below pin what must happen instead.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from metis.pricing.candidate_selection import (
    CandidateItem,
    CandidateStatus,
    ReferenceItem,
    check_candidate,
    load_candidate_selection_config,
    verdict_histogram,
)
from metis.pricing.types import ProductTier


BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_candidate_selection_config(BACKEND_ROOT / "config" / "comparability.yaml")

# The state that produced the empty run: only KEMP is approved in brands.yaml.
BRANDS_AS_SHIPPED = {"KEMP": ProductTier.KEMP}

REFERENCE = ReferenceItem(
    oem="7E5 827 505 A",
    title="VW Transporter T5 T6 замок задней крышки",
    price=Decimal("1800"),
    brand="KEMP",
    category="body_lock",
    tier=ProductTier.KEMP,
)


def _candidate(**overrides) -> CandidateItem:
    values = {
        "seller_id": "3823617",
        "seller_name": "АвтоМаркет",
        "title": "7E5827505A Замок кришки багажника VW Transporter T5 T6",
        "description": None,
        "article_field": "7E5827505A",
        "brand": "Polcar",
        "price": Decimal("1500"),
        "condition": None,
    }
    values.update(overrides)
    return CandidateItem(**values)


def _run_29() -> list:
    """Rebuild the recorded distribution: 2 dismantlers, 1 used, 1 no-OE, 25 rest."""

    candidates = [
        _candidate(seller_name='интернет магазин "Avtorazborka24"', seller_id="s15"),
        _candidate(seller_name="Razborka.club", seller_id="s20"),
        _candidate(
            seller_name='Інтернет-магазин "АВТОДЕТАЛЬ"',
            seller_id="s9",
            title="Б/У замок 7E5827505A VW Transporter T5",
        ),
        _candidate(
            seller_name="VolunParts - магазин автозапчастин",
            seller_id="s21",
            title="Замок кришки багажника VW Transporter T5",
            article_field="OTHER-1",
        ),
    ]
    candidates.extend(
        _candidate(seller_id=f"s{index}", seller_name=f"Продавец {index}")
        for index in range(100, 125)
    )
    return [
        check_candidate(
            REFERENCE,
            candidate,
            CONFIG,
            brand_tiers=BRANDS_AS_SHIPPED,
        )
        for candidate in candidates
    ]


def test_recorded_run_no_longer_hides_every_candidate() -> None:
    verdicts = _run_29()
    counts = {status: 0 for status in CandidateStatus}
    for verdict in verdicts:
        counts[verdict.status] += 1

    assert len(verdicts) == 29
    assert counts[CandidateStatus.REJECTED] == 4
    assert counts[CandidateStatus.REFERENCE_ONLY] == 25
    # Still zero, and honestly so: the brand dictionary approves only KEMP, so
    # no candidate has a known level.  The difference is that 25 of them are now
    # shown to the customer instead of being suppressed.
    assert counts[CandidateStatus.PRICING_EVIDENCE] == 0


def test_recorded_run_histogram_names_outcome_and_cause() -> None:
    assert verdict_histogram(_run_29()) == {
        "REFERENCE_ONLY:TIER_UNKNOWN": 25,
        "REJECTED:DISMANTLER_SELLER": 2,
        "REJECTED:OEM_NOT_FOUND": 1,
        "REJECTED:USED": 1,
    }


def test_approved_brand_without_calibration_is_still_reference_only() -> None:
    """Approving a brand is necessary but not sufficient to price against it.

    Without a validated coefficient there is no defensible conversion to our
    own level, so the candidate stays visible and stays out of the basis.
    """

    verdict = check_candidate(
        REFERENCE,
        _candidate(),
        CONFIG,
        brand_tiers={"KEMP": ProductTier.KEMP, "POLCAR": ProductTier.AFTERMARKET_B},
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "PREMIUM_NOT_CALIBRATED"


def test_approved_brand_with_validated_coefficient_becomes_pricing_evidence() -> None:
    verdict = check_candidate(
        REFERENCE,
        _candidate(),
        CONFIG,
        brand_tiers={"KEMP": ProductTier.KEMP, "POLCAR": ProductTier.AFTERMARKET_B},
        calibrated_premiums={("body_lock", ProductTier.AFTERMARKET_B): Decimal("1.2")},
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert verdict.reason == "OK"
    assert verdict.details["gates"]["premium_calibration"]["premium"] == "1.2"


def test_our_own_brand_is_visible_but_never_prices_us() -> None:
    """A KEMP reseller is shown and excluded, not hidden as it used to be."""

    verdict = check_candidate(
        REFERENCE,
        _candidate(brand="KEMP", seller_id="other-kemp-shop"),
        CONFIG,
        brand_tiers=BRANDS_AS_SHIPPED,
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "OWN_BRAND"
    assert verdict.details["gates"]["own_brand"]["matched_by"] == "TIER"


def test_same_level_needs_no_coefficient() -> None:
    """A competitor at our own level converts by a ratio of one, by definition."""

    verdict = check_candidate(
        ReferenceItem(
            oem="7E5 827 505 A",
            title="VW Transporter T5 T6 замок задней крышки",
            price=Decimal("1800"),
            brand="Polcar",
            category="body_lock",
            tier=ProductTier.AFTERMARKET_B,
        ),
        _candidate(),
        CONFIG,
        brand_tiers={"POLCAR": ProductTier.AFTERMARKET_B},
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert (
        verdict.details["gates"]["premium_calibration"]["source"]
        == "SAME_TIER_IDENTITY"
    )


def test_identity_rejection_still_precedes_every_comparability_question() -> None:
    """A dismantler is rejected before the chain ever asks about its level."""

    verdict = check_candidate(
        REFERENCE,
        _candidate(seller_name="Razborka.club", brand="KEMP"),
        CONFIG,
        brand_tiers=BRANDS_AS_SHIPPED,
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "DISMANTLER_SELLER"
    assert "tier_classification" not in verdict.passed_gates
