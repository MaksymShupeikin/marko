"""Token classification for kemp.ua cards, against the 2026-07-29 measurement.

Every literal in this file was observed on a real card during the measurement
recorded in ``docs/METIS_IDENTITY_KEMPSITE_MEASUREMENT_2026-07-29.md``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metis.pricing.kemp_site import (
    EXTRACTION_METHOD,
    KempSiteConfigError,
    TokenClass,
    classify_token,
    extract_numbers,
    known_number_set,
    load_kemp_site_tokens,
    split_tokens,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND_ROOT / "config" / "kemp_site_tokens.yaml"
CONFIG = load_kemp_site_tokens(CONFIG_PATH)


def _classify(raw: str, *, known=(), field: str = "sku"):
    return classify_token(
        raw,
        config=CONFIG,
        known=known_number_set(known, CONFIG),
        source_field=field,
    )


# ------------------------------------------------------------------- splitting


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("713610640/7L0498287", ["713610640", "7L0498287"]),
        ("4017703/04", ["4017703", "04"]),
        ("55473/MG", ["55473", "MG"]),
        ("LM67048_LM67010", ["LM67048", "LM67010"]),
        ("94727/51804991", ["94727", "51804991"]),
        ("314766/96534981Q/G", ["314766", "96534981Q", "G"]),
        ("6455.EE", ["6455.EE"]),
        ("55310-4A500", ["55310-4A500"]),
        ("", []),
        (None, []),
    ],
)
def test_glued_values_are_cut_but_punctuation_inside_a_number_is_kept(value, expected):
    assert split_tokens(value, CONFIG) == expected


# ------------------------------------------------------- genuine OE candidates


@pytest.mark.parametrize(
    "raw",
    [
        "6Q0407621AH",   # VAG,      77641355
        "7L0498287",     # VAG,      77647561
        "038109244J",    # VAG,      77642385
        "06B109243",     # VAG,      77642917
        "7H0611775",     # VAG,      77643759
        "357419803",     # VAG,      77642644
        "0003232885",    # Mercedes, 77645167
        "6001548102",    # Renault,  77648544
        "7700312011",    # Renault,  77648476
        "2140000Q2A",    # Renault,  77648661
        "6455.EE",       # PSA,      77648504
        "1301SJ",        # PSA,      7764978
        "133389",        # PSA,      77645936
        "9170G3",        # PSA,      77645783
        "GJ5A28700B",    # Mazda,    77648745
        "4851080490",    # Toyota,   77648803
        "55310-4A500",   # Hyundai,  77648775
        "96316745",      # GM,       77648761
        "31212634106",   # BMW,      77641349
        "YC155310FC",    # Ford,     77644156
    ],
)
def test_real_oe_numbers_survive_as_candidates(raw):
    assert _classify(raw).token_class is TokenClass.OE_CANDIDATE


def test_a_candidate_keeps_its_raw_form_for_audit():
    token = _classify("55310-4A500")

    assert token.raw == "55310-4A500"
    assert token.normalized == "553104A500"
    assert token.matched_rule is None


# --------------------------------------------------------------- internal code


@pytest.mark.parametrize("raw", ["776414", "776769", "7764112", "77641229"])
def test_internal_codes_never_become_oe(raw):
    token = _classify(raw)

    assert token.token_class is TokenClass.INTERNAL_CODE
    assert token.matched_rule == "INTERNAL_CODE_PATTERN"


@pytest.mark.parametrize("raw", ["7701059269", "7700312011"])
def test_ten_digit_renault_numbers_are_not_mistaken_for_internal_codes(raw):
    """``770…`` and ``776…`` are one digit apart; length keeps them separate."""

    assert _classify(raw).token_class is TokenClass.OE_CANDIDATE


# ---------------------------------------------------------- aftermarket shapes


@pytest.mark.parametrize(
    ("raw", "rule"),
    [
        ("VKBA3901", "SKF_WHEEL_BEARING_KIT"),
        ("VKBA 741", "SKF_WHEEL_BEARING_KIT"),
        ("713610470", "FAG_WHEEL_BEARING_KIT"),
        ("713678890", "FAG_WHEEL_BEARING_KIT"),
        ("531039920", "INA_TENSIONER"),
        ("532034910", "INA_TENSIONER"),
        ("GN948", "BERU_GLOW_PLUG"),
        ("FT0364", "KK_BRAKE_HOSE"),
        ("OP-ES-0480", "MOOG_JOINT"),
        ("VO-AX-7157", "MOOG_JOINT"),
        ("CI-BJ-0523", "MOOG_JOINT"),
        ("LM67010", "SKF_BEARING_DESIGNATION"),
        ("DAC25520037", "BEARING_DAC"),
    ],
)
def test_supplier_article_shapes_are_named_not_just_rejected(raw, rule):
    token = _classify(raw)

    assert token.token_class is TokenClass.AFTERMARKET_CROSS
    assert token.matched_rule == rule


def test_moog_shape_relies_on_hyphens_that_normalization_would_erase():
    """Matching the normalized form would make ``OPES0480`` indistinguishable
    from a four-letter OE, so the raw form is what the pattern sees."""

    assert _classify("OP-ES-0480").token_class is TokenClass.AFTERMARKET_CROSS
    assert _classify("OPES0480").token_class is TokenClass.OE_CANDIDATE


# ---------------------------------------------------------------------- noise


@pytest.mark.parametrize("raw", ["04", "G", "MG", "", "   "])
def test_fragments_of_glued_values_are_noise(raw):
    assert _classify(raw).token_class is TokenClass.NOISE


def test_absurdly_long_tokens_are_noise():
    assert _classify("A" * 21).token_class is TokenClass.NOISE


# ------------------------------------------------------------- already known


def test_article_already_in_the_reference_map_is_not_news():
    assert _classify("313856", known=["313856"]).token_class is TokenClass.KNOWN_ARTICLE


def test_known_article_is_matched_through_its_glued_parts():
    """The map holds ``55473/MG``; the site shows plain ``55473``."""

    assert _classify("55473", known=["55473/MG"]).token_class is TokenClass.KNOWN_ARTICLE


def test_known_matching_ignores_punctuation_and_case():
    assert _classify("vkba 741", known=["VKBA741"]).token_class is (
        TokenClass.KNOWN_ARTICLE
    )


def test_being_known_wins_over_the_aftermarket_shape():
    """Order matters: ``713610640`` is both a FAG shape and our own article.

    Reporting it as ``KNOWN_ARTICLE`` says "nothing new here", which is the
    truth; reporting it as ``AFTERMARKET_CROSS`` would imply we learned a
    competitor's number we did not have.
    """

    token = _classify("713610640", known=["713610640"])

    assert token.token_class is TokenClass.KNOWN_ARTICLE


# ------------------------------------------------- the eight manual rejections


def test_the_eight_hand_rejected_numbers_split_as_measured():
    """Three are caught by rule; five are not, and the config says so plainly.

    Kayaba shock numbers are shape-identical to six-digit PSA OE numbers, so
    they stay candidates and reach the review queue. That is the documented
    limit of a shape-based tokeniser, not a defect to paper over.
    """

    caught = {
        "776769": TokenClass.INTERNAL_CODE,
        "04": TokenClass.NOISE,
        "55473": TokenClass.KNOWN_ARTICLE,
    }
    for raw, expected in caught.items():
        known = ["55473/MG"] if raw == "55473" else []
        assert _classify(raw, known=known).token_class is expected, raw

    for raw in ("343205", "349080", "333707", "0100226457", "803054"):
        assert _classify(raw).token_class is TokenClass.OE_CANDIDATE, raw


# ------------------------------------------------------- both fields together


def test_both_fields_are_read_and_the_label_decides_nothing():
    """77648745: the OE-labelled field holds the Sachs article, the
    article-labelled field holds the Mazda OE."""

    extraction = extract_numbers(
        [("oe", "313856"), ("sku", "GJ5A28700B")],
        config=CONFIG,
        known=known_number_set(["313856"], CONFIG),
    )

    assert [t.normalized for t in extraction.oe_candidates] == ["GJ5A28700B"]
    assert extraction.oe_candidates[0].source_field == "sku"


def test_the_reverse_layout_works_the_same_way():
    """77642751: here the OE-labelled field is the one holding the Fiat OE."""

    extraction = extract_numbers(
        [("oe", "1382419080"), ("sku", "606554")],
        config=CONFIG,
        known=known_number_set(["606554"], CONFIG),
    )

    assert [t.normalized for t in extraction.oe_candidates] == ["1382419080"]
    assert extraction.oe_candidates[0].source_field == "oe"


def test_a_glued_field_yields_the_known_part_and_the_new_one():
    """77647561: ``713610640/7L0498287`` is our FAG article plus a VAG OE."""

    extraction = extract_numbers(
        [("oe", "713610640"), ("sku", "713610640/7L0498287")],
        config=CONFIG,
        known=known_number_set(["713610640"], CONFIG),
    )

    assert [t.normalized for t in extraction.oe_candidates] == ["7L0498287"]


def test_a_number_repeated_across_fields_is_kept_once_and_attributed_first():
    extraction = extract_numbers(
        [("oe", "6Q0407621AH"), ("sku", "6q0407621ah")],
        config=CONFIG,
        known=set(),
    )

    assert len(extraction.oe_candidates) == 1
    assert extraction.oe_candidates[0].source_field == "oe"


def test_empty_card_yields_nothing_rather_than_failing():
    extraction = extract_numbers(
        [("oe", ""), ("sku", None)], config=CONFIG, known=set()
    )

    assert extraction.tokens == ()
    assert extraction.oe_candidates == ()


# --------------------------------------------------------------------- config


def test_shipped_config_loads_and_is_hashed():
    assert CONFIG.method_version == "kemp-site-tokens-v1"
    assert CONFIG.min_length == 4
    assert CONFIG.max_length == 20
    assert CONFIG.source_sha256 is not None
    assert len(CONFIG.source_sha256) == 64
    assert {"/", "_", ",", ";"} <= set(CONFIG.value_separators)


def test_extraction_method_is_distinguishable_from_other_sources():
    """NO_7: a number from the site must never be confused with one from the
    reference map or from our own export."""

    assert EXTRACTION_METHOD == "KEMP_SITE"


def test_missing_config_is_rejected(tmp_path):
    with pytest.raises(KempSiteConfigError):
        load_kemp_site_tokens(tmp_path / "absent.yaml")


@pytest.mark.parametrize(
    "payload",
    [
        "schema_version: wrong-v9\n",
        "schema_version: metis-kemp-site-tokens-v1\nvalue_separators: []\n",
        (
            "schema_version: metis-kemp-site-tokens-v1\n"
            "method_version: x\n"
            "value_separators: ['/']\n"
            "limits: {min_length: 9, max_length: 4}\n"
            "internal_code_pattern: '^7'\n"
            "aftermarket_patterns: [{name: a, pattern: '^b'}]\n"
        ),
        (
            "schema_version: metis-kemp-site-tokens-v1\n"
            "method_version: x\n"
            "value_separators: ['/']\n"
            "limits: {min_length: 4, max_length: 20}\n"
            "internal_code_pattern: '^(unclosed'\n"
            "aftermarket_patterns: [{name: a, pattern: '^b'}]\n"
        ),
        (
            "schema_version: metis-kemp-site-tokens-v1\n"
            "method_version: x\n"
            "value_separators: ['/']\n"
            "limits: {min_length: 4, max_length: 20}\n"
            "internal_code_pattern: '^7'\n"
            "aftermarket_patterns: [{name: a, pattern: '^b'}, {name: a, pattern: '^c'}]\n"
        ),
    ],
    ids=["bad-schema", "no-separators", "bad-limits", "bad-regex", "duplicate-name"],
)
def test_malformed_config_fails_closed(tmp_path, payload):
    path = tmp_path / "tokens.yaml"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(KempSiteConfigError):
        load_kemp_site_tokens(path)
