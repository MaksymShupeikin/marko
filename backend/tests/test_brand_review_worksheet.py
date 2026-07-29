"""Variation matrix for the brand markup worksheet (master plan phase 2).

The mandated test of §2.2 lives here: KEMP must be absent from the competitor
set and present in the anchor set, including the customer's own stores. Getting
those two sets confused does not raise — it quietly corrupts every premium
downstream — so the distinction is pinned explicitly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from marko.infrastructure.db.models import CatalogDiscoveryOffer
from marko.services.brand_review_worksheet import (
    BrandObservation,
    build_brand_worksheet,
    deduplicate_observations,
    is_reviewable_evidence_url,
    load_existing_records,
    median_decimal,
    observation_from_offer,
    oem_identity_lane,
    price_ratio_vs_kemp,
    render_brands_draft_yaml,
    render_worksheet_csv,
)
from metis.pricing import (
    BrandRuleContractError,
    CandidateItem,
    ProductTier,
    ReferenceItem,
    check_candidate,
    load_approved_brand_rules,
    load_candidate_selection_config,
)


GENERATED_AT = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "comparability.yaml"


def _observation(**overrides: Any) -> BrandObservation:
    payload: dict[str, Any] = {
        "target_oe": "7E5827505A",
        "brand_raw": "Polcar",
        "brand_normalized": "POLCAR",
        "seller_id": "seller-1",
        "listing_id": "listing-1",
        "url": "https://prom.ua/ua/p1-polcar.html",
        "price": Decimal("2000.00"),
        "is_owned": False,
        "is_kemp": False,
        "is_used": False,
        "identity_lane": "ARTICLE_FIELD",
        "selection_reason": "TIER_UNKNOWN",
    }
    payload.update(overrides)
    return BrandObservation(**payload)


def _kemp(**overrides: Any) -> BrandObservation:
    payload: dict[str, Any] = {
        "brand_raw": "KEMP",
        "brand_normalized": "KEMP",
        "is_kemp": True,
        "price": Decimal("1000.00"),
        "seller_id": "2847093",
        "listing_id": "kemp-listing",
        "url": "https://prom.ua/ua/p2-kemp.html",
        "selection_reason": "OWN_SELLER",
    }
    payload.update(overrides)
    return _observation(**payload)


# --------------------------------------------------------------------------
# The two sets the master plan warns about
# --------------------------------------------------------------------------


def test_kemp_is_the_anchor_but_never_a_competitor() -> None:
    """§2.2: KEMP leaves the target median yet must stay as premium anchor."""

    kemp = _kemp()

    assert kemp.in_kemp_anchor_set is True
    assert kemp.in_competitor_set is False


def test_own_store_kemp_listing_still_anchors_the_ratio() -> None:
    """The customer's own KEMP card *is* the anchor price; dropping it would
    leave most positions with no denominator at all."""

    owned_kemp = _kemp(is_owned=True)

    assert owned_kemp.in_kemp_anchor_set is True
    assert owned_kemp.in_competitor_set is False


def test_own_store_non_kemp_listing_is_in_neither_set() -> None:
    owned = _observation(is_owned=True)

    assert owned.in_competitor_set is False
    assert owned.in_kemp_anchor_set is False


def test_used_listing_is_in_neither_set() -> None:
    used = _observation(is_used=True)
    used_kemp = _kemp(is_used=True)

    assert used.in_competitor_set is False
    assert used_kemp.in_kemp_anchor_set is False


def test_listing_without_identity_is_in_neither_set() -> None:
    anonymous = _observation(identity_lane=None)
    anonymous_kemp = _kemp(identity_lane=None)

    assert anonymous.in_competitor_set is False
    assert anonymous_kemp.in_kemp_anchor_set is False


def test_worksheet_never_emits_a_row_for_kemp() -> None:
    worksheet = build_brand_worksheet(
        [_observation(), _kemp()],
        generated_at=GENERATED_AT,
    )

    assert [row.brand_normalized for row in worksheet.rows] == ["POLCAR"]
    assert worksheet.kemp_anchor_observation_count == 1
    assert worksheet.competitor_observation_count == 1


# --------------------------------------------------------------------------
# Identity lane
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sku", "title", "description", "expected"),
    [
        ("7E5 827 505 A", "Замок", None, "ARTICLE_FIELD"),
        ("POL-1", "Замок 7E5827505A VW", None, "TITLE"),
        ("POL-1", "Замок", "OE 7E5827505A", "DESCRIPTION"),
        ("POL-1", "Замок", "нет номера", None),
        (None, None, None, None),
    ],
)
def test_identity_lane_precedence(
    sku: str | None,
    title: str | None,
    description: str | None,
    expected: str | None,
) -> None:
    assert (
        oem_identity_lane(
            "7E5827505A",
            sku=sku,
            title=title,
            description=description,
        )
        == expected
    )


def test_identity_lane_without_a_target_is_none() -> None:
    assert oem_identity_lane("", sku="7E5827505A", title=None, description=None) is None


@pytest.mark.parametrize(
    ("sku", "title", "description"),
    [
        ("7E5 827 505 A", "Замок", None),
        ("POL-1", "Замок 7E5827505A VW", None),
        ("POL-1", "Замок", "OE 7E5827505A"),
        ("POL-1", "Замок", "нет номера"),
    ],
)
def test_identity_lane_agrees_with_the_production_gate(
    sku: str,
    title: str,
    description: str | None,
) -> None:
    """The anchor set must not drift from what the gate chain calls identity."""

    config = load_candidate_selection_config(_CONFIG_PATH)
    verdict = check_candidate(
        ReferenceItem(oem="7E5827505A", title="Замок", price=None),
        CandidateItem(
            seller_id="s1",
            seller_name="Продавець",
            title=title,
            description=description,
            article_field=sku,
            brand="Polcar",
            price=Decimal("2000"),
        ),
        config,
    )
    gate_evidence = verdict.details["gates"].get("oem_identity", {}).get("evidence")

    assert (
        oem_identity_lane("7E5827505A", sku=sku, title=title, description=description)
        == gate_evidence
    )


# --------------------------------------------------------------------------
# Robust statistics
# --------------------------------------------------------------------------


def test_median_of_an_empty_sample_is_none_not_zero() -> None:
    assert median_decimal([]) is None


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ([Decimal("5")], Decimal("5")),
        ([Decimal("1"), Decimal("2")], Decimal("1.5")),
        ([Decimal("1"), Decimal("2"), Decimal("9")], Decimal("2")),
        ([Decimal("4"), Decimal("4"), Decimal("4")], Decimal("4")),
    ],
)
def test_median_boundaries(values: list[Decimal], expected: Decimal) -> None:
    assert median_decimal(values) == expected


def test_ratio_is_median_across_oes_of_per_oe_medians() -> None:
    brand = {
        "OE1": [Decimal("2000")],
        "OE2": [Decimal("1900")],
        "OE3": [Decimal("2200")],
    }
    kemp = {
        "OE1": [Decimal("1000")],
        "OE2": [Decimal("1000")],
        "OE3": [Decimal("1000")],
    }

    summary = price_ratio_vs_kemp(brand, kemp)

    assert summary.paired_oe_count == 3
    assert summary.median == Decimal("2.0000")


def test_one_seller_flooding_a_single_oe_cannot_dominate_the_ratio() -> None:
    """Per-OE medians collapse first, so ten listings on OE1 count once."""

    brand = {
        "OE1": [Decimal("9000")] * 10,
        "OE2": [Decimal("1000")],
        "OE3": [Decimal("1000")],
    }
    kemp = {
        "OE1": [Decimal("1000")],
        "OE2": [Decimal("1000")],
        "OE3": [Decimal("1000")],
    }

    summary = price_ratio_vs_kemp(brand, kemp)

    assert summary.paired_oe_count == 3
    assert summary.median == Decimal("1.0000")


def test_ratio_without_a_shared_oe_is_undefined_not_one() -> None:
    summary = price_ratio_vs_kemp(
        {"OE1": [Decimal("2000")]},
        {"OE2": [Decimal("1000")]},
    )

    assert summary.median is None
    assert summary.paired_oe_count == 0


def test_ratio_skips_a_non_positive_kemp_denominator() -> None:
    summary = price_ratio_vs_kemp(
        {"OE1": [Decimal("2000")], "OE2": [Decimal("2000")]},
        {"OE1": [Decimal("0")], "OE2": [Decimal("1000")]},
    )

    assert summary.paired_oe_count == 1
    assert summary.median == Decimal("2.0000")


def test_ratio_on_empty_input_is_undefined() -> None:
    summary = price_ratio_vs_kemp({}, {})

    assert summary.median is None
    assert summary.paired_oe_count == 0
    assert summary.spread is None
    assert summary.is_trustworthy is False


def test_measured_volkswagen_spread_marks_the_median_untrustworthy() -> None:
    """Real 2026-07-26 pairing: 0.81, 6.88, 11.51, 16.45 -> median 9.20.

    The median is arithmetically right and descriptively useless, which is why
    the spread has to travel with it.
    """

    brand = {
        "09G409061": [Decimal("1040.00")],
        "1F0129620": [Decimal("2758.57")],
        "7E0905865": [Decimal("4697.67")],
        "7L6127434A": [Decimal("2914.00")],
    }
    kemp = {
        "09G409061": [Decimal("1285.20")],
        "1F0129620": [Decimal("239.62")],
        "7E0905865": [Decimal("285.60")],
        "7L6127434A": [Decimal("423.50")],
    }

    summary = price_ratio_vs_kemp(brand, kemp)

    assert summary.median == Decimal("9.1965")
    assert summary.paired_oe_count == 4
    assert summary.minimum == Decimal("0.8092")
    assert summary.maximum == Decimal("16.4484")
    assert summary.is_trustworthy is False


def test_a_consistent_brand_keeps_a_trustworthy_ratio() -> None:
    brand = {"OE1": [Decimal("2000")], "OE2": [Decimal("2100")]}
    kemp = {"OE1": [Decimal("1000")], "OE2": [Decimal("1000")]}

    summary = price_ratio_vs_kemp(brand, kemp)

    assert summary.spread == Decimal("1.0500")
    assert summary.is_trustworthy is True


def test_a_single_paired_oe_is_never_trustworthy() -> None:
    """One pair has zero spread by construction; that is not agreement."""

    summary = price_ratio_vs_kemp(
        {"OE1": [Decimal("2000")]}, {"OE1": [Decimal("1000")]}
    )

    assert summary.paired_oe_count == 1
    assert summary.spread == Decimal("1.0000")
    assert summary.is_trustworthy is False


@pytest.mark.parametrize(
    ("high", "trustworthy"),
    [(Decimal("3900"), True), (Decimal("4100"), False)],
)
def test_spread_threshold_boundary(high: Decimal, trustworthy: bool) -> None:
    summary = price_ratio_vs_kemp(
        {"OE1": [Decimal("1000")], "OE2": [high]},
        {"OE1": [Decimal("1000")], "OE2": [Decimal("1000")]},
    )

    assert summary.is_trustworthy is trustworthy


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------


def test_worksheet_counts_sellers_not_listings() -> None:
    worksheet = build_brand_worksheet(
        [
            _observation(listing_id="a", seller_id="s1"),
            _observation(listing_id="b", seller_id="s1"),
            _observation(listing_id="c", seller_id="s2"),
        ],
        generated_at=GENERATED_AT,
    )
    row = worksheet.rows[0]

    assert row.offer_count == 3
    assert row.seller_count == 2


def test_worksheet_collects_raw_spelling_variants() -> None:
    worksheet = build_brand_worksheet(
        [
            _observation(brand_raw="Polcar", listing_id="a"),
            _observation(brand_raw="POLCAR", listing_id="b"),
        ],
        generated_at=GENERATED_AT,
    )

    assert worksheet.rows[0].brand_variants == ("POLCAR", "Polcar")


def test_worksheet_orders_by_positions_unblocked_first() -> None:
    observations = [
        _observation(brand_raw="Narrow", brand_normalized="NARROW", listing_id=f"n{i}")
        for i in range(5)
    ] + [
        _observation(
            brand_raw="Wide",
            brand_normalized="WIDE",
            listing_id=f"w{i}",
            target_oe=f"OE{i}",
        )
        for i in range(3)
    ]

    worksheet = build_brand_worksheet(observations, generated_at=GENERATED_AT)

    assert [row.brand_normalized for row in worksheet.rows] == ["WIDE", "NARROW"]


def test_min_offer_count_drops_long_tail_brands() -> None:
    observations = [
        _observation(brand_raw="Rare", brand_normalized="RARE"),
        _observation(brand_raw="Common", brand_normalized="COMMON", listing_id="a"),
        _observation(brand_raw="Common", brand_normalized="COMMON", listing_id="b"),
    ]

    worksheet = build_brand_worksheet(
        observations,
        generated_at=GENERATED_AT,
        min_offer_count=2,
    )

    assert [row.brand_normalized for row in worksheet.rows] == ["COMMON"]


def test_brand_without_a_kemp_pair_reports_no_ratio() -> None:
    worksheet = build_brand_worksheet([_observation()], generated_at=GENERATED_AT)

    assert worksheet.rows[0].median_price_vs_kemp is None
    assert worksheet.rows[0].paired_oe_count == 0


def test_brand_with_a_kemp_pair_reports_the_ratio() -> None:
    worksheet = build_brand_worksheet(
        [_observation(price=Decimal("2000")), _kemp(price=Decimal("1000"))],
        generated_at=GENERATED_AT,
    )

    assert worksheet.rows[0].median_price_vs_kemp == Decimal("2.0000")
    assert worksheet.rows[0].paired_oe_count == 1


def test_worksheet_on_no_observations_is_empty_not_an_error() -> None:
    worksheet = build_brand_worksheet([], generated_at=GENERATED_AT)

    assert worksheet.rows == ()
    assert worksheet.observation_count == 0
    assert worksheet.distinct_target_oes == 0


def test_blank_brand_values_do_not_become_a_row() -> None:
    worksheet = build_brand_worksheet(
        [_observation(brand_raw=None, brand_normalized="")],
        generated_at=GENERATED_AT,
    )

    assert worksheet.rows == ()


def test_example_urls_prefer_distinct_target_oes() -> None:
    observations = [
        _observation(
            listing_id=f"l{index}",
            target_oe=f"OE{index % 2}",
            url=f"https://prom.ua/ua/p{index}-x.html",
        )
        for index in range(4)
    ]

    worksheet = build_brand_worksheet(observations, generated_at=GENERATED_AT)

    assert len(worksheet.rows[0].example_urls) == 3
    assert worksheet.rows[0].example_urls[0] != worksheet.rows[0].example_urls[1]


def test_unusable_urls_are_never_offered_as_evidence() -> None:
    worksheet = build_brand_worksheet(
        [_observation(url="http://example.com/x")],
        generated_at=GENERATED_AT,
    )

    assert worksheet.rows[0].example_urls == ()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://prom.ua/ua/p1-x.html", True),
        ("https://shop.prom.ua/p1", True),
        ("http://prom.ua/ua/p1-x.html", False),
        ("https://evil.com/prom.ua", False),
        ("https://user:pw@prom.ua/p1", False),
        ("https://prom.ua", False),
        ("not a url", False),
    ],
)
def test_evidence_url_contract(url: str, expected: bool) -> None:
    assert is_reviewable_evidence_url(url) is expected


# --------------------------------------------------------------------------
# observation_from_offer
# --------------------------------------------------------------------------


def test_offer_row_becomes_an_observation_with_derived_flags() -> None:
    offer = CatalogDiscoveryOffer(
        source_listing_id="l1",
        seller_id="s1",
        seller_name="Продавець",
        title="Замок 7E5827505A",
        url="https://prom.ua/ua/p1-x.html",
        sku="7E5827505A",
        brand="KEMP",
        sale_price=Decimal("1000"),
        currency="UAH",
        is_owned=True,
        identity_status="QUERY_TOKEN_PRESENT",
        source_confidence=Decimal("1"),
        selection_status="SKIP",
        selection_reason="OWN_SELLER",
        raw_snapshot={},
    )

    observation = observation_from_offer(offer, target_oe="7E5 827 505 A")

    assert observation.brand_normalized == "KEMP"
    assert observation.is_kemp is True
    assert observation.is_owned is True
    assert observation.identity_lane == "ARTICLE_FIELD"
    assert observation.in_kemp_anchor_set is True
    assert observation.in_competitor_set is False


def test_used_marker_in_the_snapshot_description_is_detected() -> None:
    offer = CatalogDiscoveryOffer(
        source_listing_id="l1",
        seller_id="s1",
        seller_name="Продавець",
        title="Замок 7E5827505A",
        url="https://prom.ua/ua/p1-x.html",
        sku="7E5827505A",
        brand="Polcar",
        sale_price=Decimal("1000"),
        currency="UAH",
        is_owned=False,
        identity_status="QUERY_TOKEN_PRESENT",
        source_confidence=Decimal("1"),
        selection_status="SKIP",
        selection_reason="USED",
        raw_snapshot={"description": "Знято з робочої машини, вживаний"},
    )

    observation = observation_from_offer(offer, target_oe="7E5827505A")

    assert observation.is_used is True
    assert observation.in_competitor_set is False


# --------------------------------------------------------------------------
# Draft round-trip: the generated file must survive the real loader
# --------------------------------------------------------------------------


def _draft(**kwargs: Any) -> str:
    worksheet = build_brand_worksheet(
        [_observation(price=Decimal("2000")), _kemp(price=Decimal("1000"))],
        generated_at=GENERATED_AT,
    )
    return render_brands_draft_yaml(worksheet, dataset_id="test-draft", **kwargs)


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "brands.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_generated_draft_loads_and_activates_nothing(tmp_path: Path) -> None:
    rules = load_approved_brand_rules(_write(tmp_path, _draft()))

    assert rules.domain_policy_approved is False
    assert dict(rules.tiers) == {"KEMP": ProductTier.KEMP}


def test_draft_keeps_kemp_as_the_contractual_invariant(tmp_path: Path) -> None:
    document = yaml.safe_load(_draft())
    kemp = next(item for item in document["brands"] if item["normalized"] == "KEMP")

    assert kemp["tier"] == "kemp"
    assert kemp["approved"] is True


def test_a_fully_approved_record_activates(tmp_path: Path) -> None:
    """The whole point of the draft: a human edit must actually take effect."""

    document = yaml.safe_load(_draft())
    document["domain_policy_approved"] = True
    document["approved_by"] = "Yuri"
    document["approved_at"] = "2026-07-27"
    record = next(item for item in document["brands"] if item["normalized"] == "POLCAR")
    record.update(
        tier="oes",
        confidence="0.9000",
        approved=True,
        approved_by="Yuri",
        approved_at="2026-07-27",
    )

    rules = load_approved_brand_rules(
        _write(tmp_path, yaml.safe_dump(document, allow_unicode=True))
    )

    assert rules.tiers["POLCAR"] is ProductTier.OES
    assert rules.confidence["POLCAR"] == Decimal("0.9000")


def test_prefilled_evidence_urls_satisfy_the_loader(tmp_path: Path) -> None:
    document = yaml.safe_load(_draft())
    record = next(item for item in document["brands"] if item["normalized"] == "POLCAR")

    assert record["evidence"]
    assert all(is_reviewable_evidence_url(url) for url in record["evidence"])


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda record: record.update(approved_by=None), "missing reviewer"),
        (lambda record: record.update(approved_at=None), "missing timestamp"),
        (lambda record: record.update(approved_at="вчера"), "non ISO timestamp"),
        (lambda record: record.update(evidence=[]), "empty evidence"),
        (
            lambda record: record.update(evidence={"offer_count": 3}),
            "statistics mapping instead of URLs",
        ),
        (
            lambda record: record.update(evidence=["http://prom.ua/p1"]),
            "insecure evidence URL",
        ),
        (
            lambda record: record.update(evidence=["https://evil.com/p1"]),
            "off-market evidence URL",
        ),
        (lambda record: record.update(tier="unknown"), "unassignable tier"),
        (lambda record: record.update(tier="kemp"), "kemp tier on a rival"),
        (lambda record: record.update(confidence="0.0000"), "zero confidence"),
    ],
)
def test_incomplete_approval_is_refused_whole_file(
    tmp_path: Path,
    mutate: Any,
    reason: str,
) -> None:
    """Fail-closed: a half-signed record must not activate silently."""

    document = yaml.safe_load(_draft())
    document["domain_policy_approved"] = True
    document["approved_by"] = "Yuri"
    document["approved_at"] = "2026-07-27"
    record = next(item for item in document["brands"] if item["normalized"] == "POLCAR")
    record.update(
        tier="oes",
        confidence="0.9000",
        approved=True,
        approved_by="Yuri",
        approved_at="2026-07-27",
    )
    mutate(record)

    with pytest.raises(BrandRuleContractError):
        load_approved_brand_rules(
            _write(tmp_path, yaml.safe_dump(document, allow_unicode=True))
        )


def test_record_approved_while_policy_is_not_is_refused(tmp_path: Path) -> None:
    document = yaml.safe_load(_draft())
    record = next(item for item in document["brands"] if item["normalized"] == "POLCAR")
    record.update(
        tier="oes",
        confidence="0.9000",
        approved=True,
        approved_by="Yuri",
        approved_at="2026-07-27",
    )

    with pytest.raises(BrandRuleContractError):
        load_approved_brand_rules(
            _write(tmp_path, yaml.safe_dump(document, allow_unicode=True))
        )


# --------------------------------------------------------------------------
# Regeneration must not destroy human work
# --------------------------------------------------------------------------


def test_regeneration_preserves_an_earlier_human_decision(tmp_path: Path) -> None:
    decided = {
        "POLCAR": {
            "tier": "oes",
            "confidence": "0.9000",
            "approved": True,
            "approved_by": "Yuri",
            "approved_at": "2026-07-27",
            "evidence": ["https://prom.ua/ua/p9-reviewed.html"],
        }
    }

    document = yaml.safe_load(_draft(existing=decided))
    record = next(item for item in document["brands"] if item["normalized"] == "POLCAR")

    assert record["tier"] == "oes"
    assert record["approved"] is True
    assert record["approved_by"] == "Yuri"
    assert record["evidence"] == ["https://prom.ua/ua/p9-reviewed.html"]


def test_regeneration_refreshes_statistics_for_a_decided_brand() -> None:
    decided = {"POLCAR": {"tier": "oes", "approved": True}}

    document = yaml.safe_load(_draft(existing=decided))
    record = next(item for item in document["brands"] if item["normalized"] == "POLCAR")

    assert record["statistics"]["offer_count"] == 1
    assert record["statistics"]["median_price_vs_kemp"] == "2.0000"


def test_existing_records_are_read_back_by_normalized_brand(tmp_path: Path) -> None:
    path = _write(tmp_path, _draft())

    decided = load_existing_records(path)

    assert decided["POLCAR"]["tier"] == "unknown"
    assert decided["POLCAR"]["approved"] is False


def test_legacy_statistics_mapping_is_not_carried_over_as_evidence(
    tmp_path: Path,
) -> None:
    """The old draft stored statistics under ``evidence``; reusing that as
    approval evidence would hand the loader an unusable mapping."""

    path = _write(
        tmp_path,
        yaml.safe_dump(
            {
                "schema_version": "metis-brand-tiers-v1",
                "brands": [
                    {
                        "brand": "Polcar",
                        "normalized": "POLCAR",
                        "tier": "unknown",
                        "evidence": {"offer_count": 9},
                    }
                ],
            }
        ),
    )

    decided = load_existing_records(path)

    assert "evidence" not in decided["POLCAR"]


# --------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------


def test_csv_leaves_the_tier_column_empty_for_the_reviewer() -> None:
    worksheet = build_brand_worksheet(
        [_observation(price=Decimal("2000")), _kemp(price=Decimal("1000"))],
        generated_at=GENERATED_AT,
    )

    csv_text = render_worksheet_csv(worksheet)
    header, row = csv_text.splitlines()[:2]

    assert "tier_TO_FILL" in header
    assert row.split(",")[2] == ""


# --------------------------------------------------------------------------
# Repeated batches must not inflate the counts
# --------------------------------------------------------------------------


def test_repeating_a_batch_does_not_double_the_offer_count() -> None:
    """Measured 2026-07-26: two batches over the same 30 OEs doubled every
    offer_count while seller_count stayed put."""

    first = _observation(listing_id="l1", price=Decimal("2000"))
    second = _observation(listing_id="l1", price=Decimal("2500"))

    deduplicated = deduplicate_observations([first, second])

    assert len(deduplicated) == 1
    assert deduplicated[0].price == Decimal("2500")


def test_the_same_listing_under_a_different_oe_stays_separate() -> None:
    observations = deduplicate_observations(
        [
            _observation(listing_id="l1", target_oe="OE1"),
            _observation(listing_id="l1", target_oe="OE2"),
        ]
    )

    assert len(observations) == 2


def test_deduplication_of_nothing_is_empty() -> None:
    assert deduplicate_observations([]) == ()


def test_worksheet_counts_are_stable_when_a_batch_is_replayed() -> None:
    batch = [
        _observation(listing_id="a", seller_id="s1"),
        _observation(listing_id="b", seller_id="s2"),
        _kemp(listing_id="k1"),
    ]

    once = build_brand_worksheet(
        deduplicate_observations(batch), generated_at=GENERATED_AT
    )
    twice = build_brand_worksheet(
        deduplicate_observations(batch + batch), generated_at=GENERATED_AT
    )

    assert once.rows[0].offer_count == twice.rows[0].offer_count == 2
    assert once.rows[0].seller_count == twice.rows[0].seller_count == 2
