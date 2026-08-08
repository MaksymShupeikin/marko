"""The driver that turns saved avto.pro part pages into an ingestible dataset.

The parsing is already covered by ``test_avto_pro_parse``; the ingestion by
``test_avtopro_card_source``.  What this driver adds is everything between:
which codes get visited, whether a page's URL really belongs to the code it is
filed under, and — the part that breaks silently — whether a page that rendered
tiles actually gave up its numbers.

The last one is the whole reason the script exists as a script.  A redesign of
the tile markup produces cards with zero numbers, which reads downstream as
"avto.pro knows no OE for these parts".  That is the failure this file is
written to make loud.
"""

from __future__ import annotations

import csv
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from marko.services.catalog_identity_reparse import load_avtopro_source
from metis.pricing.avto_pro import load_avto_pro_tokens, parse_part_page

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
TOKENS_PATH = BACKEND / "config/avto_pro_tokens.yaml"
TOKENS = load_avto_pro_tokens(TOKENS_PATH)
CARD_HTML = BACKEND / "tests/fixtures/avto_pro/part_page_kemp_77641834.html"
WAF_HTML = BACKEND / "tests/fixtures/avto_pro/waf_challenge.html"


def _harvest() -> ModuleType:
    path = ROOT / "scripts/avtopro_part_harvest.py"
    spec = importlib.util.spec_from_file_location("avtopro_part_harvest", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HARVEST = _harvest()


def _targets(tmp_path: Path, *codes: str) -> Path:
    path = tmp_path / "targets.csv"
    path.write_text(
        "код_kemp,статус,название\n"
        + "".join(f"{code},MPN_ONLY,Деталь\n" for code in codes),
        encoding="utf-8",
    )
    return path


def _urls(tmp_path: Path, *pairs: tuple[str, str]) -> Path:
    path = tmp_path / "urls.csv"
    path.write_text(
        "код_kemp,ссылка\n" + "".join(f"{code},{url}\n" for code, url in pairs),
        encoding="utf-8",
    )
    return path


# --------------------------------------------------------------- the population


def test_targets_are_read_by_their_normalized_code(tmp_path) -> None:
    """The customer's book writes ``7764 586``; every URL writes ``7764586``.
    Comparing the two spellings by eye is what created the phantom join."""

    path = _targets(tmp_path, "77641834", "7764 586")

    assert HARVEST.load_targets(path) == {"77641834", "7764586"}


def test_a_url_outside_the_target_population_is_dropped(tmp_path) -> None:
    """The brand listing covers the whole catalogue.  Fetching a code whose OE
    is already confirmed spends a request to learn nothing."""

    targets = HARVEST.load_targets(_targets(tmp_path, "77641834"))
    urls = _urls(
        tmp_path,
        ("77641834", "https://avto.pro/part-77641834-KEMP-562/"),
        ("77642465", "https://avto.pro/part-77642465-KEMP-562/"),
    )

    assert HARVEST.load_url_map([urls], targets=targets) == {
        "77641834": "https://avto.pro/part-77641834-KEMP-562/"
    }


@pytest.mark.parametrize(
    "url",
    [
        "https://avto.pro/part-77649999-KEMP-562/",
        "https://avto.pro/part-77641834-FEBI-562/",
        "http://avto.pro/part-77641834-KEMP-562/",
        "https://avto.pro/search/?q=77641834",
    ],
)
def test_a_url_that_does_not_bind_its_code_stops_the_run(tmp_path, url) -> None:
    """A mis-filed URL would attribute another part's numbers to this code, and
    nothing downstream could tell.  The loader refuses such a row too; refusing
    here costs one run instead of one dataset."""

    targets = HARVEST.load_targets(_targets(tmp_path, "77641834"))

    with pytest.raises(SystemExit, match="77641834"):
        HARVEST.load_url_map([_urls(tmp_path, ("77641834", url))], targets=targets)


# ------------------------------------------------------------ the silent break


def test_a_renamed_section_id_is_a_parse_failure_not_an_empty_card() -> None:
    """This is the redesign that hides itself.

    The section ids are how the parser tells the maker's numbers from the
    analogs; rename them and both sections simply stop existing.  The page
    still renders, still lists every cross, and the harvest records a part for
    which avto.pro knows nothing.
    """

    renamed = CARD_HTML.read_text(encoding="utf-8").replace(
        "original-manufacturers", "original-makers"
    ).replace("analog-parts", "analog-tiles")
    card = parse_part_page(renamed, TOKENS, url=None)

    assert card.numbers  # the self article still parses, which is the trap
    assert HARVEST.card_looks_parsed(renamed, card) is False


def test_a_stale_link_regex_inside_a_living_section_is_a_parse_failure() -> None:
    """The other redesign: the sections are still found, still full of card
    links, and the parser's href pattern no longer matches them.

    Dropping the trailing slash is enough to do it.  The census counts
    ``/part-`` by substring precisely so it does not go blind at the same
    moment the parser does.
    """

    html = CARD_HTML.read_text(encoding="utf-8")
    broken = html.replace('/" class="feed-pages-tile__link"', '" class="x"')
    card = parse_part_page(broken, TOKENS, url=None)
    census = HARVEST.census_part_tiles(broken, TOKENS)

    assert census.sections_present == 2
    assert census.tiles_in_sections == 0
    assert census.part_paths_in_markup > 5
    assert HARVEST.card_looks_parsed(broken, card) is False


def test_a_page_with_no_tiles_at_all_is_not_a_parse_failure() -> None:
    """avto.pro simply not knowing this part is ordinary data, and the run has
    to be able to record it."""

    page = (
        '<html><body><main class="part-page">'
        "<h1>77649999 Kemp Деталь</h1></main></body></html>"
    )
    card = parse_part_page(page, TOKENS, url=None)

    assert HARVEST.card_looks_parsed(page, card) is True


def test_the_captured_card_passes_the_guard() -> None:
    html = CARD_HTML.read_text(encoding="utf-8")
    card = parse_part_page(html, TOKENS, url=None)

    assert HARVEST.card_looks_parsed(html, card) is True


# --------------------------------------------------------------------- the run


def test_a_blocked_page_is_quarantined_and_stops_the_run(tmp_path) -> None:
    """A WAF challenge is not a card without numbers.  Writing it into the
    dataset would publish an absence the site never stated, and the identity
    loader refuses such a row anyway — so the run stops at the source."""

    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "77641834.html").write_text(
        WAF_HTML.read_text(encoding="utf-8"), encoding="utf-8"
    )
    out = tmp_path / "dataset.csv"
    quarantine = tmp_path / "quarantine.csv"

    code = HARVEST.main(
        [
            "--targets", str(_targets(tmp_path, "77641834")),
            "--urls", str(_urls(
                tmp_path, ("77641834", "https://avto.pro/part-77641834-KEMP-562/")
            )),
            "--html-dir", str(html_dir),
            "--out", str(out),
            "--quarantine", str(quarantine),
            "--manifest", str(tmp_path / "manifest.json"),
        ]
    )

    assert code != 0
    rows = list(csv.DictReader(quarantine.open(encoding="utf-8")))
    assert [row["extraction_status"] for row in rows] == ["WAF"]
    assert not out.exists()


def test_the_run_writes_rows_the_identity_loader_accepts(tmp_path) -> None:
    """The driver's only job is to feed ``load_avtopro_source``.  Asserting on
    its columns would test my idea of that contract; loading them tests it."""

    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "77641834.html").write_text(
        CARD_HTML.read_text(encoding="utf-8"), encoding="utf-8"
    )
    out = tmp_path / "dataset.csv"
    manifest = tmp_path / "manifest.json"

    code = HARVEST.main(
        [
            "--targets", str(_targets(tmp_path, "77641834")),
            "--urls", str(_urls(
                tmp_path, ("77641834", "https://avto.pro/part-77641834-KEMP-562/")
            )),
            "--html-dir", str(html_dir),
            "--out", str(out),
            "--quarantine", str(tmp_path / "quarantine.csv"),
            "--manifest", str(manifest),
        ]
    )

    assert code == 0
    oe, cross = load_avtopro_source(out)
    assert "132915010" in oe["77641834"].numbers
    assert "KSA8112I" in cross["77641834"].numbers

    counters = json.loads(manifest.read_text(encoding="utf-8"))
    assert counters["counters"] == {
        "targets": 1,
        "with_url": 1,
        "pages_read": 1,
        "quarantined": 0,
        "unparsed_cards": 0,
        "with_oe_candidate": 1,
        "requests_made": 0,
    }


def test_the_manifest_pins_both_the_dataset_and_the_rules_that_made_it(
    tmp_path,
) -> None:
    """A dataset whose token config is unknown cannot be re-derived, and the
    brand filter in that config decides which numbers counted as OE."""

    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "77641834.html").write_text(
        CARD_HTML.read_text(encoding="utf-8"), encoding="utf-8"
    )
    manifest = tmp_path / "manifest.json"

    HARVEST.main(
        [
            "--targets", str(_targets(tmp_path, "77641834")),
            "--urls", str(_urls(
                tmp_path, ("77641834", "https://avto.pro/part-77641834-KEMP-562/")
            )),
            "--html-dir", str(html_dir),
            "--out", str(tmp_path / "dataset.csv"),
            "--quarantine", str(tmp_path / "quarantine.csv"),
            "--manifest", str(manifest),
        ]
    )

    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["extraction_method"] == "AVTO_PRO_OPTKIEV"
    assert len(payload["dataset_sha256"]) == 64
    assert len(payload["token_config_sha256"]) == 64
    # Every page that produced a row is nameable, so a disputed number leads
    # back to the exact capture rather than to "the harvest".
    assert payload["page_sha256s"]["77641834"]


def test_a_target_without_a_url_is_counted_rather_than_invented(tmp_path) -> None:
    """The suffix in a card URL is opaque, so a code the listing did not cover
    cannot be reached by building a URL for it."""

    html_dir = tmp_path / "html"
    html_dir.mkdir()
    (html_dir / "77641834.html").write_text(
        CARD_HTML.read_text(encoding="utf-8"), encoding="utf-8"
    )
    manifest = tmp_path / "manifest.json"

    HARVEST.main(
        [
            "--targets", str(_targets(tmp_path, "77641834", "77649999")),
            "--urls", str(_urls(
                tmp_path, ("77641834", "https://avto.pro/part-77641834-KEMP-562/")
            )),
            "--html-dir", str(html_dir),
            "--out", str(tmp_path / "dataset.csv"),
            "--quarantine", str(tmp_path / "quarantine.csv"),
            "--manifest", str(manifest),
        ]
    )

    counters = json.loads(manifest.read_text(encoding="utf-8"))["counters"]
    assert counters["targets"] == 2
    assert counters["with_url"] == 1
