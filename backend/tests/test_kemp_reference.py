"""Splitting OE from MPN in the KEMP reference map (WP-2).

The rule under test is the one the catalogue got wrong before: an article is an
OE only when the brand beside it is a vehicle maker, and never by default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metis.pricing.kemp_reference import (
    ARTICLE_BRAND_KINDS_SCHEMA_VERSION,
    BrandKind,
    IdentityReason,
    IdentityStatus,
    KempReferenceError,
    ReferenceRow,
    load_article_brand_kinds,
    load_kemp_reference_map,
    normalize_brand_value,
    resolve_all,
    resolve_identity,
    unknown_brand_values,
    validation_details,
)
from metis.pricing.kemp_site import load_kemp_site_tokens

BACKEND = Path(__file__).resolve().parents[1]
KINDS_PATH = BACKEND / "config/article_brand_kinds.yaml"
REFERENCE_PATH = BACKEND / "data/kemp_reference_map.csv"
OE_MAP_PATH = BACKEND / "data/kemp_oe_map.csv"
TOKENS = load_kemp_site_tokens(BACKEND / "config/kemp_site_tokens.yaml")


@pytest.fixture(scope="module")
def kinds():
    return load_article_brand_kinds(KINDS_PATH)


@pytest.fixture(scope="module")
def reference():
    return load_kemp_reference_map(REFERENCE_PATH)


def _row(**overrides) -> ReferenceRow:
    base = {
        "name": "Амортизатор",
        "mpn": "77641229",
        "make": "KEMP",
        "article": "1K0413031BK",
        "article_brand": "VAG",
    }
    return ReferenceRow(**{**base, **overrides})


def _resolve(row: ReferenceRow, kinds):
    return resolve_identity(row, kinds=kinds, tokens=TOKENS)


@pytest.fixture(scope="module")
def oe_map():
    return load_kemp_reference_map(OE_MAP_PATH)


# --- the dictionary ---------------------------------------------------------


def test_every_brand_value_in_the_shipped_map_is_classified(reference, kinds) -> None:
    """The contract of the pair of files: no value left to guesswork."""

    assert unknown_brand_values(reference, kinds) == ()


def test_the_dictionary_covers_all_101_observed_values(reference, kinds) -> None:
    observed = {
        row.article_brand.strip() for row in reference.rows if row.article_brand.strip()
    }

    assert len(observed) == 100  # 101 distinct cells, one of them empty
    assert all(kinds.kind_of(value) is not BrandKind.UNKNOWN for value in observed)


@pytest.mark.parametrize(
    "brand, kind",
    [
        ("VAG", BrandKind.VEHICLE_MANUFACTURER),
        ("Peugeot/Citroen", BrandKind.VEHICLE_MANUFACTURER),
        ("Evobus/Setra", BrandKind.VEHICLE_MANUFACTURER),
        ("Sachs", BrandKind.AFTERMARKET),
        ("SKF", BrandKind.AFTERMARKET),
        ("Kayaba", BrandKind.AFTERMARKET),
        ("China", BrandKind.NOT_A_BRAND),
    ],
)
def test_named_brands_land_in_their_measured_class(brand, kind, kinds) -> None:
    assert kinds.kind_of(brand) is kind


def test_conveyor_suppliers_are_still_aftermarket(kinds) -> None:
    """SKF, FAG, INA and LUK do supply assembly lines, but their own number is
    not the vehicle maker's number, and only the latter is an OE."""

    for brand in ("SKF", "FAG", "INA", "LUK", "Kolbenschmidt", "Bosch"):
        assert kinds.kind_of(brand) is BrandKind.AFTERMARKET


def test_an_unlisted_brand_is_unknown_rather_than_assumed(kinds) -> None:
    assert (
        kinds.kind_of("Some Supplier That Did Not Exist Yesterday") is BrandKind.UNKNOWN
    )


def test_lookup_ignores_case_and_surrounding_whitespace(kinds) -> None:
    assert kinds.kind_of("  vag ") is BrandKind.VEHICLE_MANUFACTURER
    assert kinds.kind_of("MAHLE ORIGINAL") is BrandKind.AFTERMARKET
    assert kinds.kind_of("Victor  Reinz") is BrandKind.AFTERMARKET


def test_spacing_around_punctuation_is_not_folded(kinds) -> None:
    """Documenting the limit rather than inventing a rule: no export has been
    seen writing ``GKN - Spidan``, and if one appears the value reads UNKNOWN,
    which closes the position instead of mis-typing it."""

    assert kinds.kind_of("GKN - Spidan") is BrandKind.UNKNOWN


def test_punctuation_is_kept_because_it_separates_suppliers() -> None:
    """``K+F`` and ``K&K`` are two companies; folding punctuation merges them."""

    assert normalize_brand_value("K+F") != normalize_brand_value("K&K")


def test_empty_brand_is_unknown_not_an_error(kinds) -> None:
    assert kinds.kind_of("") is BrandKind.UNKNOWN
    assert kinds.kind_of(None) is BrandKind.UNKNOWN


def test_dictionary_is_hashed_for_the_audit_trail(kinds) -> None:
    assert len(kinds.source_sha256) == 64
    assert kinds.method_version == "article-brand-kinds-v1"


# --- fail-closed loading ----------------------------------------------------


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "kinds.yaml"
    path.write_text(body, encoding="utf-8")
    return path


VALID_TAIL = """
method_version: t
vehicle_manufacturer:
  - name: "VAG"
aftermarket:
  - name: "Sachs"
not_a_brand:
  - name: "China"
"""


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(KempReferenceError):
        load_article_brand_kinds(tmp_path / "absent.yaml")


def test_unknown_schema_version_raises(tmp_path) -> None:
    path = _write(tmp_path, "schema_version: something-else" + VALID_TAIL)

    with pytest.raises(KempReferenceError):
        load_article_brand_kinds(path)


def test_broken_yaml_raises(tmp_path) -> None:
    with pytest.raises(KempReferenceError):
        load_article_brand_kinds(_write(tmp_path, "schema_version: [unclosed"))


def test_missing_section_raises(tmp_path) -> None:
    path = _write(
        tmp_path,
        f"schema_version: {ARTICLE_BRAND_KINDS_SCHEMA_VERSION}\nmethod_version: t\n"
        'vehicle_manufacturer:\n  - name: "VAG"\naftermarket:\n  - name: "Sachs"\n',
    )

    with pytest.raises(KempReferenceError):
        load_article_brand_kinds(path)


def test_a_brand_classified_twice_raises(tmp_path) -> None:
    """One of the two entries is wrong about whether that brand's numbers are
    OEs; picking either silently would decide it by file order."""

    path = _write(
        tmp_path,
        f"schema_version: {ARTICLE_BRAND_KINDS_SCHEMA_VERSION}\nmethod_version: t\n"
        'vehicle_manufacturer:\n  - name: "VAG"\n'
        'aftermarket:\n  - name: "Sachs"\n  - name: "vag"\n'
        'not_a_brand:\n  - name: "China"\n',
    )

    with pytest.raises(KempReferenceError, match="classified twice"):
        load_article_brand_kinds(path)


def test_reference_map_without_a_join_key_raises(tmp_path) -> None:
    path = tmp_path / "map.csv"
    path.write_text("name,article_brand\nfoo,VAG\n", encoding="utf-8")

    with pytest.raises(KempReferenceError, match="missing columns"):
        load_kemp_reference_map(path)


def test_reference_map_carrying_no_identity_evidence_raises(tmp_path) -> None:
    """Neither the article's brand nor an OE column: reading such a file would
    produce thousands of MPN_ONLY rows that look like decisions and are not."""

    path = tmp_path / "map.csv"
    path.write_text("name,mpn,article\nfoo,77640001,ABC123\n", encoding="utf-8")

    with pytest.raises(KempReferenceError, match="no identity evidence"):
        load_kemp_reference_map(path)


# --- the split --------------------------------------------------------------


def test_vehicle_maker_article_becomes_an_oe(kinds) -> None:
    identity = _resolve(_row(article="1K0413031BK", article_brand="VAG"), kinds)

    assert identity.identity_status is IdentityStatus.OE_CONFIRMED
    assert identity.reason is IdentityReason.BRAND_IS_VEHICLE_MANUFACTURER
    assert identity.oe_raw == "1K0413031BK"
    assert identity.oe_norm == "1K0413031BK"
    assert identity.mpn_norm == ""


def test_supplier_article_becomes_an_mpn_and_never_an_oe(kinds) -> None:
    identity = _resolve(_row(article="313856", article_brand="Sachs"), kinds)

    assert identity.identity_status is IdentityStatus.MPN_ONLY
    assert identity.mpn_norm == "313856"
    assert identity.oe_norm == ""
    assert identity.has_oe is False


def test_unknown_brand_closes_the_position_instead_of_guessing(kinds) -> None:
    identity = _resolve(_row(article="606554", article_brand="未知"), kinds)

    assert identity.identity_status is IdentityStatus.MPN_ONLY
    assert identity.reason is IdentityReason.BRAND_UNKNOWN
    assert identity.oe_norm == ""


def test_country_of_origin_does_not_make_a_number_an_oe(kinds) -> None:
    identity = _resolve(_row(article="123456", article_brand="China"), kinds)

    assert identity.reason is IdentityReason.BRAND_NOT_A_BRAND
    assert identity.oe_norm == ""


def test_empty_article_gives_mpn_only_even_under_a_vehicle_brand(kinds) -> None:
    """The brand describes an article that is not in the cell. Eight such rows
    exist in the map; trusting the brand would invent eight OEs."""

    identity = _resolve(_row(article="", article_brand="VAG"), kinds)

    assert identity.identity_status is IdentityStatus.MPN_ONLY
    assert identity.reason is IdentityReason.ARTICLE_EMPTY
    assert identity.oe_norm == ""
    assert identity.mpn_norm == ""


def test_article_repeating_the_internal_code_is_not_an_oe(kinds) -> None:
    """Row 77641853 of the map literally repeats our own warehouse code in the
    article column. That code is ours, not Opel's."""

    identity = _resolve(
        _row(mpn="77641853", article="77641853", article_brand="General Motors"), kinds
    )

    assert identity.reason is IdentityReason.ARTICLE_IS_INTERNAL_CODE
    assert identity.oe_norm == ""


def test_any_internal_code_shape_is_refused_not_only_our_own_row(kinds) -> None:
    identity = _resolve(
        _row(mpn="77641229", article="77642269", article_brand="VAG"), kinds
    )

    assert identity.reason is IdentityReason.ARTICLE_IS_INTERNAL_CODE


def test_spacing_inside_a_number_does_not_hide_a_self_reference(kinds) -> None:
    """``115 070`` and ``115070`` are one number (WP-1); so are these."""

    identity = _resolve(
        _row(mpn="77641853", article="776 41853", article_brand="VAG"), kinds
    )

    assert identity.reason is IdentityReason.ARTICLE_IS_INTERNAL_CODE


def test_oe_is_normalized_with_the_shared_cross_normalizer(kinds) -> None:
    """One normalizer, or the seeded graph and the read side miss each other."""

    identity = _resolve(_row(article="6455.EE", article_brand="Peugeot/Citroen"), kinds)

    assert identity.oe_raw == "6455.EE"
    assert identity.oe_norm == "6455EE"


# --- the whole shipped dataset ----------------------------------------------


def test_the_shipped_map_resolves_as_measured(reference, kinds) -> None:
    """Numbers from the 2026-07-29 measurement, on sha256 54687209…"""

    resolved = resolve_all(reference, kinds=kinds, tokens=TOKENS)
    reasons = {reason: 0 for reason in IdentityReason}
    for identity in resolved:
        reasons[identity.reason] += 1

    assert len(resolved) == 4646
    assert reasons[IdentityReason.ARTICLE_EMPTY] == 8
    assert reasons[IdentityReason.ARTICLE_IS_INTERNAL_CODE] == 3
    assert reasons[IdentityReason.BRAND_IS_VEHICLE_MANUFACTURER] == 3250
    assert sum(1 for identity in resolved if identity.has_oe) == 3250


def test_no_position_carries_both_an_oe_and_an_mpn(reference, kinds) -> None:
    """The two fields answer different questions and a row fills exactly one."""

    for identity in resolve_all(reference, kinds=kinds, tokens=TOKENS):
        assert not (identity.oe_norm and identity.mpn_norm)


def test_the_dataset_is_identified_by_its_own_hash(reference) -> None:
    assert reference.source_sha256 == (
        "54687209e28a4fc30b42daefdc196b3222ac1dc16dfd705d9807dac52537bbd7"
    )
    assert reference.dataset_id == "kemp_reference_map:54687209e28a4fc3"


def test_validation_details_carry_both_hashes(reference, kinds) -> None:
    identity = _resolve(_row(), kinds)

    details = validation_details(
        identity,
        reference=reference,
        kinds=kinds,
        extraction_method="KEMP_REFERENCE_MAP_V1",
    )

    assert details["extraction_method"] == "KEMP_REFERENCE_MAP_V1"
    assert details["reference_map_sha256"] == reference.source_sha256
    assert details["article_brand_kinds_sha256"] == kinds.source_sha256
    assert details["identity_reason"] == "BRAND_IS_VEHICLE_MANUFACTURER"


def test_validation_details_refuse_a_method_from_another_source(
    reference, kinds
) -> None:
    """A link is permanent; the wrong edition stamped on it outlives the run."""

    identity = _resolve(_row(), kinds)

    with pytest.raises(KempReferenceError, match="not a reference-map source"):
        validation_details(
            identity,
            reference=reference,
            kinds=kinds,
            extraction_method="KEMP_SITE",
        )


# --- the 2026-07-29 layout, which states the OE outright --------------------


def _v2(**overrides) -> ReferenceRow:
    """A row of the newer export: an OE column, no article brand."""

    base = {
        "name": "Маточина колеса передня BMW 3 E30",
        "mpn": "77641360",
        "make": "KEMP",
        "article": "561948-AEZ72",
        "oe": "31211128157",
    }
    return ReferenceRow(**{**base, **overrides})


def test_the_oe_column_is_used_when_it_holds_an_oe(kinds) -> None:
    identity = _resolve(_v2(), kinds)

    assert identity.identity_status is IdentityStatus.OE_CONFIRMED
    assert identity.reason is IdentityReason.OE_COLUMN
    assert identity.oe_norm == "31211128157"


def test_the_oe_column_also_carries_the_article_as_an_mpn(kinds) -> None:
    """Unlike the older layout, this one can state both numbers at once, and
    both are worth keeping: the OE finds competitors, the MPN finds the same
    supplier part."""

    identity = _resolve(_v2(), kinds)

    assert identity.mpn_norm == "561948AEZ72"


def test_an_internal_code_in_the_oe_column_is_not_an_oe(kinds) -> None:
    """810 rows of the 2026-07-29 file repeat our own warehouse code in the
    column labelled «Номер». The label is not evidence (NO_9)."""

    identity = _resolve(_v2(mpn="77642695", oe="77642695", article="OP-WP-5571"), kinds)

    assert identity.identity_status is IdentityStatus.MPN_ONLY
    assert identity.reason is IdentityReason.OE_COLUMN_NOT_AN_OE
    assert identity.oe_norm == ""


def test_a_supplier_number_in_the_oe_column_is_not_an_oe(kinds) -> None:
    """344 rows hold a supplier number there — an INA tensioner here."""

    identity = _resolve(_v2(oe="534012320", article=""), kinds)

    assert identity.identity_status is IdentityStatus.MPN_ONLY
    assert identity.reason is IdentityReason.OE_COLUMN_NOT_AN_OE
    assert identity.oe_norm == ""


def test_the_widened_ina_rule_catches_the_534_series(kinds) -> None:
    """Extended from 53[12] to 53[1-4] on 2026-07-29. Without it these four
    tensioners read as candidate OEs."""

    for number in ("533006520", "533007630", "534011620", "534012320"):
        assert _resolve(_v2(oe=number, article=""), kinds).oe_norm == ""


def test_the_widened_ina_rule_still_admits_ordinary_nine_digit_oes(kinds) -> None:
    """The risk of widening a supplier pattern is eating real OEs; 535/539 and
    every other nine-digit number stay candidates."""

    assert _resolve(_v2(oe="535109244", article=""), kinds).oe_norm == "535109244"
    assert _resolve(_v2(oe="058109244", article=""), kinds).oe_norm == "058109244"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("КМ 281", "KM281"), ("КМ 533", "KM533"), ("ОС 232", "OC232")],
)
def test_cyrillic_homoglyphs_in_the_oe_column_are_recovered(
    raw: str,
    expected: str,
    kinds,
) -> None:
    identity = _resolve(_v2(oe=raw, article=""), kinds)

    assert identity.identity_status is IdentityStatus.OE_CONFIRMED
    assert identity.reason is IdentityReason.OE_COLUMN
    assert identity.oe_norm == expected


def test_the_newer_layout_loads_without_a_brand_column(oe_map) -> None:
    assert len(oe_map.rows) == 7743
    assert all(row.article_brand == "" for row in oe_map.rows)
    assert oe_map.rows[0].oe == "31211128157"


def test_real_customer_row_keeps_vehicle_oe_separate_from_kemp_mpn(oe_map, kinds) -> None:
    """The imported workbook's columns must retain their semantic roles.

    ``Номер`` is the vehicle manufacturer's original OE used for the Prom
    market query.  ``Номер производителя`` is KEMP's private join key and
    ``Артикул`` is the supplier article.  A regression which swaps either
    column would still produce a syntactically valid identity while searching
    the wrong market.
    """

    row = next(row for row in oe_map.rows if row.mpn == "77641360")
    assert row.oe == "31211128157"
    assert row.article == "561948-AEZ72"
    identity = _resolve(row, kinds)

    assert identity.identity_status is IdentityStatus.OE_CONFIRMED
    assert identity.oe_norm == "31211128157"
    assert identity.mpn == "77641360"
    assert identity.mpn_norm == "561948AEZ72"


def test_the_newer_file_nearly_doubles_the_positions_with_an_oe(
    oe_map, reference, kinds
) -> None:
    """Coverage after private-code rejection, measured on both customer files."""

    old = {
        i.mpn for i in resolve_all(reference, kinds=kinds, tokens=TOKENS) if i.has_oe
    }
    new = {i.mpn for i in resolve_all(oe_map, kinds=kinds, tokens=TOKENS) if i.has_oe}

    assert len(old) == 3248
    # The widened private 776 namespace deliberately rejects 77646444-34 as
    # an OE: it is a KEMP shelf-code variant, not a public Renault number.
    assert len(new) == 5796
    assert len(old | new) == 6159


def test_private_catalog_code_with_variant_suffix_is_not_an_oe(kinds) -> None:
    """Exact customer row: ``77646444-34`` is shelf code plus variant 34.

    Before the bounded 776 namespace was measured, punctuation let it inflate
    OE coverage and create a false public identity for a Renault Laguna shock.
    """

    identity = _resolve(_v2(oe="77646444-34", article="339704"), kinds)

    assert identity.identity_status is IdentityStatus.MPN_ONLY
    assert identity.reason is IdentityReason.OE_COLUMN_NOT_AN_OE
    assert identity.oe_norm == ""


def test_the_two_files_join_cleanly_on_the_internal_code(oe_map, reference) -> None:
    """Keeping both only works if the newer one is a near-superset."""

    old = {row.mpn for row in reference.rows if row.mpn}
    new = {row.mpn for row in oe_map.rows if row.mpn}

    assert len(old - new) == 4


def test_internal_codes_are_not_clean_join_keys(oe_map, reference) -> None:
    """Recording a data defect rather than papering over it. Some internal
    codes carry a space (``7764 3734``) and 483 rows of the newer file have no
    code at all, so a join on the raw value silently drops them. Whether
    ``7764 3734`` and ``77643734`` are one code is a question for the data
    owner, not something to decide by normalising quietly."""

    assert sum(1 for row in reference.rows if row.mpn and not row.mpn.isdigit()) == 19
    assert sum(1 for row in oe_map.rows if not row.mpn) == 483
