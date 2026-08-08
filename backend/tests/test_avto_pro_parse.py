"""Avto.pro OPTKiev pure HTML parsers (offline fixtures, no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from metis.pricing.avto_pro import (
    EXTRACTION_METHOD,
    ExtractionStatus,
    PageKind,
    classify_page_kind,
    extraction_rows_for_csv,
    is_oem_brand,
    is_waf_challenge,
    load_avto_pro_tokens,
    parse_part_page,
    parse_product_card,
    parse_seller_profile,
    seller_profile_to_dict,
)

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = BACKEND_ROOT / "config" / "avto_pro_tokens.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "avto_pro"


@pytest.fixture(scope="module")
def config():
    return load_avto_pro_tokens(CONFIG_PATH)


def test_load_avto_pro_tokens_hashes_source(config) -> None:
    assert config.method_version == "avto-pro-optkiev-v2"
    assert config.default_seller_slug == "optkiev"
    assert config.source_sha256 is not None
    assert len(config.source_sha256) == 64
    assert "oe" in config.field_labels
    assert config.original_section_id == "original-manufacturers"
    assert is_oem_brand("CHERY", config)
    assert is_oem_brand("General Motors", config)
    assert not is_oem_brand("KEMP", config)
    assert not is_oem_brand("OEM", config)


def test_waf_challenge_is_detected(config) -> None:
    html = (FIXTURES / "waf_challenge.html").read_text(encoding="utf-8")
    assert is_waf_challenge(html, config) is True
    profile = parse_seller_profile(html, config)
    assert profile.page_kind is PageKind.WAF
    assert profile.extraction_status is ExtractionStatus.WAF
    assert profile.product_refs == ()

    card = parse_product_card(html, config)
    assert card.page_kind is PageKind.WAF
    assert card.extraction_status is ExtractionStatus.WAF
    assert card.numbers == ()


def test_seller_profile_extracts_product_seeds(config) -> None:
    html = (FIXTURES / "seller_optkiev_profile.html").read_text(encoding="utf-8")
    profile = parse_seller_profile(html, config, seller_slug="optkiev")

    assert profile.extraction_status is ExtractionStatus.OK
    assert profile.page_kind is PageKind.SELLER_PROFILE
    assert profile.display_name is not None
    assert "OPTKiev" in (profile.display_name or "")
    assert len(profile.product_refs) >= 4

    ids = {ref.product_id for ref in profile.product_refs}
    assert "26108" in ids
    assert "1271" in ids
    assert "1783" in ids
    assert "1395" in ids

    for ref in profile.product_refs:
        assert ref.url.startswith("https://avto.pro/catalog/")
        assert ref.product_id.isdigit()

    assert any("Амортизатор" in group for group in profile.product_groups)


def test_seller_showcase_cards_from_carousel(config) -> None:
    html = (FIXTURES / "seller_optkiev_showcase.html").read_text(encoding="utf-8")
    profile = parse_seller_profile(html, config, seller_slug="optkiev")

    assert profile.extraction_status is ExtractionStatus.OK
    assert len(profile.showcase_cards) == 3

    by_article = {c.article: c for c in profile.showcase_cards}
    assert "JGT1316T" in by_article
    trw = by_article["JGT1316T"]
    assert trw.brand == "TRW"
    assert trw.title == "Амортизатор задний"
    assert trw.price_raw and "3007" in trw.price_raw
    assert trw.url == "https://avto.pro/part-JGT1316T-TRW-531/"
    assert by_article["50701"].brand == "BIRTH"
    assert by_article["1H0145828C"].brand == "VAG"

    assert profile.email == "optkiev@i.ua"
    assert profile.phone == "+380635062921"
    assert profile.product_groups_count == 35
    assert any("Пн" in h for h in profile.working_hours)

    payload = seller_profile_to_dict(profile)
    assert payload["cards_count"] == 3
    assert any(c["article"] == "JGT1316T" for c in payload["cards"])


def test_product_card_reads_labelled_fields_only(config) -> None:
    html = (FIXTURES / "product_card_sample.html").read_text(encoding="utf-8")
    card = parse_product_card(
        html,
        config,
        url="https://avto.pro/catalog/chery/amulet/amortizator-zadniy-m26108/",
    )

    assert card.extraction_status is ExtractionStatus.OK
    assert card.page_kind is PageKind.PRODUCT_CARD
    assert card.product_id == "26108"
    assert card.seller_slug == "optkiev"
    assert card.brand_raw == "KEMP"
    assert card.article_raw == "77641703"
    assert card.oe_raw is not None
    assert "313031" in (card.oe_raw or "")

    norms = {number.normalized for number in card.numbers}
    # article + oe/mpn (313031 may appear once after de-dupe per field)
    assert "77641703" in norms
    assert "313031" in norms
    # unlabelled description digits must not become identity numbers
    assert "99999999" not in norms

    fields = {number.source_field for number in card.numbers}
    assert "article" in fields
    assert "oe" in fields or "mpn" in fields


def test_csv_rows_are_flat_and_non_pricing(config) -> None:
    html = (FIXTURES / "product_card_sample.html").read_text(encoding="utf-8")
    card = parse_product_card(html, config, url="/catalog/x/y/z-m26108/")
    rows = extraction_rows_for_csv(
        card,
        seller_slug="optkiev",
        product_url="https://avto.pro/catalog/x/y/z-m26108/",
        query="77641703",
    )
    assert rows
    assert all(row["extraction_method"] == EXTRACTION_METHOD for row in rows)
    assert all(row["seller_slug"] == "optkiev" for row in rows)
    assert all("price" not in row for row in rows)
    assert any(row["number_norm"] == "77641703" for row in rows)


def test_empty_html_is_fail_closed(config) -> None:
    profile = parse_seller_profile("", config)
    assert profile.extraction_status is ExtractionStatus.EMPTY
    card = parse_product_card("", config)
    assert card.extraction_status is ExtractionStatus.EMPTY


def test_part_page_extracts_oe_from_original_manufacturers(config) -> None:
    html = (FIXTURES / "part_page_kemp_77641834.html").read_text(encoding="utf-8")
    url = "https://avto.pro/part-77641834-KEMP-204/"
    assert classify_page_kind(html, config, url=url) is PageKind.PART_PAGE

    card = parse_part_page(html, config, url=url)
    assert card.page_kind is PageKind.PART_PAGE
    assert card.extraction_status is ExtractionStatus.OK
    assert card.brand_raw and card.brand_raw.upper() == "KEMP"
    assert card.article_raw == "77641834"
    assert card.product_id == "204"
    assert card.crossgroup_id == "2070165489"
    assert card.seller_slug == "optkiev"
    assert card.is_original_brand is False

    oe_numbers = [n for n in card.numbers if n.source_field == "oe"]
    oe_norms = {n.normalized for n in oe_numbers}
    oe_brands = {n.brand_raw.upper() for n in oe_numbers if n.brand_raw}

    # Probe baseline OE-like set (OEM brands only).
    for expected in (
        "A112915010B",
        "A112915010",
        "A132915010",
        "13409599",
        "132915010",
        "A112915010BA",
        "13409600",
        "191513033B",
        "A158401505RA",
    ):
        assert expected in oe_norms, expected

    assert oe_brands <= {"CHERY", "GM", "ZAZ", "OPEL", "PORSCHE", "BENTLEY"}
    # 15 original tiles collapse by normalized code (same OE under GM+OPEL etc.)
    # and noise markers (ALLYT).  Live probe listed 14 raw-ish codes; after
    # de-dupe + noise filter we keep 11 unique OE candidates.
    assert len(oe_numbers) == 11

    # Aftermarket analogues are not OE.
    analog_norms = {n.normalized for n in card.numbers if n.source_field == "analog"}
    assert "KSA8112I" in analog_norms or any(
        n.raw.upper().startswith("KSA") for n in card.numbers if n.source_field == "analog"
    )
    assert "KSA8112I" not in oe_norms

    # Free-floating / MARKET packaging links outside the original section
    # must not become OE candidates.
    assert "A112915010BAMARKET" not in oe_norms
    assert "99999999" not in oe_norms

    # parse_product_card routes part pages automatically.
    routed = parse_product_card(html, config, url=url)
    assert routed.page_kind is PageKind.PART_PAGE
    assert {n.normalized for n in routed.numbers if n.source_field == "oe"} == oe_norms

    rows = extraction_rows_for_csv(
        card,
        seller_slug="optkiev",
        product_url=url,
        query="77641834",
    )
    assert any(row["source_field"] == "oe" and row["number_brand"] == "CHERY" for row in rows)
    assert all(row["page_kind"] == "PART_PAGE" for row in rows)
