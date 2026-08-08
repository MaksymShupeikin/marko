#!/usr/bin/env python3
"""Offline-first OPTKiev seller harvest for Avto.pro.

Pure HTML parse only — network is optional and fail-closed on Azure WAF.

Default input is a saved seller profile HTML.  The public ``/seller/optkiev/``
page only embeds a short showcase carousel (~20 tiles), not the full stock.
Each showcase card URL is a ``/part-`` page; pass ``--enrich-parts`` with
saved part HTML or enable network to run :func:`parse_part_page` for OE.

Examples::

    PYTHONPATH=backend/src python3 scripts/harvest_avto_pro_seller.py \\
        --html .artifacts/avto_pro_card_probe_20260807/seller.html

    PYTHONPATH=backend/src python3 scripts/harvest_avto_pro_seller.py \\
        --html seller.html --enrich-part-html-dir .artifacts/parts/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
DEFAULT_CONFIG = BACKEND_ROOT / "config" / "avto_pro_tokens.yaml"
sys.path.insert(0, str(BACKEND_ROOT / "src"))

from metis.pricing.avto_pro import (  # noqa: E402
    EXTRACTION_METHOD,
    ExtractionStatus,
    load_avto_pro_tokens,
    parse_part_page,
    parse_seller_profile,
    seller_profile_to_dict,
)


def _load_html(path: Path | None, url: str | None) -> tuple[str, str]:
    if path is not None:
        return path.read_text(encoding="utf-8", errors="replace"), str(path)
    if not url:
        raise SystemExit("Provide --html PATH or --fetch-url URL")
    try:
        import urllib.request
        import ssl

        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return body, url
    except Exception as exc:  # noqa: BLE001 — CLI surface
        raise SystemExit(f"Fetch failed ({type(exc).__name__}): {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html", type=Path, help="Saved seller profile HTML")
    parser.add_argument(
        "--fetch-url",
        default=None,
        help="Optional live URL (often blocked by Azure WAF)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="avto_pro_tokens.yaml path",
    )
    parser.add_argument(
        "--seller-slug",
        default="optkiev",
        help="Seller slug (default optkiev)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("optkiev_seller_harvest.json"),
        help="Output JSON path",
    )
    parser.add_argument(
        "--enrich-part-html-dir",
        type=Path,
        default=None,
        help="Directory of saved part-*.html to attach OE candidates",
    )
    args = parser.parse_args(argv)

    config = load_avto_pro_tokens(args.config)
    html, source = _load_html(args.html, args.fetch_url)
    profile = parse_seller_profile(html, config, seller_slug=args.seller_slug)
    payload = seller_profile_to_dict(profile)
    payload["source"] = source
    payload["extraction_method"] = EXTRACTION_METHOD
    payload["method_version"] = config.method_version

    if profile.extraction_status is ExtractionStatus.WAF:
        payload["error"] = "WAF_CHALLENGE"
        args.out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"WAF challenge — wrote {args.out}", file=sys.stderr)
        return 2

    if args.enrich_part_html_dir and args.enrich_part_html_dir.is_dir():
        by_article: dict[str, Path] = {}
        for path in args.enrich_part_html_dir.glob("*.html"):
            by_article[path.stem.upper()] = path
        enriched = []
        for card in payload["cards"]:
            row = dict(card)
            article = (card.get("article") or "").upper()
            # match part_part-CODE-BRAND-ID.html or part-CODE-...
            match = None
            for key, path in by_article.items():
                if article and article in key.upper():
                    match = path
                    break
            if match is None:
                row["oe_candidates"] = []
                row["part_parse_status"] = "NO_LOCAL_HTML"
            else:
                part = parse_part_page(
                    match.read_text(encoding="utf-8", errors="replace"),
                    config,
                    url=card.get("url") or None,
                )
                row["part_parse_status"] = part.extraction_status.value
                row["oe_candidates"] = [
                    {
                        "raw": n.raw,
                        "norm": n.normalized,
                        "brand": n.brand_raw or "",
                    }
                    for n in part.numbers
                    if n.source_field == "oe"
                ]
                row["full_title"] = part.title or ""
            enriched.append(row)
        payload["cards"] = enriched

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"OK status={profile.extraction_status.value} "
        f"cards={payload['cards_count']} "
        f"catalog_seeds={len(payload['catalog_seeds'])} "
        f"email={payload['seller_info'].get('email')!r} "
        f"-> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
