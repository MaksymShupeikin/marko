"""Card parsing and the fail-closed guard of the kemp.ua harvest script.

The classification rules live in ``metis.pricing.kemp_site`` and are covered by
``test_kemp_site_tokens``.  What is proved here is the part that reads HTML:
it is the piece that breaks silently when the site is redesigned.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Markup copied verbatim from a live card (77642803) during the 2026-07-29
# measurement, tabs and all.
CARD = (
    '<div class="breadcrumb-h1"><h1 class="heading">'
    'Амортизатор задній правий Toyota Camry (V40) (2006 - 2011)'
    '</h1></div>'
    '<div class="product-block col-sm-7"><div class="product-data">\n'
    '\t<div class="product-data__item model">'
    '<div class="product-data__item-div">ОЕ номер:</div> 443121251T</div>\n'
    '\t<div class="product-data__item sku">'
    '<div class="product-data__item-div">Артикул:</div> AI2091</div>\n'
    '\t<div class="product-data__item manufacturer">'
    '<div class="product-data__item-div">Виробники</div>'
    '<a href="https://kemp.ua/index.php?route=product/manufacturer/info'
    '&amp;manufacturer_id=89">KEMP</a></div>\n'
    '\t<div class="product-data__item mpn">'
    '<div class="product-data__item-div">Номер виробника:</div> 77642803</div>\n'
    "</div></div>"
)


def _harvest() -> ModuleType:
    path = ROOT / "scripts/kemp_site_harvest.py"
    spec = importlib.util.spec_from_file_location("kemp_site_harvest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` resolves annotations through ``sys.modules[cls.__module__]``,
    # which is empty for a module loaded straight off a path unless we register
    # it first.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HARVEST = _harvest()


def test_all_three_fields_are_read_off_a_real_card() -> None:
    assert HARVEST.read_card(CARD) == {
        "model": "443121251T",
        "sku": "AI2091",
        "mpn": "77642803",
    }


def test_card_title_is_retained_as_non_monetary_seed_evidence() -> None:
    assert HARVEST.read_card_title(CARD) == (
        "Амортизатор задній правий Toyota Camry (V40) (2006 - 2011)"
    )


def test_card_title_parser_does_not_fall_back_to_arbitrary_markup() -> None:
    assert HARVEST.read_card_title("<h2>not a product heading</h2>") == ""


def test_structured_product_jsonld_is_read_without_monetary_fields() -> None:
    page = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Амортизатор задній правий Toyota Camry",
      "brand": {"@type": "Brand", "name": "KEMP"},
      "manufacturer": "KEMP",
      "model": "313452",
      "sku": "4853089025",
      "mpn": "77648791",
      "image": ["https://kemp.ua/image/catalog/camry.jpg"],
      "offers": {"price": "1739.65", "priceCurrency": "UAH"}
    }
    </script>
    """

    structured = HARVEST.read_product_jsonld(page)

    assert structured["mpn"] == "77648791"
    assert structured["brand"] == "KEMP"
    assert structured["image"].endswith("camry.jpg")
    assert "price" not in structured
    assert HARVEST.structured_mpn_status(structured, "77648791") == "PRODUCT_MATCH"


def test_structured_product_mpn_mismatch_is_not_fuzzy_accepted() -> None:
    structured = {"mpn": "77648792"}

    assert HARVEST.structured_mpn_status(structured, "77648791") == "MPN_MISMATCH"
    assert HARVEST.structured_mpn_status({}, "77648791") == "MISSING"


def test_manifest_record_counts_use_csv_row_denominator() -> None:
    records = [
        {"structured_status": "PRODUCT_MATCH"},
        {"structured_status": "PRODUCT_MATCH"},
        {"structured_status": "MISSING"},
    ]

    assert HARVEST.record_structured_counts(records) == {
        "rows": 3,
        "structured_product_matches": 2,
        "structured_missing": 1,
        "structured_mismatches": 0,
    }


def test_only_the_primary_card_image_is_retained_for_review() -> None:
    page = (
        '<img class="product-page__image-main-img" '
        'src="https://kemp.ua/image/cache/thumb.jpg" '
        'data-full="https://kemp.ua/image/catalog/full.jpg">'
        '<img class="product-page__image-addit-img" '
        'src="https://kemp.ua/image/cache/related.jpg">'
    )

    assert HARVEST.read_card_image(page) == (
        "https://kemp.ua/image/catalog/full.jpg"
    )


def test_image_parser_does_not_use_social_logo_or_related_thumbnail() -> None:
    page = (
        '<meta property="og:image" content="https://kemp.ua/logo.svg">'
        '<img class="product-page__image-addit-img" '
        'src="https://kemp.ua/image/cache/related.jpg">'
    )

    assert HARVEST.read_card_image(page) == ""


def test_the_manufacturer_row_is_not_mistaken_for_a_number_field() -> None:
    """``manufacturer`` sits between ``sku`` and ``mpn`` and holds a link."""

    assert "KEMP" not in HARVEST.read_card(CARD).values()


def test_missing_fields_come_back_empty_rather_than_absent() -> None:
    card = HARVEST.read_card('<div class="product-data"></div>')

    assert card == {"model": "", "sku": "", "mpn": ""}


def test_a_card_with_the_expected_markup_counts_as_parsed() -> None:
    assert HARVEST.card_looks_parsed(CARD, HARVEST.read_card(CARD)) is True


def test_a_page_without_the_data_block_is_not_a_parse_failure() -> None:
    """Some search hits are not product cards at all; that is data, not breakage."""

    page = "<html><body>Немає товарів</body></html>"

    assert HARVEST.card_looks_parsed(page, HARVEST.read_card(page)) is True


def test_a_renamed_field_class_is_reported_as_a_parse_failure() -> None:
    """The block is still there, so the site did not stop having cards — our
    reader stopped understanding them. Fail closed."""

    renamed = CARD.replace("product-data__item mpn", "product-data__item partno")
    card = HARVEST.read_card(renamed)

    assert card["mpn"] == ""
    assert HARVEST.card_looks_parsed(renamed, card) is False


def test_population_excludes_vehicle_manufacturer_rows(tmp_path) -> None:
    """WP-1B harvests only the positions where no OE is known from anywhere."""

    csv_path = tmp_path / "reference.csv"
    csv_path.write_text(
        "name,mpn,make,article,article_brand\n"
        "Амортизатор,77641229,KEMP,27C06F,Boge\n"
        "Амортизатор капота,77641543,KEMP,4B0823359A,VAG\n"
        "Радиатор,77642751,KEMP,606554,Nissens\n"
        "Без кода,,KEMP,123,Sachs\n"
        "Без бренда,77649999,KEMP,999,\n",
        encoding="utf-8",
    )

    population = HARVEST.load_population(csv_path)

    assert [row["mpn"] for row in population] == ["77641229", "77642751"]


def test_an_explicit_code_list_replaces_the_brand_heuristic(tmp_path) -> None:
    """The brand filter was a proxy for "no OE is known"; identity status is
    the fact itself.  A code that stayed MPN_ONLY has to be probed whatever
    its article brand says, and a code that resolved must not be probed again.
    """

    csv_path = tmp_path / "reference.csv"
    csv_path.write_text(
        "name,mpn,make,article,article_brand\n"
        "Амортизатор,77641229,KEMP,27C06F,Boge\n"
        "Амортизатор капота,77641543,KEMP,4B0823359A,VAG\n"
        "Радиатор,77642751,KEMP,606554,Nissens\n",
        encoding="utf-8",
    )

    population = HARVEST.load_population(csv_path, codes={"77641543"})

    assert [row["mpn"] for row in population] == ["77641543"]


def test_a_code_is_probed_once_across_both_reference_editions(tmp_path) -> None:
    """The two editions overlap.  Probing a code twice would double the traffic
    and write the same card into the dataset under two article columns."""

    first = tmp_path / "v1.csv"
    first.write_text(
        "name,mpn,make,article,article_brand\n"
        "Радиатор,77642751,KEMP,,Nissens\n",
        encoding="utf-8",
    )
    second = tmp_path / "v2.csv"
    second.write_text(
        "name,oe,mpn,article,make\n"
        "Радіатор,1234567,77642751,606554,KEMP\n"
        "Маточина,31211128157,77641360,561948-AEZ72,KEMP\n",
        encoding="utf-8",
    )

    population = HARVEST.load_population(
        [first, second], codes={"77642751", "77641360"}
    )

    assert [row["mpn"] for row in population] == ["77641360", "77642751"]
    # The edition that knows the article wins: an empty ``article`` would make
    # the harvest report an already-known number as a fresh OE candidate.
    assert [row["article"] for row in population] == ["561948-AEZ72", "606554"]


def test_neither_edition_knowing_the_article_keeps_the_richer_row(tmp_path) -> None:
    """A replacement has to be an improvement, not merely the later file.

    Only ``article`` decides the winner, and when both are empty there is
    nothing to decide. Taking the later row anyway drops the columns the
    other edition does carry — ``article_brand`` is provenance a reviewer
    reads, and losing it is a silent data loss.
    """

    first = tmp_path / "v1.csv"
    first.write_text(
        "name,mpn,make,article,article_brand\n"
        "Датчик,77645614,KEMP,,HC Parts\n",
        encoding="utf-8",
    )
    second = tmp_path / "v2.csv"
    second.write_text(
        "name,oe,mpn,article,make\n"
        "Датчик,,77645614,,KEMP\n",
        encoding="utf-8",
    )

    population = HARVEST.load_population([first, second], codes={"77645614"})

    assert [row.get("article_brand") for row in population] == ["HC Parts"]


@pytest.mark.parametrize(
    "line",
    [
        "Disallow: /index.php?route=product/search",
        "disallow: /*route=product/search*",
    ],
)
def test_harvest_refuses_to_run_when_robots_forbids_search(line, monkeypatch) -> None:
    """The measurement ran under a robots.txt that allowed search. If that
    changes, stopping is the only honest response."""

    class _Fetcher:
        def get(self, url: str) -> str:
            return f"User-agent: *\n{line}\n"

    with pytest.raises(SystemExit):
        HARVEST.check_robots(_Fetcher())


def test_unrelated_disallow_rules_do_not_stop_the_harvest() -> None:
    class _Fetcher:
        def get(self, url: str) -> str:
            return "User-agent: *\nDisallow: /*route=checkout/\nDisallow: /catalog\n"

    HARVEST.check_robots(_Fetcher())
