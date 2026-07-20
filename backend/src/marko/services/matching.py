"""Similarity scoring and cross-seller offer matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median
from types import MappingProxyType
from typing import Any, Iterable

from marko.services.parser_models import Product, SeedInfo
from metis.pricing import (
    COMPARABILITY_DIMENSIONS,
    COMPARABILITY_POLICY_HASH,
    COMPARABILITY_POLICY_ID,
    ComparisonEvidence,
    DimensionEvidence,
    EvidenceState,
    HardGateResult,
    SellerIdentityEvidence,
    SourceProvenance,
    categorical_dimension,
    comparison_evidence_to_dict,
    evaluate_comparison_evidence,
    normalize_oe,
)

# Tokens carrying no discriminative value for product-name similarity.
_STOPWORDS: frozenset[str] = frozenset(
    {
        "для",
        "від",
        "до",
        "та",
        "і",
        "в",
        "на",
        "з",
        "по",
        "the",
        "for",
        "and",
        "шт",
        "уп",
        "грн",
        "оригінал",
        "новий",
        "нова",
        "нове",
    }
)
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


def _token_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
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
    (frozenset({"лів", "лев"}), frozenset({"прав"})),  # лівий / правий (left / right)
    (frozenset({"перед"}), frozenset({"задн"})),  # передній / задній (front / rear)
    (frozenset({"верхн"}), frozenset({"нижн"})),  # верхній / нижній (upper / lower)
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
    """Return true only for two known equal brands; unknown is not evidence."""
    a, b = _norm_brand(seed), _norm_brand(cand)
    return bool(a and b and a == b)


def build_search_query(product: Product) -> str:
    """Use exact OE first; only fall back to a focused name/brand phrase."""
    if normalize_oe(product.oe_raw):
        return str(product.oe_raw).strip()
    tokens = normalize_tokens(product.name)[:_MAX_QUERY_TOKENS]
    query = " ".join(tokens) if tokens else (product.name or "")
    brand = _norm_brand(product.brand)
    if brand and brand not in query.lower():
        query = f"{product.brand} {query}".strip()
    return query


@dataclass(frozen=True)
class Match:
    """Why a candidate is considered the same/similar product, with a score."""

    kind: str  # "oe" | "model" | "sku" | "fuzzy"
    score: float


def match_offer(seed: Product, cand: Product, threshold: float) -> Match | None:
    """Retrieve a candidate without treating retrieval as comparability proof."""
    seed_tokens = normalize_tokens(seed.name)
    cand_tokens = normalize_tokens(cand.name)
    if laterality_conflict(seed_tokens, cand_tokens):
        return None
    seed_oe = normalize_oe(seed.oe_raw)
    candidate_oe = normalize_oe(cand.oe_raw)
    if seed_oe is not None and candidate_oe is not None:
        if seed_oe != candidate_oe:
            return None
        return Match("oe", 1.0)
    # Exact IDs strengthen retrieval only. All hard fields are evaluated by
    # build_product_comparison_evidence before Metis pricing eligibility.
    if seed.model_id and cand.model_id and seed.model_id == cand.model_id:
        return Match("model", 1.0)
    if seed.sku and cand.sku and seed.sku == cand.sku:
        return Match("sku", 1.0)
    score = _token_similarity(set(seed_tokens), set(cand_tokens))
    if score >= threshold:
        return Match("fuzzy", score)
    return None


def _price_value(product: Product) -> float | None:
    """Best-effort numeric price for comparison, or None if unusable."""
    raw = product.price or product.price_original
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
    comparison_evidence: ComparisonEvidence


@dataclass(frozen=True)
class PriceComparison:
    """Result of comparing a seed product against offers from other sellers."""

    seed: SeedInfo
    query: str
    offers: list[Offer]  # cheapest-per-seller, price-ascending, capped
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
                    "product_id": offer.product.id,
                    "sku": offer.product.sku,
                    "model_id": offer.product.model_id,
                    "seller_name": offer.product.seller_name,
                    "seller_id": offer.product.seller_id,
                    "price": offer.price,
                    "currency": offer.product.currency,
                    "presence": offer.product.presence,
                    "match_kind": offer.match.kind,
                    "match_score": offer.match.score,
                    "name": offer.product.name,
                    "description": offer.product.description,
                    "condition": offer.product.condition,
                    "oe_raw": offer.product.oe_raw,
                    "brand": offer.product.brand,
                    "url": offer.product.url,
                    "automatic_eligible": (
                        offer.comparison_evidence.hard_gate_result
                        == HardGateResult.PASS
                    ),
                    "comparison_evidence": comparison_evidence_to_dict(
                        offer.comparison_evidence
                    ),
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
        seller_key = str(cand.seller_id).strip() if cand.seller_id is not None else ""
        if not seller_key:
            continue
        evidence = build_product_comparison_evidence(
            seed_product,
            cand,
            retrieval_kind=match.kind,
        )
        current = cheapest_by_seller.get(seller_key)
        if current is None or price < current.price:
            cheapest_by_seller[seller_key] = Offer(
                product=cand,
                match=match,
                price=price,
                comparison_evidence=evidence,
            )

    offers = sorted(cheapest_by_seller.values(), key=lambda offer: offer.price)
    return PriceComparison(
        seed=seed,
        query=params.query,
        offers=offers[: params.max_sellers],
        candidates_scanned=scanned,
    )


def build_product_comparison_evidence(
    seed: Product,
    candidate: Product,
    *,
    retrieval_kind: str,
    source_type: str | None = None,
    source_record_id: str | None = None,
    raw_evidence_sha256: str | None = None,
    parser_contract_version: str | None = None,
) -> ComparisonEvidence:
    """Build typed evidence without inventing absent parser/enrichment fields."""

    reference = source_record_id or str(candidate.id or "")
    refs = (reference,) if reference else ()
    seed_oe = normalize_oe(seed.oe_raw)
    candidate_oe = normalize_oe(candidate.oe_raw)
    if seed_oe is None or candidate_oe is None:
        oe_state = EvidenceState.UNKNOWN
    elif seed_oe == candidate_oe:
        oe_state = EvidenceState.MATCH
    else:
        oe_state = EvidenceState.CONFLICT
    dimensions: dict[str, DimensionEvidence] = {
        "oe_reference": DimensionEvidence(
            state=oe_state,
            raw_value=candidate.oe_raw,
            normalized_value=candidate_oe,
            evidence_refs=refs,
        ),
        "brand_manufacturer": categorical_dimension(
            seed.brand, candidate.brand, evidence_refs=refs
        ),
        "fitment": categorical_dimension(
            seed.fitment, candidate.fitment, evidence_refs=refs
        ),
        "vehicle_generation": categorical_dimension(
            seed.vehicle_generation,
            candidate.vehicle_generation,
            evidence_refs=refs,
        ),
        "year_interval": _year_dimension(seed, candidate, refs),
        "engine": categorical_dimension(
            seed.engine, candidate.engine, evidence_refs=refs
        ),
        "body_variant": categorical_dimension(
            seed.body_variant, candidate.body_variant, evidence_refs=refs
        ),
        "side": categorical_dimension(seed.side, candidate.side, evidence_refs=refs),
        "position": categorical_dimension(
            seed.position, candidate.position, evidence_refs=refs
        ),
        "condition": categorical_dimension(
            seed.condition, candidate.condition, evidence_refs=refs
        ),
        "package_quantity": _quantity_dimension(seed, candidate, refs),
        "currency_presence": DimensionEvidence(
            state=(
                EvidenceState.MATCH
                if candidate.currency and candidate.currency.strip()
                else EvidenceState.UNKNOWN
            ),
            raw_value=candidate.currency,
            normalized_value=(
                candidate.currency.strip().upper() if candidate.currency else None
            ),
            evidence_refs=refs,
        ),
    }
    assert set(dimensions) == set(COMPARABILITY_DIMENSIONS)
    stable_seller_id = (
        str(candidate.seller_id).strip() if candidate.seller_id is not None else None
    )
    provenance_verified = bool(
        source_type
        and source_record_id
        and raw_evidence_sha256
        and parser_contract_version
    )
    initial = ComparisonEvidence(
        dimensions=MappingProxyType(dimensions),
        provenance=SourceProvenance(
            source_type=source_type,
            source_record_id=source_record_id,
            raw_evidence_sha256=raw_evidence_sha256,
            parser_contract_version=parser_contract_version,
            verified=provenance_verified,
        ),
        seller_identity=SellerIdentityEvidence(
            stable_seller_id=stable_seller_id,
            identity_source="prom:company.id" if stable_seller_id else None,
            verified=bool(stable_seller_id),
        ),
        policy_id=COMPARABILITY_POLICY_ID,
        policy_hash=COMPARABILITY_POLICY_HASH,
        retrieval_kind=retrieval_kind,
        seed_product_id=str(seed.id) if seed.id is not None else None,
        candidate_product_id=(str(candidate.id) if candidate.id is not None else None),
    )
    decision = evaluate_comparison_evidence(
        initial,
        seller_id=stable_seller_id,
        currency_raw=candidate.currency,
        currency_normalized=_normalized_currency(candidate.currency),
        required_currency="UAH",
    )
    return ComparisonEvidence(
        dimensions=initial.dimensions,
        provenance=initial.provenance,
        seller_identity=initial.seller_identity,
        policy_id=initial.policy_id,
        policy_hash=initial.policy_hash,
        retrieval_kind=initial.retrieval_kind,
        seed_product_id=initial.seed_product_id,
        candidate_product_id=initial.candidate_product_id,
        hard_gate_result=decision.hard_gate_result,
        reason_codes=decision.reason_codes,
    )


def _year_dimension(
    seed: Product, candidate: Product, refs: tuple[str, ...]
) -> DimensionEvidence:
    values = (seed.year_from, seed.year_to, candidate.year_from, candidate.year_to)
    if any(value is None for value in values):
        state = EvidenceState.UNKNOWN
    else:
        assert all(value is not None for value in values)
        overlap = max(
            0,
            min(seed.year_to, candidate.year_to)
            - max(seed.year_from, candidate.year_from)
            + 1,
        )
        state = EvidenceState.MATCH if overlap > 0 else EvidenceState.CONFLICT
    return DimensionEvidence(state=state, evidence_refs=refs)


def _quantity_dimension(
    seed: Product, candidate: Product, refs: tuple[str, ...]
) -> DimensionEvidence:
    if seed.package_quantity is None or candidate.package_quantity is None:
        state = EvidenceState.UNKNOWN
    elif seed.package_quantity == candidate.package_quantity:
        state = EvidenceState.MATCH
    else:
        state = EvidenceState.CONFLICT
    return DimensionEvidence(
        state=state,
        raw_value=(
            str(candidate.package_quantity)
            if candidate.package_quantity is not None
            else None
        ),
        normalized_value=(
            str(candidate.package_quantity)
            if candidate.package_quantity is not None
            else None
        ),
        evidence_refs=refs,
    )


def _normalized_currency(value: str | None) -> str | None:
    normalized = (value or "").strip().casefold()
    if normalized in {"uah", "грн", "₴", "гривня", "гривень"}:
        return "UAH"
    return normalized.upper()[:3] or None
