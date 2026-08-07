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

from decimal import Decimal
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
    site_semantic_conflicts,
    supplier_articles_by_code,
)
from marko.services.offer_identity import (
    ConfirmedCross,
    OeEvidenceSourceKind,
    OeVerificationStatus,
    canonical_cross_identity_key,
    extract_oe_evidence,
    verify_offer_identity,
)
from metis.pricing.identity_graph import (
    DISCARD_UNSAFE_PUBLIC_NUMBER_SHAPE,
    Anomaly,
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


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("037103493AK+037103211", ("037103493AK", "037103211")),
        ("1K0905851 + 1K0905865", ("1K0905851", "1K0905865")),
        (
            "6Q1907521A 6Q1907521B 5HL351321281",
            ("6Q1907521A", "6Q1907521B", "5HL351321281"),
        ),
    ),
)
def test_complete_identifiers_are_never_concatenated(
    raw: str, expected: tuple[str, ...]
) -> None:
    assert article_numbers(raw, own_code="776999", tokens=TOKENS) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("Audi 4F0260403E", ("4F0260403E",)),
        ("Opel 1850062", ("1850062",)),
        ("OE 7E5 827 505 A", ("7E5 827 505 A",)),
    ),
)
def test_editorial_labels_do_not_become_part_of_public_identity(
    raw: str, expected: tuple[str, ...]
) -> None:
    assert article_numbers(raw, own_code="776999", tokens=TOKENS) == expected


def test_our_own_code_inside_an_article_is_not_a_cross() -> None:
    assert article_numbers("77646363", own_code="77646363", tokens=TOKENS) == ()


def test_an_empty_article_yields_nothing() -> None:
    assert article_numbers("   ", own_code="77646363", tokens=TOKENS) == ()


@pytest.mark.parametrize(
    ("raw", "expected"),
    (
        ("1J0959455A/K", ("1J0959455A", "1J0959455K")),
        (
            "1K0959455Q/ET/DH",
            ("1K0959455Q", "1K0959455ET", "1K0959455DH"),
        ),
        ("1K0411105EG/EH", ("1K0411105EG", "1K0411105EH")),
        (
            "8k0407151/152/695/696",
            ("8k0407151", "8K0407152", "8K0407695", "8K0407696"),
        ),
        ("H982/5", ("H982", "H985")),
        ("1618134/142", ("1618134", "1618142")),
        ("KL228/2D", ("KL228", "KL22D")),
        ("331/28235L", ("331/28235L",)),
        ("331/28235R", ("331/28235R",)),
        (
            "811959455B,L,R",
            ("811959455B", "811959455L", "811959455R"),
        ),
        # No existing alphabetic suffix to replace: do not invent one and do
        # not publish the editorial/brand fragment as a global identifier.
        ("251489/MG", ("251489",)),
    ),
)
def test_slash_shorthand_expands_variants_instead_of_global_fragments(
    raw: str,
    expected: tuple[str, ...],
) -> None:
    assert article_numbers(raw, own_code="776999", tokens=TOKENS) == expected


@pytest.mark.parametrize("raw", ("11,2*866", "210*180*25", "650 x 430 mm"))
def test_dimension_only_article_cells_do_not_become_public_numbers(raw: str) -> None:
    assert article_numbers(raw, own_code="776999", tokens=TOKENS) == ()


def test_formatted_private_code_in_reference_article_is_not_a_cross() -> None:
    """The second customer XLS contains this exact spaced shelf code."""

    assert article_numbers("7764 1257", own_code="77646059", tokens=TOKENS) == ()


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


def test_real_xls_revision_identity_conflicts_are_measured_not_superseded(index) -> None:
    """A shared private key cannot make opposite sides/positions one part."""

    assert set(index.semantic_conflicts) == {
        "7764",
        "77643614",
        "77644736",
        "77645658",
        "77647853",
        "77648805",
    }
    assert {
        conflict["dimension"]
        for pair in index.semantic_conflicts["7764"]
        for conflict in pair["conflicts"]
    } == {"part_type", "part_subtype"}
    assert index.semantic_conflicts["77643614"][0]["conflicts"][0]["dimension"] == (
        "side"
    )
    assert {
        conflict["dimension"]
        for conflict in index.semantic_conflicts["77644736"][0]["conflicts"]
    } == {"part_subtype", "assembly_level"}
    assert index.semantic_conflicts["77648805"][0]["conflicts"][0][
        "dimension"
    ] == "position"
    assert {
        conflict["dimension"]
        for conflict in index.semantic_conflicts["77645658"][0]["conflicts"]
    } == {"part_type", "part_subtype"}
    assert {
        conflict["dimension"]
        for conflict in index.semantic_conflicts["77647853"][0]["conflicts"]
    } == {"part_type", "part_subtype", "assembly_level"}


def test_xls_semantic_conflict_cannot_confirm_or_fill_an_identity(index) -> None:
    plan = _plan(index, "77648805")

    assert plan.graph.anomalies == (Anomaly.SOURCE_SEMANTIC_CONFLICT.value,)
    assert plan.links
    assert all(link.validation_status == "REVIEW" for link in plan.links)
    assert all(
        link.anomaly == Anomaly.SOURCE_SEMANTIC_CONFLICT.value
        for link in plan.links
    )
    assert plan.identity_status == "MPN_ONLY"
    assert plan.fill_oe_norm == ""
    details = plan.links[0].validation_details["source_semantic_conflicts"]
    assert details["77648805"][0]["right_title"].startswith(
        "Амортизатор передній"
    )


def test_truncated_private_code_cannot_fuse_three_unrelated_parts(index) -> None:
    plan = _plan(index, "7764")

    assert plan.graph.anomalies == (Anomaly.SOURCE_SEMANTIC_CONFLICT.value,)
    assert {link.extracted_oem_norm for link in plan.links} == {
        "4256911",
        "4353",
        "4473240904",
        "6394230112",
    }
    assert all(link.validation_status == "REVIEW" for link in plan.links)
    assert plan.identity_status == "MPN_ONLY"
    assert plan.fill_oe_norm == ""


def test_structurally_conflicting_public_number_fanout_is_measured(index) -> None:
    # Card-bound KEMP titles are now paired with the exact matching card URL.
    # This preserves the measured 28 real conflicts and avoids false
    # quarantines caused by the last search hit's title leaking into another
    # number.
    assert len(index.semantic_fanout_conflicts) == 28
    assert "8200418329" not in index.semantic_fanout_conflicts
    # The KEMP-site title uses Latin transliteration ("radiator kondicionera")
    # for the same A/C condenser family as the Cyrillic reference title.
    assert "GHR161480B" not in index.semantic_fanout_conflicts
    assert "148" in index.semantic_fanout_conflicts
    assert {
        "025121321B",  # expansion tank versus cap
        "025121403A",  # expansion tank versus cap
        "02G409356B",  # halfshaft repair kit versus complete halfshaft
        "028145278E",  # timing roller versus serpentine tensioner
        "068121132A",  # cooling fan versus coolant sensor flange
        "0A5409343",  # halfshaft flange versus complete drive shaft
        "1H0121321B",  # coolant sensor flange versus expansion tank cap
        "1J1823533B",  # hood-release handle versus its mounting bracket
        "1J0121321B",  # cabin blower versus expansion tank cap
        "443121321",  # cooling fan versus expansion tank cap
        "4F0121403N",  # expansion tank versus cap
        "60613A",  # explicitly with-A/C versus without-A/C radiator
        "6N0905865",  # ignition-lock cylinder versus electrical contact group
        "7M0959455J",  # expansion tank cap versus cooling fan
        "94234",  # timing belt versus A/C condenser
        "DU49847",  # front versus rear wheel bearing
    } <= set(index.semantic_fanout_conflicts)
    assert not {"1", "4", "331", "MG"} & set(index.semantic_fanout_conflicts)
    serviceability = index.semantic_fanout_conflicts["148"][0]
    assert {
        finding["dimension"] for finding in serviceability["conflicts"]
    } == {"serviceability"}
    conflict = index.semantic_fanout_conflicts["1K0905851"][0]
    assert {conflict["left_code"], conflict["right_code"]} == {
        "77649046",
        "77649047",
    }
    assert {
        finding["dimension"] for finding in conflict["conflicts"]
    } == {"part_subtype", "assembly_level"}


def test_current_kemp_card_title_agrees_with_latest_reference(index) -> None:
    """The retained Camry card must not be quarantined by wording drift."""

    assert "77648791" not in index.semantic_conflicts


def test_kemp_card_title_conflict_quarantines_private_join(tmp_path) -> None:
    """A card bound to the private code cannot silently change its part family."""

    path = tmp_path / "site.csv"
    path.write_text(
        "mpn,number_raw,token_class,source_url,source_title\n"
        "77648791,ZZ9999,OE_CANDIDATE,"
        "https://kemp.ua/index.php?route=product/product&product_id=42&search=77648791,"
        "Контактна група замка запалювання Toyota Camry V40\n",
        encoding="utf-8",
    )
    site, _ = load_site_source(path)
    conflicts = site_semantic_conflicts(
        [
            load_reference_edition(V1_PATH, config=CONFIG),
            load_reference_edition(V2_PATH, config=CONFIG),
        ],
        site,
        config=CONFIG,
    )

    assert "77648791" in conflicts
    finding = conflicts["77648791"][0]
    assert finding["right_source"] == SITE_SOURCE
    assert {
        item["dimension"] for item in finding["conflicts"]
    } >= {"part_type", "part_subtype"}


@pytest.mark.parametrize(
    ("code", "unsafe_raw", "remaining_number"),
    (
        ("77643994", "0", "251201551C"),
        ("77644989", "Fiat/Alfa/Lancia", "46737733"),
    ),
)
def test_real_editorial_fragments_never_enter_the_public_identity_graph(
    index,
    code: str,
    unsafe_raw: str,
    remaining_number: str,
) -> None:
    plan = _plan(index, code)

    assert plan.graph.all_numbers == (remaining_number,)
    assert (
        plan.graph.discarded[unsafe_raw]
        == DISCARD_UNSAFE_PUBLIC_NUMBER_SHAPE
    )


@pytest.mark.parametrize("code", ("77649046", "77649047"))
def test_canonical_only_public_fanout_cannot_confirm_or_fill_oe(index, code) -> None:
    plan = _plan(index, code)

    assert plan.graph.canonical == "1K0905851"
    assert plan.graph.links == ()
    assert plan.graph.anomalies == (
        Anomaly.PUBLIC_NUMBER_SEMANTIC_FANOUT.value,
    )
    assert plan.identity_status == "MPN_ONLY"
    assert plan.fill_oe_norm == ""


# ------------------------------------------------------- what the site may say


def test_only_oe_candidates_come_off_the_site() -> None:
    numbers, not_an_oe = load_site_source(SITE_PATH)

    # Counts of the shipped dataset, extended on 2026-08-07 from the
    # article-brand heuristic to every identity-blocked code (539 -> 832 codes
    # carrying a candidate).  The point of the assertion is the split: only
    # OE_CANDIDATE tokens reach the graph, and the other three classes are
    # counted and discarded rather than quietly admitted.
    assert not_an_oe == 2340  # KNOWN_ARTICLE + INTERNAL_CODE + AFTERMARKET_CROSS
    assert len(numbers) == 832


def test_site_card_context_survives_on_a_reference_preferred_edge(index) -> None:
    """The canonical reference article must not hide the KEMP card evidence."""

    plan = _plan(index, "77648791")

    # The source files contain a KEMP article and an unlabelled KEMP-site SKU,
    # but no independent OE-asserting source for 4853089025.  It remains a
    # confirmed cross for discovery while the catalog OE stays unfilled.
    assert plan.identity_status == "MPN_ONLY"
    assert plan.fill_oe_norm == ""
    assert plan.links[0].validation_status == "CONFIRMED"
    details = plan.links[0].validation_details
    site_context = details["source_contexts"][SITE_SOURCE]
    assert "Амортизатор задній правий" in site_context
    assert "search=77648791" in site_context
    assert "image=https://kemp.ua/" in site_context


def test_non_oe_article_cannot_promote_site_number_to_catalog_oe(index) -> None:
    """A cross-list agreement is not an OE corroboration."""

    plan = _plan(index, "77648791")

    assert plan.identity_reason == "ONLY_CROSS_LIST_NUMBERS"
    assert all(
        link.extracted_oem_norm != "4853089025"
        or link.validation_status == "CONFIRMED"
        for link in plan.links
    )
    # No source row with asserts_oe=True names this number, so it cannot be
    # copied into CatalogItem.oe_norm despite the KEMP_SITE + article match.
    assert plan.fill_oe_raw == ""


def test_site_card_title_is_preserved_with_its_url(tmp_path) -> None:
    path = tmp_path / "site.csv"
    path.write_text(
        "mpn,number_raw,token_class,source_url,source_title\n"
        "77649999,123456,OE_CANDIDATE,"
        "https://kemp.ua/index.php?route=product/product&product_id=42&search=77649999,"
        "Амортизатор задній правий Toyota Camry V40\n",
        encoding="utf-8",
    )

    numbers, _ = load_site_source(path)

    assert numbers["77649999"].raw_context == (
        "Амортизатор задній правий Toyota Camry V40 | "
        "https://kemp.ua/index.php?route=product/product&product_id=42&search=77649999"
    )


def test_site_card_image_is_preserved_only_as_bound_review_context(tmp_path) -> None:
    path = tmp_path / "site.csv"
    path.write_text(
        "mpn,number_raw,token_class,source_url,source_title,source_image_url\n"
        "77649999,123456,OE_CANDIDATE,"
        "https://kemp.ua/index.php?route=product/product&product_id=42&search=77649999,"
        "Амортизатор задній правий Toyota Camry V40,"
        "https://kemp.ua/image/catalog/camry.jpg\n",
        encoding="utf-8",
    )

    numbers, _ = load_site_source(path)

    assert numbers["77649999"].raw_context.endswith(
        "image=https://kemp.ua/image/catalog/camry.jpg"
    )


def test_structured_product_binding_is_retained_as_non_monetary_context(tmp_path) -> None:
    path = tmp_path / "site.csv"
    path.write_text(
        "mpn,number_raw,token_class,source_url,source_title,structured_status,"
        "structured_name,structured_mpn,structured_image_url\n"
        "77649999,123456,OE_CANDIDATE,"
        "https://kemp.ua/index.php?route=product/product&product_id=42&search=77649999,"
        "Видимый заголовок,PRODUCT_MATCH,Структурированный заголовок,77649999,"
        "https://kemp.ua/image/catalog/camry.jpg\n",
        encoding="utf-8",
    )

    numbers, _ = load_site_source(path)

    context = numbers["77649999"].raw_context
    assert context.startswith("Структурированный заголовок |")
    assert "visible_title=Видимый заголовок" in context
    assert "structured_mpn_status=PRODUCT_MATCH" in context
    assert "structured_image=https://kemp.ua/image/catalog/camry.jpg" in context


def test_structured_product_mpn_mismatch_is_refused(tmp_path) -> None:
    path = tmp_path / "site.csv"
    path.write_text(
        "mpn,number_raw,token_class,source_url,structured_status,structured_mpn\n"
        "77649999,123456,OE_CANDIDATE,"
        "https://kemp.ua/index.php?route=product/product&product_id=42&search=77649999,"
        "MPN_MISMATCH,77640000\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogIdentityReparseError, match="structured Product.mpn"):
        load_site_source(path)


@pytest.mark.parametrize(
    "url",
    [
        "https://attacker.example/kemp-part?search=77649999",
        "http://kemp.ua/kemp-part-77649999?search=77649999",
        "https://kemp.ua/kemp-part-77649999?search=77640000",
        "https://kemp.ua/index.php?route=product/search&search=77649999",
    ],
)
def test_site_source_rejects_unbound_or_non_product_urls(tmp_path, url) -> None:
    path = tmp_path / "site.csv"
    path.write_text(
        "mpn,number_raw,token_class,source_url\n"
        f"77649999,123456,OE_CANDIDATE,{url}\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogIdentityReparseError, match="untrusted|unbound"):
        load_site_source(path)


def test_site_source_rejects_untrusted_image_url(tmp_path) -> None:
    path = tmp_path / "site.csv"
    path.write_text(
        "mpn,number_raw,token_class,source_url,source_image_url\n"
        "77649999,123456,OE_CANDIDATE,"
        "https://kemp.ua/index.php?route=product/product&product_id=42&search=77649999,"
        "https://attacker.example/camry.jpg\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogIdentityReparseError, match="source_image_url"):
        load_site_source(path)


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


def test_private_code_in_characteristics_is_join_key_not_cross(index) -> None:
    """The current export carries the reference-book key beside the public OE.

    This is the dominant live shape: treating ``776415`` as a cross created
    3,374 false CONFIRMED edges and failed to consult the two reference books.
    """

    plan = _plan(index, "1086282", part_numbers=["776415"])

    assert plan.internal_catalog_codes == ("776415",)
    assert plan.reference_lookup_codes == ("1086282", "776415")
    assert "776415" not in plan.graph.all_numbers
    assert plan.identity_status == "OE_CONFIRMED"
    assert plan.graph.canonical == "1086282"


def test_private_join_key_recovers_reference_crosses_without_leaking(index) -> None:
    plan = _plan(index, "PUBLIC-SEED", part_numbers=["77641229"])

    assert plan.internal_catalog_codes == ("77641229",)
    assert "77641229" not in plan.graph.all_numbers
    assert "27C06F" in plan.graph.all_numbers


def test_real_customer_xls_cross_reaches_candidate_identity_boundary(index) -> None:
    """The shipped customer files must improve live positive recall, not only parse.

    The imported row searches by the public KEMP/Elring number ``863130`` and
    carries private shelf code ``77646363`` in its characteristics.  The newer
    customer XLS maps that shelf code to supplier article ``0209.0F``.  This is
    the exact catalog shape used by pricing; exercising only the private code
    would miss a broken join between import, identity graph and offer matching.
    """

    plan = _plan(
        index,
        "863130",
        part_numbers=["77646363"],
        current_oe="863130",
    )
    link = next(
        item for item in plan.links if item.extracted_oem_norm == "02090F"
    )

    assert link.our_oem_norm == "863130"
    assert link.validation_status == "CONFIRMED"
    assert link.anomaly is None
    assert link.extraction_method == REFERENCE_ARTICLE_SOURCE
    assert link.validation_details["automatic_eligible"] is True
    assert "77646363" not in plan.graph.all_numbers

    cross = ConfirmedCross(
        search_oe_norm=link.our_oem_norm,
        candidate_oe_norm=link.extracted_oem_norm,
        canonical_identity_key=canonical_cross_identity_key(
            link.our_oem_norm,
            link.extracted_oem_norm,
        ),
        confidence=Decimal(str(link.validation_details["confidence"])),
        cross_link_id="customer-xls-regression",
    )
    evidence = extract_oe_evidence(
        {"oe_raw": "0209.0F"},
        {
            "source_record_id": "prom-detail-02090f",
            "raw_capture_id": "capture-02090f",
            "raw_content_sha256": "a" * 64,
        },
    )
    result = verify_offer_identity("863130", evidence, (cross,))

    assert evidence[0].source_kind is OeEvidenceSourceKind.STRUCTURED_OE_FIELD
    assert result.status is OeVerificationStatus.VERIFIED_CROSS
    assert result.verified_matched_oe_norm == "02090F"
    assert result.comparison_identity_key == "XREF:02090F|863130"


def test_multiple_private_codes_are_discarded_without_guessing_a_join(index) -> None:
    plan = _plan(
        index,
        "PUBLIC-1-SEED",
        part_numbers=["776415", "776422"],
    )

    assert plan.internal_catalog_codes == ("776415", "776422")
    assert plan.reference_lookup_codes == ("PUBLIC1SEED",)
    assert "776415" not in plan.graph.all_numbers
    assert "776422" not in plan.graph.all_numbers
    assert plan.graph.all_numbers == ("PUBLIC1SEED",)


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
        assert link.validation_details["confidence"] == (
            "0.90" if link.validation_status == "CONFIRMED" else "0"
        )
        assert link.validation_details["automatic_eligible"] is (
            link.validation_status == "CONFIRMED"
        )


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


def test_existing_public_number_is_not_replaced_even_when_it_is_the_lookup_code(
    index,
) -> None:
    """Production passes the same imported field as lookup and current OE.

    Equality between those arguments is not evidence that the field is a shelf
    code.  Only the explicit private-code classifier may authorise replacement.
    """

    plan = _plan(index, "056121113D", current_oe="056121113D")

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
    path.write_text(
        "name,mpn,make,article,article_brand\nx,776001,KEMP,ABC,VAG\n", "utf-8"
    )

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
