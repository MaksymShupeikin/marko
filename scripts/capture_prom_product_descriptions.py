#!/usr/bin/env python3
"""Capture a pinned Prom product-description snapshot for offline replay.

The script enriches an existing offer CSV without changing the frozen Apollo
parser.  Every fetched product page is retained as gzip-compressed normalized
HTML and bound to the output row by SHA-256, so cross extraction can be rerun
without another network request.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from marko.parsers.prom.client import HttpClient
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.parser import parse_product_page


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = (
    PROJECT_ROOT / ".artifacts" / "metis_next_steps_20260719" / "METIS_30_OE_OFFERS.csv"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / ".artifacts" / "metis_cross_coverage_20260719"
_PRODUCT_PATH_RE = re.compile(r"^/(?:[a-z]{2}/)?p(?P<id>\d+)-[\w-]+\.html$", re.I)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--delay-jitter", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    args = parser.parse_args()

    if args.limit < 0:
        raise SystemExit("--limit must be zero or positive")
    input_path = args.input.resolve()
    output_dir = args.output_dir.resolve()
    evidence_dir = output_dir / "raw_product_pages"
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "METIS_30_OE_OFFERS_WITH_DESCRIPTIONS.csv"
    manifest_path = output_dir / "METIS_DESCRIPTION_SNAPSHOT_MANIFEST.json"

    rows, fieldnames = _read_rows(input_path)
    selected = rows[: args.limit or None]
    output_rows: list[dict[str, str]] = []
    fetches = 0
    cache_hits = 0

    config = ScrapeConfig(
        delay=args.delay,
        delay_jitter=args.delay_jitter,
        timeout=args.timeout,
        max_attempts=args.max_attempts,
    )
    with HttpClient(config) as client:
        for index, row in enumerate(selected, start=1):
            enriched = dict(row)
            listing_id = row["listing_id"]
            url = row["url"]
            evidence_path = evidence_dir / f"{_safe_filename(listing_id)}.html.gz"
            fetched_at = ""
            status = ""
            error = ""
            normalized_html_sha256 = ""
            description_sha256 = ""
            description = row.get("description") or ""
            try:
                expected_product_id = validate_product_url(url)
                if evidence_path.is_file():
                    html = gzip.decompress(evidence_path.read_bytes()).decode("utf-8")
                    cache_hits += 1
                    status = "REPLAYED"
                else:
                    html = client.get_html(url)
                    evidence_path.write_bytes(gzip.compress(html.encode("utf-8")))
                    fetches += 1
                    status = "FETCHED"
                    fetched_at = datetime.now(UTC).isoformat()
                normalized_html_sha256 = _sha256_bytes(html.encode("utf-8"))
                seed = parse_product_page(html)
                if seed.product.id != expected_product_id:
                    raise ValueError(
                        "product identity mismatch: "
                        f"URL={expected_product_id}, parsed={seed.product.id}"
                    )
                parsed_description = (seed.product.description or "").strip()
                if parsed_description:
                    description = parsed_description
                    description_sha256 = _sha256_bytes(description.encode("utf-8"))
                else:
                    status = f"{status}_NO_DESCRIPTION"
            except Exception as exc:  # preserve every failed row for audit
                status = "FAILED"
                error = f"{type(exc).__name__}: {exc}"

            enriched.update(
                {
                    "description": description,
                    "description_snapshot_status": status,
                    "description_snapshot_error": error,
                    "description_snapshot_fetched_at": fetched_at,
                    "description_sha256": description_sha256,
                    "normalized_html_sha256": normalized_html_sha256,
                    "raw_evidence_path": (
                        str(evidence_path.relative_to(PROJECT_ROOT))
                        if evidence_path.is_file()
                        else ""
                    ),
                }
            )
            output_rows.append(enriched)
            if index % 10 == 0 or index == len(selected):
                _write_rows(output_path, output_rows, _output_fields(fieldnames))
                print(
                    f"captured={index}/{len(selected)} fetched={fetches} "
                    f"replayed={cache_hits} descriptions="
                    f"{sum(bool(item.get('description')) for item in output_rows)}",
                    flush=True,
                )

    status_counts: dict[str, int] = {}
    for row in output_rows:
        status = row["description_snapshot_status"]
        status_counts[status] = status_counts.get(status, 0) + 1
    manifest: dict[str, Any] = {
        "schema_version": "metis-prom-description-snapshot-v1",
        "created_at": datetime.now(UTC).isoformat(),
        "network_scope": "pinned input URLs only",
        "input": {
            "path": str(input_path),
            "sha256": _sha256_file(input_path),
            "rows": len(selected),
        },
        "output": {
            "path": str(output_path),
            "sha256": _sha256_file(output_path),
            "rows": len(output_rows),
        },
        "parser_boundary": {
            "parser_sha256": _sha256_file(
                PROJECT_ROOT / "backend" / "src" / "marko" / "parsers" / "prom" / "parser.py"
            ),
            "parser_models_sha256": _sha256_file(
                PROJECT_ROOT / "backend" / "src" / "marko" / "services" / "parser_models.py"
            ),
        },
        "capture": {
            "network_fetches": fetches,
            "cache_replays": cache_hits,
            "descriptions_available": sum(
                bool(row.get("description")) for row in output_rows
            ),
            "status_counts": status_counts,
            "raw_evidence_files": sum(
                bool(row.get("raw_evidence_path")) for row in output_rows
            ),
        },
    }
    _write_json(manifest_path, manifest)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if status_counts.get("FAILED", 0) == 0 else 2


def validate_product_url(url: str) -> int:
    parsed = urlsplit(url)
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() not in {"prom.ua", "www.prom.ua"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"unsafe or unsupported Prom product URL: {url!r}")
    match = _PRODUCT_PATH_RE.fullmatch(parsed.path)
    if match is None:
        raise ValueError(f"unsupported Prom product path: {parsed.path!r}")
    return int(match.group("id"))


def _read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    if not path.is_file():
        raise SystemExit(f"Input CSV does not exist: {path}")
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        fieldnames = list(reader.fieldnames or ())
        missing = {"listing_id", "url", "description"} - set(fieldnames)
        if missing:
            raise SystemExit(f"Input CSV is missing columns: {sorted(missing)}")
        rows = [dict(row) for row in reader]
    if len({row["listing_id"] for row in rows}) != len(rows):
        raise SystemExit("Input CSV contains duplicate listing_id values")
    return rows, fieldnames


def _output_fields(input_fields: list[str]) -> list[str]:
    additions = [
        "description_snapshot_status",
        "description_snapshot_error",
        "description_snapshot_fetched_at",
        "description_sha256",
        "normalized_html_sha256",
        "raw_evidence_path",
    ]
    return input_fields + [field for field in additions if field not in input_fields]


def _write_rows(path: Path, rows: list[dict[str, str]], fields: list[str]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_filename(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


if __name__ == "__main__":
    raise SystemExit(main())
