from __future__ import annotations

from pathlib import Path

import pytest

from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.catalog_internal_code_join import (
    CatalogInternalCodeJoinRow,
    extract_listing_internal_codes,
    summarize_catalog_internal_code_join,
)
from marko.services.xlsx_catalog import normalize_identifier


@pytest.mark.parametrize(
    ("raw_data", "expected"),
    (
        (
            {"part_numbers": ["056121113D", "050121113C", "776416"]},
            ("776416",),
        ),
        ({"part_numbers": ["056121113D", "050121113C"]}, ()),
        ({"part_numbers": ["776416", "776440"]}, ("776416", "776440")),
        ({"part_numbers": ["776 416", "776-416"]}, ("776416",)),
        ({"name": "legacy snapshot without part_numbers"}, ()),
        ({"part_numbers": None}, ()),
    ),
)
def test_listing_internal_code_extraction_is_unique_and_fail_closed(
    raw_data: dict[str, object], expected: tuple[str, ...]
) -> None:
    assert extract_listing_internal_codes(raw_data) == expected


@pytest.mark.parametrize("raw", ("7764 586", "776-440", " 776440 "))
def test_live_internal_code_forms_share_the_import_normalization(raw: str) -> None:
    extracted = extract_listing_internal_codes({"part_numbers": [raw]})

    assert extracted == (normalize_identifier(raw),)
    assert is_internal_catalog_code(raw) is True


def test_join_summary_counts_card_groups_without_choosing_a_first_card() -> None:
    rows = (
        CatalogInternalCodeJoinRow(
            catalog_item_id="item-1",
            source_row=2,
            internal_code_norm="776416",
            listing_ids=("listing-a", "listing-b", "listing-c", "listing-d"),
            store_ids=("store-a", "store-b", "store-c", "store-d"),
            ambiguous_listing_ids=(),
        ),
        CatalogInternalCodeJoinRow(
            catalog_item_id="item-2",
            source_row=3,
            internal_code_norm="776440",
            listing_ids=(),
            store_ids=(),
            ambiguous_listing_ids=("listing-ambiguous",),
        ),
        CatalogInternalCodeJoinRow(
            catalog_item_id="item-3",
            source_row=4,
            internal_code_norm="",
            listing_ids=(),
            store_ids=(),
            ambiguous_listing_ids=(),
        ),
    )

    report = summarize_catalog_internal_code_join(
        rows,
        owned_listing_count=12,
        snapshots_without_part_numbers=5,
        listings_with_one_internal_code=6,
        listings_with_multiple_internal_codes=1,
    )

    assert report.catalog_positions == 3
    assert report.catalog_positions_with_code == 2
    assert report.matched_catalog_positions == 1
    assert report.matched_listing_cards == 4
    assert report.unmatched_catalog_positions == 1
    assert report.ambiguous_catalog_positions == 1
    assert report.rows[0].status == "MATCHED_OWNED_LISTING_GROUP"
    assert report.rows[0].requires_single_card_consumer_stop is True
    assert report.rows[1].status == "AMBIGUOUS_OWNED_LISTING_INTERNAL_CODES"
    assert report.rows[2].status == "CATALOG_INTERNAL_CODE_MISSING"


def test_ambiguous_listing_code_blocks_even_when_a_clear_card_also_exists() -> None:
    row = CatalogInternalCodeJoinRow(
        catalog_item_id="item-overlap",
        source_row=5,
        internal_code_norm="776416",
        listing_ids=("listing-clear",),
        store_ids=("store-a",),
        ambiguous_listing_ids=("listing-with-two-kemp-codes",),
    )

    report = summarize_catalog_internal_code_join(
        (row,),
        owned_listing_count=2,
        snapshots_without_part_numbers=0,
        listings_with_one_internal_code=1,
        listings_with_multiple_internal_codes=1,
    )

    assert report.matched_catalog_positions == 0
    assert report.matched_listing_cards == 0
    assert report.ambiguous_catalog_positions == 1
    assert report.rows[0].status == "AMBIGUOUS_OWNED_LISTING_INTERNAL_CODES"
    assert report.rows[0].requires_single_card_consumer_stop is True


def test_migration_contract_uses_json_not_jsonb_and_keeps_identity_ids_unchanged() -> (
    None
):
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20260809_0050_listing_internal_code_join.py"
    ).read_text(encoding="utf-8")

    assert "CREATE FUNCTION public.marko_listing_internal_code(json)" in migration
    assert "CREATE FUNCTION public.marko_listing_internal_code_count(json)" in migration
    assert "catalog_internal_code_norm" in migration
    assert "catalog_internal_code_count" in migration
    assert "GENERATED ALWAYS AS" in migration
    assert "ix_listings_catalog_internal_code_norm" in migration
    assert "json_typeof" in migration
    assert "raw_data ?" not in migration
    assert "marko_catalog_identity_kind" not in migration
    assert "marko_catalog_identity_value" not in migration
