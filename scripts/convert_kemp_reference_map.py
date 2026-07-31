"""Convert the KEMP reference workbook to the committed CSV dataset.

Run once per workbook revision, not as part of any pipeline.

The workbook is a legacy OLE2/BIFF ``.xls``.  ``openpyxl``, the only spreadsheet
package in ``pyproject.toml``, cannot read that format, and adding ``xlrd`` as a
permanent dependency to serve a file that changes a few times a year is a poor
trade.  So this script asks for ``xlrd`` on demand and says so plainly when it
is missing:

    uv pip install --python backend/.venv/bin/python xlrd
    python scripts/convert_kemp_reference_map.py <workbook.xls> backend/data/kemp_reference_map.csv
    uv pip uninstall --python backend/.venv/bin/python xlrd

Output is deterministic: same workbook in, byte-identical CSV out, so the
sha256 recorded against a harvest can be re-derived from the source.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

#: Workbook layouts seen so far, keyed by their header row, each mapping to the
#: canonical CSV column names in source order.  The export changed shape
#: between 2026-07-28 and 2026-07-29 — it lost the article's brand and gained a
#: column of OE numbers — and the two revisions are not interchangeable, so the
#: layout is recognised by header name rather than by column order.  An unknown
#: header stops the conversion instead of shifting every value one column left.
#:
#: Each layout keeps its own column set rather than a shared superset: the CSV
#: of the 2026-07-28 workbook is already committed and its sha256 is recorded in
#: the WP-1B harvest manifest as the input that harvest actually ran against.
#: Padding it with an empty column would change that hash and quietly falsify
#: the record.  The loader treats the differing columns as optional.
LAYOUTS: dict[tuple[str, ...], tuple[str, ...]] = {
    (
        "Наименование",
        "Номер производителя",
        "Фирма изготовитель",
        "Артикул",
        "фирма по артикулу",
    ): ("name", "mpn", "make", "article", "article_brand"),
    (
        "Наименование",
        "Номер",
        "Номер производителя",
        "Артикул",
        "Фирма изготовитель",
    ): ("name", "oe", "mpn", "article", "make"),
}


def _clean(value: object) -> str:
    """Excel gives back floats for numeric cells and NBSP inside brand names."""

    if isinstance(value, float) and value.is_integer():
        text = str(int(value))
    else:
        text = str(value)
    return text.replace("\xa0", " ").strip()


def _rows(sheet) -> tuple[tuple[str, ...], list[list[str]]]:
    header = tuple(_clean(sheet.cell_value(0, column)) for column in range(sheet.ncols))
    columns = LAYOUTS.get(header)
    if columns is None:
        known = "\n".join("  " + " | ".join(layout) for layout in LAYOUTS)
        raise SystemExit(
            f"Unknown workbook layout: {' | '.join(header)}\nKnown layouts:\n{known}"
        )
    out = []
    for index in range(1, sheet.nrows):
        values = [_clean(sheet.cell_value(index, column)) for column in range(len(columns))]
        if not any(values):
            continue
        out.append(values)
    return columns, out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    try:
        import xlrd
    except ModuleNotFoundError:
        print(
            "xlrd is not installed and is deliberately not a project dependency.\n"
            "  uv pip install --python backend/.venv/bin/python xlrd",
            file=sys.stderr,
        )
        return 2

    book = xlrd.open_workbook(args.workbook)
    if book.nsheets != 1:
        # The catalogue export taught us that a stray second sheet silently wins
        # over the real one; refuse rather than guess.
        raise SystemExit(f"Expected exactly one sheet, found {book.nsheets}")
    columns, rows = _rows(book.sheet_by_index(0))

    args.destination.parent.mkdir(parents=True, exist_ok=True)
    with args.destination.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        writer.writerows(rows)

    digest = hashlib.sha256(args.destination.read_bytes()).hexdigest()
    print(f"rows={len(rows)} sha256={digest} -> {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
