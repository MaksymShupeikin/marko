"""Command-line access to the Prom parser."""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from marko.parsers.prom import PromGateway, ScrapeConfig
from marko.services.parser_models import Product

log = logging.getLogger(__name__)
_DEFAULT_SCRAPE_CONFIG = ScrapeConfig()


def _write_rows(
    path: Path,
    *,
    format: str,
    document: Any,
    rows: list[dict[str, Any]],
    columns: list[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if format == "json":
        path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def export_products(products: Iterable[Product], path: Path, format: str) -> int:
    rows = [product.as_dict() for product in products]
    _write_rows(
        path,
        format=format,
        document=rows,
        rows=rows,
        columns=Product.field_names(),
    )
    return len(rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marko", description="Prom parser tools")
    commands = parser.add_subparsers(dest="command", required=True)
    scrape = commands.add_parser("scrape", help="Import a seller catalog")
    scrape.add_argument("url")
    scrape.add_argument("--max-pages", type=int, default=0)
    scrape.add_argument("--start-page", type=int, default=1)
    scrape.add_argument(
        "--concurrency",
        type=int,
        default=_DEFAULT_SCRAPE_CONFIG.page_concurrency,
    )
    scrape.add_argument("--output", "-o", default="products")
    scrape.add_argument("--format", "-f", choices=("json", "csv"), default="json")
    scrape.add_argument("--delay", type=float, default=_DEFAULT_SCRAPE_CONFIG.delay)
    scrape.add_argument("--verbose", "-v", action="store_true")
    return parser


def _scrape(args: argparse.Namespace) -> int:
    products = PromGateway(
        ScrapeConfig(
            delay=args.delay,
            max_pages=args.max_pages,
            start_page=args.start_page,
            page_concurrency=args.concurrency,
        )
    ).scrape(args.url)
    path = Path(f"{args.output}.{args.format}")
    count = export_products(products, path, args.format)
    print(f"OK: {count} товарів -> {path}")
    return 0 if count else 1


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return _scrape(args)
    except (RuntimeError, ValueError) as exc:
        print(f"Помилка: {exc}")
        return 2
