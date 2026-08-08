"""Similarity scoring and cross-seller offer matching."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import median
from types import MappingProxyType
from typing import Any, Iterable

from marko.services.parser_models import (
    Product,
    SeedInfo,
    extract_labelled_original_oe_numbers,
)
from marko.services.catalog_identity_safety import is_internal_catalog_code
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
    comparison_evidence_to_dict,
    evaluate_comparison_evidence,
    normalized_categorical_dimension,
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
_SHORT_NUMERIC_SEARCH_NUMBER_MAX_DIGITS = 6
_IDENTIFIER_LABEL_RE = re.compile(
    r"(?:\b(?:oe|oem|art|article|артикул|арт)\b|"
    r"\bpart\s+(?:no|number)\b|"
    r"\bкод\s+(?:запчасти|запчастини|виробника|производителя)\b|[#№])",
    re.IGNORECASE,
)
_IDENTIFIER_BOUNDARY_CHARS = r"A-Za-zА-Яа-яЇїІіЄєҐґ0-9"


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


def _explicit_semantic_identity_conflict(seed: Product, candidate: Product) -> bool:
    """Reject a retrieval hit with an explicit semantic identity conflict.

    Prom's text endpoint is intentionally broad: a query for an absorber can
    return a tail lamp because both cards mention the same vehicle and rear
    position.  It can also return a rigid brake line for a flexible brake hose.
    Those are useful raw discovery outputs, but must not enter the
    comparative-offer list.  Reuse the closed semantic extractor and remove
    only explicit hard-stop conflicts.  Missing or ambiguous values stay
    visible for the downstream manual gate.
    """

    from marko.services.semantic_candidate_features import (
        build_semantic_feature_matrix,
    )
    from marko.services.semantic_candidate_gate import (
        category_required_semantic_conflicts,
    )

    def payload(product: Product) -> dict[str, Any]:
        return {
            "name": product.name,
            "title": product.name,
            "description": product.description,
            "category": product.category,
            "brand": product.brand,
            # Structured card fields are evidence, not positive identity
            # proof. They must nevertheless reach the contradiction detector:
            # a listing whose title looks right but whose card says "used",
            # "left", or a different connector/package must not survive the
            # broad search adapter as a competitor candidate.
            "sku": product.sku,
            "mpn": product.mpn,
            "oe_raw": product.oe_raw,
            "part_numbers": list(product.part_numbers),
            "fitment": product.fitment,
            "vehicle_generation": product.vehicle_generation,
            "year_from": product.year_from,
            "year_to": product.year_to,
            "engine": product.engine,
            "body_variant": product.body_variant,
            "side": product.side,
            "position": product.position,
            "condition": product.condition,
            "package_quantity": product.package_quantity,
            "measure_unit": product.measure_unit,
            "characteristics": product.characteristics,
        }

    matrix = build_semantic_feature_matrix(payload(seed), payload(candidate))
    conflicts = matrix.get("hard_stop_conflicts")
    if isinstance(conflicts, (list, tuple)) and conflicts:
        return True
    # The generic extractor intentionally keeps noisy dimensions such as
    # ports/mounting soft.  For a typed category those dimensions are part of
    # the product identity (e.g. a radiator's inlet/outlet), so an explicit
    # contradiction must be removed from the comparison list as well.  UNKNOWN
    # remains visible and is handled by the manual comparability gate.
    return bool(category_required_semantic_conflicts(matrix))


def _norm_brand(brand: str | None) -> str:
    return (brand or "").strip().lower()


def brands_compatible(seed: str | None, cand: str | None) -> bool:
    """Return true only for two known equal brands; unknown is not evidence."""
    a, b = _norm_brand(seed), _norm_brand(cand)
    return bool(a and b and a == b)


def _search_number_matches_field(
    value: str | None,
    wanted: str,
    *,
    structured: bool = False,
) -> bool:
    """Match a search number as a token, never as an arbitrary substring.

    The marketplace search endpoint can return a seller SKU that merely
    contains the query digits.  Such a row is retrieval output, not proof that
    the part identifier is present.  Structured SKU/MPN equality remains accepted;
    free-text title matching requires identifier boundaries and an explicit
    label for short all-numeric values.
    """

    if not value or not wanted:
        return False
    if structured:
        return normalize_oe(value) == wanted

    pieces = r"[\s./_-]*".join(re.escape(character) for character in wanted)
    pattern = re.compile(
        rf"(?<![{_IDENTIFIER_BOUNDARY_CHARS}]){pieces}"
        rf"(?![{_IDENTIFIER_BOUNDARY_CHARS}])",
        re.IGNORECASE,
    )
    if wanted.isdigit() and len(wanted) <= _SHORT_NUMERIC_SEARCH_NUMBER_MAX_DIGITS:
        for match in pattern.finditer(value):
            prefix = value[max(0, match.start() - 48) : match.start()]
            if _IDENTIFIER_LABEL_RE.search(prefix):
                return True
        return False
    return pattern.search(value) is not None


def _public_identity_norm(value: str | None) -> str | None:
    """Normalize a public identity value, excluding private KEMP shelf codes."""

    normalized = normalize_oe(value)
    if normalized is None or is_internal_catalog_code(normalized):
        return None
    return normalized


def build_search_query_parts(
    *,
    name: str | None,
    brand: str | None = None,
    part_number: str | None = None,
    fallback: str | None = None,
) -> str:
    """Build a bounded query from public identity or a focused title phrase."""

    if _public_identity_norm(part_number) is not None:
        return str(part_number).strip()[:255]
    tokens = normalize_tokens(name)[:_MAX_QUERY_TOKENS]
    query = " ".join(tokens)
    brand_text = (brand or "").strip()
    brand_norm = _norm_brand(brand)
    if brand_norm and brand_norm not in query.lower():
        query = f"{brand_text} {query}".strip()
    if not query:
        query = " ".join(normalize_tokens(fallback))
    return query[:255]


def build_search_query(product: Product) -> str:
    """Use exact OE/MPN first; only fall back to a focused name/brand phrase.

    An MPN-only catalog row is still a deterministic identity.  Falling back
    directly to a title for that row turns a precise lookup into a noisy text
    search and silently loses recall.
    """
    def public_identifier(value: str | None) -> str | None:
        normalized = normalize_oe(value)
        if not normalized or is_internal_catalog_code(normalized):
            return None
        return str(value).strip()

    if (identifier := public_identifier(product.oe_raw)) is not None:
        return identifier
    # A catalogue/export row may carry a private KEMP shelf code in ``oe_raw``
    # while the same Prom card explicitly labels the vehicle manufacturer's
    # number as OE/OEM. Prefer that public, source-labelled identity over a
    # supplier MPN or an unlabelled part number. Generic ``Артикул`` fields
    # intentionally remain below MPN because they are not an OE assertion.
    for value in extract_labelled_original_oe_numbers(product.characteristics):
        if (identifier := public_identifier(value)) is not None:
            return identifier
    if (identifier := public_identifier(product.mpn)) is not None:
        return identifier
    if product.part_numbers:
        for value in product.part_numbers:
            if (identifier := public_identifier(value)) is not None:
                return identifier
    # ``sku`` is deliberately not a public market identity.  On Prom it is
    # commonly a seller-local code (and in our own catalog it may be the
    # marketplace product id), so using it as a fallback sends an arbitrary
    # number to the public search and can create a false cohort.  When no
    # public OE/MPN/labelled part number exists, the only honest fallback is a
    # title discovery query, which remains review-only downstream.
    tokens = normalize_tokens(product.name)[:_MAX_QUERY_TOKENS]
    query = " ".join(tokens) if tokens else (product.name or "")
    brand = _norm_brand(product.brand)
    if brand and brand not in query.lower():
        query = f"{product.brand} {query}".strip()
    return query


@dataclass(frozen=True)
class Match:
    """Why a candidate is considered the same/similar product, with a score."""

    kind: str  # "oe" | "mpn" | "number" | "model" | "sku" | "fuzzy"
    score: float


def match_offer(
    seed: Product,
    cand: Product,
    threshold: float,
    identity_source: str | None = None,
    search_number: str | None = None,
) -> Match | None:
    """Retrieve a candidate without treating retrieval as comparability proof.

    ``identity_source`` names a marketplace grouping that already filed this
    offer with our part — prom.ua's ``/auto/oen/`` listing for our normalized
    part code.  Then the wording is not consulted: sellers there do not repeat
    the number in their titles, and requiring them to would discard the very
    offers the listing was consulted for.

    ``search_number`` is the number the marketplace was searched by.  A listing
    that repeats it is exactly what the identity gate downstream accepts as
    ``TITLE`` evidence, so refusing it here on the wording alone discards
    candidates the pipeline would have taken.  Measured over the 12 catalogue
    positions with no part-code page on 2026-07-31: name similarity found three
    or more independent sellers for 2 of them, the number in the text for 5, and
    the two signals together for 6 — they overlap only partly, which is why this
    is an additional route and not a replacement.

    The laterality check still runs first.  It is a retrieval-level sanity check
    and costs nothing, and a left part filed beside a right one is a mistake no
    grouping should be trusted through.  Everything else about comparability is
    decided downstream, exactly as it is for a fuzzy match — including the
    ``WEAK_NUMERIC_IDENTITY`` flag that marks a short all-digit number found only
    in free text, which is the collision this route is most exposed to.
    """

    seed_tokens = normalize_tokens(seed.name)
    cand_tokens = normalize_tokens(cand.name)
    if laterality_conflict(seed_tokens, cand_tokens):
        return None
    if identity_source:
        # A marketplace grouping is authoritative only when the number that
        # produced it is public.  Do not let a direct/replay caller smuggle a
        # private KEMP shelf code through this strategy-only fast path.
        if search_number and _public_identity_norm(search_number) is None:
            return None
        return Match(identity_source, 1.0)
    if search_number:
        wanted = _public_identity_norm(search_number)
        # A private or malformed query is not a retrieval identity.  Returning
        # here is important: otherwise the generic fuzzy branch below can
        # resurrect a legacy private-code request as a name-only match.
        if wanted is None:
            return None
        # A candidate-native MPN/OE is a conflict-bearing fact.  Do this
        # before looking at the title: sellers sometimes copy a searched code
        # into a marketing title while the structured manufacturer number says
        # it is another part.  A seller SKU alone is intentionally ignored —
        # it is commonly a private namespace and may differ from our MPN.
        structured_identity_values = tuple(
            normalized
            for value in (cand.mpn, cand.oe_raw)
            if (normalized := _public_identity_norm(value))
        )
        labelled_part_values = tuple(
            normalized
            for value in cand.part_numbers
            if (normalized := _public_identity_norm(value))
        )
        # A candidate may expose both namespaces: an exact OE alongside a
        # different supplier MPN is a normal cross-level representation.  The
        # conflict exists only when *none* of the native namespaces matches
        # the searched identifier.  Rejecting on ``any(value != wanted)``
        # caused a false negative for that common shape.
        if (
            wanted
            and structured_identity_values
            and wanted not in structured_identity_values
        ):
            return None
        if wanted and not structured_identity_values and labelled_part_values:
            if wanted not in labelled_part_values:
                return None
        if wanted and (
            _search_number_matches_field(cand.name, wanted)
            # A public, exact SKU can be the marketplace's representation of
            # the requested OE.  The private namespace is already removed
            # from ``wanted`` above, so an internal KEMP code can never pass
            # through this branch.
            or _search_number_matches_field(cand.sku, wanted, structured=True)
            or _search_number_matches_field(cand.mpn, wanted, structured=True)
            or _search_number_matches_field(cand.oe_raw, wanted, structured=True)
            or any(
                _search_number_matches_field(value, wanted, structured=True)
                for value in cand.part_numbers
            )
        ):
            return Match("number", 1.0)
        # A card with no native/labelled identifier can still be useful as
        # *raw discovery* when the caller explicitly requested a broad search.
        # Its comparison evidence remains UNKNOWN/MANUAL_REVIEW downstream;
        # it must never be treated as automatic identity proof.  The
        # marketplace grouping path is handled above by ``identity_source``
        # and may intentionally admit cards that do not repeat the number.
    seed_oe = _public_identity_norm(seed.oe_raw)
    candidate_oe = _public_identity_norm(cand.oe_raw)
    if seed_oe is not None and candidate_oe is not None:
        if seed_oe != candidate_oe:
            return None
        return Match("oe", 1.0)
    # Exact marketplace model IDs strengthen retrieval only. All hard fields
    # are evaluated by build_product_comparison_evidence before Metis pricing
    # eligibility.
    if seed.model_id and cand.model_id and seed.model_id == cand.model_id:
        return Match("model", 1.0)
    # A seller SKU is permitted as a retrieval identity only when it is a
    # public, exact token.  Private KEMP shelf codes are never allowed to
    # create this match, even if two owned storefronts reuse the same SKU.
    seed_sku = _public_identity_norm(seed.sku)
    candidate_sku = _public_identity_norm(cand.sku)
    if seed_sku is not None and seed_sku == candidate_sku:
        return Match("sku", 1.0)
    # MPN is a separate manufacturer namespace. Non-equal MPNs are not
    # rejected here because an approved cross may legitimately use another
    # number; downstream identity and comparability gates remain authoritative.
    seed_mpn = _public_identity_norm(seed.mpn)
    candidate_mpn = _public_identity_norm(cand.mpn)
    if seed_mpn is not None and candidate_mpn is not None:
        if seed_mpn == candidate_mpn:
            return Match("mpn", 1.0)
    seed_numbers = {
        normalized
        for value in seed.part_numbers
        if (normalized := _public_identity_norm(value))
    }
    candidate_numbers = {
        normalized
        for value in cand.part_numbers
        if (normalized := _public_identity_norm(value))
    }
    if seed_numbers and candidate_numbers and seed_numbers & candidate_numbers:
        return Match("number", 1.0)
    if seed_numbers and candidate_mpn in seed_numbers:
        return Match("mpn", 1.0)
    if candidate_numbers and seed_mpn in candidate_numbers:
        return Match("number", 1.0)
    score = _token_similarity(set(seed_tokens), set(cand_tokens))
    if score >= threshold:
        return Match("fuzzy", score)
    return None


def _price_value(product: Product) -> Decimal | None:
    """Return the active sale price, never a crossed-out reference price."""

    # Prom's card payload commonly carries ``price=412`` and
    # ``discountedPrice=330``.  The legacy matcher used ``price`` first and
    # therefore inflated the market by the crossed-out amount.  Keep the
    # boundary deterministic here as well as in offer_processing, because the
    # Prom gateway still builds its comparison through this module.
    def parse(raw: object) -> Decimal | None:
        if raw in (None, ""):
            return None
        try:
            parsed = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() and parsed > 0 else None

    current = parse(product.price)
    discounted = parse(product.discounted_price)
    original = parse(product.price_original)
    if discounted is not None:
        if current is not None and discounted > current:
            return current
        if current is None and original is not None and discounted > original:
            return original
        return discounted
    if current is not None:
        return current
    return original


def _reference_price(product: Product, sale_price: Decimal) -> Decimal | None:
    """Return a higher crossed-out/original price as reference evidence only."""

    candidates: list[Decimal] = []
    for raw in (
        product.price,
        product.price_original,
        product.discounted_price,
    ):
        if raw in (None, ""):
            continue
        try:
            parsed = Decimal(str(raw))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if parsed.is_finite() and parsed > sale_price:
            candidates.append(parsed)
    return max(candidates) if candidates else None


def _decimal_text(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


@dataclass(frozen=True)
class Offer:
    """A single seller's matched offer for the seed product."""

    product: Product
    match: Match
    price: Decimal
    comparison_evidence: ComparisonEvidence


@dataclass(frozen=True)
class PriceComparison:
    """Result of comparing a seed product against offers from other sellers."""

    seed: SeedInfo
    query: str
    offers: list[Offer]  # cheapest-per-seller, price-ascending, capped
    candidates_scanned: int
    #: Where the candidates came from.  Persisted so a recommendation can be
    #: read back knowing whether its basis was a text search or the
    #: marketplace's own part-code listing.
    source: str = "SEARCH"
    #: The number whose market was actually taken.  Differs from our own code
    #: when the listing came from its supersession chain.
    via_oe_number: str | None = None
    #: Whether that number is a related one rather than ours.  An offer from a
    #: related number's market is a different sellable part until something
    #: proves otherwise, so this has to survive as far as the grader.
    is_widened: bool = False

    @property
    def acquisition(self) -> dict[str, Any]:
        """Where this market came from, in one serializable block."""

        return {
            "source": self.source,
            "via_oe_number": self.via_oe_number,
            "is_widened": self.is_widened,
        }

    @property
    def prices(self) -> list[Decimal]:
        return [offer.price for offer in self.offers]

    @property
    def cheapest(self) -> Offer | None:
        return self.offers[0] if self.offers else None

    @property
    def min_price(self) -> Decimal | None:
        return min(self.prices) if self.offers else None

    @property
    def max_price(self) -> Decimal | None:
        return max(self.prices) if self.offers else None

    @property
    def median_price(self) -> Decimal | None:
        return median(self.prices) if self.offers else None

    @property
    def spread_pct(self) -> float | None:
        lo, hi = self.min_price, self.max_price
        if not lo:
            return None
        return float(((hi - lo) / lo * Decimal("100")).quantize(Decimal("0.1")))

    @property
    def seed_price(self) -> Decimal | None:
        return _price_value(self.seed.product)

    @property
    def savings_vs_seed(self) -> Decimal | None:
        """How much the cheapest offer saves against the seed's own price."""
        seed_p, lo = self.seed_price, self.min_price
        if seed_p is None or lo is None:
            return None
        return seed_p - lo

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": {
                **self.seed.product.as_dict(),
                "buybox_seller_count": self.seed.seller_count,
                "buybox_min_price": _decimal_text(self.seed.min_price),
                "buybox_max_price": _decimal_text(self.seed.max_price),
            },
            "query": self.query,
            # The origin travels with the comparison itself: whoever reads a
            # recommendation back has to see whose market it rests on, not
            # only the prices taken from it.
            "source": self.source,
            "acquisition": self.acquisition,
            "candidates_scanned": self.candidates_scanned,
            "stats": {
                "sellers_compared": len(self.offers),
                "min_price": _decimal_text(self.min_price),
                "median_price": _decimal_text(self.median_price),
                "max_price": _decimal_text(self.max_price),
                "spread_pct": self.spread_pct,
                "savings_vs_seed": _decimal_text(self.savings_vs_seed),
            },
            "offers": [
                {
                    "product_id": offer.product.id,
                    "sku": offer.product.sku,
                    "mpn": offer.product.mpn,
                    "part_numbers": list(offer.product.part_numbers),
                    "model_id": offer.product.model_id,
                    "seller_name": offer.product.seller_name,
                    "seller_id": offer.product.seller_id,
                    "price": _decimal_text(offer.price),
                    # ``price`` remains the compatibility key and is always
                    # the active sale price.  Keep the two roles explicit so a
                    # downstream replay cannot mistake a crossed-out value
                    # for the market observation.
                    "sale_price": _decimal_text(offer.price),
                    "reference_price": _decimal_text(
                        _reference_price(offer.product, offer.price)
                    ),
                    "price_original": offer.product.price_original,
                    "discounted_price": offer.product.discounted_price,
                    "currency": offer.product.currency,
                    "presence": offer.product.presence,
                    "match_kind": offer.match.kind,
                    "match_score": offer.match.score,
                    "name": offer.product.name,
                    "description": offer.product.description,
                    "condition": offer.product.condition,
                    "package_quantity": offer.product.package_quantity,
                    "measure_unit": offer.product.measure_unit,
                    "oe_raw": offer.product.oe_raw,
                    "brand": offer.product.brand,
                    "category": offer.product.category,
                    "category_id": offer.product.category_id,
                    "category_ids": offer.product.category_ids,
                    "characteristics": offer.product.characteristics,
                    "fitment": offer.product.fitment,
                    "vehicle_generation": offer.product.vehicle_generation,
                    "year_from": offer.product.year_from,
                    "year_to": offer.product.year_to,
                    "engine": offer.product.engine,
                    "body_variant": offer.product.body_variant,
                    "side": offer.product.side,
                    "position": offer.product.position,
                    "detail_evidence": offer.product.detail_evidence,
                    "url": offer.product.url,
                    # A raw gateway comparison has not yet passed the
                    # persisted-market admission boundary.  The comparability
                    # hard gate only evaluates the fields present on this
                    # in-memory candidate; it does not prove retained detail
                    # provenance, OE namespace, seller verification, cohort
                    # role, or the current semantic gate.  Exposing that
                    # partial result as ``automatic_eligible=true`` made the
                    # diagnostic/CLI payload look price-ready even though the
                    # persistence layer (correctly) would reject it.  Keep the
                    # compatibility key fail-closed and expose the narrower
                    # fact under an explicit name.
                    "comparability_hard_gate_pass": (
                        offer.comparison_evidence.hard_gate_result
                        == HardGateResult.PASS
                    ),
                    "automatic_eligible": False,
                    "automatic_eligibility_reason": (
                        "PERSISTED_ADMISSION_NOT_EVALUATED"
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
    #: Set when the candidates arrive from a marketplace grouping rather than a
    #: text search, so retrieval does not re-derive an identity already asserted.
    identity_source: str | None = None
    #: The number the search was run by, accepted as retrieval evidence when a
    #: listing repeats it.
    search_number: str | None = None
    #: The number whose market these candidates were taken from.
    via_oe_number: str | None = None
    #: Whether that number is a related one rather than our own.
    is_widened: bool = False
    #: Every storefront of ours, not merely the one that owns the seed.  KEMP
    #: runs four on prom.ua and they upload identical cards, so they resemble our
    #: product better than any competitor does: measured 2026-07-31, 48 of 65
    #: name matches were our own shops, and each of them consumed a slot of the
    #: ``max_sellers`` cap before the pricing gates ever saw it.
    excluded_seller_ids: frozenset[str] = frozenset()


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
        if params.excluded_seller_ids and (
            str(cand.seller_id or "") in params.excluded_seller_ids
        ):
            continue
        match = match_offer(
            seed_product,
            cand,
            params.threshold,
            params.identity_source,
            params.search_number,
        )
        if match is None:
            continue
        # Keep a broad search useful for discovery, but do not surface an
        # explicit semantic hard-stop as a competitor offer.  For example,
        # Camry's rear shock absorber and rear tail lamp share vehicle/side
        # tokens, while a brake line can share the same vehicle with a brake
        # hose. Unknown families and missing dimensions remain visible as
        # manual evidence and are held by the downstream gates.
        if _explicit_semantic_identity_conflict(seed_product, cand):
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
        source=params.identity_source or "SEARCH",
        via_oe_number=params.via_oe_number,
        is_widened=params.is_widened,
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
        # Prom category ids are useful retrieval hints but are too broad to
        # prove that two sellable parts have the same type.  The semantic
        # reviewer may fill this UNKNOWN value with cited card evidence.
        "part_type": DimensionEvidence(
            state=EvidenceState.UNKNOWN,
            evidence_refs=refs,
        ),
        "brand_manufacturer": normalized_categorical_dimension(
            "brand_manufacturer", seed.brand, candidate.brand, evidence_refs=refs
        ),
        "fitment": normalized_categorical_dimension(
            "fitment", seed.fitment, candidate.fitment, evidence_refs=refs
        ),
        "vehicle_generation": normalized_categorical_dimension(
            "vehicle_generation",
            seed.vehicle_generation,
            candidate.vehicle_generation,
            evidence_refs=refs,
        ),
        "year_interval": _year_dimension(seed, candidate, refs),
        "engine": normalized_categorical_dimension(
            "engine", seed.engine, candidate.engine, evidence_refs=refs
        ),
        "body_variant": normalized_categorical_dimension(
            "body_variant",
            seed.body_variant,
            candidate.body_variant,
            evidence_refs=refs,
        ),
        "side": normalized_categorical_dimension(
            "side", seed.side, candidate.side, evidence_refs=refs
        ),
        "position": normalized_categorical_dimension(
            "position", seed.position, candidate.position, evidence_refs=refs
        ),
        "condition": normalized_categorical_dimension(
            "condition", seed.condition, candidate.condition, evidence_refs=refs
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
    hard_gate_result = decision.hard_gate_result
    reason_codes = decision.reason_codes
    detail_evidence = candidate.detail_evidence
    if isinstance(detail_evidence, dict):
        conflicts = detail_evidence.get("conflicts")
        if isinstance(conflicts, dict) and any(
            str(field).strip().casefold() in {"mpn", "oe_raw", "part_numbers"}
            for field in conflicts
        ):
            # The listing/detail identity disagreement is stronger than the
            # compatibility payload assembled from the listing alone.  Keep
            # the observation visible, but never expose it as automatically
            # eligible through the public comparison serializer.
            hard_gate_result = HardGateResult.MANUAL_REVIEW
            reason_codes = tuple(
                dict.fromkeys((*reason_codes, "DETAIL_IDENTITY_CONFLICT"))
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
        hard_gate_result=hard_gate_result,
        reason_codes=reason_codes,
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
