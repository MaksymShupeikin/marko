"""CLI for strict scraper architecture audit summary validation."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .scraper_audit_summary import (
    ScraperAuditSummaryError,
    parse_scraper_audit_yaml,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate a scraper-architecture-audit.v2 YAML manifest."
    )
    parser.add_argument("--manifest", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        parse_scraper_audit_yaml(args.manifest.read_text(encoding="utf-8"))
    except (OSError, ScraperAuditSummaryError) as exc:
        print(f"SCRAPER_AUDIT_SUMMARY_INVALID: {exc}", file=sys.stderr)
        return 1
    print("SCRAPER_AUDIT_SUMMARY_VALID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
