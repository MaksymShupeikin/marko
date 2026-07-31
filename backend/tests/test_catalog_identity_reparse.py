"""Seeding the identity graph from the shipped files (WP-6).

The table has been empty since WP-3 created it, so this is the first code that
decides what actually goes into it, and the tests that matter are the ones about
what it refuses to put there.

The reference files are used as shipped rather than mocked. Fabricated rows
would prove the code runs; the real files are what proves it is right, and two
of the checks below exist only because the real files disagreed with the first
version of this module.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from marko.services.catalog_identity_reparse import (
    OWN_EXPORT_CODE_SOURCE,
    OWN_EXPORT_SOURCE,
    REFERENCE_ARTICLE_SOURCE,
    SITE_SOURCE,
    CatalogIdentityReparseError,
    SourceIndex,
    article_numbers,
    build_source_index,
    load_reference_edition,
    load_site_source,
    plan_identity,
    supplier_articles_by_code,
)
from metis.pricing.identity_graph import (
    IdentityGraphConfigError,
    SourceNumbers,
    load_identity_graph_config,
)
from metis.pricing.kemp_reference import load_article_brand_kinds
from metis.pricing.kemp_site import load_kemp_site_tokens

BACKEND = Path(__file__).resolve().parents[1]
V1_PATH = BACKEND / "data/kemp_reference_map.csv"
V2_PATH = BACKEND / "data/kemp_oe_map.csv"
SITE_PATH = BACKEND / "data/kemp_site_numbers.csv"

CONFIG = load_identity_graph_config(BACKEND / "config/identity_graph.yaml")
KINDS = load_article_brand_kinds(BACKEND / "config/article_brand_kinds.yaml")
TOKENS = load_kemp_site_tokens(BACKEND / "config/kemp_site_tokens.yaml")


@pytest.fixture(scope="module")
def index() -> SourceIndex:
    return build_source_index(
        config=CONFIG,
        kinds=KINDS,
        tokens=TOKENS,
        reference_paths=[V1_PATH, V2_PATH],
        site_path=SITE_PATH,
    )


def _plan(index: SourceIndex, code: str, *, part_numbers=(), current_oe=""):
    return plan_identity(
        own_code=code,
        code_raw=code,
        part_numbers_raw=list(part_numbers),
        current_oe_norm=current_oe,
        index=index,
        config=CONFIG,
        tokens=TOKENS,
    )


def _numbers_from(index: SourceIndex, code: str, source: str) -> tuple[str, ...]:
    return tuple(
        number
        for entry in index.by_code.get(code, ())
        if entry.extraction_method == source
        for number in entry.numbers
    )


# ------------------------------------------------------- splitting the article


def test_an_article_cell_holding_two_numbers_becomes_two_numbers() -> None:
    """``61339502002090F`` is a string no seller has ever listed anything under."""

    assert article_numbers(
        "61-33950-20/0209.0F", own_code="77646363", tokens=TOKENS
    ) == ("61-33950-20", "0209.0F")


def test_our_own_code_inside_an_article_is_not_a_cross() -> None:
    assert article_numbers("77646363", own_code="77646363", tokens=TOKENS) == ()


def test_an_empty_article_yields_nothing() -> None:
    assert article_numbers("   ", own_code="77646363", tokens=TOKENS) == ()


# --------------------------------------------- the supplier-number cross-check


def test_the_older_edition_names_the_brands_the_newer_one_omits() -> None:
    editions = [
        load_reference_edition(V1_PATH, config=CONFIG),
        load_reference_edition(V2_PATH, config=CONFIG),
    ]

    supplier = supplier_articles_by_code(editions, KINDS)

    # Elring is a gasket maker, so 863.130 is its own number and not Fiat's.
    assert "863130" in supplier["77646363"]


def test_an_elring_number_is_not_offered_as_this_parts_oe(index) -> None:
    """The newer file states ``863130`` in a column literally headed OE.

    It is still an Elring catalogue number. Writing it into the row's OE would
    repeat, through the one door WP-2 does not watch, exactly the mistake WP-2
    was written to stop.
    """

    for source in ("KEMP_REFERENCE_MAP_V1", "KEMP_REFERENCE_MAP_V2"):
        assert "863130" not in _numbers_from(index, "77646363", source)


def test_the_refused_number_is_still_kept_as_a_cross(index) -> None:
    """Refusing to call it an OE is not the same as throwing it away.

    A competitor selling this gasket may well list it under the Elring number,
    which is precisely what widens an identity at the gate.
    """

    assert "863.130" in _numbers_from(index, "77646363", REFERENCE_ARTICLE_SOURCE)


def test_a_carmaker_number_is_offered_as_an_oe(index) -> None:
    plan = _plan(index, "77641360")

    assert plan.identity_status == "OE_CONFIRMED"
    assert plan.fill_oe_norm == "31211128157"


def test_refusals_are_counted_rather_than_silent(index) -> None:
    """A silent refusal at this scale is indistinguishable from a coverage drop."""

    assert index.supplier_number_claims == 456


# ------------------------------------------------------- what the site may say


def test_only_oe_candidates_come_off_the_site() -> None:
    numbers, not_an_oe = load_site_source(SITE_PATH)

    assert not_an_oe == 1810  # KNOWN_ARTICLE + INTERNAL_CODE + AFTERMARKET_CROSS
    assert len(numbers) == 540


def test_a_site_only_number_does_not_confirm_an_oe(index) -> None:
    """kemp.ua is declared REVIEW because its field labels are unreliable.

    A review status that still writes the OE column is not a review status.
    """

    plan = _plan(index, "77642116")

    assert plan.identity_status != "OE_CONFIRMED"
    assert plan.fill_oe_norm == ""


# -------------------------------------------------------------- the item plan


def test_the_own_export_cross_list_never_claims_an_oe(index) -> None:
    """``776999`` is a shelf number, so the crosses are all this row has."""

    plan = _plan(index, "776999", part_numbers=["1K0413031BK", "27C06F"])

    assert plan.graph.canonical == "1K0413031BK"
    assert plan.identity_status == "MPN_ONLY"
    assert plan.identity_reason == "ONLY_CROSS_LIST_NUMBERS"
    assert plan.fill_oe_norm == ""


def test_a_shelf_number_is_discarded_but_a_part_number_is_not(index) -> None:
    """The distinction the live catalogue forced, measured 2026-07-31.

    554 rows carry ``776*`` in the code column and 4093 carry a real number.
    Treating the second kind as a self reference would delete from the graph the
    one number the candidate gate looks the position up by — for 88% of rows.
    """

    shelf = _plan(index, "776999", part_numbers=["1K0413031BK"])
    real = _plan(index, "056121113D", part_numbers=["1K0413031BK"])

    assert "776999" not in shelf.graph.all_numbers
    # And it becomes the anchor, so every edge starts at the number the gate
    # searches by instead of running between two crosses beside it.
    assert real.graph.canonical == "056121113D"
    assert real.graph.canonical_source == OWN_EXPORT_CODE_SOURCE
    assert [link.extracted_oem_norm for link in real.links] == ["1K0413031BK"]


def test_the_code_column_never_claims_an_oe_either(index) -> None:
    """It is headed "код товару", and we have measured what it actually holds."""

    plan = _plan(index, "056121113D", part_numbers=["1K0413031BK"])

    assert plan.identity_status == "MPN_ONLY"
    assert plan.fill_oe_norm == ""


def test_a_row_with_no_evidence_stays_unresolved(index) -> None:
    plan = _plan(index, "776999")

    assert plan.identity_status == "UNRESOLVED"
    assert plan.identity_reason is None
    assert plan.links == ()


def test_every_planned_link_carries_the_text_it_came_from(index) -> None:
    plan = _plan(index, "77646363")

    assert plan.links
    for link in plan.links:
        assert link.raw_context
        assert link.extracted_raw
        assert link.validation_status in {"CONFIRMED", "REVIEW"}
        assert link.our_oem_norm != link.extracted_oem_norm


def test_the_plan_is_the_same_on_two_runs(index) -> None:
    """A dry run is only a truthful preview if the computation is reproducible."""

    first = _plan(index, "77646363")
    second = _plan(index, "77646363")

    assert first.links == second.links
    assert first.graph.canonical == second.graph.canonical


# --------------------------------------------------- filling the OE column


def test_an_imported_oe_is_never_overwritten(index) -> None:
    """It may be wrong, but it came from the customer's own export."""

    plan = _plan(index, "77641360", current_oe="SOMETHINGELSE")

    assert plan.fill_oe_norm == ""


def test_an_oe_column_holding_our_own_code_is_the_defect_and_is_filled(index) -> None:
    """The whole arc started here: the OE living in the code column."""

    plan = _plan(index, "77641360", current_oe="77641360")

    assert plan.fill_oe_norm == "31211128157"


def test_nothing_is_filled_without_an_asserting_source(index) -> None:
    plan = _plan(index, "776999", part_numbers=["1K0413031BK"])

    assert plan.fill_oe_raw == ""
    assert plan.fill_oe_norm == ""


# ------------------------------------------------------------ refusing to load


def test_the_same_edition_twice_is_refused() -> None:
    with pytest.raises(CatalogIdentityReparseError, match="supplied twice"):
        build_source_index(
            config=CONFIG,
            kinds=KINDS,
            tokens=TOKENS,
            reference_paths=[V1_PATH, V1_PATH],
        )


def test_an_undeclared_reference_file_is_refused(tmp_path) -> None:
    """A file renamed to look like the checked one must not inherit its standing."""

    path = tmp_path / "map.csv"
    path.write_text("name,mpn,make,article,article_brand\nx,776001,KEMP,ABC,VAG\n", "utf-8")

    with pytest.raises(IdentityGraphConfigError, match="No declared dataset"):
        load_reference_edition(path, config=CONFIG)


def test_a_missing_site_file_is_refused(tmp_path) -> None:
    with pytest.raises(CatalogIdentityReparseError, match="do not exist"):
        load_site_source(tmp_path / "absent.csv")


# ------------------------------------------------------- the shape of the index


def test_the_index_reports_every_source_it_actually_used(index) -> None:
    assert set(index.loaded_sources) == {
        "KEMP_REFERENCE_MAP_V1",
        "KEMP_REFERENCE_MAP_V2",
        REFERENCE_ARTICLE_SOURCE,
        SITE_SOURCE,
    }


def test_rows_the_files_could_not_join_are_reported(index) -> None:
    assert index.rows_without_code == 484


def test_an_index_without_the_site_still_works() -> None:
    index = build_source_index(
        config=CONFIG,
        kinds=KINDS,
        tokens=TOKENS,
        reference_paths=[V2_PATH],
    )

    assert SITE_SOURCE not in index.loaded_sources
    assert index.by_code


def test_own_export_numbers_are_attributed_to_their_own_source(index) -> None:
    plan = _plan(index, "776999", part_numbers=["1K0413031BK", "27C06F"])

    assert {link.extraction_method for link in plan.links} == {OWN_EXPORT_SOURCE}


def test_a_source_numbers_entry_is_what_the_graph_receives() -> None:
    """Guards the contract between this module and ``build_identity_graph``."""

    entry = SourceNumbers(
        extraction_method=OWN_EXPORT_SOURCE, numbers=("A1",), raw_context="ctx"
    )

    assert entry.extraction_method in CONFIG.sources
