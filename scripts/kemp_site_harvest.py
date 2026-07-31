"""Harvest OE numbers off kemp.ua product cards (WP-1B).

Offline data collection, deliberately outside the pricing path: the network is
touched here and nowhere else, and the only thing downstream reads is the CSV
this script writes (NO_10).  Import stays deterministic because it reads a file
with a known sha256.

Population: reference-map rows whose ``article_brand`` is a component supplier.
For those the article is not an OE and no OE is known from anywhere, which is
the gap the site closes for about a third of them.  Rows whose brand is a
vehicle maker are skipped — the control measurement showed the site merely
confirms the reference map there (161 of 162).

A card counts as ours only when its ``Номер виробника`` equals the code we
searched for.  The site's search also matches descriptions, so a hit in the
result list proves nothing: during the measurement 100 codes produced 135
cards.

    python scripts/kemp_site_harvest.py \
        --reference backend/data/kemp_reference_map.csv \
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
FIELD = re.compile(
    r'product-data__item (?P<key>model|sku|mpn)">'
    r'<div class="product-data__item-div">[^<]*</div>\s*(?P<value>.*?)</div>',
    re.S,
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


def check_robots(fetcher: Fetcher) -> None:
    body = fetcher.get(ROBOTS)
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("disallow:") and ROBOTS_SEARCH_RULE in stripped:
            raise SystemExit(
                "robots.txt now disallows product search; harvest stops.\n"
                f"  offending line: {stripped}"
            )


def load_population(path: Path) -> list[dict[str, str]]:
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            brand = (row.get("article_brand") or "").strip()
            mpn = (row.get("mpn") or "").strip()
            if not mpn or not brand or brand in VEHICLE_MAKERS:
                continue
            rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
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
    reference_sha = hashlib.sha256(args.reference.read_bytes()).hexdigest()
    fetcher = Fetcher(cache=args.cache, delay=args.delay, user_agent=args.user_agent)
    check_robots(fetcher)

    population = load_population(args.reference)
    if args.limit:
        population = population[: args.limit]

    records: list[dict[str, str]] = []
    counters: dict[str, int] = {
        "positions": 0, "absent": 0, "ambiguous": 0, "with_candidate": 0,
        "errors": 0, "cards_read": 0, "unparsed_cards": 0,
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
                counters["cards_read"] += 1
                if not card_looks_parsed(page, card):
                    counters["unparsed_cards"] += 1
                if card["mpn"].strip() == mpn:
                    cards.append((href, card))
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

        href, card = cards[0]
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
        "raw_oe_field", "raw_sku_field", "extraction_method",
    ]
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)

    manifest = {
        "extraction_method": EXTRACTION_METHOD,
        "method_version": config.method_version,
        "token_config_sha256": config.source_sha256,
        "reference_map_sha256": reference_sha,
        "dataset_sha256": hashlib.sha256(args.out.read_bytes()).hexdigest(),
        "requests_made": fetcher.requests_made,
        "counters": counters,
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
