#!/usr/bin/env python3
"""Report what a directory of saved catalogue pages actually contains.

Run this before reading a single number off a harvest. The verdicts come from
``marko.services.oe_page_triage``; this only walks the directory, joins the
manifest and prints a table an operator can act on.

Exits non-zero when any page is unusable, so a harvest cannot be accepted by
looking at a file count.

Example::

    python3 scripts/oe_pages_triage.py \\
        --pages stage3_pages/ \\
        --urls stage3_urls.csv \\
        --targets stage2_all_blocked.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from marko.services.oe_page_triage import triage_page  # noqa: E402


def _read(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {(row.get(key) or "").strip(): row for row in csv.DictReader(handle)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=Path, required=True)
    parser.add_argument("--urls", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args(argv)

    targets = _read(args.targets, "код_kemp")
    urls = _read(args.urls, "код_kemp")

    pages = sorted(p for p in args.pages.iterdir() if p.suffix in {".html", ".htm", ".mhtml"})
    if not pages:
        print(f"нет сохранённых страниц в {args.pages}", file=sys.stderr)
        return 2

    verdicts: Counter[str] = Counter()
    rows: list[dict[str, str]] = []
    unusable = 0
    for page in pages:
        code = page.stem
        target = targets.get(code, {})
        result = triage_page(
            page.read_text(encoding="utf-8", errors="replace"),
            url=(urls.get(code, {}).get("ссылка") or "").strip(),
            expected_article=(target.get("артикул") or "").strip(),
            expected_brand=(target.get("бренд_артикула") or "").strip(),
        )
        verdicts[result.verdict.value] += 1
        if not result.usable:
            unusable += 1
        rows.append(
            {
                "код_kemp": code,
                "артикул": (target.get("артикул") or "").strip(),
                "бренд": (target.get("бренд_артикула") or "").strip(),
                "вердикт": result.verdict.value,
                "годится": "да" if result.usable else "нет",
                "причина": result.reason,
                "ссылка": (urls.get(code, {}).get("ссылка") or "").strip(),
            }
        )
        marker = "  " if result.usable else "! "
        print(f"{marker}{code:<14}{result.verdict.value:<18}{result.reason}")

    print()
    for verdict, count in verdicts.most_common():
        print(f"  {verdict:<18}{count}")
    print(f"\nстраниц {len(pages)}, непригодных {unusable}")

    not_in_targets = [r["код_kemp"] for r in rows if r["код_kemp"] not in targets]
    if not_in_targets:
        print(f"нет в задании: {', '.join(not_in_targets)}", file=sys.stderr)

    if args.report:
        with args.report.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"отчёт -> {args.report}")

    return 1 if unusable else 0


if __name__ == "__main__":
    raise SystemExit(main())
