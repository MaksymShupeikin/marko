"""Similarity scoring and cross-seller offer matching."""
from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable

from marko.services.parser_models import Product, SeedInfo

# Tokens carrying no discriminative value for product-name similarity.
_STOPWORDS: frozenset[str] = frozenset({
    "для", "від", "до", "та", "і", "в", "на", "з", "по", "the", "for", "and",
    "шт", "уп", "грн", "оригінал", "новий", "нова", "нове",
})
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_MIN_TOKEN_LENGTH = 2  # drop single-character noise tokens
_MAX_QUERY_TOKENS = 8  # longest search phrase, in tokens, built from a product name


def normalize_tokens(name: str | None) -> list[str]:
    """Lowercase word tokens with stopwords and single-char noise removed."""
    if not name:
        return []
    return [
        token
        for token in _WORD_RE.findall(name.lower())
        if len(token) >= _MIN_TOKEN_LENGTH and token not in _STOPWORDS
    ]


def token_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Token-set similarity in [0, 1]: an equal blend of Jaccard and containment."""
    if not tokens_a or not tokens_b:
        return 0.0
    inter = len(tokens_a & tokens_b)
    jaccard = inter / len(tokens_a | tokens_b)
    containment = inter / min(len(tokens_a), len(tokens_b))
    return round(0.5 * jaccard + 0.5 * containment, 3)


# Antonym groups: parts differing only by one of these are NOT the same item.
# Each group lists mutually-exclusive "sides" as token prefixes (ua + ru forms).
_ANTONYM_GROUPS: tuple[tuple[frozenset[str], ...], ...] = (
    (frozenset({"лів", "лев"}), frozenset({"прав"})),   # лівий / правий (left / right)
    (frozenset({"перед"}), frozenset({"задн"})),        # передній / задній (front / rear)
    (frozenset({"верхн"}), frozenset({"нижн"})),        # верхній / нижній (upper / lower)
)


def _side_in_group(tokens: list[str], group: tuple[frozenset[str], ...]) -> int | None:
    """Index of the side whose prefix matches any token, or None if unspecified."""
    for idx, side in enumerate(group):
        if any(tok.startswith(pref) for tok in tokens for pref in side):
            return idx
    return None


def laterality_conflict(a_tokens: list[str], b_tokens: list[str]) -> bool:
    """True when both names explicitly name opposite sides (e.g. left vs right)."""
    for group in _ANTONYM_GROUPS:
        sa = _side_in_group(a_tokens, group)
        sb = _side_in_group(b_tokens, group)
        if sa is not None and sb is not None and sa != sb:
            return True
    return False


def _norm_brand(brand: str | None) -> str:
    return (brand or "").strip().lower()


def brands_compatible(seed: str | None, cand: str | None) -> bool:
    """Brands match, or at least one is unknown (do not reject on missing data)."""
    a, b = _norm_brand(seed), _norm_brand(cand)
    return not a or not b or a == b


def build_search_query(product: Product) -> str:
    """A focused search phrase from the product name (+ brand if informative)."""
    tokens = normalize_tokens(product.name)[:_MAX_QUERY_TOKENS]
    query = " ".join(tokens) if tokens else (product.name or "")
    brand = _norm_brand(product.brand)
    if brand and brand not in query.lower():
        query = f"{product.brand} {query}".strip()
    return query


@dataclass(frozen=True)
class Match:
    """Why a candidate is considered the same/similar product, with a score."""
    kind: str   # "model" | "sku" | "fuzzy"
    score: float


def match_offer(seed: Product, cand: Product, threshold: float) -> Match | None:
    """Decide whether cand is the same/similar product as seed."""
    # Tier 1: prom.ua's own identity keys (exact, high confidence, authoritative).
    if seed.model_id and cand.model_id and seed.model_id == cand.model_id:
        return Match("model", 1.0)
    if seed.sku and cand.sku and seed.sku == cand.sku:
        return Match("sku", 1.0)
    # Tier 2: fuzzy. Brand must be compatible and the names must not name
    # opposite sides (лівий/правий, передній/задній, ...).
    if not brands_compatible(seed.brand, cand.brand):
        return None
    seed_tokens = normalize_tokens(seed.name)
    cand_tokens = normalize_tokens(cand.name)
    if laterality_conflict(seed_tokens, cand_tokens):
        return None
    score = token_similarity(set(seed_tokens), set(cand_tokens))
    if score >= threshold:
        return Match("fuzzy", score)
    return None


def _price_value(product: Product) -> float | None:
    """Best-effort numeric price for comparison, or None if unusable."""
    raw = product.effective_price
    try:
        return float(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class Offer:
    """A single seller's matched offer for the seed product."""
    product: Product
    match: Match
    price: float


@dataclass(frozen=True)
class PriceComparison:
    """Result of comparing a seed product against offers from other sellers."""
    seed: SeedInfo
    query: str
    offers: list[Offer]          # cheapest-per-seller, price-ascending, capped
    candidates_scanned: int

    @property
    def prices(self) -> list[float]:
        return [offer.price for offer in self.offers]

    @property
    def cheapest(self) -> Offer | None:
        return self.offers[0] if self.offers else None

    @property
    def min_price(self) -> float | None:
        return min(self.prices) if self.offers else None

    @property
    def max_price(self) -> float | None:
        return max(self.prices) if self.offers else None

    @property
    def median_price(self) -> float | None:
        return median(self.prices) if self.offers else None

    @property
    def spread_pct(self) -> float | None:
        lo, hi = self.min_price, self.max_price
        if not lo:
            return None
        return round((hi - lo) / lo * 100, 1)

    @property
    def seed_price(self) -> float | None:
        return _price_value(self.seed.product)

    @property
    def savings_vs_seed(self) -> float | None:
        """How much the cheapest offer saves against the seed's own price."""
        seed_p, lo = self.seed_price, self.min_price
        if seed_p is None or lo is None:
            return None
        return round(seed_p - lo, 2)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": {
                **self.seed.product.as_dict(),
                "buybox_seller_count": self.seed.seller_count,
                "buybox_min_price": self.seed.min_price,
                "buybox_max_price": self.seed.max_price,
            },
            "query": self.query,
            "candidates_scanned": self.candidates_scanned,
            "stats": {
                "sellers_compared": len(self.offers),
                "min_price": self.min_price,
                "median_price": self.median_price,
                "max_price": self.max_price,
                "spread_pct": self.spread_pct,
                "savings_vs_seed": self.savings_vs_seed,
            },
            "offers": [
                {
                    "seller_name": offer.product.seller_name,
                    "seller_id": offer.product.seller_id,
                    "price": offer.price,
                    "currency": offer.product.currency,
                    "presence": offer.product.presence,
                    "match_kind": offer.match.kind,
                    "match_score": offer.match.score,
                    "name": offer.product.name,
                    "brand": offer.product.brand,
                    "url": offer.product.url,
                }
                for offer in self.offers
            ],
        }


@dataclass(frozen=True)
class ComparisonParams:
    """How to run a comparison: the search query plus matching/limit knobs."""
    query: str
    threshold: float
    max_sellers: int


def build_comparison(
    seed: SeedInfo, candidates: Iterable[Product], params: ComparisonParams
) -> PriceComparison:
    """Match candidates, keep the cheapest offer per seller, cap at max_sellers."""
    seed_product = seed.product
    cheapest_by_seller: dict[Any, Offer] = {}
    scanned = 0
    for cand in candidates:
        scanned += 1
        # Keep other sellers only: skip the seed product and its own seller.
        if cand.id == seed_product.id:
            continue
        if seed_product.seller_id and cand.seller_id == seed_product.seller_id:
            continue
        match = match_offer(seed_product, cand, params.threshold)
        if match is None:
            continue
        price = _price_value(cand)
        if price is None:
            continue
        seller_key = cand.seller_id or cand.seller_name
        if seller_key is None:
            continue
        current = cheapest_by_seller.get(seller_key)
        if current is None or price < current.price:
            cheapest_by_seller[seller_key] = Offer(product=cand, match=match, price=price)

    offers = sorted(cheapest_by_seller.values(), key=lambda offer: offer.price)
    return PriceComparison(
        seed=seed,
        query=params.query,
        offers=offers[: params.max_sellers],
        candidates_scanned=scanned,
    )
