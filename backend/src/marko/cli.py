"""Command-line access to the Prom parser and comparison engine."""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from marko.parsers.prom import PromGateway, ScrapeConfig
from marko.services.matching import Match, Offer, PriceComparison
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


def export_comparison(comparison: PriceComparison, path: Path, format: str) -> int:
    document = comparison.as_dict()
    rows = document["offers"]
    columns = list(rows[0]) if rows else []
    _write_rows(
        path,
        format=format,
        document=document,
        rows=rows,
        columns=columns,
    )
    return len(rows)


def _match_marker(match: Match) -> str:
    if match.kind == "fuzzy":
        return f"~{match.score:.0%}"
    return {"model": "=модель", "sku": "=артикул"}.get(match.kind, match.kind)


def _offer_lines(index: int, offer: Offer, currency: str) -> list[str]:
    seller = (offer.product.seller_name or "—")[:32]
    presence = (
        "в наявності"
        if offer.product.is_available
        else (offer.product.presence or "")
    )
    lines = [
        f"  {index:>2}. {offer.price:>10.0f} {currency}  "
        f"{seller:<32} [{_match_marker(offer.match)}] {presence}".rstrip()
    ]
    if offer.product.url:
        lines.append(f"      {offer.product.url}")
    return lines


def format_comparison(comparison: PriceComparison) -> str:
    seed = comparison.seed.product
    currency = seed.currency or ""
    lines = [
        f"Товар:   {seed.name}",
        f"Бренд:   {seed.brand or '—'}   |   ваша ціна: "
        f"{comparison.seed_price or '—'} {currency}".rstrip(),
        "",
    ]
    if not comparison.offers:
        lines.append("Схожих пропозицій в інших продавців не знайдено.")
        return "\n".join(lines)
    lines.append(f"Знайдено пропозицій: {len(comparison.offers)}")
    for index, offer in enumerate(comparison.offers, 1):
        lines.extend(_offer_lines(index, offer, currency))
    lines.extend(
        [
            "",
            f"min {comparison.min_price:.0f} / median "
            f"{comparison.median_price:.0f} / max {comparison.max_price:.0f} "
            f"{currency} · розкид {comparison.spread_pct}%",
        ]
    )
    return "\n".join(lines)


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output", "-o", default="products")
    parser.add_argument("--format", "-f", choices=("json", "csv"), default="json")
    parser.add_argument("--delay", type=float, default=_DEFAULT_SCRAPE_CONFIG.delay)
    parser.add_argument("--verbose", "-v", action="store_true")


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
    _common_arguments(scrape)
    compare = commands.add_parser("compare", help="Compare a product across sellers")
    compare.add_argument("url")
    compare.add_argument("--max-sellers", type=int, default=10)
    compare.add_argument("--threshold", type=float, default=0.55)
    compare.add_argument("--max-search-pages", type=int, default=3)
    compare.add_argument("--query")
    _common_arguments(compare)
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


def _compare(args: argparse.Namespace) -> int:
    comparison = PromGateway(
        ScrapeConfig(
            delay=args.delay,
            max_sellers=args.max_sellers,
            similarity_threshold=args.threshold,
            max_search_pages=args.max_search_pages,
        )
    ).compare(args.url, query=args.query)
    print(format_comparison(comparison))
    if comparison.offers:
        path = Path(f"{args.output}.{args.format}")
        export_comparison(comparison, path, args.format)
        print(f"\nOK: {len(comparison.offers)} продавців -> {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        return _scrape(args) if args.command == "scrape" else _compare(args)
    except (RuntimeError, ValueError) as exc:
        print(f"Помилка: {exc}")
        return 2
