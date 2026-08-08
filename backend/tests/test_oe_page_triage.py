"""Triage for saved catalogue pages, before any number is read off them.

Two outsourced rounds failed the same way: the pages were the catalogue's
*search by OE number* view, which prints the query back as if it were an OE
(``68789 (original number of VOLVO)`` for a Nissens radiator article). Nothing
downstream could tell that from a real cross list, so the check has to happen
at the page, not at the number.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from marko.services.oe_page_triage import (
    PageVerdict,
    triage_page,
)

# Phrases below are copied verbatim from the five pages saved on 2026-08-08.
SEARCH_PAGE = """
<html><head><title>68789 | 68789 in AUTODOC</title></head><body>
<h1>Engine radiator 68789</h1>
<p>An OEM number is a unique code containing letters and digits.
All spare parts in the list below are equivalent to OEM number 68789:</p>
<ul><li>68789 (original number of VOLVO)</li>
<li>68789 (original number of NISSAN)</li></ul>
</body></html>
"""

EMPTY_PAGE = """
<html><head><title>OC266 | OC266 in AUTODOC</title></head><body>
<h1>Oil filter OC266</h1>
<p>An OEM number is a unique code containing letters and digits.
No spare parts corresponding to your request have been found.
We will gladly notify you when the product becomes available in stock.</p>
</body></html>
"""

ARTICLE_CARD = """
<html><head><title>MAHLE ORIGINAL OC 266 Oil filter</title></head><body>
<h1>Oil filter MAHLE ORIGINAL OC 266</h1>
<div>Manufacturer: MAHLE ORIGINAL</div>
<div>Article number: OC 266</div>
<div>Reference number OEM: 1088179</div>
<button>Show OEM numbers of the product</button>
<ul><li>FORD 1088179</li><li>FORD 5025275</li></ul>
</body></html>
"""

CHALLENGE = """
<html><head><title>Attention Required! | Cloudflare</title></head><body>
<h1>Please verify you are a human</h1><div class="cf-error-details">429</div>
</body></html>
"""


def test_search_by_oe_view_is_refused_even_though_it_is_full_of_numbers() -> None:
    """The failure both outsourced rounds shipped, caught at the page."""

    result = triage_page(
        SEARCH_PAGE, url="https://www.autodoc.parts/car-parts/oem/68789"
    )

    assert result.verdict is PageVerdict.SEARCH_BY_NUMBER
    assert not result.usable
    assert "equivalent to oem number" in result.reason


def test_a_page_that_found_nothing_is_not_a_page_that_says_nothing_exists() -> None:
    """``not found`` has to reach the operator, not become an empty cross list."""

    result = triage_page(EMPTY_PAGE, url="https://www.autodoc.parts/car-parts/oem/oc266")

    assert result.verdict is PageVerdict.NOTHING_FOUND
    assert not result.usable


def test_challenge_page_is_refused_rather_than_read_as_a_part_with_no_crosses() -> None:
    result = triage_page(CHALLENGE, url="https://example.invalid/x")

    assert result.verdict is PageVerdict.BLOCKED
    assert not result.usable


def test_article_card_passes_and_reports_what_it_is_a_card_for() -> None:
    result = triage_page(
        ARTICLE_CARD,
        url="https://www.autodoc.parts/mahle-original/1234",
        expected_article="OC 266",
        expected_brand="Mahle Original",
    )

    assert result.verdict is PageVerdict.ARTICLE_CARD
    assert result.usable
    assert result.article_matches is True
    assert result.brand_matches is True


def test_card_for_a_different_article_is_refused() -> None:
    """Two of five pilot pages were a neighbouring article's card.

    A card that parses perfectly still attributes its numbers to the wrong
    catalogue row, and no later check can notice.
    """

    result = triage_page(
        ARTICLE_CARD,
        url="https://www.autodoc.parts/mahle-original/1234",
        expected_article="OC 267",
        expected_brand="Mahle Original",
    )

    assert result.article_matches is False
    assert not result.usable
    assert "OC 267" in result.reason


def test_card_for_the_right_number_but_another_brand_is_refused() -> None:
    result = triage_page(
        ARTICLE_CARD,
        url="https://www.autodoc.parts/mahle-original/1234",
        expected_article="OC 266",
        expected_brand="Knecht",
    )

    assert result.brand_matches is False
    assert not result.usable


def test_oem_in_the_url_is_enough_on_its_own() -> None:
    """A card URL never carries ``/oem/``; the search view always does."""

    result = triage_page(
        ARTICLE_CARD, url="https://www.autodoc.parts/car-parts/oem/oc266"
    )

    assert result.verdict is PageVerdict.SEARCH_BY_NUMBER
    assert not result.usable


def test_unrecognised_page_is_refused_rather_than_assumed_good() -> None:
    """Fail closed: a catalogue we have never seen is not a catalogue we trust."""

    result = triage_page("<html><body><p>hello</p></body></html>", url="https://x/y")

    assert result.verdict is PageVerdict.UNKNOWN
    assert not result.usable


@pytest.mark.skipif(
    not os.environ.get("OE_PAGES_DIR"),
    reason="set OE_PAGES_DIR to triage a real harvest directory",
)
def test_real_directory_triage() -> None:
    directory = Path(os.environ["OE_PAGES_DIR"])
    pages = sorted(directory.glob("*.htm*"))
    assert pages, f"no saved pages under {directory}"
    for page in pages:
        result = triage_page(
            page.read_text(encoding="utf-8", errors="replace"), url=""
        )
        print(f"{page.name}: {result.verdict.value} — {result.reason}")


def test_the_car_selector_saying_nothing_matched_is_not_the_article_missing() -> None:
    """``Sorry, no matches were found for your query`` is on every page.

    Read as a result, it marked four of the five pilot pages as "the catalogue
    has no such article" when they were the wrong view of an article it does
    have — a wrong reason on a right refusal, which sends the operator to
    re-search instead of to re-save.
    """

    page = SEARCH_PAGE.replace(
        "<h1>", "<div>Select engine Other Sorry, no matches were found "
        "for your query</div><h1>"
    )

    result = triage_page(page, url="https://www.autodoc.parts/car-parts/oem/68789")

    assert result.verdict is PageVerdict.SEARCH_BY_NUMBER
