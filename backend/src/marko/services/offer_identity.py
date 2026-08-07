"""Deterministic candidate-OE extraction and verified identity boundary.

The catalog/search OE is discovery intent only.  This module can verify a
candidate exclusively from retained candidate evidence and an optional
confirmed one-hop cross reference.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from enum import StrEnum
import hashlib
import re
from types import MappingProxyType
from typing import Any

from metis.pricing import (
    ComparisonEvidence,
    DimensionEvidence,
    EvidenceState,
    evaluate_comparison_evidence,
    normalize_oe,
)
from marko.services.catalog_identity_safety import is_internal_catalog_code
from marko.services.offer_processing import (
    ACQUISITION_METHOD_OE_PAGE_LISTING,
    ACQUISITION_SOURCE_OE_PAGE,
    ASSERTING_RETRIEVAL_KINDS,
    WIDENED_RETRIEVAL_KINDS,
    AcquisitionLineage,
)


OE_EXTRACTOR_VERSION = "oe-extractor-v5"
PROM_MOTORS_CROSS_PROPOSAL_VERSION = "prom-motors-cross-proposal-v1"
OE_VERIFICATION_THRESHOLD = Decimal("0.90")
# A short bare number is common in seller stock codes, phone fragments and
# catalogue row ids.  Even an ``OE:`` prefix in free text is not enough to
# make that number an automatic identity claim: the same seller can repeat a
# private code in both the title and description.  Structured OE/cross fields
# and a provenance-verified detail page remain authoritative.
SHORT_NUMERIC_OE_MAX_DIGITS = 6
#: Уверенность заявления страницы кода детали. Не новая доменная величина:
#: приравнена к порогу проверки, то есть «ровно настолько авторитетно, чтобы
#: считаться подтверждением, и не более». Владелец может пересмотреть её
#: отдельным решением.
SOURCE_PAGE_ASSERTION_CONFIDENCE = OE_VERIFICATION_THRESHOLD
_STRONG_THRESHOLD = Decimal("0.90")
_MEDIUM_THRESHOLD = Decimal("0.70")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ANCHOR_RE = re.compile(
    r"(?:\bOE\b|\bOEM\b|\bOEM[- ]?NO\b|\bARTICLE\b|\bPART[- ]?NO\b|"
    r"АРТИКУЛ|КОД\s+(?:ВИРОБНИКА|ПРОИЗВОДИТЕЛЯ|ЗАПЧАСТИНИ|ЗАПЧАСТИ)|"
    r"КРОС+[- ]?(?:КОД|НОМЕРИ|НОМЕРА))"
    r"\s*[:#№=-]?\s*([A-Z0-9][A-Z0-9 ./_-]{2,38}[A-Z0-9])",
    re.IGNORECASE,
)
_PART_TOKEN_RE = re.compile(
    r"\b(?=[A-Z0-9./_-]{5,32}\b)(?=[A-Z0-9./_-]*\d)(?=[A-Z0-9./_-]*[A-Z])[A-Z0-9]+(?:[./_-][A-Z0-9]+)+\b",
    re.IGNORECASE,
)


class OeVerificationStatus(StrEnum):
    VERIFIED_EXACT = "VERIFIED_EXACT"
    VERIFIED_CROSS = "VERIFIED_CROSS"
    UNKNOWN = "UNKNOWN"
    CONFLICT = "CONFLICT"
    AMBIGUOUS = "AMBIGUOUS"
    LEGACY_UNVERIFIED = "LEGACY_UNVERIFIED"


class IdentityNamespace(StrEnum):
    """The namespace of a customer identity query.

    A customer article/MPN is not interchangeable with an OE number merely
    because the marketplace card repeats the same token.  Keeping the
    namespace explicit prevents an article such as ``313452`` from colliding
    with an unrelated OE carrying the same normalized value.
    """

    OE = "OE"
    MPN = "MPN"
    PART_NUMBER = "PART_NUMBER"
    CROSS = "CROSS"
    UNKNOWN = "UNKNOWN"


IDENTITY_NAMESPACE_VERSION = "identity-namespace-v1"


class OeEvidenceSourceKind(StrEnum):
    STRUCTURED_OE_FIELD = "STRUCTURED_OE_FIELD"
    LABELED_CHARACTERISTIC = "LABELED_CHARACTERISTIC"
    COMPATIBLE_REFERENCE_LIST = "COMPATIBLE_REFERENCE_LIST"
    PLATFORM_COMPATIBLE_REFERENCE_LIST = "PLATFORM_COMPATIBLE_REFERENCE_LIST"
    CANDIDATE_PART_NUMBER = "CANDIDATE_PART_NUMBER"
    SKU = "SKU"
    TITLE = "TITLE"
    DESCRIPTION = "DESCRIPTION"
    MANUFACTURER_PART_NUMBER = "MANUFACTURER_PART_NUMBER"
    DETAIL_PAGE = "DETAIL_PAGE"


@dataclass(frozen=True, slots=True)
class OeEvidenceItem:
    raw_value: str
    normalized_value: str
    source_kind: OeEvidenceSourceKind
    source_record_id: str
    raw_capture_id: str
    raw_content_sha256: str
    json_path: str | None
    char_span: tuple[int, int] | None
    context_label: str | None
    extractor_method: str
    extractor_version: str
    confidence: Decimal
    correlation_group: str

    @property
    def reference_id(self) -> str:
        payload = "|".join(
            (
                self.raw_capture_id,
                self.source_record_id,
                self.source_kind.value,
                self.json_path or "",
                f"{self.char_span[0]}:{self.char_span[1]}" if self.char_span else "",
                self.normalized_value,
            )
        )
        return f"oe-evidence:{hashlib.sha256(payload.encode()).hexdigest()}"

    def as_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_kind"] = self.source_kind.value
        value["confidence"] = format(self.confidence, "f")
        value["char_span"] = (
            {"start": self.char_span[0], "end": self.char_span[1]}
            if self.char_span is not None
            else None
        )
        value["evidence_ref"] = self.reference_id
        return value


@dataclass(frozen=True, slots=True)
class ConfirmedCross:
    search_oe_norm: str
    candidate_oe_norm: str
    canonical_identity_key: str
    confidence: Decimal
    cross_link_id: str | None = None


@dataclass(frozen=True, slots=True)
class PromMotorsCrossProposal:
    """Unconfirmed one-hop edge asserted by one verified Prom product card."""

    search_oe_norm: str
    candidate_oe_norm: str
    source_record_id: str
    raw_capture_id: str
    raw_content_sha256: str
    confidence: Decimal = Decimal("0.70")
    validation_state: str = "UNVALIDATED"
    automatic_identity_eligible: bool = False
    extraction_method_version: str = PROM_MOTORS_CROSS_PROPOSAL_VERSION

    @property
    def evidence_ref(self) -> str:
        payload = "|".join(
            (
                self.search_oe_norm,
                self.candidate_oe_norm,
                self.source_record_id,
                self.raw_capture_id,
                self.raw_content_sha256,
            )
        )
        return f"prom-motors-cross:{hashlib.sha256(payload.encode()).hexdigest()}"

    def as_dict(self, *, source_observation_id: str) -> dict[str, Any]:
        return {
            "raw_token": self.candidate_oe_norm,
            "normalized_token": self.candidate_oe_norm,
            "context_window": (
                "verified Prom motors compatible OE: "
                f"{self.search_oe_norm} <-> {self.candidate_oe_norm}"
            ),
            "source_observation_id": source_observation_id,
            "extraction_method_version": self.extraction_method_version,
            "confidence": format(self.confidence, "f"),
            "validation_state": self.validation_state,
            "automatic_identity_eligible": self.automatic_identity_eligible,
            "source_kind": "PROM_MOTORS_COMPATIBLE_OE",
            "candidate_native_part_code": self.candidate_oe_norm,
            "raw_content_sha256": self.raw_content_sha256,
            "source_record_id": self.source_record_id,
            "evidence_ref": self.evidence_ref,
        }


def extract_prom_motors_cross_proposals(
    raw_offer: Mapping[str, Any],
    verified_detail_manifest: Mapping[str, Any] | None,
    *,
    search_oe_norm: str,
) -> tuple[PromMotorsCrossProposal, ...]:
    """Return at most one relevant proposal; never a confirmed cross.

    The card must name its own normalized code and must list the current search
    identity among compatible numbers. This single-source assertion can soften
    a would-be hard conflict to manual review, but cannot verify identity.
    """

    if verified_detail_manifest is None:
        return ()
    source_record_id = str(
        verified_detail_manifest.get("source_record_id") or ""
    ).strip()
    raw_capture_id = str(
        verified_detail_manifest.get("raw_capture_id") or ""
    ).strip()
    raw_hash = str(
        verified_detail_manifest.get("raw_content_sha256") or ""
    ).casefold()
    if not (
        source_record_id
        and raw_capture_id
        and _SHA256_RE.fullmatch(raw_hash)
    ):
        return ()
    detail = raw_offer.get("detail_evidence")
    motors = _nested(detail, "motors") if isinstance(detail, Mapping) else None
    if not isinstance(motors, Mapping):
        return ()
    search = normalize_oe(search_oe_norm)
    candidate = _valid_normalized_oe(
        str(motors.get("normalized_part_code") or ""),
        allow_long_numeric=True,
    )
    compatible = {
        normalized
        for value in _split_structured_values(motors.get("compatible_oe_numbers"))
        if (
            normalized := _valid_normalized_oe(
                value,
                allow_long_numeric=True,
            )
        )
        is not None
    }
    if search is None or candidate is None or candidate == search:
        return ()
    if search not in compatible:
        return ()
    return (
        PromMotorsCrossProposal(
            search_oe_norm=search,
            candidate_oe_norm=candidate,
            source_record_id=source_record_id,
            raw_capture_id=raw_capture_id,
            raw_content_sha256=raw_hash,
        ),
    )


@dataclass(frozen=True, slots=True)
class OeVerification:
    status: OeVerificationStatus
    extracted_oe_norms: tuple[str, ...]
    verified_matched_oe_norm: str | None
    comparison_identity_key: str | None
    confidence: Decimal
    evidence_refs: tuple[str, ...]
    reason_codes: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return self.status in {
            OeVerificationStatus.VERIFIED_EXACT,
            OeVerificationStatus.VERIFIED_CROSS,
        }


def _public_identity_value(value: Any) -> str | None:
    normalized = normalize_oe(str(value or ""))
    if normalized is None or is_internal_catalog_code(normalized):
        return None
    return normalized


def customer_identity_namespace(candidate: Any) -> IdentityNamespace:
    """Classify the frozen customer query without treating search intent as OE.

    ``identity_status`` is produced by the catalog importer/reparser.  The
    status, not the mere presence of ``oe_norm``, determines whether a value
    is an OE.  This is deliberately fail-closed for malformed/legacy rows.
    """

    status = str(getattr(candidate, "identity_status", "") or "").strip().upper()
    oe = _public_identity_value(getattr(candidate, "oe_norm", None))
    mpn = _public_identity_value(getattr(candidate, "mpn_norm", None))
    parts = tuple(
        value
        for raw in (getattr(candidate, "part_numbers_norm", None) or ())
        if (value := _public_identity_value(raw)) is not None
    )
    if status == "OE_CONFIRMED" and oe:
        return IdentityNamespace.OE
    if status == "MPN_ONLY" and (mpn or oe or parts):
        return IdentityNamespace.MPN
    if parts:
        return IdentityNamespace.PART_NUMBER
    return IdentityNamespace.UNKNOWN


def verified_identity_namespace(
    seed_namespace: IdentityNamespace,
    status: OeVerificationStatus | str,
) -> IdentityNamespace:
    """Return the namespace of the verified candidate identity."""

    try:
        verification_status = OeVerificationStatus(str(status))
    except (TypeError, ValueError):
        return IdentityNamespace.UNKNOWN
    if verification_status is OeVerificationStatus.VERIFIED_CROSS:
        return IdentityNamespace.CROSS
    if verification_status is OeVerificationStatus.VERIFIED_EXACT:
        return seed_namespace if seed_namespace is not IdentityNamespace.UNKNOWN else IdentityNamespace.UNKNOWN
    return IdentityNamespace.UNKNOWN


def namespace_bound_verification(
    verification: OeVerification,
    seed_namespace: IdentityNamespace,
) -> OeVerification:
    """Namespace exact non-OE keys while preserving generic verifier semantics."""

    if (
        verification.status is OeVerificationStatus.VERIFIED_EXACT
        and verification.verified_matched_oe_norm
        and seed_namespace in {
            IdentityNamespace.MPN,
            IdentityNamespace.PART_NUMBER,
        }
    ):
        prefix = seed_namespace.value
        return replace(
            verification,
            comparison_identity_key=(
                f"{prefix}:{verification.verified_matched_oe_norm}"
            ),
        )
    return verification


def namespace_identity_admission(
    *,
    seed_namespace: IdentityNamespace,
    verification: OeVerification,
    evidence_items: Iterable[OeEvidenceItem],
    base_automatic_evidence: bool,
) -> tuple[bool, str | None]:
    """Apply namespace-specific automatic-admission rules.

    The customer MPN is a retrieval/enrichment key, not the vehicle identity.
    Therefore an MPN-seeded row can be displayed and manually reviewed, but it
    can never enter the automatic pricing cohort until the identity graph has
    promoted the row to ``OE_CONFIRMED`` (or supplied a confirmed OE cross).
    This is deliberately stricter than merely seeing the same MPN in a native
    candidate field: sellers can copy an aftermarket number correctly while
    still advertising a different configuration or application.
    """

    verified_namespace = verified_identity_namespace(
        seed_namespace, verification.status
    )
    if not base_automatic_evidence:
        return False, "IDENTITY_EVIDENCE_INSUFFICIENT"
    if seed_namespace is IdentityNamespace.OE:
        if verification.status in {
            OeVerificationStatus.VERIFIED_EXACT,
            OeVerificationStatus.VERIFIED_CROSS,
        }:
            return True, None
        return False, "IDENTITY_NAMESPACE_NOT_VERIFIED"
    if seed_namespace is IdentityNamespace.MPN:
        return False, "MPN_NAMESPACE_REQUIRES_CONFIRMED_OE"
    if seed_namespace is IdentityNamespace.PART_NUMBER:
        return False, "PART_NUMBER_NAMESPACE_REQUIRES_OE_OR_CONFIRMED_CROSS"
    if verified_namespace is IdentityNamespace.CROSS:
        return False, "IDENTITY_NAMESPACE_SEED_UNKNOWN"
    return False, "IDENTITY_NAMESPACE_UNKNOWN"


def identity_admission_snapshot_is_current(
    identity_admission: Any,
    *,
    expected_identity_key: str | None = None,
) -> bool:
    """Validate the persisted namespace proof used by pricing boundaries."""

    if not isinstance(identity_admission, Mapping):
        return False
    if identity_admission.get("namespace_version") != IDENTITY_NAMESPACE_VERSION:
        return False
    try:
        seed = IdentityNamespace(
            str(identity_admission.get("seed_identity_namespace") or "")
        )
        verified = IdentityNamespace(
            str(identity_admission.get("verified_identity_namespace") or "")
        )
    except ValueError:
        return False
    if seed is IdentityNamespace.UNKNOWN or verified is IdentityNamespace.UNKNOWN:
        return False
    if identity_admission.get("automatic_evidence_sufficient") is not True:
        return False
    key = str(identity_admission.get("comparison_identity_key") or "").strip()
    if expected_identity_key is not None and key != str(expected_identity_key).strip():
        return False
    if verified is IdentityNamespace.CROSS:
        # Automatic analogue pricing is currently defined only for an
        # explicitly OE-typed seed.  MPN/PART_NUMBER crosses remain visible
        # for review and cannot be revived by a hand-edited snapshot.
        return seed is IdentityNamespace.OE and key.startswith("XREF:")
    if verified is IdentityNamespace.MPN:
        # A native MPN match is useful review evidence, but it is not a
        # vehicle-OE identity and must never revive an old automatic-pricing
        # snapshot.  Only OE and confirmed-cross namespaces can authorize the
        # pricing cohort.
        return False
    if verified is IdentityNamespace.PART_NUMBER:
        return key.startswith("PART_NUMBER:") and seed is IdentityNamespace.PART_NUMBER
    if verified is IdentityNamespace.OE:
        return seed is IdentityNamespace.OE and not key.startswith(
            ("MPN:", "PART_NUMBER:", "XREF:")
        )
    return False


# Free-form seller text is useful for discovery and manual review, but it is
# not a sufficiently independent identity assertion for the automatic pricing
# cohort.  A seller can copy an OE token into an SEO title or description even
# when the article is a component, an alternative configuration, or simply a
# bad listing.  Structured/detail namespaces carry a field boundary and can
# therefore support automatic admission when the verifier has already
# selected exactly one identity.
AUTOMATIC_IDENTITY_EVIDENCE_SOURCES = frozenset(
    {
        OeEvidenceSourceKind.STRUCTURED_OE_FIELD,
        OeEvidenceSourceKind.LABELED_CHARACTERISTIC,
        OeEvidenceSourceKind.COMPATIBLE_REFERENCE_LIST,
        OeEvidenceSourceKind.PLATFORM_COMPATIBLE_REFERENCE_LIST,
        OeEvidenceSourceKind.DETAIL_PAGE,
    }
)
FREE_TEXT_IDENTITY_EVIDENCE_SOURCES = frozenset(
    {
        OeEvidenceSourceKind.TITLE,
        OeEvidenceSourceKind.DESCRIPTION,
    }
)

# A candidate MPN, seller SKU, or generic part-number field is useful for
# retrieval and operator review, but it does not state that the value is the
# vehicle manufacturer's original OE. The pricing boundary therefore needs at
# least one source from this explicit OE/cross namespace. This is stricter than
# the generic discovery verifier on purpose: two copies of one seller's own
# code (for example ``mpn == sku``) are correlated evidence, not two
# independent assertions of original-part identity.
OE_NAMESPACE_EVIDENCE_SOURCES = frozenset(
    {
        OeEvidenceSourceKind.STRUCTURED_OE_FIELD,
        OeEvidenceSourceKind.LABELED_CHARACTERISTIC,
        OeEvidenceSourceKind.COMPATIBLE_REFERENCE_LIST,
        OeEvidenceSourceKind.PLATFORM_COMPATIBLE_REFERENCE_LIST,
        OeEvidenceSourceKind.DETAIL_PAGE,
    }
)


def automatic_identity_evidence_sufficient(
    verification: OeVerification,
    evidence_items: Iterable[OeEvidenceItem],
    *,
    authoritative_identity: bool = False,
    require_oe_namespace: bool = False,
) -> bool:
    """Return whether identity evidence may enter automatic pricing.

    ``verify_offer_identity`` intentionally remains useful for discovery and
    manual review, so a repeated title OE can still produce ``VERIFIED_EXACT``
    there.  This stricter admission predicate is used only at the persisted
    pricing boundary and during deterministic re-enrichment.  It prevents a
    single free-form title/description token from becoming price evidence.

    A retained Prom part-code page is an independent source assertion and is
    allowed through this predicate even when the seller card is silent. For
    ordinary cards, one strong structured/detail source is sufficient; the
    generic discovery mode may also use two non-text sources. The pricing mode
    passes ``require_oe_namespace=True`` and disallows that shortcut when both
    fields are merely MPN/SKU/part-number namespaces. Provenance-invalid
    evidence has confidence zero upstream and cannot satisfy either branch.
    """

    if authoritative_identity:
        return verification.verified
    if not verification.verified or not verification.verified_matched_oe_norm:
        return False
    matched = verification.verified_matched_oe_norm
    relevant = tuple(
        item
        for item in evidence_items
        if item.normalized_value == matched and item.confidence >= _MEDIUM_THRESHOLD
    )
    if require_oe_namespace and not any(
        item.source_kind in OE_NAMESPACE_EVIDENCE_SOURCES
        and item.confidence >= OE_VERIFICATION_THRESHOLD
        for item in relevant
    ):
        return False
    if any(
        item.source_kind in AUTOMATIC_IDENTITY_EVIDENCE_SOURCES
        and item.confidence >= OE_VERIFICATION_THRESHOLD
        for item in relevant
    ):
        return True
    non_text_groups = {
        item.correlation_group
        for item in relevant
        if item.source_kind not in FREE_TEXT_IDENTITY_EVIDENCE_SOURCES
    }
    return len(non_text_groups) >= 2


def extract_oe_evidence(
    raw_offer: Mapping[str, Any],
    raw_capture_manifest: Mapping[str, Any],
    *,
    verified_detail_manifest: Mapping[str, Any] | None = None,
) -> tuple[OeEvidenceItem, ...]:
    """Extract candidate-native identifiers without consulting search intent.

    ``verified_detail_manifest`` is accepted only after the product URL, id,
    seller, exact content hash and retained product-page journal entry have all
    been checked.  Prom's ``motors.normalized_part_code`` is the candidate
    card's own code.  ``compatible_oe_numbers`` are deliberately not promoted
    to candidate identifiers: they describe a cross graph and still require
    the confirmed-cross boundary.
    """

    source_record_id = str(raw_capture_manifest.get("source_record_id") or "").strip()
    raw_capture_id = str(raw_capture_manifest.get("raw_capture_id") or "").strip()
    raw_hash = str(raw_capture_manifest.get("raw_content_sha256") or "").casefold()
    provenance_complete = bool(
        source_record_id and raw_capture_id and _SHA256_RE.fullmatch(raw_hash)
    )
    if not provenance_complete:
        # Review-time evidence without immutable lineage is not allowed to verify.
        raw_hash = raw_hash if _SHA256_RE.fullmatch(raw_hash) else ""

    items: list[OeEvidenceItem] = []
    detail_evidence = raw_offer.get("detail_evidence")
    detail_fields = {
        str(field)
        for field in (
            _nested(detail_evidence, "field_sources") or {}
            if isinstance(detail_evidence, Mapping)
            else {}
        )
    }

    def manifest_for(field: str) -> Mapping[str, Any] | None:
        if field in detail_fields:
            # A detail-derived value must never inherit the listing capture's
            # provenance. An empty manifest deliberately reduces it to zero
            # confidence until the retained product-page bytes are verified.
            return verified_detail_manifest or {}
        return None

    def add(
        raw_value: Any,
        *,
        source_kind: OeEvidenceSourceKind,
        json_path: str | None,
        char_span: tuple[int, int] | None,
        context_label: str | None,
        method: str,
        confidence: Decimal,
        correlation_source: str,
        source_manifest: Mapping[str, Any] | None = None,
        allow_long_numeric: bool = False,
    ) -> None:
        if raw_value is None:
            return
        text = str(raw_value).strip()
        normalized = _valid_normalized_oe(
            text,
            allow_long_numeric=allow_long_numeric,
        )
        if normalized is None:
            return
        # Customer spreadsheets prove that KEMP 776... values are private
        # shelf/join codes, not public part identities.  Letting one of them
        # leave a mixed "Код запчастини"/"Кросс-номери" attribute creates an
        # artificial OE conflict beside the real OE on the same card.
        if is_internal_catalog_code(normalized):
            return
        if source_manifest is None:
            item_source_record_id = source_record_id
            item_raw_capture_id = raw_capture_id
            item_raw_hash = raw_hash
            item_provenance_complete = provenance_complete
        else:
            item_source_record_id = str(
                source_manifest.get("source_record_id") or ""
            ).strip()
            item_raw_capture_id = str(
                source_manifest.get("raw_capture_id") or ""
            ).strip()
            item_raw_hash = str(
                source_manifest.get("raw_content_sha256") or ""
            ).casefold()
            item_provenance_complete = bool(
                item_source_record_id
                and item_raw_capture_id
                and _SHA256_RE.fullmatch(item_raw_hash)
            )
            if not item_provenance_complete:
                item_raw_hash = (
                    item_raw_hash if _SHA256_RE.fullmatch(item_raw_hash) else ""
                )
        effective_confidence = (
            confidence if item_provenance_complete else Decimal("0")
        )
        group_digest = hashlib.sha256(
            correlation_source.strip().casefold().encode("utf-8")
        ).hexdigest()[:20]
        items.append(
            OeEvidenceItem(
                raw_value=text,
                normalized_value=normalized,
                source_kind=source_kind,
                source_record_id=item_source_record_id,
                raw_capture_id=item_raw_capture_id,
                raw_content_sha256=item_raw_hash,
                json_path=json_path,
                char_span=char_span,
                context_label=context_label,
                extractor_method=method,
                extractor_version=OE_EXTRACTOR_VERSION,
                confidence=effective_confidence,
                correlation_group=f"candidate-text:{group_digest}",
            )
        )

    structured_values = (
        (raw_offer.get("oe_raw"), "$.oe_raw"),
        (raw_offer.get("oe"), "$.oe"),
        (
            _nested(raw_offer, "comparisonEvidence", "oeRaw"),
            "$.comparisonEvidence.oeRaw",
        ),
        (
            _nested(
                raw_offer,
                "comparison_evidence",
                "dimensions",
                "oe_reference",
                "raw_value",
            ),
            "$.comparison_evidence.dimensions.oe_reference.raw_value",
        ),
    )
    for raw_value, path in structured_values:
        for value in _split_structured_values(raw_value):
            add(
                value,
                source_kind=OeEvidenceSourceKind.STRUCTURED_OE_FIELD,
                json_path=path,
                char_span=None,
                context_label="OE",
                method="structured_field",
                confidence=Decimal("0.99"),
                correlation_source=f"{path}:{value}",
                source_manifest=manifest_for("oe_raw"),
                allow_long_numeric=True,
            )

    for label, value, path in _iter_characteristics(raw_offer.get("characteristics")):
        label_confidence = _oe_label_confidence(label)
        if label_confidence is None:
            continue
        if _is_compatible_reference_label(label):
            source_kind = OeEvidenceSourceKind.COMPATIBLE_REFERENCE_LIST
        elif _is_candidate_part_number_label(label):
            source_kind = OeEvidenceSourceKind.CANDIDATE_PART_NUMBER
        else:
            source_kind = OeEvidenceSourceKind.LABELED_CHARACTERISTIC
        for candidate in _split_structured_values(value):
            candidate = _strip_manufacturer_prefix(candidate)
            add(
                candidate,
                source_kind=source_kind,
                json_path=path,
                char_span=None,
                context_label=label,
                method="structured_field",
                confidence=label_confidence,
                correlation_source=f"{path}:{candidate}",
                source_manifest=manifest_for("characteristics"),
                allow_long_numeric=True,
            )

    mpn = raw_offer.get("mpn")
    if mpn is not None:
        for value in _split_structured_values(mpn):
            add(
                value,
                source_kind=OeEvidenceSourceKind.MANUFACTURER_PART_NUMBER,
                json_path="$.mpn",
                char_span=None,
                context_label="MPN",
                method="manufacturer_part_number",
                # An MPN identifies the candidate's manufacturer article but
                # is not automatically the seed OE. It needs independent
                # support or a confirmed cross to verify identity.
                confidence=Decimal("0.88"),
                correlation_source=f"mpn:{value}",
                source_manifest=manifest_for("mpn"),
                allow_long_numeric=True,
            )

    # The normalized Prom parser keeps explicitly labelled card codes in a
    # dedicated ``part_numbers`` namespace.  Older evidence consumers only
    # looked at ``characteristics``; accepting this additive field keeps the
    # verified-identity boundary aligned with the parser without reclassifying
    # the value as OE or MPN.  It remains a medium-confidence native signal
    # and still obeys the namespace-specific admission rules below.
    part_numbers = raw_offer.get("part_numbers")
    if isinstance(part_numbers, (list, tuple, set)):
        for index, part_number in enumerate(part_numbers):
            for value in _split_structured_values(part_number):
                add(
                    value,
                    source_kind=OeEvidenceSourceKind.CANDIDATE_PART_NUMBER,
                    json_path=f"$.part_numbers[{index}]",
                    char_span=None,
                    context_label="PART_NUMBER",
                    method="parsed_labelled_part_number",
                    confidence=Decimal("0.88"),
                    correlation_source=f"part_numbers:{index}:{value}",
                    source_manifest=manifest_for("part_numbers"),
                    allow_long_numeric=True,
                )

    if verified_detail_manifest is not None and isinstance(detail_evidence, Mapping):
        normalized_part_code = _nested(
            detail_evidence,
            "motors",
            "normalized_part_code",
        )
        if normalized_part_code is not None:
            add(
                normalized_part_code,
                source_kind=OeEvidenceSourceKind.DETAIL_PAGE,
                json_path="$.result.motorsProductPage.normalizedPartCode",
                char_span=None,
                context_label="PROM_MOTORS_NORMALIZED_PART_CODE",
                method="prom_motors_normalized_part_code",
                confidence=Decimal("0.99"),
                correlation_source=(
                    "prom-motors-normalized-part-code:"
                    f"{normalized_part_code}"
                ),
                source_manifest=verified_detail_manifest,
                allow_long_numeric=True,
            )
        compatible_oe_numbers = _nested(
            detail_evidence,
            "motors",
            "compatible_oe_numbers",
        )
        for index, compatible_value in enumerate(
            compatible_oe_numbers
            if isinstance(compatible_oe_numbers, (list, tuple, set))
            else ()
        ):
            for value in _split_structured_values(compatible_value):
                add(
                    value,
                    source_kind=(
                        OeEvidenceSourceKind.PLATFORM_COMPATIBLE_REFERENCE_LIST
                    ),
                    json_path=(
                        "$.result.motorsProductPage.compatibleOeNumbers"
                        f"[{index}]"
                    ),
                    char_span=None,
                    context_label="PROM_MOTORS_COMPATIBLE_OE",
                    method="prom_motors_compatible_oe",
                    confidence=Decimal("0.97"),
                    correlation_source=(
                        "prom-motors-compatible-oe:"
                        f"{index}:{value}"
                    ),
                    source_manifest=verified_detail_manifest,
                    allow_long_numeric=True,
                )

    sku = raw_offer.get("sku")
    if sku is not None:
        sku_text = str(sku).strip()
        sku_labeled = _is_oe_label(str(raw_offer.get("sku_label") or ""))
        add(
            sku_text,
            source_kind=OeEvidenceSourceKind.SKU,
            json_path="$.sku",
            char_span=None,
            context_label=("OE" if sku_labeled else "SKU"),
            method=("exact_sku_with_oe_label" if sku_labeled else "exact_sku"),
            confidence=Decimal("0.93" if sku_labeled else "0.78"),
            correlation_source=f"sku:{sku_text}",
            source_manifest=manifest_for("sku"),
            allow_long_numeric=sku_labeled,
        )

    _extract_text_items(
        raw_offer.get("name") or raw_offer.get("title"),
        source_kind=OeEvidenceSourceKind.TITLE,
        json_path="$.name",
        anchored_confidence=Decimal("0.90"),
        add=add,
    )
    _extract_text_items(
        raw_offer.get("description"),
        source_kind=OeEvidenceSourceKind.DESCRIPTION,
        json_path="$.description",
        anchored_confidence=Decimal("0.75"),
        add=add,
        source_manifest=manifest_for("description"),
    )

    unique: dict[tuple[Any, ...], OeEvidenceItem] = {}
    for item in items:
        key = (
            item.normalized_value,
            item.source_kind,
            item.json_path,
            item.char_span,
            item.correlation_group,
        )
        current = unique.get(key)
        if current is None or item.confidence > current.confidence:
            unique[key] = item
    return tuple(
        sorted(
            unique.values(),
            key=lambda item: (
                item.normalized_value,
                -item.confidence,
                item.source_kind.value,
                item.json_path or "",
                item.char_span or (-1, -1),
            ),
        )
    )


def evidence_strength(
    oe_norm: str,
    evidence_items: Iterable[OeEvidenceItem],
) -> Decimal:
    grouped: dict[str, Decimal] = {}
    for item in evidence_items:
        if item.normalized_value != oe_norm:
            continue
        grouped[item.correlation_group] = max(
            grouped.get(item.correlation_group, Decimal("0")),
            item.confidence,
        )
    complement = Decimal("1")
    for confidence in grouped.values():
        complement *= Decimal("1") - confidence
    return (Decimal("1") - complement).quantize(Decimal("0.0001"))


#: Способы извлечения, при которых сама площадка утверждает идентичность.
#: Обычный текстовый поиск сюда не входит намеренно: выдача поиска — это
#: совпадение слов, а не заявление о том, что товар тот же самый.
_ASSERTING_RETRIEVAL_KINDS = ASSERTING_RETRIEVAL_KINDS
_WIDENED_RETRIEVAL_KINDS = WIDENED_RETRIEVAL_KINDS


@dataclass(frozen=True, slots=True)
class SourceAssertion:
    """Заявление площадки о том, под каким номером она подшила предложение.

    Продавцы на странице кода детали номер в заголовке не повторяют: замер
    2026-07-31 показал 1887 отброшенных предложений из 2181. Требовать номер в
    тексте карточки — значит выбрасывать рынок, который площадка уже собрала за
    нас. Но принять заявление можно только вместе с его происхождением, иначе
    любой запрос превращается в подтверждённую идентичность.

    Собирать его вручную нельзя: единственный поддерживаемый конструктор —
    :meth:`from_lineage`, потому что заявление обязано происходить из
    родословной приобретения, а не из наших собственных намерений.
    """

    #: Номер, по которому запрашивалась страница. Приходит ИЗ приобретения.
    queried_oe_norm: str
    #: Способ извлечения (``prom_oe_page`` / ``prom_oe_page_widened`` / поиск).
    retrieval_kind: str
    #: SHA-256 неизменяемого захвата, на который опирается заявление.
    capture_sha256: str
    confidence: Decimal
    #: Номер, по которому фактически взят рынок. Обязателен для расширения:
    #: кросс, не называющий, к чему он относится, — это не кросс.
    via_oe_number: str | None = None
    #: Откуда и как взят рынок. ``None`` — родословная не дошла, и тогда
    #: заявление проверяется только по способу извлечения (retained-строки).
    acquisition_source: str | None = None
    acquisition_method: str | None = None
    #: Подготовленный URL запроса, к которому привязан захват.
    source_url: str | None = None

    @property
    def is_widened(self) -> bool:
        return self.retrieval_kind.strip() in _WIDENED_RETRIEVAL_KINDS

    @classmethod
    def from_lineage(
        cls,
        lineage: AcquisitionLineage | None,
        *,
        capture_sha256: str,
        confidence: Decimal,
    ) -> SourceAssertion | None:
        """Собрать заявление ТОЛЬКО из проверенной родословной приобретения.

        Возвращает ``None``, когда приобретение ничего не утверждает: обычный
        поиск, отсутствующая или противоречивая родословная. Ключевое отличие
        от прежнего кода: запрошенный номер берётся из ``lineage``, а не из
        ``CatalogItem.oe_norm``. Восстанавливать его из каталога — значит
        превращать наше намерение в заявление площадки.
        """

        if lineage is None or not lineage.asserts_identity:
            return None
        queried = (lineage.queried_oe_norm or "").strip()
        if not queried:
            return None
        return cls(
            queried_oe_norm=queried,
            retrieval_kind=lineage.retrieval_kind,
            capture_sha256=capture_sha256,
            confidence=confidence,
            via_oe_number=lineage.via_oe_number,
            acquisition_source=lineage.source,
            acquisition_method=lineage.method,
            source_url=lineage.source_url,
        )

    def authoritative_for(self, query: str | None) -> bool:
        """Достаточно ли заявление авторитетно для этого запроса.

        Условия обязательны все: способ извлечения — страница конкретного
        номера, а не поиск; названный источник и способ приобретения не
        противоречат ему; есть неизменяемый захват; страница именно нашего
        номера; уверенность не нулевая.
        """

        if query is not None and is_internal_catalog_code(query):
            # KEMP shelf codes are private join keys.  Even a valid Prom OE
            # page assertion must not turn one into a public identity; callers
            # must resolve it through the customer identity graph first.
            return False
        if self.retrieval_kind.strip() not in _ASSERTING_RETRIEVAL_KINDS:
            return False
        # Родословная, если она названа, обязана согласовываться со способом
        # извлечения. Именно эта пара — ``prom_oe_page`` с ``source=SEARCH`` —
        # доезжала до ``VERIFIED_EXACT``.
        if (
            self.acquisition_source is not None
            and self.acquisition_source != ACQUISITION_SOURCE_OE_PAGE
        ):
            return False
        if (
            self.acquisition_method is not None
            and self.acquisition_method != ACQUISITION_METHOD_OE_PAGE_LISTING
        ):
            return False
        if not self.capture_sha256.strip():
            return False
        if self.confidence <= 0:
            return False
        # Расширение обязано назвать номер, по которому взят рынок.
        if self.is_widened and not normalize_oe(self.via_oe_number or ""):
            return False
        return query is not None and normalize_oe(self.queried_oe_norm) == query


def verify_offer_identity(
    search_oe_norm: str,
    evidence_items: Iterable[OeEvidenceItem],
    confirmed_crosses: Iterable[ConfirmedCross] = (),
    proposed_crosses: Iterable[PromMotorsCrossProposal] = (),
    *,
    legacy_without_reenrichment: bool = False,
    source_assertion: SourceAssertion | None = None,
    allow_short_numeric_native: bool = False,
) -> OeVerification:
    query = normalize_oe(search_oe_norm)
    evidence = tuple(evidence_items)

    # Fail closed before considering source assertions or candidate evidence:
    # a private KEMP code is not a public OE and cannot be verified in-place.
    if query is not None and is_internal_catalog_code(query):
        return OeVerification(
            status=OeVerificationStatus.UNKNOWN,
            extracted_oe_norms=tuple(
                sorted({item.normalized_value for item in evidence})
            ),
            verified_matched_oe_norm=None,
            comparison_identity_key=None,
            confidence=Decimal("0"),
            evidence_refs=(),
            reason_codes=("OE_PRIVATE_CATALOG_CODE_NOT_PUBLIC",),
        )

    def _asserted_by_source() -> OeVerification | None:
        """Принять заявление источника, когда карточка молчит.

        Только когда молчит: заявление подставляется вместо ОТСУТСТВИЯ улик, а
        не вместо противоречия. Извлечённый из карточки чужой номер — факт о
        самом товаре, и он остаётся решающим (см. ветки AMBIGUOUS/CONFLICT ниже).
        """

        if source_assertion is None or not source_assertion.authoritative_for(query):
            return None
        assert query is not None
        if source_assertion.is_widened:
            # Рынок родственного номера — это кросс, а не тот же номер, и он
            # требует доказанного родства. Запрос по номеру доказательством не
            # является: площадка могла подшить рынок под родственный код
            # ошибочно. Без подтверждённого кросса target↔via это
            # предположение, и оно остаётся UNKNOWN.
            via = normalize_oe(source_assertion.via_oe_number or "")
            proven = next(
                (
                    cross
                    for cross in confirmed_crosses
                    if normalize_oe(cross.search_oe_norm) == query
                    and normalize_oe(cross.candidate_oe_norm) == via
                ),
                None,
            )
            if via is None or proven is None:
                return None
            # Честная идентичность: подтверждён тот номер, по которому взят
            # рынок, а не наш собственный. Потолок грейда
            # ``ACCEPTABLE_ANALOGUE`` держится отдельно, на персистентности.
            return _verified_result(
                OeVerificationStatus.VERIFIED_CROSS,
                via,
                proven.canonical_identity_key,
                extracted,
                min(source_assertion.confidence, proven.confidence),
                evidence,
                "OE_ASSERTED_BY_WIDENED_SOURCE_PAGE",
            )
        return _verified_result(
            OeVerificationStatus.VERIFIED_EXACT,
            query,
            query,
            extracted,
            source_assertion.confidence,
            evidence,
            "OE_ASSERTED_BY_SOURCE_PAGE",
        )

    extracted = tuple(sorted({item.normalized_value for item in evidence}))
    if legacy_without_reenrichment:
        strengths = {value: evidence_strength(value, evidence) for value in extracted}
        return OeVerification(
            status=OeVerificationStatus.LEGACY_UNVERIFIED,
            extracted_oe_norms=extracted,
            verified_matched_oe_norm=None,
            comparison_identity_key=None,
            confidence=max(strengths.values(), default=Decimal("0")),
            evidence_refs=(),
            reason_codes=("OE_LEGACY_NOT_REENRICHED",),
        )
    if query is None or not extracted:
        # Карточка молчит — здесь и только здесь заявление источника имеет
        # право заменить отсутствующую улику.
        asserted = _asserted_by_source()
        if asserted is not None:
            return asserted
        return OeVerification(
            status=OeVerificationStatus.UNKNOWN,
            extracted_oe_norms=extracted,
            verified_matched_oe_norm=None,
            comparison_identity_key=None,
            confidence=Decimal("0"),
            evidence_refs=(),
            reason_codes=("OE_EVIDENCE_NOT_FOUND",),
        )

    strengths = {value: evidence_strength(value, evidence) for value in extracted}
    eligible = {
        value
        for value in extracted
        if strengths[value] >= OE_VERIFICATION_THRESHOLD
        and _has_independent_support(value, evidence)
    }
    # Keep the evidence in ``extracted_oe_norms`` for review, but do not let a
    # short all-numeric title/description token become a priceable identity.
    # This is deliberately narrower than the general OE rule: a structured
    # ``oe_raw``/OE-labelled cross field or a retained Prom detail card is a
    # separate provenance-bearing namespace and may still verify the number.
    blocked_short_numeric = {
        value
        for value in eligible
        if _short_numeric_identity_requires_structured_proof(value, evidence)
        and not (
            allow_short_numeric_native
            and _short_numeric_identity_has_native_proof(value, evidence)
        )
    }
    eligible = {
        value
        for value in eligible
        if value not in blocked_short_numeric
    }
    if not eligible:
        # Улики есть, но ни одна не дотянула до порога. Если среди них нет
        # нашего номера, это молчание, а не противоречие: карточка просто не
        # называет номер убедительно. Заявление источника допустимо только
        # тогда, когда извлечённое не противоречит запросу.
        contradicts = any(value != query for value in extracted)
        if not contradicts:
            asserted = _asserted_by_source()
            if asserted is not None:
                return asserted
        return OeVerification(
            status=OeVerificationStatus.UNKNOWN,
            extracted_oe_norms=extracted,
            verified_matched_oe_norm=None,
            comparison_identity_key=None,
            confidence=max(strengths.values(), default=Decimal("0")),
            evidence_refs=(),
            reason_codes=(
                "OE_SHORT_NUMERIC_REQUIRES_STRUCTURED_PROOF"
                if blocked_short_numeric
                else "OE_EVIDENCE_BELOW_THRESHOLD",
            ),
        )

    cross_by_candidate = {
        cross.candidate_oe_norm: cross
        for cross in confirmed_crosses
        if cross.search_oe_norm == query
    }
    proposed_candidates = {
        proposal.candidate_oe_norm
        for proposal in proposed_crosses
        if proposal.search_oe_norm == query
        and proposal.automatic_identity_eligible is False
        and proposal.validation_state == "UNVALIDATED"
    }
    exact = {value for value in eligible if value == query}
    cross_values = {value for value in eligible if value in cross_by_candidate}
    incompatible = eligible - exact - cross_values
    native_detail_values = {
        item.normalized_value
        for item in evidence
        if item.source_kind is OeEvidenceSourceKind.DETAIL_PAGE
        and item.confidence >= OE_VERIFICATION_THRESHOLD
    }
    native_cross_values = cross_values & native_detail_values
    native_incompatible = incompatible & native_detail_values
    platform_compatible_values = {
        item.normalized_value
        for item in evidence
        if item.source_kind
        is OeEvidenceSourceKind.PLATFORM_COMPATIBLE_REFERENCE_LIST
        and item.confidence >= OE_VERIFICATION_THRESHOLD
    }
    if (
        exact == {query}
        and query in native_detail_values
        and not native_incompatible
        and incompatible <= platform_compatible_values
    ):
        # The retained Prom detail card names our exact number as its own
        # normalized part code. Other numbers in the platform's compatible
        # list are graph context, not competing candidate identities.
        return _verified_result(
            OeVerificationStatus.VERIFIED_EXACT,
            query,
            query,
            extracted,
            strengths[query],
            evidence,
            "OE_VERIFIED_DETAIL_NATIVE_EXACT",
        )
    if (
        not exact
        and len(native_cross_values) == 1
        and not native_incompatible
    ):
        # ``motors.normalizedPartCode`` is Prom's candidate-native identifier.
        # A detail card may additionally publish a long list of compatible OE
        # references in ordinary characteristics. Those references remain in
        # ``extracted_oe_norms`` for audit, but they do not make the card's own
        # verified code ambiguous once that exact one-hop cross is already
        # confirmed. This authority is deliberately unavailable to titles,
        # SKUs, MPNs, unretained detail metadata, or an unconfirmed cross.
        candidate = next(iter(native_cross_values))
        cross = cross_by_candidate[candidate]
        confidence = min(strengths[candidate], cross.confidence)
        return _verified_result(
            OeVerificationStatus.VERIFIED_CROSS,
            candidate,
            cross.canonical_identity_key,
            extracted,
            confidence,
            evidence,
            "OE_VERIFIED_DETAIL_NATIVE_CONFIRMED_CROSS",
        )
    compatible_reference_values = {
        item.normalized_value
        for item in evidence
        if item.source_kind is OeEvidenceSourceKind.COMPATIBLE_REFERENCE_LIST
        and item.confidence >= OE_VERIFICATION_THRESHOLD
    }
    nonconflicting_namespace_kinds = {
        OeEvidenceSourceKind.COMPATIBLE_REFERENCE_LIST,
        OeEvidenceSourceKind.PLATFORM_COMPATIBLE_REFERENCE_LIST,
        OeEvidenceSourceKind.CANDIDATE_PART_NUMBER,
        OeEvidenceSourceKind.MANUFACTURER_PART_NUMBER,
        OeEvidenceSourceKind.SKU,
        OeEvidenceSourceKind.DETAIL_PAGE,
    }
    hard_incompatible = {
        value
        for value in incompatible
        if any(
            item.normalized_value == value
            and item.confidence >= OE_VERIFICATION_THRESHOLD
            and item.source_kind not in nonconflicting_namespace_kinds
            for item in evidence
        )
    }
    platform_exact = exact & platform_compatible_values
    platform_cross = cross_values & platform_compatible_values
    awaiting_platform_candidates = native_detail_values & proposed_candidates
    if (
        platform_exact == {query}
        and len(awaiting_platform_candidates) == 1
        and not hard_incompatible
    ):
        candidate = next(iter(awaiting_platform_candidates))
        return OeVerification(
            status=OeVerificationStatus.UNKNOWN,
            extracted_oe_norms=extracted,
            verified_matched_oe_norm=None,
            comparison_identity_key=None,
            confidence=strengths[candidate],
            evidence_refs=tuple(
                sorted(
                    item.reference_id
                    for item in evidence
                    if item.normalized_value == candidate
                )
            ),
            reason_codes=("OE_CROSS_AWAITING_CONFIRMATION",),
        )
    if len(platform_cross) == 1 and not hard_incompatible:
        # Prom Motors exposes the candidate's supplier article separately from
        # the platform's compatible OE list. When that retained detail list
        # contains exactly one already confirmed one-hop XLS cross, the
        # supplier article is a namespace, not a contradictory OE. Neither an
        # unconfirmed search result nor an unverified detail can enter here.
        candidate = next(iter(platform_cross))
        cross = cross_by_candidate[candidate]
        return _verified_result(
            OeVerificationStatus.VERIFIED_CROSS,
            candidate,
            cross.canonical_identity_key,
            extracted,
            min(strengths[candidate], cross.confidence),
            evidence,
            "OE_VERIFIED_PLATFORM_COMPATIBILITY_BRIDGE",
        )
    if (
        platform_exact == {query}
        and cross_by_candidate
        and not hard_incompatible
    ):
        # A confirmed acquisition route may return a supplier article whose
        # platform compatibility list names the seed directly but omits the
        # route number. The exact seed is stronger than the route: retain it as
        # exact compatibility, while still requiring that the widened search
        # itself came from a confirmed one-hop edge.
        return _verified_result(
            OeVerificationStatus.VERIFIED_EXACT,
            query,
            query,
            extracted,
            min(strengths[query], max(c.confidence for c in cross_by_candidate.values())),
            evidence,
            "OE_VERIFIED_PLATFORM_EXACT_ON_CONFIRMED_ROUTE",
        )
    compatible_support = (exact | cross_values) & compatible_reference_values
    if compatible_support and not hard_incompatible:
        # A field explicitly labelled as a cross/compatible-number list is a
        # set of equivalent references, not several competing native codes.
        # Supplier MPN/SKU/native part-code values live in their own namespaces
        # and remain auditable without manufacturing an OE conflict. A
        # contradictory structured OE or ordinary OE-labelled characteristic
        # is *not* ignored and keeps the result ambiguous.
        if exact == {query}:
            return _verified_result(
                OeVerificationStatus.VERIFIED_EXACT,
                query,
                query,
                extracted,
                strengths[query],
                evidence,
                "OE_VERIFIED_COMPATIBLE_REFERENCE_EXACT",
            )
        if not exact and len(cross_values) == 1:
            candidate = next(iter(cross_values))
            cross = cross_by_candidate[candidate]
            return _verified_result(
                OeVerificationStatus.VERIFIED_CROSS,
                candidate,
                cross.canonical_identity_key,
                extracted,
                min(strengths[candidate], cross.confidence),
                evidence,
                "OE_VERIFIED_COMPATIBLE_REFERENCE_CONFIRMED_CROSS",
            )
    if incompatible and (exact or cross_values) or len(exact | cross_values) > 1:
        return _unverified_result(
            OeVerificationStatus.AMBIGUOUS,
            extracted,
            strengths,
            "OE_EVIDENCE_AMBIGUOUS",
        )
    if exact == {query} and not cross_values:
        return _verified_result(
            OeVerificationStatus.VERIFIED_EXACT,
            query,
            query,
            extracted,
            strengths[query],
            evidence,
            "OE_VERIFIED_EXACT",
        )
    if not exact and len(cross_values) == 1 and not incompatible:
        candidate = next(iter(cross_values))
        cross = cross_by_candidate[candidate]
        confidence = min(strengths[candidate], cross.confidence)
        return _verified_result(
            OeVerificationStatus.VERIFIED_CROSS,
            candidate,
            cross.canonical_identity_key,
            extracted,
            confidence,
            evidence,
            "OE_VERIFIED_CONFIRMED_CROSS",
        )
    if (
        not exact
        and not cross_values
        and incompatible
        and incompatible.issubset(proposed_candidates)
    ):
        return OeVerification(
            status=OeVerificationStatus.UNKNOWN,
            extracted_oe_norms=extracted,
            verified_matched_oe_norm=None,
            comparison_identity_key=None,
            confidence=max((strengths[value] for value in incompatible)),
            evidence_refs=tuple(
                sorted(
                    item.reference_id
                    for item in evidence
                    if item.normalized_value in incompatible
                )
            ),
            reason_codes=("OE_CROSS_AWAITING_CONFIRMATION",),
        )
    return _unverified_result(
        OeVerificationStatus.CONFLICT,
        extracted,
        strengths,
        "OE_EVIDENCE_CONFLICT",
    )


def bind_oe_verification(
    evidence: ComparisonEvidence,
    verification: OeVerification,
    *,
    seller_id: str | None,
    currency_raw: str | None,
    currency_normalized: str | None,
    required_currency: str,
    category: str | None,
) -> ComparisonEvidence:
    """Bind verified OE evidence, then recompute the comparability hard gate."""

    dimensions = dict(evidence.dimensions)
    if verification.verified:
        state = EvidenceState.MATCH
        raw_value = verification.verified_matched_oe_norm
        normalized_value = verification.verified_matched_oe_norm
    elif verification.status == OeVerificationStatus.CONFLICT:
        state = EvidenceState.CONFLICT
        raw_value = ",".join(verification.extracted_oe_norms) or None
        normalized_value = None
    else:
        state = EvidenceState.UNKNOWN
        raw_value = ",".join(verification.extracted_oe_norms) or None
        normalized_value = None
    dimensions["oe_reference"] = DimensionEvidence(
        state=state,
        raw_value=raw_value,
        normalized_value=normalized_value,
        evidence_refs=verification.evidence_refs,
        reason_code=verification.reason_codes[0] if verification.reason_codes else None,
    )
    bound = replace(evidence, dimensions=MappingProxyType(dimensions))
    decision = evaluate_comparison_evidence(
        bound,
        seller_id=seller_id,
        currency_raw=currency_raw,
        currency_normalized=currency_normalized,
        required_currency=required_currency,
        category=category,
    )
    return replace(
        bound,
        hard_gate_result=decision.hard_gate_result,
        reason_codes=decision.reason_codes,
    )


def evidence_items_to_dicts(
    evidence_items: Iterable[OeEvidenceItem],
) -> list[dict[str, Any]]:
    return [item.as_dict() for item in evidence_items]


def persisted_identity_fields_consistent(observation: Any) -> bool:
    """Validate the denormalized Q/E/V/K fields before automatic use."""

    try:
        status = OeVerificationStatus(str(observation.oe_verification_status))
    except (AttributeError, ValueError):
        return False
    query = normalize_oe(getattr(observation, "search_oe_norm", None))
    verified = normalize_oe(getattr(observation, "verified_matched_oe_norm", None))
    extracted = {
        normalized
        for raw in (getattr(observation, "extracted_oe_norms", None) or ())
        if (normalized := normalize_oe(str(raw))) is not None
    }
    # Legacy rows may predate the private-code filter and still carry a
    # materialized 776... value in Q/E/V.  They must not be revived merely
    # because their denormalized fields are internally self-consistent: the
    # value is a warehouse join key, not a public identity.
    if (
        (query and is_internal_catalog_code(query))
        or (verified and is_internal_catalog_code(verified))
        or any(is_internal_catalog_code(value) for value in extracted)
    ):
        return False
    identity_key = str(
        getattr(observation, "comparison_identity_key", None) or ""
    ).strip()
    # ``MPN:`` is an explicit supplier/manufacturer namespace.  It is useful
    # for discovery and operator review, but it is never a vehicle identity
    # eligible for calibration.  Keep this guard independent of the optional
    # snapshot so a legacy row cannot be revived by a replay path that predates
    # namespace versioning.
    if identity_key.startswith("MPN:"):
        return False
    via_cross = bool(getattr(observation, "via_cross", False))
    cross_link_id = getattr(observation, "cross_link_id", None)
    snapshot = getattr(observation, "candidate_snapshot", None)
    identity_admission = (
        snapshot.get("identity_admission")
        if isinstance(snapshot, Mapping)
        else None
    )
    # New materialized rows carry a namespace proof.  Legacy synthetic
    # adapters intentionally retain the old raw-key fallback, while any row
    # that claims to have a namespace version must satisfy it completely.
    if isinstance(identity_admission, Mapping) and (
        "namespace_version" in identity_admission
    ):
        if not identity_admission_snapshot_is_current(
            identity_admission,
            expected_identity_key=identity_key,
        ):
            return False

    if status == OeVerificationStatus.VERIFIED_EXACT:
        if isinstance(identity_admission, Mapping) and identity_admission.get(
            "namespace_version"
        ):
            try:
                verified_namespace = IdentityNamespace(
                    str(
                        identity_admission.get("verified_identity_namespace")
                        or ""
                    )
                )
            except ValueError:
                return False
            if verified_namespace is IdentityNamespace.MPN:
                expected_key = f"MPN:{verified}" if verified else ""
            elif verified_namespace is IdentityNamespace.PART_NUMBER:
                expected_key = f"PART_NUMBER:{verified}" if verified else ""
            else:
                expected_key = verified or ""
        else:
            expected_key = verified or ""
        return bool(
            query
            and verified == query
            and verified in extracted
            and identity_key == expected_key
            and not via_cross
            and cross_link_id is None
        )
    if status == OeVerificationStatus.VERIFIED_CROSS:
        return bool(
            query
            and verified
            and verified != query
            and verified in extracted
            and identity_key == canonical_cross_identity_key(query, verified)
            and via_cross
            and cross_link_id is not None
        )
    return (
        verified is None
        and not identity_key
        and not via_cross
        and cross_link_id is None
    )


def _extract_text_items(
    value: Any,
    *,
    source_kind: OeEvidenceSourceKind,
    json_path: str,
    anchored_confidence: Decimal,
    add: Any,
    source_manifest: Mapping[str, Any] | None = None,
) -> None:
    if value is None:
        return
    text = str(value).strip()
    if not text:
        return
    normalized_text = text.upper()
    anchored_spans: set[tuple[int, int]] = set()
    for match in _ANCHOR_RE.finditer(normalized_text):
        raw_candidate = _trim_anchored_candidate(match.group(1))
        start = match.start(1)
        end = start + len(raw_candidate)
        anchored_spans.add((start, end))
        add(
            raw_candidate,
            source_kind=source_kind,
            json_path=json_path,
            char_span=(start, end),
            context_label=match.group(0)[: match.start(1) - match.start()].strip(),
            method="anchored_token",
            confidence=anchored_confidence,
            correlation_source=normalized_text,
            source_manifest=source_manifest,
        )
    for match in _PART_TOKEN_RE.finditer(normalized_text):
        span = (match.start(), match.end())
        if any(start <= span[0] and span[1] <= end for start, end in anchored_spans):
            continue
        add(
            match.group(0),
            source_kind=source_kind,
            json_path=json_path,
            char_span=span,
            context_label=None,
            method="unanchored_token",
            confidence=Decimal("0.20"),
            correlation_source=normalized_text,
            source_manifest=source_manifest,
        )


def _trim_anchored_candidate(value: str) -> str:
    # An anchor may be followed by ordinary words. Keep the leading part-number
    # shape and at most six whitespace-separated alphanumeric segments.
    tokens = re.findall(r"[A-Z0-9]+", value.upper())[:6]
    selected: list[str] = []
    for token in tokens:
        if selected and token.isalpha() and len(token) > 2:
            break
        selected.append(token)
    return " ".join(selected)


def _valid_normalized_oe(
    value: str,
    *,
    allow_long_numeric: bool = False,
) -> str | None:
    normalized = normalize_oe(value)
    if normalized is None or not 4 <= len(normalized) <= 32:
        return None
    if not any(character.isdigit() for character in normalized):
        return None
    if normalized.isdigit():
        if len(normalized) >= 10 and not allow_long_numeric:
            return None
        if len(normalized) == 4 and 1900 <= int(normalized) <= 2100:
            return None
    return normalized


_MANUFACTURER_PREFIX_RE = re.compile(
    r"^(?:[A-ZА-ЯІЇЄ][A-ZА-ЯІЇЄ-]{1,20}\s+){1,3}"
    r"(?P<number>[A-Z0-9][A-Z0-9./_-]{0,31}"
    r"(?:\s+[A-Z0-9./_-]+){0,8})$",
    re.IGNORECASE,
)


def _strip_manufacturer_prefix(value: str) -> str:
    """Remove an explicit brand prefix from one structured cross-number cell.

    ``BMW 34211157046`` and ``AUTOFREN SEINSA D42387A`` contain a publisher
    label followed by the actual identifier. A grouped identifier such as
    ``A 000 090 26 51`` remains whole after an optional manufacturer prefix is
    removed; it is never collapsed to the final numeric token.
    """

    match = _MANUFACTURER_PREFIX_RE.fullmatch(value.strip())
    return match.group("number") if match is not None else value


def _split_structured_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list | tuple | set):
        return tuple(
            chunk
            for item in value
            if str(item).strip()
            for chunk in _structured_identity_chunks(str(item))
        )
    text = str(value).strip()
    if not text:
        return ()
    return _structured_identity_chunks(text)


def _structured_identity_chunks(value: str) -> tuple[str, ...]:
    """Split complete IDs without destroying formatted multi-token numbers.

    Prom characteristics use comma, semicolon, pipe, plus, newline, and often
    plain whitespace between complete OE references. Conversely, a Mercedes
    identifier such as ``A 000 090 26 51`` intentionally contains spaces. A
    whitespace chunk is split only when every digit-bearing fragment is long
    enough to be a complete identifier on its own.
    """

    result: list[str] = []
    for raw_chunk in re.split(r"[,;|+\r\n]+", value):
        chunk = raw_chunk.strip()
        if not chunk:
            continue
        fragments = chunk.split()
        digit_fragments = [
            fragment
            for fragment in fragments
            if any(character.isdigit() for character in fragment)
        ]
        if (
            len(digit_fragments) >= 2
            and all(
                len(re.sub(r"[^A-Z0-9]", "", fragment.upper())) >= 4
                for fragment in digit_fragments
            )
        ):
            result.extend(digit_fragments)
        else:
            result.append(chunk)
    return tuple(result)


def _iter_characteristics(value: Any) -> Iterable[tuple[str, Any, str]]:
    if isinstance(value, Mapping):
        for label, item in value.items():
            yield str(label), item, f"$.characteristics.{label}"
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if not isinstance(item, Mapping):
                continue
            label = item.get("name") or item.get("label")
            if label is not None:
                yield str(label), item.get("value"), f"$.characteristics[{index}].value"


def _is_oe_label(value: str) -> bool:
    return _oe_label_confidence(value) is not None


def _is_compatible_reference_label(value: str) -> bool:
    compact = re.sub(r"[^A-ZА-ЯІЇЄ]", "", value.upper())
    return compact in {
        "КРОСНОМЕРИ",
        "КРОССНОМЕРИ",
        "КРОСНОМЕРА",
        "КРОССНОМЕРА",
        "КРОСКОД",
        "КРОССКОД",
    }


def _is_candidate_part_number_label(value: str) -> bool:
    compact = re.sub(r"[^A-ZА-ЯІЇЄ]", "", value.upper())
    return compact in {
        "АРТИКУЛ",
        "КОДВИРОБНИКА",
        "КОДПРОИЗВОДИТЕЛЯ",
        "КОДЗАПЧАСТИНИ",
        "КОДЗАПЧАСТИ",
    }


def _oe_label_confidence(value: str) -> Decimal | None:
    compact = re.sub(r"[^A-ZА-ЯІЇЄ]", "", value.upper())
    if compact in {
        "OE",
        "OEM",
        "OEMNO",
        "OEНОМЕР",
        "КРОСНОМЕРИ",
        "КРОССНОМЕРИ",
        "КРОСНОМЕРА",
        "КРОССНОМЕРА",
        "КРОСКОД",
        "КРОССКОД",
    }:
        return Decimal("0.97")
    if compact in {
        "АРТИКУЛ",
        "КОДВИРОБНИКА",
        "КОДПРОИЗВОДИТЕЛЯ",
        "КОДЗАПЧАСТИНИ",
        "КОДЗАПЧАСТИ",
    }:
        # A seller article can be a private stock code.  It becomes strong only
        # when the same number is independently supported (for example by SKU,
        # title, a cross field, or an approved cross edge).
        return Decimal("0.88")
    return None


def _nested(value: Mapping[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _has_independent_support(
    oe_norm: str,
    evidence: tuple[OeEvidenceItem, ...],
) -> bool:
    relevant = [item for item in evidence if item.normalized_value == oe_norm]
    if any(item.confidence >= _STRONG_THRESHOLD for item in relevant):
        return True
    medium_groups = {
        item.correlation_group
        for item in relevant
        if item.confidence >= _MEDIUM_THRESHOLD
    }
    return len(medium_groups) >= 2


def _short_numeric_identity_requires_structured_proof(
    oe_norm: str,
    evidence: tuple[OeEvidenceItem, ...],
) -> bool:
    """Return whether a short numeric identity lacks an authoritative source.

    ``extract_oe_evidence`` intentionally preserves free-text findings so an
    operator can inspect them.  Automatic identity, however, must not be
    created from a repeated seller string.  Only the explicit structured OE
    namespace, explicit compatible-reference namespaces, or a retained detail
    page can clear this precision gate.
    """

    if not oe_norm.isdigit() or len(oe_norm) > SHORT_NUMERIC_OE_MAX_DIGITS:
        return False
    trusted_sources = {
        OeEvidenceSourceKind.STRUCTURED_OE_FIELD,
        OeEvidenceSourceKind.LABELED_CHARACTERISTIC,
        OeEvidenceSourceKind.COMPATIBLE_REFERENCE_LIST,
        OeEvidenceSourceKind.PLATFORM_COMPATIBLE_REFERENCE_LIST,
        OeEvidenceSourceKind.DETAIL_PAGE,
    }
    return not any(
        item.normalized_value == oe_norm
        and item.source_kind in trusted_sources
        and item.confidence >= OE_VERIFICATION_THRESHOLD
        for item in evidence
    )


def _short_numeric_identity_has_native_proof(
    oe_norm: str,
    evidence: tuple[OeEvidenceItem, ...],
) -> bool:
    """Return whether a short number is native to the candidate MPN namespace."""

    native_sources = {
        OeEvidenceSourceKind.MANUFACTURER_PART_NUMBER,
        OeEvidenceSourceKind.CANDIDATE_PART_NUMBER,
        OeEvidenceSourceKind.SKU,
        OeEvidenceSourceKind.DETAIL_PAGE,
    }
    return any(
        item.normalized_value == oe_norm
        and item.source_kind in native_sources
        and item.confidence >= _MEDIUM_THRESHOLD
        for item in evidence
    )


def _verified_result(
    status: OeVerificationStatus,
    verified_value: str,
    identity_key: str,
    extracted: tuple[str, ...],
    confidence: Decimal,
    evidence: tuple[OeEvidenceItem, ...],
    reason: str,
) -> OeVerification:
    refs = tuple(
        sorted(
            item.reference_id
            for item in evidence
            if item.normalized_value == verified_value
        )
    )
    return OeVerification(
        status=status,
        extracted_oe_norms=extracted,
        verified_matched_oe_norm=verified_value,
        comparison_identity_key=identity_key,
        confidence=confidence,
        evidence_refs=refs,
        reason_codes=(reason,),
    )


def _unverified_result(
    status: OeVerificationStatus,
    extracted: tuple[str, ...],
    strengths: Mapping[str, Decimal],
    reason: str,
) -> OeVerification:
    return OeVerification(
        status=status,
        extracted_oe_norms=extracted,
        verified_matched_oe_norm=None,
        comparison_identity_key=None,
        confidence=max(strengths.values(), default=Decimal("0")),
        evidence_refs=(),
        reason_codes=(reason,),
    )


def canonical_cross_identity_key(first: str, second: str) -> str:
    values = sorted((first, second))
    return f"XREF:{values[0]}|{values[1]}"


__all__ = [
    "ConfirmedCross",
    "AUTOMATIC_IDENTITY_EVIDENCE_SOURCES",
    "FREE_TEXT_IDENTITY_EVIDENCE_SOURCES",
    "IDENTITY_NAMESPACE_VERSION",
    "IdentityNamespace",
    "OE_EXTRACTOR_VERSION",
    "SHORT_NUMERIC_OE_MAX_DIGITS",
    "OE_VERIFICATION_THRESHOLD",
    "OeEvidenceItem",
    "OeEvidenceSourceKind",
    "OeVerification",
    "OeVerificationStatus",
    "PROM_MOTORS_CROSS_PROPOSAL_VERSION",
    "PromMotorsCrossProposal",
    "bind_oe_verification",
    "canonical_cross_identity_key",
    "automatic_identity_evidence_sufficient",
    "customer_identity_namespace",
    "evidence_items_to_dicts",
    "evidence_strength",
    "extract_oe_evidence",
    "extract_prom_motors_cross_proposals",
    "identity_admission_snapshot_is_current",
    "namespace_bound_verification",
    "namespace_identity_admission",
    "persisted_identity_fields_consistent",
    "verified_identity_namespace",
    "verify_offer_identity",
]
