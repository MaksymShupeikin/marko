"""Total candidate validation and versioned source-confidence assessment.

This module also owns the *closed acquisition vocabulary*: the small set of
values that may describe where one market came from and how it was taken.  It
lives here, with no ``marko`` imports, so that both the frozen scraper boundary
(:mod:`marko.services.scraper_contract`) and persistence
(:mod:`marko.services.market_collection`) can validate against exactly the same
contract without importing each other.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

from metis.pricing import normalize_oe


SOURCE_CONFIDENCE_METHOD_VERSION = "source-confidence-v1"
ACQUISITION_CONTRACT_VERSION = "acquisition-lineage-v1"
_ZERO = Decimal("0")
_ONE = Decimal("1")
_WEIGHTS = {
    "listing_identity": Decimal("0.20"),
    "seller_identity": Decimal("0.20"),
    "price_currency": Decimal("0.20"),
    "availability": Decimal("0.10"),
    "url": Decimal("0.10"),
    "structured_completeness": Decimal("0.20"),
}


# --------------------------------------------------------------------------
# Closed acquisition vocabulary
# --------------------------------------------------------------------------
#
# Three orthogonal facts describe one acquisition, and all three are needed
# before anything downstream may treat it as a claim about identity:
#
#   * ``source``          — whose surface produced the market;
#   * ``method``          — how it was taken from that surface;
#   * ``retrieval_kind``  — the per-record label that survives the
#                           ``comparison_evidence`` round trip.
#
# Naming any one of them without the others is what let a text search be stored
# with ``retrieval_kind=prom_oe_page`` and then be graded ``VERIFIED_EXACT``.

#: prom.ua's own part-code page: the marketplace itself filed these offers.
ACQUISITION_SOURCE_OE_PAGE = "PROM_OE_PAGE"
#: An ordinary text search: word overlap, never a statement about identity.
ACQUISITION_SOURCE_SEARCH = "SEARCH"
#: Retained payloads that predate the acquisition contract.
ACQUISITION_SOURCE_LEGACY = "LEGACY_UNKNOWN"
ACQUISITION_SOURCES = frozenset(
    {
        ACQUISITION_SOURCE_OE_PAGE,
        ACQUISITION_SOURCE_SEARCH,
        ACQUISITION_SOURCE_LEGACY,
    }
)

ACQUISITION_METHOD_OE_PAGE_LISTING = "OE_PAGE_LISTING"
ACQUISITION_METHOD_TEXT_SEARCH = "TEXT_SEARCH"
ACQUISITION_METHOD_LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"
ACQUISITION_METHODS = frozenset(
    {
        ACQUISITION_METHOD_OE_PAGE_LISTING,
        ACQUISITION_METHOD_TEXT_SEARCH,
        ACQUISITION_METHOD_LEGACY_UNVERIFIED,
    }
)

RETRIEVAL_KIND_PRODUCT_SEED_COMPARISON = "product_seed_comparison"
RETRIEVAL_KIND_SEARCH_QUERY = "search_query"
RETRIEVAL_KIND_LEGACY_PRODUCT_SEED = "legacy_product_seed_comparison"
#: Offline replay lane.  In the vocabulary because it is a real acquisition
#: lane, and non-asserting because a fixture is not the marketplace speaking.
RETRIEVAL_KIND_FIXTURE_REPLAY = "fixture_replay"
RETRIEVAL_KIND_PROM_OE_PAGE = "prom_oe_page"
RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED = "prom_oe_page_widened"

#: Retrieval kinds whose market belongs to a number other than ours.
WIDENED_RETRIEVAL_KINDS = frozenset({RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED})
#: Retrieval kinds the marketplace itself grouped under a part code.
ASSERTING_RETRIEVAL_KINDS = frozenset(
    {RETRIEVAL_KIND_PROM_OE_PAGE, RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED}
)
_SEARCH_RETRIEVAL_KINDS = frozenset(
    {
        RETRIEVAL_KIND_PRODUCT_SEED_COMPARISON,
        RETRIEVAL_KIND_SEARCH_QUERY,
        RETRIEVAL_KIND_LEGACY_PRODUCT_SEED,
        RETRIEVAL_KIND_FIXTURE_REPLAY,
    }
)

_SOURCE_BY_METHOD = {
    ACQUISITION_METHOD_OE_PAGE_LISTING: ACQUISITION_SOURCE_OE_PAGE,
    ACQUISITION_METHOD_TEXT_SEARCH: ACQUISITION_SOURCE_SEARCH,
    ACQUISITION_METHOD_LEGACY_UNVERIFIED: ACQUISITION_SOURCE_LEGACY,
}


class AcquisitionContractError(ValueError):
    """One acquisition description contradicts itself.

    Deliberately distinct from "the market was empty": an empty result is a
    truthful answer, an inconsistent lineage is a payload that cannot be
    believed at all.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def method_for_retrieval_kind(retrieval_kind: str | None) -> str:
    """The only acquisition method a given retrieval kind may belong to."""

    kind = (retrieval_kind or "").strip()
    if kind in ASSERTING_RETRIEVAL_KINDS:
        return ACQUISITION_METHOD_OE_PAGE_LISTING
    if kind in _SEARCH_RETRIEVAL_KINDS:
        return ACQUISITION_METHOD_TEXT_SEARCH
    return ACQUISITION_METHOD_LEGACY_UNVERIFIED


@dataclass(frozen=True, slots=True)
class AcquisitionLineage:
    """Where one market came from, as a closed and mutually consistent whole.

    Every field is evidence produced by the acquisition itself.  Nothing here
    may be reconstructed from the catalog: the moment ``queried_oe_norm`` is
    filled in from ``CatalogItem.oe_norm`` the record stops being a statement
    by the marketplace and becomes a restatement of our own intent.
    """

    source: str
    method: str
    retrieval_kind: str
    is_widened: bool
    #: The number the page was actually requested by, as the acquisition
    #: reported it.  ``None`` for a text search — a search asserts nothing.
    queried_oe_norm: str | None
    #: The number whose market was actually taken (widening only).
    via_oe_number: str | None
    #: The prepared/source URL the request was issued against.
    source_url: str | None
    #: Identity of the acquisition request itself, so the retained bytes can be
    #: bound to *this* request rather than to any capture with the same hash.
    input_hash: str | None = None
    contract_version: str = ACQUISITION_CONTRACT_VERSION

    @property
    def asserts_identity(self) -> bool:
        """Whether this acquisition may stand in for missing card evidence."""

        return self.method == ACQUISITION_METHOD_OE_PAGE_LISTING

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "method": self.method,
            "is_widened": self.is_widened,
            "queried_oe_norm": self.queried_oe_norm,
            "via_oe_number": self.via_oe_number,
            "source_url": self.source_url,
            "input_hash": self.input_hash,
            "contract_version": self.contract_version,
        }

    @classmethod
    def unverified(
        cls,
        *,
        retrieval_kind: str | None,
        via_oe_number: str | None = None,
        is_widened: bool = False,
    ) -> AcquisitionLineage:
        """A lineage that can never assert identity.

        Used for retained payloads and for any block that failed the contract:
        the market datum survives, the claim about identity does not.
        """

        via = (via_oe_number or "").strip() or None
        return cls(
            source=ACQUISITION_SOURCE_LEGACY,
            method=ACQUISITION_METHOD_LEGACY_UNVERIFIED,
            retrieval_kind=(retrieval_kind or "").strip()[:80],
            is_widened=bool(is_widened) and via is not None,
            queried_oe_norm=None,
            via_oe_number=via,
            source_url=None,
            input_hash=None,
        )

    @classmethod
    def validated(
        cls,
        raw: Any,
        *,
        retrieval_kind: str | None,
        prepared_url: str | None = None,
        input_hash: str | None = None,
        fallback_queried_oe: str | None = None,
        require_url_binding: bool = False,
    ) -> AcquisitionLineage:
        """Build a lineage or refuse; never silently repair a contradiction."""

        kind = (retrieval_kind or "").strip()
        if raw is None:
            if kind in ASSERTING_RETRIEVAL_KINDS:
                raise AcquisitionContractError(
                    "ACQUISITION_BLOCK_MISSING",
                    f"{kind} claims a part-code page with no acquisition block",
                )
            raw = {}
        if not isinstance(raw, Mapping):
            raise AcquisitionContractError(
                "ACQUISITION_BLOCK_NOT_MAPPING", type(raw).__name__
            )

        expected_method = method_for_retrieval_kind(kind)
        if expected_method == ACQUISITION_METHOD_LEGACY_UNVERIFIED and kind:
            raise AcquisitionContractError("ACQUISITION_RETRIEVAL_KIND_UNKNOWN", kind)
        expected_source = _SOURCE_BY_METHOD[expected_method]

        stated_source = str(raw.get("source") or "").strip().upper()
        if stated_source and stated_source not in ACQUISITION_SOURCES:
            raise AcquisitionContractError(
                "ACQUISITION_SOURCE_UNKNOWN", stated_source[:80]
            )
        if stated_source and stated_source != expected_source:
            raise AcquisitionContractError(
                "ACQUISITION_SOURCE_CONFLICT",
                f"{kind} cannot come from {stated_source}",
            )
        stated_method = str(raw.get("method") or "").strip().upper()
        if stated_method and stated_method not in ACQUISITION_METHODS:
            raise AcquisitionContractError(
                "ACQUISITION_METHOD_UNKNOWN", stated_method[:80]
            )
        if stated_method and stated_method != expected_method:
            raise AcquisitionContractError(
                "ACQUISITION_METHOD_CONFLICT",
                f"{kind} cannot be taken by {stated_method}",
            )

        stated_widened = bool(raw.get("is_widened"))
        kind_widened = kind in WIDENED_RETRIEVAL_KINDS
        if stated_widened != kind_widened:
            raise AcquisitionContractError(
                "ACQUISITION_WIDENING_CONFLICT",
                f"is_widened={stated_widened} with retrieval_kind={kind!r}",
            )

        via_raw = str(raw.get("via_oe_number") or "").strip() or None
        via_norm = normalize_oe(via_raw) if via_raw else None
        queried_raw = str(raw.get("queried_oe_norm") or "").strip() or None
        if queried_raw is None:
            queried_raw = (fallback_queried_oe or "").strip() or None
        queried_norm = normalize_oe(queried_raw) if queried_raw else None

        if expected_method == ACQUISITION_METHOD_OE_PAGE_LISTING:
            if queried_norm is None:
                raise AcquisitionContractError(
                    "ACQUISITION_QUERY_OE_MISSING",
                    "a part-code page must name the number it was requested by",
                )
            if kind_widened:
                if via_norm is None:
                    raise AcquisitionContractError(
                        "ACQUISITION_VIA_OE_MISSING",
                        "a widened acquisition must name the number it used",
                    )
                if via_norm == queried_norm:
                    raise AcquisitionContractError(
                        "ACQUISITION_WIDENING_WITHOUT_A_DIFFERENT_NUMBER",
                        f"{via_norm} is the requested number",
                    )
            elif via_norm is not None and via_norm != queried_norm:
                raise AcquisitionContractError(
                    "ACQUISITION_VIA_OE_NOT_WIDENED",
                    f"market taken by {via_norm}, requested {queried_norm}",
                )
        else:
            if queried_raw is not None and raw.get("queried_oe_norm"):
                raise AcquisitionContractError(
                    "ACQUISITION_QUERY_OE_ON_SEARCH",
                    "a text search does not assert a part number",
                )
            queried_norm = None
            if via_norm is not None:
                raise AcquisitionContractError(
                    "ACQUISITION_VIA_OE_ON_SEARCH",
                    "a text search cannot be taken by a related number",
                )

        prepared = (prepared_url or "").strip() or None
        stated_url = str(raw.get("source_url") or "").strip() or None
        if stated_url is not None and prepared is not None and stated_url != prepared:
            raise AcquisitionContractError(
                "ACQUISITION_SOURCE_URL_MISMATCH",
                f"{stated_url} is not the prepared URL {prepared}",
            )
        # ``require_url_binding`` is only true for the caller that owns the
        # payload envelope and therefore knows whether a prepared URL exists at
        # all.  A caller handing us a bare record cannot distinguish "there was
        # no URL" from "I did not pass it", so it must not be able to reject.
        if require_url_binding and stated_url is not None and prepared is None:
            raise AcquisitionContractError(
                "ACQUISITION_SOURCE_URL_UNEXPECTED",
                "a query-only acquisition has no prepared URL",
            )
        if require_url_binding and stated_url is None and prepared is not None:
            stated_url = prepared

        stated_hash = str(raw.get("input_hash") or "").strip() or None
        expected_hash = (input_hash or "").strip() or None
        if (
            stated_hash is not None
            and expected_hash is not None
            and stated_hash != expected_hash
        ):
            raise AcquisitionContractError(
                "ACQUISITION_INPUT_HASH_MISMATCH",
                "the block names a different acquisition request",
            )

        return cls(
            source=expected_source,
            method=expected_method,
            retrieval_kind=kind,
            is_widened=kind_widened,
            queried_oe_norm=queried_norm,
            via_oe_number=via_raw if kind_widened else None,
            source_url=stated_url or prepared,
            input_hash=stated_hash or expected_hash,
        )

    @classmethod
    def from_record(
        cls,
        raw: Any,
        *,
        retrieval_kind: str | None,
        prepared_url: str | None = None,
        input_hash: str | None = None,
        fallback_queried_oe: str | None = None,
        require_url_binding: bool = False,
    ) -> tuple[AcquisitionLineage, tuple[str, ...]]:
        """Lineage plus the reason it could not be trusted, if it could not.

        Persistence must not lose a market datum because its origin block is
        malformed — it must lose the *claim*.  A contract failure therefore
        degrades to :meth:`unverified` and reports why.
        """

        try:
            return (
                cls.validated(
                    raw,
                    retrieval_kind=retrieval_kind,
                    prepared_url=prepared_url,
                    input_hash=input_hash,
                    fallback_queried_oe=fallback_queried_oe,
                    require_url_binding=require_url_binding,
                ),
                (),
            )
        except AcquisitionContractError as exc:
            block = raw if isinstance(raw, Mapping) else {}
            return (
                cls.unverified(
                    retrieval_kind=retrieval_kind,
                    via_oe_number=str(block.get("via_oe_number") or "").strip() or None,
                    is_widened=bool(block.get("is_widened")),
                ),
                (exc.code,),
            )


#: Родословная retained-записи, о происхождении которой ничего не известно.
_LEGACY_LINEAGE = AcquisitionLineage.unverified(retrieval_kind="legacy_unknown")


class EvidenceAccountingError(ValueError):
    """The terminal offer partition does not conserve retrieved elements."""


class OfferOutcomeCode(StrEnum):
    OBSERVATION_PERSISTED = "OBSERVATION_PERSISTED"
    REJECTED_NOT_MAPPING = "REJECTED_NOT_MAPPING"
    REJECTED_INVALID_PRICE = "REJECTED_INVALID_PRICE"
    REJECTED_INVALID_MATCH_SCORE = "REJECTED_INVALID_MATCH_SCORE"
    REJECTED_MISSING_LISTING_IDENTITY = "REJECTED_MISSING_LISTING_IDENTITY"
    REJECTED_SCHEMA_MISMATCH = "REJECTED_SCHEMA_MISMATCH"
    REJECTED_SERIALIZATION = "REJECTED_SERIALIZATION"
    FAILED_INTERNAL_PROCESSING = "FAILED_INTERNAL_PROCESSING"


@dataclass(frozen=True, slots=True)
class RejectedOffer:
    raw_offer_index: int
    outcome_code: OfferOutcomeCode
    reason_codes: tuple[str, ...]
    safe_sample: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class AcceptedCandidate:
    raw_offer_index: int
    retrieval_kind: str
    retrieval_score: Decimal | None
    product: Mapping[str, Any]
    upstream_comparison_evidence: Mapping[str, Any] | None
    #: Номер, по которому фактически взят рынок. Отличается от нашего кода,
    #: когда у него самого нет листинга и использован номер из цепочки
    #: замещений. Без него расширенный кросс не может назвать, к чему относится.
    via_oe_number: str | None
    #: Расширение утверждается только вместе с ``via_oe_number``: заявление без
    #: названного номера — заявление без содержания.
    is_widened: bool
    price: Decimal
    reference_price: Decimal | None
    source_listing_id: str
    listing_identity_quality: Decimal
    #: Полная типизированная родословная приобретения. ``LEGACY_UNVERIFIED``
    #: там, где блок происхождения отсутствовал или противоречил сам себе.
    acquisition: AcquisitionLineage = _LEGACY_LINEAGE
    #: Почему родословную нельзя было принять целиком.
    acquisition_reason_codes: tuple[str, ...] = ()

    @property
    def acquisition_source(self) -> str:
        return self.acquisition.source

    @property
    def acquisition_method(self) -> str:
        return self.acquisition.method

    @property
    def queried_oe_norm(self) -> str | None:
        """Номер, по которому источник действительно брал рынок."""

        return self.acquisition.queried_oe_norm

    @property
    def source_url(self) -> str | None:
        return self.acquisition.source_url


@dataclass(frozen=True, slots=True)
class SourceConfidenceAssessment:
    value: Decimal
    method_version: str
    factors: Mapping[str, str | bool]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OfferAccounting:
    retrieved: int
    observations_persisted: int
    rejected: int
    internal_failures: int

    def validate(self) -> None:
        values = (
            self.retrieved,
            self.observations_persisted,
            self.rejected,
            self.internal_failures,
        )
        if any(value < 0 for value in values):
            raise EvidenceAccountingError(
                "offer accounting counters cannot be negative"
            )
        if self.retrieved != sum(values[1:]):
            raise EvidenceAccountingError("EVIDENCE_ACCOUNTING_ERROR: R != O + J + F")

    def as_dict(self) -> dict[str, int]:
        self.validate()
        return {
            "retrieved": self.retrieved,
            "observations_persisted": self.observations_persisted,
            "rejected": self.rejected,
            "internal_failures": self.internal_failures,
        }


def process_offer_candidate(
    raw_offer: Any,
    *,
    fallback_index: int,
    prepared_url: str | None = None,
    input_hash: str | None = None,
    fallback_queried_oe: str | None = None,
) -> AcceptedCandidate | RejectedOffer:
    """Return exactly one typed validation result for one retrieved element.

    ``prepared_url``/``input_hash``/``fallback_queried_oe`` describe the
    acquisition request this element was retrieved by.  They are supplied by
    the caller that owns the payload envelope; a record whose own block
    disagrees with them keeps its price but loses its identity claim.
    """

    if not isinstance(raw_offer, Mapping):
        return _rejected(
            fallback_index,
            OfferOutcomeCode.REJECTED_NOT_MAPPING,
            "OFFER_NOT_MAPPING",
            raw_offer,
        )
    is_envelope = "product" in raw_offer or "raw_offer_index" in raw_offer
    raw_index = raw_offer.get("raw_offer_index", fallback_index)
    if not isinstance(raw_index, int) or isinstance(raw_index, bool) or raw_index < 0:
        return _rejected(
            fallback_index,
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
            "RAW_OFFER_INDEX_INVALID",
            raw_offer,
        )
    if raw_index != fallback_index:
        return _rejected(
            fallback_index,
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
            "RAW_OFFER_INDEX_NOT_CANONICAL",
            raw_offer,
        )
    product: Any = raw_offer.get("product") if is_envelope else raw_offer
    if not isinstance(product, Mapping):
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
            "CANDIDATE_PRODUCT_NOT_MAPPING",
            raw_offer,
        )
    price, reference_price = resolve_offer_price_boundary(product)
    if price is None:
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_INVALID_PRICE,
            "PRICE_NOT_DECIMAL",
            product,
        )

    retrieval_raw = (
        raw_offer.get("retrieval_score")
        if is_envelope
        else raw_offer.get("match_score")
    )
    retrieval_score: Decimal | None = None
    if retrieval_raw is not None:
        try:
            retrieval_score = Decimal(str(retrieval_raw)).quantize(Decimal("0.0001"))
        except (InvalidOperation, TypeError, ValueError):
            return _rejected(
                raw_index,
                OfferOutcomeCode.REJECTED_INVALID_MATCH_SCORE,
                "RETRIEVAL_SCORE_NOT_DECIMAL",
                product,
            )
        if (
            not retrieval_score.is_finite()
            or retrieval_score < 0
            or retrieval_score > 1
        ):
            return _rejected(
                raw_index,
                OfferOutcomeCode.REJECTED_INVALID_MATCH_SCORE,
                "RETRIEVAL_SCORE_OUT_OF_RANGE",
                product,
            )

    product_id = product.get("product_id", product.get("id"))
    url = str(product.get("url") or "").strip()
    if product_id is not None and str(product_id).strip():
        source_listing_id = str(product_id).strip()[:255]
        listing_quality = Decimal("1")
    elif _valid_http_url(url):
        source_listing_id = hashlib.sha256(url.encode("utf-8")).hexdigest()
        listing_quality = Decimal("0.75")
    else:
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_MISSING_LISTING_IDENTITY,
            "LISTING_IDENTITY_MISSING",
            product,
        )

    upstream = (
        raw_offer.get("upstream_comparison_evidence")
        if is_envelope
        else raw_offer.get("comparison_evidence")
    )
    if upstream is not None and not isinstance(upstream, Mapping):
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
            "COMPARISON_EVIDENCE_NOT_MAPPING",
            product,
        )
    try:
        json.dumps(
            raw_offer,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return _rejected(
            raw_index,
            OfferOutcomeCode.REJECTED_SERIALIZATION,
            "OFFER_NOT_DETERMINISTIC_JSON",
            raw_offer,
        )
    retrieval_kind = str(
        raw_offer.get("retrieval_kind")
        or raw_offer.get("match_kind")
        or "legacy_unknown"
    )[:80]
    raw_acquisition = raw_offer.get("acquisition")
    if raw_acquisition is None and "acquisition" not in raw_offer:
        raw_acquisition = None
    # Признак расширения раньше жил только в блоке; ``retrieval_kind`` и блок
    # могли разойтись. Приводим их к самому осторожному прочтению ДО проверки
    # контракта: объявить рынок родственного номера своим — та ошибка, которую
    # хранить нельзя.
    if (
        isinstance(raw_acquisition, Mapping)
        and bool(raw_acquisition.get("is_widened"))
        and str(raw_acquisition.get("via_oe_number") or "").strip()
        and retrieval_kind in ASSERTING_RETRIEVAL_KINDS
    ):
        retrieval_kind = RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED
    lineage, acquisition_reasons = AcquisitionLineage.from_record(
        raw_acquisition,
        retrieval_kind=retrieval_kind,
        prepared_url=prepared_url,
        input_hash=input_hash,
        fallback_queried_oe=fallback_queried_oe,
    )
    return AcceptedCandidate(
        raw_offer_index=raw_index,
        retrieval_kind=retrieval_kind,
        retrieval_score=retrieval_score,
        product=dict(product),
        upstream_comparison_evidence=(dict(upstream) if upstream is not None else None),
        via_oe_number=lineage.via_oe_number if lineage.is_widened else None,
        is_widened=lineage.is_widened,
        price=price,
        reference_price=reference_price,
        source_listing_id=source_listing_id,
        listing_identity_quality=listing_quality,
        acquisition=lineage,
        acquisition_reason_codes=acquisition_reasons,
    )


def resolve_offer_price_boundary(
    product: Mapping[str, Any],
) -> tuple[Decimal | None, Decimal | None]:
    """Return active sale price and optional crossed-out reference price.

    Prom snapshots have used both camelCase and normalized snake_case keys.
    A valid discounted price wins over ``price``; a higher current/original
    value is retained only as reference evidence and never enters market math.
    """

    def parse(value: Any) -> Decimal | None:
        try:
            parsed = Decimal(str(value)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return parsed if parsed.is_finite() and parsed > 0 else None

    explicit_sale = parse(product.get("sale_price", product.get("salePrice")))
    explicit_reference = parse(
        product.get("reference_price", product.get("referencePrice"))
    )
    current = parse(product.get("price"))
    discounted = parse(
        product.get("discounted_price", product.get("discountedPrice"))
    )
    original = parse(product.get("price_original", product.get("priceOriginal")))
    active_discount = explicit_sale or discounted
    # A malformed/stale payload can place the crossed-out value in
    # ``discounted_price``. Never let a value higher than the current price
    # inflate the market; retain it as reference evidence instead.
    if active_discount is not None:
        lower_base = current
        if lower_base is None:
            lower_base = min(
                (
                    value
                    for value in (original, explicit_reference)
                    if value is not None
                ),
                default=None,
            )
        if lower_base is not None and active_discount > lower_base:
            active_discount = lower_base
    if active_discount is not None:
        sale = active_discount
        reference_candidates = [
            value
            for value in (explicit_reference, current, original, discounted)
            if value is not None and value > sale
        ]
        return sale, max(reference_candidates) if reference_candidates else None
    sale = current or original
    if sale is None:
        return None, None
    reference_candidates = [
        value
        for value in (explicit_reference, original)
        if value is not None and value > sale
    ]
    reference = max(reference_candidates) if reference_candidates else None
    return sale, reference


def assess_source_confidence(
    *,
    raw_capture_verified: bool,
    parser_contract_verified: bool,
    listing_identity_quality: Decimal,
    seller_identity_quality: Decimal,
    price_currency_quality: Decimal,
    availability_quality: Decimal,
    url_quality: Decimal,
    structured_completeness: Decimal,
) -> SourceConfidenceAssessment:
    values = {
        "listing_identity": _bounded(listing_identity_quality),
        "seller_identity": _bounded(seller_identity_quality),
        "price_currency": _bounded(price_currency_quality),
        "availability": _bounded(availability_quality),
        "url": _bounded(url_quality),
        "structured_completeness": _bounded(structured_completeness),
    }
    reasons: list[str] = []
    if not raw_capture_verified:
        reasons.append("SOURCE_RAW_CAPTURE_UNVERIFIED")
    if not parser_contract_verified:
        reasons.append("SOURCE_PARSER_CONTRACT_UNRECOGNIZED")
    for name, value in values.items():
        if value < _ONE:
            reasons.append(f"SOURCE_{name.upper()}_INCOMPLETE")
    confidence = (
        sum((_WEIGHTS[name] * value for name, value in values.items()), _ZERO)
        if raw_capture_verified and parser_contract_verified
        else _ZERO
    )
    confidence = confidence.quantize(Decimal("0.0001"))
    return SourceConfidenceAssessment(
        value=confidence,
        method_version=SOURCE_CONFIDENCE_METHOD_VERSION,
        factors={
            "raw_capture_verified": raw_capture_verified,
            "parser_contract_verified": parser_contract_verified,
            **{name: format(value, "f") for name, value in values.items()},
        },
        reason_codes=tuple(reasons),
    )


def assess_candidate_source(
    candidate: AcceptedCandidate,
    *,
    raw_capture_verified: bool,
    parser_contract_verified: bool,
) -> SourceConfidenceAssessment:
    product = candidate.product
    seller_id = str(product.get("seller_id") or "").strip()
    seller_name = str(product.get("seller_name") or "").strip()
    seller_quality = _ONE if seller_id else Decimal("0.35") if seller_name else _ZERO
    currency = str(product.get("currency") or "").strip()
    price_currency_quality = (
        _ONE
        if currency.casefold() in {"uah", "грн", "₴", "гривня", "гривень"}
        else Decimal("0.60")
        if currency
        else Decimal("0.30")
    )
    availability_quality = (
        _ONE
        if isinstance(product.get("is_available"), bool)
        else Decimal("0.60")
        if str(product.get("presence") or "").strip()
        else _ZERO
    )
    url = str(product.get("url") or "").strip()
    url_quality = (
        _ONE
        if _valid_prom_url(url)
        else Decimal("0.40")
        if _valid_http_url(url)
        else _ZERO
    )
    completeness_fields = (
        bool(str(product.get("name") or "").strip()),
        candidate.price > 0,
        bool(currency),
        bool(seller_id or seller_name),
        isinstance(product.get("is_available"), bool)
        or bool(str(product.get("presence") or "").strip()),
        bool(url),
    )
    completeness = Decimal(sum(completeness_fields)) / Decimal(len(completeness_fields))
    return assess_source_confidence(
        raw_capture_verified=raw_capture_verified,
        parser_contract_verified=parser_contract_verified,
        listing_identity_quality=candidate.listing_identity_quality,
        seller_identity_quality=seller_quality,
        price_currency_quality=price_currency_quality,
        availability_quality=availability_quality,
        url_quality=url_quality,
        structured_completeness=completeness,
    )


def safe_offer_sample(raw_offer: Any, *, raw_offer_index: int) -> dict[str, Any]:
    if not isinstance(raw_offer, Mapping):
        return {
            "raw_offer_index": raw_offer_index,
            "value_type": type(raw_offer).__name__,
        }
    product = raw_offer.get("product")
    value = product if isinstance(product, Mapping) else raw_offer
    return {
        "raw_offer_index": raw_offer_index,
        "keys": sorted(str(key)[:80] for key in value.keys())[:40],
        "has_product_id": bool(value.get("product_id") or value.get("id")),
        "has_url": bool(value.get("url")),
        "has_seller_id": bool(value.get("seller_id")),
        "has_price": value.get("price") is not None,
        "has_currency": bool(value.get("currency")),
    }


def _rejected(
    index: int,
    code: OfferOutcomeCode,
    reason: str,
    raw_offer: Any,
) -> RejectedOffer:
    return RejectedOffer(
        raw_offer_index=index,
        outcome_code=code,
        reason_codes=(reason,),
        safe_sample=safe_offer_sample(raw_offer, raw_offer_index=index),
    )


def _bounded(value: Decimal) -> Decimal:
    decimal = Decimal(str(value))
    if not decimal.is_finite() or decimal < _ZERO or decimal > _ONE:
        raise ValueError("source-confidence factor must be finite and in [0, 1]")
    return decimal


def _valid_http_url(value: str) -> bool:
    if not value:
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme.casefold() in {"http", "https"} and bool(parsed.netloc)


def _valid_prom_url(value: str) -> bool:
    if not _valid_http_url(value):
        return False
    hostname = (urlsplit(value).hostname or "").casefold()
    return hostname in {"prom.ua", "www.prom.ua"} or hostname.endswith(".prom.ua")


__all__ = [
    "ACQUISITION_CONTRACT_VERSION",
    "ACQUISITION_METHODS",
    "ACQUISITION_METHOD_LEGACY_UNVERIFIED",
    "ACQUISITION_METHOD_OE_PAGE_LISTING",
    "ACQUISITION_METHOD_TEXT_SEARCH",
    "ACQUISITION_SOURCES",
    "ACQUISITION_SOURCE_LEGACY",
    "ACQUISITION_SOURCE_OE_PAGE",
    "ACQUISITION_SOURCE_SEARCH",
    "ASSERTING_RETRIEVAL_KINDS",
    "RETRIEVAL_KIND_LEGACY_PRODUCT_SEED",
    "RETRIEVAL_KIND_PRODUCT_SEED_COMPARISON",
    "RETRIEVAL_KIND_PROM_OE_PAGE",
    "RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED",
    "RETRIEVAL_KIND_SEARCH_QUERY",
    "WIDENED_RETRIEVAL_KINDS",
    "AcceptedCandidate",
    "AcquisitionContractError",
    "AcquisitionLineage",
    "EvidenceAccountingError",
    "method_for_retrieval_kind",
    "OfferAccounting",
    "OfferOutcomeCode",
    "RejectedOffer",
    "SOURCE_CONFIDENCE_METHOD_VERSION",
    "SourceConfidenceAssessment",
    "assess_candidate_source",
    "assess_source_confidence",
    "process_offer_candidate",
    "safe_offer_sample",
]
