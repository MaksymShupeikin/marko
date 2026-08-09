from __future__ import annotations

from pathlib import Path
import re

from metis.identifiers import OEM_HOMOGLYPHS, normalize_oem_identifier


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations"
    / "versions"
    / "20260809_0050_listing_internal_code_join.py"
)

# The two quoted arguments of the SQL ``translate`` call: a run of non-ASCII
# letters mapped onto the same number of ASCII ones.
_TRANSLATE_RE = re.compile(
    r"'(?P<source>[^\x00-\x7f']{10,})',\s*'(?P<target>[A-Z]{10,})'"
)


def _sql_homoglyph_map() -> dict[str, str]:
    """The Cyrillic->Latin folding the join key applies inside PostgreSQL."""

    source_text = MIGRATION.read_text(encoding="utf-8")
    assert "translate(" in source_text, (
        "the join key must fold confusable Cyrillic letters in SQL: "
        "marko_catalog_normalize keeps them, normalize_oem_identifier does not"
    )
    match = _TRANSLATE_RE.search(source_text)
    assert match is not None, (
        "the join key must fold confusable Cyrillic letters in SQL: "
        "marko_catalog_normalize keeps them, normalize_oem_identifier does not"
    )
    source = match.group("source")
    target = match.group("target")
    assert len(source) == len(target)
    return dict(zip(source, target, strict=True))


def test_sql_join_key_folds_exactly_the_letters_python_folds() -> None:
    """Two normalizers over one join column is a silent miss, not a mismatch.

    ``catalog_items.internal_code_norm`` is written by ``normalize_identifier``,
    which folds confusable Cyrillic letters into Latin ones.  The listing side
    derives its key in SQL.  If the two disagree on a single letter the position
    simply never joins, and nothing reports why.
    """

    assert _sql_homoglyph_map() == dict(OEM_HOMOGLYPHS)


def test_the_observed_prom_card_code_needs_the_folding() -> None:
    """Measured on the customer's own Prom export, 2026-08-09.

    The card characteristic "Kod zapchastyny" carries ``77643352`` followed by a
    Cyrillic ``s``; the catalogue row for the same position carries a Latin
    ``C``.  Without folding the SQL key is a different string and the position
    never joins.
    """

    observed = "77643352\u0441"

    assert normalize_oem_identifier(observed) == "77643352C"
    folded = observed.upper().translate(str.maketrans(_sql_homoglyph_map()))
    assert re.sub(r"[^A-Z0-9]", "", folded) == normalize_oem_identifier(observed)
