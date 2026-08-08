"""Reading the avto.pro part-page harvest into the identity graph.

``metis.pricing.avto_pro`` already turns a captured card into rows: it splits
``#original-manufacturers`` from ``#analog-parts`` and tags every number with
``source_field``.  What did not exist is the step after that — putting those
rows into the graph as a *second publisher*, bound to the card that produced
them.

So the tests here are about the boundary, not the parse: a row whose URL does
not belong to the code it claims, a card published under someone else's brand,
a ``source_field`` this loader has never seen, and a WAF challenge whose empty
result would otherwise read as "avto.pro knows no OE for this part".

The last test runs the real captured card end to end.  A loader that agrees
with a fixture the parser never produced proves nothing about the seam.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from marko.services.catalog_identity_reparse import (
    AVTOPRO_CROSS_SOURCE,
    AVTOPRO_OE_SOURCE,
    CatalogIdentityReparseError,
    load_avtopro_source,
)
from metis.pricing.avto_pro import (
    extraction_rows_for_csv,
    load_avto_pro_tokens,
    parse_part_page,
)

BACKEND = Path(__file__).resolve().parents[1]
TOKENS = load_avto_pro_tokens(BACKEND / "config/avto_pro_tokens.yaml")
CARD_HTML = BACKEND / "tests/fixtures/avto_pro/part_page_kemp_77641834.html"

COLUMNS = (
    "article_raw",
    "number_raw",
    "source_field",
    "number_brand",
    "product_url",
    "title",
    "extraction_status",
)
CARD_URL = "https://avto.pro/part-77642361-KEMP-606/"


def _dataset(tmp_path: Path, *rows: dict[str, str]) -> Path:
    path = tmp_path / "avtopro.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in COLUMNS})
    return path


def _row(**overrides: str) -> dict[str, str]:
    row = {
        "article_raw": "77642361",
        "number_raw": "1H0411105AH",
        "source_field": "oe",
        "number_brand": "VAG",
        "product_url": CARD_URL,
        "title": "Пружина передня VW Golf 2",
        "extraction_status": "OK",
    }
    row.update(overrides)
    return row


# ------------------------------------------------- the split the source is for


def test_the_two_sections_become_two_different_sources(tmp_path) -> None:
    """One merged mapping would hand a Konner article to a source declared to
    assert OEs — the shape of the ``+276`` defect, and the reason
    ``KEMP_REFERENCE_ARTICLE`` is separate from ``KEMP_REFERENCE_MAP``."""

    path = _dataset(
        tmp_path,
        _row(),
        _row(number_raw="KSA8112I", source_field="analog", number_brand="KONNER"),
    )

    oe, cross = load_avtopro_source(path)

    assert oe["77642361"].extraction_method == AVTOPRO_OE_SOURCE
    assert oe["77642361"].numbers == ("1H0411105AH",)
    assert cross["77642361"].extraction_method == AVTOPRO_CROSS_SOURCE
    assert cross["77642361"].numbers == ("KSA8112I",)


def test_the_cards_own_article_is_not_a_relation(tmp_path) -> None:
    """``source_field=article`` is the card restating the code we searched for.
    It is real, and it relates the part to nothing."""

    path = _dataset(
        tmp_path,
        _row(number_raw="77642361", source_field="article", number_brand="KEMP"),
        _row(),
    )

    oe, cross = load_avtopro_source(path)

    assert oe["77642361"].numbers == ("1H0411105AH",)
    assert cross == {}


def test_an_unknown_source_field_stops_the_load(tmp_path) -> None:
    """The parser may grow a field; deciding here what it means would be a
    guess, and the two possible guesses lose an OE or invent one."""

    path = _dataset(tmp_path, _row(source_field="oem_maybe"))

    with pytest.raises(CatalogIdentityReparseError, match="source_field"):
        load_avtopro_source(path)


def test_a_waf_challenge_row_stops_the_load(tmp_path) -> None:
    """A blocked page yields no numbers, and that is not the same fact as a
    card without OE numbers.  Loading it quietly would record the absence."""

    path = _dataset(
        tmp_path,
        _row(number_raw="", source_field="", extraction_status="WAF"),
    )

    with pytest.raises(CatalogIdentityReparseError, match="WAF|extraction_status"):
        load_avtopro_source(path)


def test_a_card_without_numbers_is_read_as_silence_not_as_breakage(tmp_path) -> None:
    """``extraction_rows_for_csv`` emits one blank-number row for such a card.
    avto.pro simply not knowing this part is ordinary data."""

    path = _dataset(
        tmp_path,
        _row(number_raw="", source_field="", extraction_status="NO_NUMBERS"),
    )

    assert load_avtopro_source(path) == ({}, {})


# ----------------------------------------------------------- provenance rules


@pytest.mark.parametrize(
    "url",
    [
        # Another code's card.
        "https://avto.pro/part-77649999-KEMP-606/",
        # Another maker's card: it says nothing about our part.
        "https://avto.pro/part-77642361-FEBI-606/",
        # Another host wearing an avto.pro-shaped path.
        "https://attacker.example/part-77642361-KEMP-606/",
        # Plaintext.
        "http://avto.pro/part-77642361-KEMP-606/",
        # A search result rather than a card.
        "https://avto.pro/search/?q=77642361",
    ],
)
def test_a_row_whose_url_does_not_bind_the_code_is_refused(tmp_path, url) -> None:
    path = _dataset(tmp_path, _row(product_url=url))

    with pytest.raises(CatalogIdentityReparseError, match="untrusted|unbound"):
        load_avtopro_source(path)


def test_a_code_that_is_not_ours_is_refused(tmp_path) -> None:
    """``article_raw`` is a join key into the customer catalogue, not free text.
    The seller showcase harvest is full of other makers' articles."""

    path = _dataset(
        tmp_path,
        _row(
            article_raw="JGT1316T",
            product_url="https://avto.pro/part-JGT1316T-KEMP-606/",
        ),
    )

    with pytest.raises(CatalogIdentityReparseError, match="untrusted|unbound"):
        load_avtopro_source(path)


def test_any_internal_shelf_code_is_dropped_rather_than_published(tmp_path) -> None:
    """No ``776…`` number is a public identity, and one that reached the graph
    would be searched on Prom as an OE."""

    path = _dataset(
        tmp_path,
        _row(number_raw="77649999", source_field="analog", number_brand="KEMP"),
        _row(number_raw="KSA8112I", source_field="analog", number_brand="KONNER"),
    )

    _, cross = load_avtopro_source(path)

    assert cross["77642361"].numbers == ("KSA8112I",)


def test_the_card_title_and_url_are_kept_as_review_context(tmp_path) -> None:
    """Every link this source makes is born REVIEW, so what a human needs in
    order to judge it has to travel with the number."""

    path = _dataset(tmp_path, _row())

    oe, _ = load_avtopro_source(path)

    assert oe["77642361"].raw_context == (
        f"Пружина передня VW Golf 2 | {CARD_URL} | brands=VAG"
    )


def test_every_brand_in_the_section_reaches_the_review_context(tmp_path) -> None:
    """``SourceNumbers`` carries one context per code, so a single number's
    brand cannot be attached to the group without lying about the others.

    For a cross list the brand is half the identity — ``FEBI 26749`` and
    ``SACHS 26749`` are different parts — so the set travels, in card order.
    """

    path = _dataset(
        tmp_path,
        _row(number_raw="KSA8112I", source_field="analog", number_brand="KONNER"),
        _row(number_raw="320910AC", source_field="analog", number_brand="FITSHI"),
        _row(number_raw="MSA1020", source_field="analog", number_brand="KONNER"),
    )

    _, cross = load_avtopro_source(path)

    assert cross["77642361"].raw_context.endswith("brands=KONNER, FITSHI")


def test_a_missing_dataset_is_an_error_rather_than_an_empty_source(tmp_path) -> None:
    with pytest.raises(CatalogIdentityReparseError, match="do not exist"):
        load_avtopro_source(tmp_path / "absent.csv")


# ------------------------------------------------------------------- the seam


def test_the_real_captured_card_survives_parse_then_load(tmp_path) -> None:
    """Parser and loader are two halves of one contract.

    Hand-written CSV proves the loader agrees with my idea of the parser; the
    captured page is what proves it agrees with the parser.
    """

    url = "https://avto.pro/part-77641834-KEMP-562/"
    card = parse_part_page(
        CARD_HTML.read_text(encoding="utf-8"), TOKENS, url=url
    )
    rows = extraction_rows_for_csv(
        card, seller_slug="optkiev", product_url=url, query="77641834"
    )
    path = tmp_path / "harvest.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    oe, cross = load_avtopro_source(path)

    # ZAZ/GM/CHERY tiles are vehicle makers; KONNER/FITSHI are not.
    assert "132915010" in oe["77641834"].numbers
    assert "13409599" in oe["77641834"].numbers
    assert "KSA8112I" in cross["77641834"].numbers
    # The card's own code reappears in no source, and the packaging SKU the
    # tokens config calls noise never left the parser.
    assert not any(
        number.startswith("776")
        for number in oe["77641834"].numbers + cross["77641834"].numbers
    )
    assert "A112915010BAALLYT" not in oe["77641834"].numbers
