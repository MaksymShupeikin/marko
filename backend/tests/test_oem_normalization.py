from __future__ import annotations

import pytest

from marko.services.catalog_characteristics import (
    normalize_part_number as normalize_characteristic_part,
)
from marko.services.xlsx_catalog import normalize_identifier
from metis.fitment import normalize_part_number as normalize_fitment_part
from metis.identifiers import OEM_HOMOGLYPHS, normalize_oem_identifier
from metis.pricing import normalize_candidate_oem, normalize_oe
from metis.pricing.crosses import normalize_cross_oem


NORMALIZERS = (
    normalize_oem_identifier,
    normalize_cross_oem,
    normalize_candidate_oem,
    normalize_oe,
    normalize_fitment_part,
    normalize_identifier,
    normalize_characteristic_part,
)


@pytest.mark.parametrize(("cyrillic", "latin"), OEM_HOMOGLYPHS.items())
def test_each_supported_cyrillic_homoglyph_folds_inside_an_oem(
    cyrillic: str,
    latin: str,
) -> None:
    for normalize in NORMALIZERS:
        assert normalize(f"4{cyrillic}0807345A") == f"4{latin}0807345A"


def test_reported_mixed_script_oem_matches_its_latin_form() -> None:
    for normalize in NORMALIZERS:
        assert normalize("4А0807345A") == normalize("4A0807345A") == "4A0807345A"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("А11-2905010ВG", "A112905010BG"),
        ("058109601С_611AM", "058109601C611AM"),
        ("КМ 533", "KM533"),
        ("ОЕ-123", "OE123"),
        ("АВС123", "ABC123"),
    ],
)
def test_wrong_keyboard_layout_identifiers_are_recovered(
    raw: str, expected: str
) -> None:
    for normalize in NORMALIZERS:
        assert normalize(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("96182261 плоск", "96182261"),
        ("1618142 металл", "1618142"),
        ("96536527 круг", "96536527"),
        ("МОТОР 123", "123"),
        ("амортизатор 4А0807345A", "4A0807345A"),
    ],
)
def test_cyrillic_annotations_do_not_become_identifier_fragments(
    raw: str,
    expected: str,
) -> None:
    for normalize in NORMALIZERS:
        assert normalize(raw) == expected
