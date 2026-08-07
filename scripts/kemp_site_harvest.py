"""Harvest OE numbers off kemp.ua product cards (WP-1B).

Offline data collection, deliberately outside the pricing path: the network is
touched here and nowhere else, and the only thing downstream reads is the CSV
this script writes (NO_10).  Import stays deterministic because it reads a file
with a known sha256.

Population, by default: reference-map rows whose ``article_brand`` is a
component supplier.  For those the article is not an OE and no OE is known from
anywhere.  Rows whose brand is a vehicle maker are skipped — the control
measurement showed the site merely confirms the reference map there (161 of
162).

That brand rule is a *proxy* for "no OE is known".  ``--codes`` states the fact
instead: pass the codes the identity reparse still reports ``MPN_ONLY`` /
``UNRESOLVED`` and the brand stops mattering.  Pass every code previously
probed as well — dropping one would remove its evidence from the dataset, and
cached responses make re-probing free.

A card counts as ours only when its ``Номер виробника`` equals the code we
searched for.  The site's search also matches descriptions, so a hit in the
result list proves nothing: during the measurement 100 codes produced 135
cards.

What the harvest can and cannot do: kemp.ua is declared ``REVIEW`` in
``identity_graph.yaml`` because its field labels are unreliable, so a number
only this site supplies never becomes a confirmed OE on its own.  The output is
review material — a candidate number with its card URL, title and image — not
an automatic identity.

    python scripts/kemp_site_harvest.py \
        --reference backend/data/kemp_reference_map.csv \
        --reference backend/data/kemp_oe_map.csv \
        --codes identity_blocked_codes.txt \
        --out backend/data/kemp_site_numbers.csv

Re-running costs no traffic: every response is cached on disk by URL.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from metis.pricing.kemp_site import (  # noqa: E402
    EXTRACTION_METHOD,
    TokenClass,
    extract_numbers,
    known_number_set,
    load_kemp_site_tokens,
)
from metis.pricing.crosses import normalize_cross_oem  # noqa: E402

BASE = "https://kemp.ua"
SEARCH = BASE + "/index.php?route=product/search&search="
ROBOTS = BASE + "/robots.txt"

# Every vehicle marque appearing in ``article_brand``; everything else is a
# component supplier.  Kept in step with backend/config/article_brand_kinds.yaml
# once WP-2 creates it.
VEHICLE_MAKERS = {
    "VAG", "General Motors", "Mercedes", "Ford", "Renault (RVI)", "Opel",
    "Peugeot/Citroen", "Fiat/Alfa/Lancia", "Chery", "BMW", "Nissan",
    "Evobus/Setra",
}

TILE = re.compile(
    r'product-thumb__name"\s+href="(?P<href>[^"]+)"', re.S
)
# The heading is retained as seed-side semantic evidence.  It is deliberately
# separate from ``read_card``: the legacy three-field contract is consumed by
# the number tokenizer and must remain byte-for-byte compatible.
TITLE = re.compile(
    r'<h1\b[^>]*class="[^"]*heading[^"]*"[^>]*>(?P<value>.*?)</h1>',
    re.S | re.I,
)
MAIN_IMAGE = re.compile(
    r'<img\b(?=[^>]*class="[^"]*product-page__image-main-img[^"]*")'
    r'(?=[^>]*\b(?:data-full|src)="[^"]+")[^>]*>',
    re.S | re.I,
)
FIELD = re.compile(
    r'product-data__item (?P<key>model|sku|mpn)">'
    r'<div class="product-data__item-div">[^<]*</div>\s*(?P<value>.*?)</div>',
    re.S,
)

JSON_LD = re.compile(
    r'<script\b[^>]*\btype=["\']application/ld\+json["\'][^>]*>'
    r'(?P<value>.*?)</script>',
    re.S | re.I,
)

# The measurement ran against this robots.txt.  A change means the site owner
# may have altered what is allowed, and the harvest stops rather than assume.
ROBOTS_SEARCH_RULE = "route=product/search"


@dataclass
class Fetcher:
    cache: Path
    delay: float
    user_agent: str
    attempts: int = 3
    requests_made: int = 0

    def get(self, url: str) -> str:
        key = self.cache / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".html")
        if key.exists():
            return key.read_text(encoding="utf-8", errors="replace")
        last: Exception | None = None
        for attempt in range(1, self.attempts + 1):
            try:
                request = urllib.request.Request(
                    url, headers={"User-Agent": self.user_agent}
                )
                with urllib.request.urlopen(request, timeout=30) as response:
                    body = response.read().decode("utf-8", errors="replace")
                break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = exc
                if attempt == self.attempts:
                    raise
                time.sleep(self.delay * attempt * 2)
        else:  # pragma: no cover - the loop always breaks or raises
            raise RuntimeError(str(last))
        self.cache.mkdir(parents=True, exist_ok=True)
        key.write_text(body, encoding="utf-8")
        self.requests_made += 1
        time.sleep(self.delay)
        return body


def _strip(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()


def read_card(page: str) -> dict[str, str]:
    """Pull the three data fields off a product page.

    Keys are the CSS classes, not the human labels, precisely because the labels
    lie: ``model`` is presented as «ОЕ номер» and ``sku`` as «Артикул», and on
    aftermarket positions the real OE is usually in the latter.
    """

    found = {match.group("key"): _strip(match.group("value")) for match in FIELD.finditer(page)}
    return {key: found.get(key, "") for key in ("model", "sku", "mpn")}


def read_card_title(page: str) -> str:
    """Read only the visible product heading, never price or availability.

    The heading is an evidence hint for seed-side semantic fan-out checks.  It
    cannot authorize a cross by itself, and the harvest keeps the source URL
    beside it so a reviewer can open the exact card.
    """

    match = TITLE.search(page)
    return _strip(match.group("value")) if match else ""


def read_card_image(page: str) -> str:
    """Read the primary product image URL as non-monetary provenance.

    ``og:image`` on the site is the KEMP logo, so it cannot be used for
    product review. The card's main image is the only image retained here;
    thumbnails for related products are intentionally ignored. The URL is
    evidence for a human/vision reviewer, never an automatic identity signal.
    """

    match = MAIN_IMAGE.search(page)
    if match is None:
        return ""
    tag = match.group(0)
    for attribute in ("data-full", "src"):
        value = re.search(
            rf'\b{attribute}="(?P<value>[^"]+)"', tag, re.I | re.S
        )
        if value is not None:
            return html.unescape(value.group("value")).strip()
    return ""


def read_product_jsonld(page: str) -> dict[str, str]:
    """Read non-monetary ``schema.org/Product`` evidence from a card.

    KEMP's visible labels are not a stable contract: the fields rendered as
    ``ОЕ номер`` and ``Артикул`` are known to swap semantic roles on
    aftermarket rows.  The same card currently publishes a structured Product
    object whose ``mpn`` is the private KEMP code and whose title/brand/image
    are independently reviewable.  We use only those identity fields here;
    offer price, currency and availability are deliberately not returned.

    Malformed or non-Product JSON-LD is treated as missing evidence.  The
    caller decides whether a legacy visible-field card may remain in a review
    dataset; it is never silently upgraded to structured evidence.
    """

    for match in JSON_LD.finditer(page):
        raw = html.unescape(match.group("value")).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        for value in values:
            if not isinstance(value, dict):
                continue
            product_type = value.get("@type")
            types = product_type if isinstance(product_type, list) else [product_type]
            if not any(str(item).casefold() == "product" for item in types):
                continue

            brand = value.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")
            images = value.get("image")
            if isinstance(images, list):
                image = next(
                    (str(item).strip() for item in images if str(item).strip()),
                    "",
                )
            else:
                image = str(images or "").strip()
            return {
                "name": str(value.get("name") or "").strip(),
                "brand": str(brand or "").strip(),
                "manufacturer": str(value.get("manufacturer") or "").strip(),
                "model": str(value.get("model") or "").strip(),
                "sku": str(value.get("sku") or "").strip(),
                "mpn": str(value.get("mpn") or "").strip(),
                "description": str(value.get("description") or "").strip(),
                "image": image,
            }
    return {}


def structured_mpn_status(structured: dict[str, str], searched_code: str) -> str:
    """Classify the JSON-LD-to-search binding without accepting a fuzzy match."""

    mpn = normalize_cross_oem(structured.get("mpn"))
    searched = normalize_cross_oem(searched_code)
    if not mpn:
        return "MISSING"
    if mpn != searched:
        return "MPN_MISMATCH"
    return "PRODUCT_MATCH"


def card_looks_parsed(page: str, card: dict[str, str]) -> bool:
    """Tell "this card has no numbers" apart from "we stopped understanding it".

    Without this the harvest fails open: a markup change makes every field come
    back empty, every position reports ``candidates=0``, and the run ends
    looking like a success that found nothing.  ``mpn`` is the sentinel — the
    manufacturer number is present on every card we care about, and it is the
    field the match rule depends on.
    """

    if card["mpn"]:
        return True
    return "product-data__item" not in page


def record_structured_counts(records: list[dict[str, str]]) -> dict[str, int]:
    """Summarize structured binding at the CSV-row level.

    ``main`` also reports card-level parser counters. Keep this separate and
    named so reports cannot accidentally compare one denominator with the
    other when a card emits multiple extracted number rows.
    """

    counts = Counter(row.get("structured_status", "") for row in records)
    return {
        "rows": len(records),
        "structured_product_matches": counts.get("PRODUCT_MATCH", 0),
        "structured_missing": counts.get("MISSING", 0),
        "structured_mismatches": counts.get("MPN_MISMATCH", 0),
    }


def check_robots(fetcher: Fetcher) -> None:
    body = fetcher.get(ROBOTS)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("disallow:") and ROBOTS_SEARCH_RULE in stripped:
            raise SystemExit(
                "robots.txt now disallows product search; harvest stops.\n"
                f"  offending line: {stripped}"
            )


def load_population(
    paths: Path | Sequence[Path],
    *,
    codes: Collection[str] | None = None,
) -> list[dict[str, str]]:
    """The rows to probe, from one or several reference editions.

    Without ``codes`` the original brand heuristic applies: a component-supplier
    article is not an OE, so those rows are the ones the site can close.  That
    was always a proxy.  ``codes`` states the fact directly — pass the codes the
    identity reparse still reports as ``MPN_ONLY``/``UNRESOLVED`` and the brand
    is irrelevant, both for a vehicle-maker row that never resolved and for a
    supplier row that did.
    """

    if isinstance(paths, Path):
        paths = (paths,)
    wanted = None if codes is None else {str(code).strip() for code in codes}
    by_code: dict[str, dict[str, str]] = {}
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                mpn = (row.get("mpn") or "").strip()
                if not mpn:
                    continue
                if wanted is None:
                    brand = (row.get("article_brand") or "").strip()
                    if not brand or brand in VEHICLE_MAKERS:
                        continue
                elif mpn not in wanted:
                    continue
                seen = by_code.get(mpn)
                if seen is None:
                    by_code[mpn] = row
                    continue
                # Editions overlap.  Probing a code twice doubles the traffic
                # and writes the same card under two article columns; keep the
                # edition that knows the article, because an empty one would
                # report an already-known number as a fresh OE candidate.
                # A replacement must be an improvement: when neither edition
                # knows the article there is nothing to decide, and taking the
                # later row anyway drops whatever else the first one carried.
                if not (seen.get("article") or "").strip() and (
                    row.get("article") or ""
                ).strip():
                    by_code[mpn] = row
    if wanted is None:
        return list(by_code.values())
    return [by_code[code] for code in sorted(by_code)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference",
        type=Path,
        action="append",
        dest="references",
        required=True,
        help="A reference edition; repeatable.",
    )
    parser.add_argument(
        "--codes",
        type=Path,
        help=(
            "File of codes, one per line: probe exactly these and ignore the "
            "article-brand heuristic. Use the codes the identity reparse still "
            "reports as MPN_ONLY/UNRESOLVED."
        ),
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "backend" / "config" / "kemp_site_tokens.yaml")
    parser.add_argument("--cache", type=Path, default=REPO_ROOT / ".artifacts" / "kemp_site_cache")
    parser.add_argument("--delay", type=float, default=1.5)
    parser.add_argument("--limit", type=int, default=0, help="stop after N positions")
    parser.add_argument(
        "--user-agent",
        default="Mozilla/5.0 (compatible; MetisHarvest/1.0; owner-authorised catalogue read)",
    )
    args = parser.parse_args()

    config = load_kemp_site_tokens(args.config)
    # One sha per file, named by file. A combined digest under the old
    # singular key would look like a known reference-map revision and match
    # none, which is worse than saying plainly that there were two.
    reference_shas = {
        reference.name: hashlib.sha256(reference.read_bytes()).hexdigest()
        for reference in args.references
    }
    codes = None
    if args.codes is not None:
        codes = {
            line.strip()
            for line in args.codes.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    fetcher = Fetcher(cache=args.cache, delay=args.delay, user_agent=args.user_agent)
    check_robots(fetcher)

    population = load_population(args.references, codes=codes)
    if args.limit:
        population = population[: args.limit]

    records: list[dict[str, str]] = []
    counters: dict[str, int] = {
        "positions": 0, "absent": 0, "ambiguous": 0, "with_candidate": 0,
        "errors": 0, "cards_read": 0, "unparsed_cards": 0,
        "structured_product_matches": 0, "structured_missing": 0,
        "structured_mismatches": 0,
    }

    for index, row in enumerate(population, 1):
        mpn, article = row["mpn"].strip(), (row.get("article") or "").strip()
        counters["positions"] += 1
        try:
            search_page = fetcher.get(SEARCH + urllib.parse.quote(mpn))
            hrefs = [html.unescape(m.group("href")) for m in TILE.finditer(search_page)]
            cards = []
            for href in hrefs:
                page = fetcher.get(href)
                card = read_card(page)
                card_title = read_card_title(page)
                card_image = read_card_image(page)
                structured = read_product_jsonld(page)
                structured_status = structured_mpn_status(structured, mpn)
                counters["cards_read"] += 1
                if not card_looks_parsed(page, card):
                    counters["unparsed_cards"] += 1
                if structured_status == "PRODUCT_MATCH":
                    counters["structured_product_matches"] += 1
                elif structured_status == "MISSING":
                    counters["structured_missing"] += 1
                else:
                    counters["structured_mismatches"] += 1
                # The structured mpn is the binding key when present.  A
                # legacy card without JSON-LD remains visible as review-only,
                # but a present, conflicting Product object is never accepted.
                if (
                    structured_status == "PRODUCT_MATCH"
                    or (
                        structured_status == "MISSING"
                        and card["mpn"].strip() == mpn
                    )
                ):
                    # Keep derived fields attached to the same card URL. A
                    # search can return multiple cards, and a loop-scoped
                    # title/image would otherwise describe the last hit.
                    cards.append(
                        (href, card, card_title, card_image, structured, structured_status)
                    )
        except Exception as exc:  # recorded, never swallowed
            counters["errors"] += 1
            print(f"{index:5d}/{len(population)} {mpn} ERROR {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            continue

        if not cards:
            counters["absent"] += 1
            state = "ABSENT"
        elif len(cards) > 1:
            counters["ambiguous"] += 1
            state = "AMBIGUOUS"
        else:
            state = "OK"

        if state != "OK":
            print(f"{index:5d}/{len(population)} {mpn} {state}", file=sys.stderr)
            continue

        href, card, card_title, card_image, structured, structured_status = cards[0]
        extraction = extract_numbers(
            [("oe", card["model"]), ("sku", card["sku"])],
            config=config,
            known=known_number_set([article, mpn], config),
        )
        candidates = extraction.oe_candidates
        if candidates:
            counters["with_candidate"] += 1
        for token in extraction.tokens:
            if token.token_class is TokenClass.NOISE:
                continue
            records.append(
                {
                    "mpn": mpn,
                    "reference_article": article,
                    "reference_brand": row.get("article_brand", "").strip(),
                    "number_raw": token.raw,
                    "number_norm": token.normalized,
                    "token_class": token.token_class.value,
                    "matched_rule": token.matched_rule or "",
                    "source_field": token.source_field,
                    "source_url": href,
                    "source_title": card_title,
                    "source_image_url": card_image,
                    "structured_status": structured_status,
                    "structured_name": structured.get("name", ""),
                    "structured_brand": structured.get("brand", ""),
                    "structured_model": structured.get("model", ""),
                    "structured_sku": structured.get("sku", ""),
                    "structured_mpn": structured.get("mpn", ""),
                    "structured_image_url": structured.get("image", ""),
                    "raw_oe_field": card["model"],
                    "raw_sku_field": card["sku"],
                    "extraction_method": EXTRACTION_METHOD,
                }
            )
        print(f"{index:5d}/{len(population)} {mpn} OK candidates={len(candidates)}",
              file=sys.stderr)

    # A handful of odd cards is data; a wall of them is a markup change, and
    # writing the dataset anyway would launder that into "the site has no OE".
    unparsed_rate = (
        counters["unparsed_cards"] / counters["cards_read"] if counters["cards_read"] else 0.0
    )
    if unparsed_rate > 0.02:
        raise SystemExit(
            f"{counters['unparsed_cards']} of {counters['cards_read']} cards did not "
            f"parse ({unparsed_rate:.1%}). The card markup has most likely changed; "
            "no dataset written. Re-check FIELD against a live page."
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    columns = list(records[0].keys()) if records else [
        "mpn", "reference_article", "reference_brand", "number_raw", "number_norm",
        "token_class", "matched_rule", "source_field", "source_url",
        "source_title", "source_image_url", "structured_status", "structured_name",
        "structured_brand", "structured_model", "structured_sku", "structured_mpn",
        "structured_image_url", "raw_oe_field", "raw_sku_field", "extraction_method",
    ]
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)

    # ``counters.structured_*`` are card-level values: one increment per
    # detail page read.  A single accepted card can yield several token rows
    # (OE, article, and internal code), so expose the CSV denominator
    # separately instead of making downstream reports infer it from rows.
    manifest = {
        "extraction_method": EXTRACTION_METHOD,
        "method_version": config.method_version,
        "token_config_sha256": config.source_sha256,
        "reference_map_sha256s": reference_shas,
        "dataset_sha256": hashlib.sha256(args.out.read_bytes()).hexdigest(),
        "requests_made": fetcher.requests_made,
        "counters": counters,
        "record_counts": record_structured_counts(records),
        "rows": len(records),
    }
    manifest_path = args.out.with_suffix(".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
