#!/usr/bin/env python3
"""Harvest avto.pro ``/part-`` pages for the codes that still have no OE.

``harvest_avto_pro_seller.py`` walks the seller showcase; this walks the part
pages of *our* catalogue codes, which is where the maker's numbers live.  The
population comes from ``plan_identity``: every code that is still ``MPN_ONLY``
or ``UNRESOLVED``.  Codes whose OE is already confirmed are not visited — the
request would buy nothing.

Offline-first, like the rest of the avto.pro work: the normal input is a
directory of saved pages.  ``--fetch`` exists, but Azure WAF challenges are a
hard stop rather than something to retry around, and the card URL cannot be
built from a code (the trailing id is opaque), so a URL map from the brand
listing is required either way.

The run refuses to write a dataset when any page was blocked or looks
unparsed.  A blocked page yields no numbers, and downstream that is
indistinguishable from a part avto.pro knows nothing about — an absence the
site never stated.

Examples::

    PYTHONPATH=backend/src python3 scripts/avtopro_part_harvest.py \\
        --targets avtopro_target_codes.csv \\
        --urls avtopro_part_urls.csv \\
        --html-dir .artifacts/avtopro_pages/ \\
        --out backend/data/avtopro_card_numbers.csv
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
DEFAULT_CONFIG = BACKEND / "config" / "avto_pro_tokens.yaml"
sys.path.insert(0, str(BACKEND / "src"))

from marko.services.catalog_identity_reparse import (  # noqa: E402
    avtopro_card_url_binds_code,
)
from metis.pricing.avto_pro import (  # noqa: E402
    EXTRACTION_METHOD,
    AvtoProTokensConfig,
    ProductCardExtract,
    census_part_tiles,
    extraction_rows_for_csv,
    load_avto_pro_tokens,
    parse_part_page,
)
from metis.pricing.crosses import normalize_cross_oem  # noqa: E402

TOKENS = load_avto_pro_tokens(DEFAULT_CONFIG)

#: Statuses whose rows the identity loader refuses outright.  Quarantining them
#: here keeps the refusal at the run that produced them, where the operator can
#: still do something about it.
BLOCKED_STATUSES = frozenset({"WAF", "PARSE_ERROR", "EMPTY"})

#: How many ``/part-`` paths a page may carry while its cross sections give up
#: nothing before we stop believing the page has no crosses.  A part avto.pro
#: really knows nothing about carries a couple of incidental links; a page whose
#: sections we stopped recognising carries the whole tile list.
LOOSE_PART_PATHS_THRESHOLD = 5

QUARANTINE_COLUMNS = ("code", "url", "extraction_status", "content_sha256", "reason")


def load_targets(path: Path) -> set[str]:
    """The codes worth visiting, by the spelling every URL uses.

    The customer's book writes ``7764 586`` and avto.pro writes ``7764586``.
    Normalizing on the way in is the difference between a join and a phantom.
    """

    codes: set[str] = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            code = normalize_cross_oem((row.get("код_kemp") or "").strip())
            if code:
                codes.add(code)
    return codes


def load_url_map(paths: Sequence[Path], *, targets: set[str]) -> dict[str, str]:
    """Card URLs for the target codes, refusing any that names another card.

    A mis-filed URL attributes one part's numbers to another code, and nothing
    downstream can tell.  The identity loader applies the same check to the
    finished dataset; applying it here costs one run instead of one dataset.
    """

    urls: dict[str, str] = {}
    for path in paths:
        with Path(path).open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                code = normalize_cross_oem((row.get("код_kemp") or "").strip())
                url = (row.get("ссылка") or "").strip()
                if not code or not url or code not in targets:
                    continue
                if not avtopro_card_url_binds_code(url, code):
                    raise SystemExit(
                        f"URL does not belong to code {code}: {url}"
                    )
                urls.setdefault(code, url)
    return urls


def card_looks_parsed(
    html: str,
    card: ProductCardExtract,
    config: AvtoProTokensConfig | None = None,
) -> bool:
    """Did this page keep its crosses to itself, or did we stop reading them?

    Two redesigns produce the same empty output and neither raises anything: a
    renamed section id makes both sections disappear, and a changed link format
    empties sections that are still found.  The census counts ``/part-`` by
    substring, so it stays honest through both.

    A page with no cross markup at all is not a failure.  avto.pro not knowing
    a part is ordinary data, and a harvest that cannot record it is useless.
    """

    census = census_part_tiles(html, config or TOKENS)
    if census.tiles_in_sections:
        return True
    return census.part_paths_in_markup < LOOSE_PART_PATHS_THRESHOLD


def _page_path(html_dir: Path, code: str) -> Path | None:
    direct = html_dir / f"{code}.html"
    if direct.is_file():
        return direct
    for candidate in sorted(html_dir.glob(f"*{code}*.html")):
        return candidate
    return None


def _fetch(url: str) -> str:
    import ssl
    import urllib.request

    # Identifies itself.  Wearing a browser's User-Agent is how you get past a
    # WAF, and getting past a WAF is not something this script decides to do —
    # it is a decision about someone else's site, and it belongs to whoever runs
    # the harvest, not to the harvest.  Offline-first is the supported path.
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "marko-avtopro-part-harvest/1.0",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
    )
    with urllib.request.urlopen(
        request, timeout=25, context=ssl.create_default_context()
    ) as response:
        return response.read().decode("utf-8", errors="replace")


def _write_csv(path: Path, rows: Iterable[dict[str, str]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--urls", type=Path, action="append", required=True)
    parser.add_argument("--html-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--quarantine", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--fetch",
        action="store_true",
        help="Allow network for codes with no saved page (WAF is a hard stop)",
    )
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)

    config = load_avto_pro_tokens(args.config)
    targets = load_targets(args.targets)
    urls = load_url_map(args.urls, targets=targets)

    codes = sorted(urls)
    if args.limit:
        codes = codes[: args.limit]

    rows: list[dict[str, str]] = []
    quarantined: list[dict[str, str]] = []
    page_sha256s: dict[str, str] = {}
    requests_made = 0
    pages_read = 0
    unparsed = 0
    with_oe: set[str] = set()

    for code in codes:
        url = urls[code]
        html: str | None = None
        if args.html_dir is not None:
            path = _page_path(args.html_dir, code)
            if path is not None:
                html = path.read_text(encoding="utf-8", errors="replace")
        if html is None and args.fetch:
            if requests_made:
                time.sleep(args.delay)
            html = _fetch(url)
            requests_made += 1
        if html is None:
            continue

        pages_read += 1
        page_sha256s[code] = hashlib.sha256(html.encode("utf-8")).hexdigest()
        card = parse_part_page(html, config, url=url)
        status = card.extraction_status.value

        if status in BLOCKED_STATUSES:
            quarantined.append(
                {
                    "code": code,
                    "url": url,
                    "extraction_status": status,
                    "content_sha256": card.content_sha256,
                    "reason": "BLOCKED_PAGE",
                }
            )
            continue
        if not card_looks_parsed(html, card, config):
            unparsed += 1
            quarantined.append(
                {
                    "code": code,
                    "url": url,
                    "extraction_status": status,
                    "content_sha256": card.content_sha256,
                    "reason": "UNPARSED_CROSS_SECTIONS",
                }
            )
            continue

        card_rows = extraction_rows_for_csv(
            card,
            seller_slug=card.seller_slug or "",
            product_url=url,
            query=code,
        )
        rows.extend(card_rows)
        if any(row["source_field"] == "oe" for row in card_rows):
            with_oe.add(code)

    counters = {
        "targets": len(targets),
        "with_url": len(urls),
        "pages_read": pages_read,
        "quarantined": len(quarantined),
        "unparsed_cards": unparsed,
        "with_oe_candidate": len(with_oe),
        "requests_made": requests_made,
    }
    manifest: dict[str, object] = {
        "extraction_method": EXTRACTION_METHOD,
        "method_version": config.method_version,
        "token_config_sha256": hashlib.sha256(
            Path(args.config).read_bytes()
        ).hexdigest(),
        "targets_sha256": hashlib.sha256(
            Path(args.targets).read_bytes()
        ).hexdigest(),
        "dataset_sha256": None,
        "counters": counters,
        "page_sha256s": page_sha256s,
    }

    if quarantined:
        _write_csv(args.quarantine, quarantined, QUARANTINE_COLUMNS)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            f"STOP {len(quarantined)} page(s) blocked or unparsed "
            f"-> {args.quarantine}",
            file=sys.stderr,
        )
        return 2

    columns = sorted(rows[0]) if rows else ["query", "article_raw"]
    _write_csv(args.out, rows, columns)
    manifest["dataset_sha256"] = hashlib.sha256(
        args.out.read_bytes()
    ).hexdigest()
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"OK pages={pages_read} rows={len(rows)} "
        f"with_oe={len(with_oe)} -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
