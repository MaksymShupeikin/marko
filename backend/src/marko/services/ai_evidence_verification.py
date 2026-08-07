"""Deterministic, provider-independent verification of AI-extracted evidence.

The extractor produces *claims*.  This module decides, without ever calling a
provider and without trusting a single string the model normalized, which of
those claims are supported by retained data.

The order matters and is the whole design:

1. **Bind or refuse.**  Before any content is looked at, the result must still
   describe the rows it was produced from: capture id and ``content_sha256``,
   observation id and ``source_listing_id``, the candidate-snapshot hash, the
   rebuilt document hash, the prompt/schema versions and the model settings.  A
   missing capture, a re-scraped listing, an edited snapshot or a bumped prompt
   all fail closed -- nothing partial is salvaged from a broken binding.
2. **Prove the citation.**  Every text excerpt must be an exact substring of the
   *bounded retained* text at the cited JSON pointer, and every structured
   reference must equal the retained value exactly.  A paraphrase, a pointer that
   does not resolve, a pointer that contradicts its declared ``source_kind`` or
   offsets that do not land on the excerpt are all rejections.
3. **Recompute, never adopt.**  Canonical OE normalization comes from
   :func:`metis.pricing.normalize_oe`; the model's ``normalized_value`` is only
   ever compared against it.  An OE token is accepted only when it is *literally*
   present in the cited excerpt, so the model cannot introduce a part number the
   listing never printed.
4. **Lexicon or manual review.**  Condition, package quantity, side and
   installation position are accepted only when a deterministic lexicon/grammar
   derives the same canonical token from the cited wording.  Everything the
   lexicon cannot support is :attr:`VerificationStatus.AMBIGUOUS` -- manual
   review, never "verified".

What a verified result may then do is deliberately small
(:func:`propose_evidence_fill`): fill a comparison dimension that is currently
``UNKNOWN``, using the existing deterministic comparison
(:func:`metis.pricing.categorical_dimension`).  It cannot overwrite a
``CONFLICT`` or a ``MATCH``, it cannot touch identity (``oe_reference``) or
currency, and it never recomputes the hard gate: shadow mode observes,
eligibility does not move.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
import hashlib
import json
import re
from typing import Any
import unicodedata

from metis.pricing import (
    ComparisonEvidence,
    EvidenceState,
    normalize_oe,
)
from metis.pricing.comparability import normalized_categorical_dimension
from metis.identifiers import OEM_HOMOGLYPHS
from marko.services.ai_evidence_extraction import (
    AI_EVIDENCE_PROMPT_VERSION,
    AI_EVIDENCE_SCHEMA_VERSION,
    AI_EVIDENCE_SOURCE_LOCATOR_VERSION,
    AiEvidenceBinding,
    AiEvidenceCandidateValue,
    AiEvidenceExtractionResult,
    AiEvidenceRuntimeConfig,
    EvidenceFieldName,
    EvidenceSourceKind,
    FindingState,
    SOURCE_KIND_POINTER_ROOTS,
    TEXT_SOURCE_KINDS,
    assert_no_authority_fields,
    build_extraction_document,
    build_extraction_input,
    candidate_snapshot_sha256,
    source_offer_locator_sha256,
)
from marko.services.offer_identity import OE_EXTRACTOR_VERSION


AI_EVIDENCE_VERIFIER_VERSION = "marko-ai-evidence-verifier-v1"


class VerificationStatus(StrEnum):
    """Per-field verdict.  Only ``VERIFIED`` may ever fill a dimension."""

    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"
    NOT_FOUND = "NOT_FOUND"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReportStatus(StrEnum):
    VERIFIED = "VERIFIED"
    #: The binding broke.  No field verdict in this report is usable.
    FAILED_CLOSED = "FAILED_CLOSED"
    #: There was nothing to verify (no extraction happened).
    NO_OUTPUT = "NO_OUTPUT"


class BindingFailure(StrEnum):
    MISSING_BINDING = "MISSING_BINDING"
    MISSING_OUTPUT = "MISSING_OUTPUT"
    CAPTURE_MISSING = "CAPTURE_MISSING"
    CAPTURE_ID_MISMATCH = "CAPTURE_ID_MISMATCH"
    CAPTURE_HASH_MISMATCH = "CAPTURE_HASH_MISMATCH"
    OBSERVATION_MISSING = "OBSERVATION_MISSING"
    OBSERVATION_ID_MISMATCH = "OBSERVATION_ID_MISMATCH"
    OBSERVATION_LISTING_STALE = "OBSERVATION_LISTING_STALE"
    OBSERVATION_CAPTURE_UNBOUND = "OBSERVATION_CAPTURE_UNBOUND"
    CANDIDATE_SNAPSHOT_STALE = "CANDIDATE_SNAPSHOT_STALE"
    SOURCE_LOCATOR_MISSING = "SOURCE_LOCATOR_MISSING"
    SOURCE_LOCATOR_MISMATCH = "SOURCE_LOCATOR_MISMATCH"
    DOCUMENT_HASH_MISMATCH = "DOCUMENT_HASH_MISMATCH"
    PROMPT_VERSION_MISMATCH = "PROMPT_VERSION_MISMATCH"
    SCHEMA_VERSION_MISMATCH = "SCHEMA_VERSION_MISMATCH"
    MODEL_SETTINGS_MISMATCH = "MODEL_SETTINGS_MISMATCH"
    INPUT_HASH_MISMATCH = "INPUT_HASH_MISMATCH"
    SCHEMA_DRIFT = "SCHEMA_DRIFT"


class CitationRefusal(StrEnum):
    """Why one cited candidate was not accepted."""

    SOURCE_PATH_UNRESOLVED = "SOURCE_PATH_UNRESOLVED"
    SOURCE_KIND_PATH_MISMATCH = "SOURCE_KIND_PATH_MISMATCH"
    SOURCE_NOT_TEXT = "SOURCE_NOT_TEXT"
    EXCERPT_NOT_SUBSTRING = "EXCERPT_NOT_SUBSTRING"
    EXCERPT_OFFSETS_INVALID = "EXCERPT_OFFSETS_INVALID"
    STRUCTURED_VALUE_MISMATCH = "STRUCTURED_VALUE_MISMATCH"
    OE_NORMALIZATION_REJECTED = "OE_NORMALIZATION_REJECTED"
    OE_NOT_SUPPORTED_BY_EXCERPT = "OE_NOT_SUPPORTED_BY_EXCERPT"
    LEXICON_UNSUPPORTED = "LEXICON_UNSUPPORTED"
    LEXICON_AMBIGUOUS = "LEXICON_AMBIGUOUS"
    UNSUPPORTED_INFERENCE = "UNSUPPORTED_INFERENCE"
    #: Informational: the value was accepted, but from our normalization only.
    MODEL_NORMALIZED_VALUE_IGNORED = "MODEL_NORMALIZED_VALUE_IGNORED"


@dataclass(frozen=True, slots=True)
class VerifiedCitation:
    raw_value: str
    canonical_value: str | None
    model_normalized_value: str | None
    source_kind: EvidenceSourceKind
    source_path: str
    source_excerpt: str
    accepted: bool
    reason_codes: tuple[CitationRefusal, ...]
    normalization_method: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_value": self.raw_value,
            "canonical_value": self.canonical_value,
            "model_normalized_value": self.model_normalized_value,
            "source_kind": self.source_kind.value,
            "source_path": self.source_path,
            "source_excerpt": self.source_excerpt,
            "accepted": self.accepted,
            "reason_codes": [code.value for code in self.reason_codes],
            "normalization_method": self.normalization_method,
        }


@dataclass(frozen=True, slots=True)
class VerifiedField:
    field_name: EvidenceFieldName
    status: VerificationStatus
    canonical_values: tuple[str, ...]
    citations: tuple[VerifiedCitation, ...]
    reason_codes: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return self.status is VerificationStatus.VERIFIED

    def as_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name.value,
            "status": self.status.value,
            "canonical_values": list(self.canonical_values),
            "citations": [citation.as_dict() for citation in self.citations],
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class AiEvidenceVerificationReport:
    status: ReportStatus
    binding_failures: tuple[BindingFailure, ...] = ()
    fields: tuple[VerifiedField, ...] = ()
    binding: AiEvidenceBinding | None = None
    verifier_version: str = AI_EVIDENCE_VERIFIER_VERSION
    oe_normalization_version: str = OE_EXTRACTOR_VERSION

    @property
    def bound(self) -> bool:
        return self.status is ReportStatus.VERIFIED and not self.binding_failures

    def field_result(self, name: EvidenceFieldName) -> VerifiedField | None:
        for item in self.fields:
            if item.field_name is name:
                return item
        return None

    def verified_fields(self) -> tuple[VerifiedField, ...]:
        if not self.bound:
            return ()
        return tuple(item for item in self.fields if item.verified)

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "status": self.status.value,
            "verifier_version": self.verifier_version,
            "oe_normalization_version": self.oe_normalization_version,
            "binding_failures": [code.value for code in self.binding_failures],
            "binding": self.binding.as_dict() if self.binding is not None else None,
            "fields": [item.as_dict() for item in self.fields],
        }
        # The report is an input to persistence and to the evidence proposal;
        # it must never carry a decision-authority key by construction.
        assert_no_authority_fields(payload, where="verification report")
        return payload


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def verify_ai_evidence(
    result: AiEvidenceExtractionResult,
    *,
    capture: Any,
    observation: Any,
    config: AiEvidenceRuntimeConfig,
    retained_payload: Mapping[str, Any] | None = None,
) -> AiEvidenceVerificationReport:
    """Bind a result to retained rows, then verify every citation it makes."""

    if result.output is None or result.binding is None:
        failure = (
            BindingFailure.MISSING_BINDING
            if result.binding is None
            else BindingFailure.MISSING_OUTPUT
        )
        # A result that never produced output is not a *failure* to verify; a
        # result that produced output without a binding is.
        status = (
            ReportStatus.NO_OUTPUT
            if result.output is None and result.binding is None
            else ReportStatus.FAILED_CLOSED
        )
        return AiEvidenceVerificationReport(
            status=status,
            binding_failures=(failure,),
            binding=result.binding,
        )

    binding = result.binding
    failures = _binding_failures(
        binding,
        capture=capture,
        observation=observation,
        retained_payload=retained_payload,
    )
    if failures:
        return AiEvidenceVerificationReport(
            status=ReportStatus.FAILED_CLOSED,
            binding_failures=tuple(failures),
            binding=binding,
        )
    expected = build_extraction_input(
        capture=capture,
        observation=observation,
        config=config,
        target_fields=result.target_fields,
    ).binding
    settings_match = (
        binding.model == expected.model
        and binding.reasoning_effort == expected.reasoning_effort
        and binding.max_output_tokens == expected.max_output_tokens
        and binding.max_input_chars == expected.max_input_chars
        and binding.model_settings_sha256 == expected.model_settings_sha256
    )
    if not settings_match:
        return AiEvidenceVerificationReport(
            status=ReportStatus.FAILED_CLOSED,
            binding_failures=(BindingFailure.MODEL_SETTINGS_MISMATCH,),
            binding=binding,
        )
    if binding.input_sha256 != expected.input_sha256:
        return AiEvidenceVerificationReport(
            status=ReportStatus.FAILED_CLOSED,
            binding_failures=(BindingFailure.INPUT_HASH_MISMATCH,),
            binding=binding,
        )
    if binding.source_offer_locator_sha256 != expected.source_offer_locator_sha256:
        return AiEvidenceVerificationReport(
            status=ReportStatus.FAILED_CLOSED,
            binding_failures=(BindingFailure.SOURCE_LOCATOR_MISMATCH,),
            binding=binding,
        )
    returned_fields = tuple(item.field_name for item in result.output.findings)
    if len(returned_fields) != len(result.target_fields) or set(returned_fields) != set(
        result.target_fields
    ):
        return AiEvidenceVerificationReport(
            status=ReportStatus.FAILED_CLOSED,
            binding_failures=(BindingFailure.SCHEMA_DRIFT,),
            binding=binding,
        )

    document = build_extraction_document(
        capture=capture,
        observation=observation,
        # Rebuild with the bound bound, not today's: the excerpt has to be
        # checked against the text that was actually shown.  A *changed* bound
        # is caught one step above as a model-settings mismatch.
        max_input_chars=binding.max_input_chars,
    ).payload

    fields = tuple(
        _verify_finding(finding, document=document)
        for finding in result.output.findings
    )
    return AiEvidenceVerificationReport(
        status=ReportStatus.VERIFIED,
        fields=fields,
        binding=binding,
    )


def _binding_failures(
    binding: AiEvidenceBinding,
    *,
    capture: Any,
    observation: Any,
    retained_payload: Mapping[str, Any] | None = None,
) -> list[BindingFailure]:
    failures: list[BindingFailure] = []
    if binding.prompt_version != AI_EVIDENCE_PROMPT_VERSION:
        failures.append(BindingFailure.PROMPT_VERSION_MISMATCH)
    if binding.schema_version != AI_EVIDENCE_SCHEMA_VERSION:
        failures.append(BindingFailure.SCHEMA_VERSION_MISMATCH)

    if capture is None:
        failures.append(BindingFailure.CAPTURE_MISSING)
    else:
        if str(getattr(capture, "id", "") or "") != binding.raw_capture_id:
            failures.append(BindingFailure.CAPTURE_ID_MISMATCH)
        if (
            str(getattr(capture, "content_sha256", "") or "")
            != binding.capture_content_sha256
        ):
            failures.append(BindingFailure.CAPTURE_HASH_MISMATCH)

    if observation is None:
        failures.append(BindingFailure.OBSERVATION_MISSING)
    else:
        if str(getattr(observation, "id", "") or "") != binding.market_observation_id:
            failures.append(BindingFailure.OBSERVATION_ID_MISMATCH)
        if (
            str(getattr(observation, "source_listing_id", "") or "")
            != binding.source_listing_id
        ):
            failures.append(BindingFailure.OBSERVATION_LISTING_STALE)
        raw_capture_id = getattr(observation, "raw_capture_id", None)
        if raw_capture_id is not None and str(raw_capture_id) != binding.raw_capture_id:
            # The observation has been re-bound to a different capture since the
            # extraction; the excerpt may still match, but the provenance chain
            # the verdict claims no longer exists.
            failures.append(BindingFailure.OBSERVATION_CAPTURE_UNBOUND)
        if candidate_snapshot_sha256(observation) != binding.candidate_snapshot_sha256:
            failures.append(BindingFailure.CANDIDATE_SNAPSHOT_STALE)
        locator = _source_locator(observation)
        if not locator:
            failures.append(BindingFailure.SOURCE_LOCATOR_MISSING)
        elif not _source_locator_matches(
            locator,
            capture=capture,
            observation=observation,
            retained_payload=retained_payload,
        ):
            failures.append(BindingFailure.SOURCE_LOCATOR_MISMATCH)
        elif (
            source_offer_locator_sha256(observation)
            != binding.source_offer_locator_sha256
        ):
            failures.append(BindingFailure.SOURCE_LOCATOR_MISMATCH)

    if capture is not None and observation is not None and not failures:
        rebuilt = build_extraction_document(
            capture=capture,
            observation=observation,
            max_input_chars=binding.max_input_chars,
        )
        if rebuilt.sha256 != binding.document_sha256:
            failures.append(BindingFailure.DOCUMENT_HASH_MISMATCH)
    return failures


def _source_locator(observation: Any) -> Mapping[str, Any]:
    snapshot = getattr(observation, "candidate_snapshot", None)
    locator = snapshot.get("source_locator") if isinstance(snapshot, Mapping) else None
    return locator if isinstance(locator, Mapping) else {}


def _source_locator_matches(
    locator: Mapping[str, Any],
    *,
    capture: Any,
    observation: Any,
    retained_payload: Mapping[str, Any] | None = None,
) -> bool:
    if capture is None:
        return False
    index = locator.get("raw_offer_index")
    offer_sha = str(locator.get("raw_offer_sha256") or "")
    shape_matches = bool(
        locator.get("locator_version") == AI_EVIDENCE_SOURCE_LOCATOR_VERSION
        and str(locator.get("raw_capture_id") or "")
        == str(getattr(capture, "id", "") or "")
        and str(locator.get("capture_content_sha256") or "")
        == str(getattr(capture, "content_sha256", "") or "")
        and isinstance(index, int)
        and not isinstance(index, bool)
        and index >= 0
        and re.fullmatch(r"[0-9a-f]{64}", offer_sha) is not None
        and str(locator.get("source_listing_id") or "")
        == str(getattr(observation, "source_listing_id", "") or "")
        and locator.get("source_pointer") == f"/candidate_records/{index}"
    )
    if not shape_matches:
        return False

    # A locator is not evidence for itself.  In production every capture has a
    # retained payload; parser-output references pass the corresponding
    # ScrapeTarget payload explicitly.  Test doubles that genuinely have no
    # payload attribute retain the old shape-only seam, while a present but
    # malformed/empty payload always fails closed.
    payload: Any = retained_payload
    if payload is None:
        if not hasattr(capture, "payload"):
            return True
        payload = getattr(capture, "payload", None)
    records = _retained_candidate_records(payload)
    if records is None or index >= len(records):
        return False
    raw_offer = records[index]
    if isinstance(raw_offer, Mapping):
        declared_index = raw_offer.get("raw_offer_index", index)
        if (
            not isinstance(declared_index, int)
            or isinstance(declared_index, bool)
            or declared_index != index
        ):
            return False
    recomputed_sha = _raw_offer_sha256(raw_offer)
    recomputed_listing_id = _raw_offer_listing_id(raw_offer)
    return bool(
        recomputed_sha is not None
        and recomputed_sha == offer_sha
        and recomputed_listing_id is not None
        and recomputed_listing_id == str(locator.get("source_listing_id") or "")
        and recomputed_listing_id
        == str(getattr(observation, "source_listing_id", "") or "")
    )


def _retained_candidate_records(payload: Any) -> list[Any] | None:
    """Resolve the exact batch representation used during materialization."""

    if not isinstance(payload, Mapping):
        return None
    direct = payload.get("candidate_records")
    if isinstance(direct, list):
        return list(direct)
    output = payload.get("output")
    if not isinstance(output, Mapping):
        return None
    records = output.get("records")
    if isinstance(records, list):
        return list(records)
    offers = output.get("offers")
    if not isinstance(offers, list):
        return None
    adapted: list[Any] = []
    for index, offer in enumerate(offers):
        if not isinstance(offer, Mapping):
            adapted.append(offer)
            continue
        adapted.append(
            {
                "raw_offer_index": index,
                "retrieval_kind": "legacy_product_seed_comparison",
                "retrieval_score": offer.get("match_score"),
                "product": {
                    key: value
                    for key, value in offer.items()
                    if key
                    not in {
                        "automatic_eligible",
                        "comparison_evidence",
                        "match_kind",
                        "match_score",
                    }
                },
                "upstream_comparison_evidence": offer.get("comparison_evidence"),
                "legacy_unverified": True,
            }
        )
    return adapted


def _raw_offer_sha256(raw_offer: Any) -> str | None:
    try:
        canonical = json.dumps(
            raw_offer,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical).hexdigest()


def _raw_offer_listing_id(raw_offer: Any) -> str | None:
    if not isinstance(raw_offer, Mapping):
        return None
    is_envelope = "product" in raw_offer or "raw_offer_index" in raw_offer
    product = raw_offer.get("product") if is_envelope else raw_offer
    if not isinstance(product, Mapping):
        return None
    product_id = product.get("product_id", product.get("id"))
    if product_id is not None and str(product_id).strip():
        return str(product_id).strip()[:255]
    url = str(product.get("url") or "").strip()
    scheme, separator, remainder = url.partition("://")
    authority = re.split(r"[/\\?#]", remainder, maxsplit=1)[0]
    if (
        separator != "://"
        or scheme.casefold() not in {"http", "https"}
        or not authority
    ):
        return None
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _verify_finding(finding: Any, *, document: Mapping[str, Any]) -> VerifiedField:
    name = finding.field_name
    state = finding.state
    if state is FindingState.NOT_FOUND:
        return VerifiedField(name, VerificationStatus.NOT_FOUND, (), (), ())
    if state is FindingState.NOT_APPLICABLE:
        return VerifiedField(name, VerificationStatus.NOT_APPLICABLE, (), (), ())

    citations = tuple(
        _verify_citation(candidate, field_name=name, document=document)
        for candidate in finding.candidates
    )
    accepted = tuple(item for item in citations if item.accepted)
    reason_codes = tuple(
        dict.fromkeys(
            code.value for citation in citations for code in citation.reason_codes
        )
    )

    if state is FindingState.CONFLICT:
        # Both sides are preserved exactly as cited.  A conflict is a fact about
        # the listing, not a problem to resolve by picking the confident one.
        return VerifiedField(
            name,
            VerificationStatus.CONFLICT,
            tuple(
                dict.fromkeys(
                    item.canonical_value for item in accepted if item.canonical_value
                )
            ),
            citations,
            reason_codes,
        )
    if state is FindingState.AMBIGUOUS:
        return VerifiedField(
            name, VerificationStatus.AMBIGUOUS, (), citations, reason_codes
        )

    # FOUND.
    if not accepted or len(accepted) != len(citations):
        status = (
            VerificationStatus.AMBIGUOUS
            if _only_soft_refusals(citations)
            else VerificationStatus.REJECTED
        )
        return VerifiedField(name, status, (), citations, reason_codes)

    canonical = tuple(
        dict.fromkeys(item.canonical_value for item in accepted if item.canonical_value)
    )
    if not canonical:
        return VerifiedField(
            name, VerificationStatus.REJECTED, (), citations, reason_codes
        )
    if name not in _MULTI_VALUE_FIELDS and len(canonical) > 1:
        # Citations that each verify but disagree are a conflict discovered by
        # us, not a verified value.
        return VerifiedField(
            name, VerificationStatus.CONFLICT, canonical, citations, reason_codes
        )
    return VerifiedField(
        name, VerificationStatus.VERIFIED, canonical, citations, reason_codes
    )


_MULTI_VALUE_FIELDS = frozenset({EvidenceFieldName.OE_NUMBERS})

#: Refusals that mean "we cannot support this", not "this is fabricated".  Only
#: these downgrade a FOUND finding to manual review instead of a rejection.
_SOFT_REFUSALS = frozenset(
    {
        CitationRefusal.LEXICON_UNSUPPORTED,
        CitationRefusal.LEXICON_AMBIGUOUS,
        CitationRefusal.UNSUPPORTED_INFERENCE,
        CitationRefusal.MODEL_NORMALIZED_VALUE_IGNORED,
    }
)


def _only_soft_refusals(citations: Sequence[VerifiedCitation]) -> bool:
    codes = {code for citation in citations for code in citation.reason_codes}
    return bool(codes) and codes <= _SOFT_REFUSALS


def _verify_citation(
    candidate: AiEvidenceCandidateValue,
    *,
    field_name: EvidenceFieldName,
    document: Mapping[str, Any],
) -> VerifiedCitation:
    refusals: list[CitationRefusal] = []

    root = SOURCE_KIND_POINTER_ROOTS.get(candidate.source_kind)
    if root is None:
        return _refused(candidate, [CitationRefusal.SOURCE_KIND_PATH_MISMATCH])
    if not (
        candidate.source_path == root or candidate.source_path.startswith(root + "/")
    ):
        return _refused(candidate, [CitationRefusal.SOURCE_KIND_PATH_MISMATCH])

    resolved, found = _resolve_pointer(document, candidate.source_path)
    if not found:
        return _refused(candidate, [CitationRefusal.SOURCE_PATH_UNRESOLVED])

    if candidate.source_kind in TEXT_SOURCE_KINDS:
        if not isinstance(resolved, str):
            return _refused(candidate, [CitationRefusal.SOURCE_NOT_TEXT])
        source_text = resolved
        if candidate.source_excerpt not in source_text:
            return _refused(candidate, [CitationRefusal.EXCERPT_NOT_SUBSTRING])
        start = candidate.source_excerpt_start
        end = candidate.source_excerpt_end
        if start is not None and end is not None:
            if (
                end > len(source_text)
                or source_text[start:end] != candidate.source_excerpt
            ):
                return _refused(candidate, [CitationRefusal.EXCERPT_OFFSETS_INVALID])
    else:
        if _structured_text(resolved) != candidate.source_excerpt:
            return _refused(candidate, [CitationRefusal.STRUCTURED_VALUE_MISMATCH])

    canonical, value_refusals = _canonical_value(
        field_name=field_name,
        raw_value=candidate.raw_value,
        excerpt=candidate.source_excerpt,
    )
    refusals.extend(value_refusals)
    if canonical is None:
        return _refused(candidate, refusals or [CitationRefusal.UNSUPPORTED_INFERENCE])

    method = _NORMALIZATION_METHOD[field_name]
    if candidate.normalized_value is not None and _compare_key(
        candidate.normalized_value
    ) != _compare_key(canonical):
        # Accepted anyway: the model's normalization simply carries no weight.
        # Recorded so a disagreeing model is visible instead of silent.
        refusals.append(CitationRefusal.MODEL_NORMALIZED_VALUE_IGNORED)

    return VerifiedCitation(
        raw_value=candidate.raw_value,
        canonical_value=canonical,
        model_normalized_value=candidate.normalized_value,
        source_kind=candidate.source_kind,
        source_path=candidate.source_path,
        source_excerpt=candidate.source_excerpt,
        accepted=True,
        reason_codes=tuple(dict.fromkeys(refusals)),
        normalization_method=method,
    )


def _refused(
    candidate: AiEvidenceCandidateValue, refusals: Iterable[CitationRefusal]
) -> VerifiedCitation:
    return VerifiedCitation(
        raw_value=candidate.raw_value,
        canonical_value=None,
        model_normalized_value=candidate.normalized_value,
        source_kind=candidate.source_kind,
        source_path=candidate.source_path,
        source_excerpt=candidate.source_excerpt,
        accepted=False,
        reason_codes=tuple(dict.fromkeys(refusals)),
        normalization_method=_NORMALIZATION_METHOD.get(EvidenceFieldName.BRAND, "none"),
    )


# ---------------------------------------------------------------------------
# Canonicalization: our code, never the model's string
# ---------------------------------------------------------------------------

_NORMALIZATION_METHOD: Mapping[EvidenceFieldName, str] = {
    EvidenceFieldName.OE_NUMBERS: f"metis.pricing.normalize_oe/{OE_EXTRACTOR_VERSION}",
    EvidenceFieldName.CONDITION: "lexicon/condition-v1",
    EvidenceFieldName.SIDE: "lexicon/side-v1",
    EvidenceFieldName.INSTALLATION_POSITION: "lexicon/position-v1",
    EvidenceFieldName.PACKAGE_QUANTITY: "grammar/package-quantity-v1",
    EvidenceFieldName.UNIT_BASIS: "lexicon/unit-basis-v1",
    EvidenceFieldName.BRAND: "casefold/literal-support-v1",
    EvidenceFieldName.PART_TYPE: "casefold/literal-support-v1",
    EvidenceFieldName.VEHICLE_MAKE: "casefold/literal-support-v1",
    EvidenceFieldName.VEHICLE_MODEL: "casefold/literal-support-v1",
    EvidenceFieldName.VEHICLE_GENERATION: "casefold/literal-support-v1",
    EvidenceFieldName.ENGINE: "casefold/literal-support-v1",
    EvidenceFieldName.BODY_VARIANT: "casefold/literal-support-v1",
    EvidenceFieldName.FITMENT: "casefold/literal-support-v1",
    EvidenceFieldName.YEAR_FROM: "grammar/year-v1",
    EvidenceFieldName.YEAR_TO: "grammar/year-v1",
}


def _canonical_value(
    *,
    field_name: EvidenceFieldName,
    raw_value: str,
    excerpt: str,
) -> tuple[str | None, list[CitationRefusal]]:
    if field_name is EvidenceFieldName.OE_NUMBERS:
        return _canonical_oe(raw_value=raw_value, excerpt=excerpt)
    if field_name in _LEXICON_FIELDS:
        return _canonical_lexicon(field_name, raw_value=raw_value, excerpt=excerpt)
    if field_name is EvidenceFieldName.PACKAGE_QUANTITY:
        return _canonical_quantity(raw_value=raw_value, excerpt=excerpt)
    if field_name in {EvidenceFieldName.YEAR_FROM, EvidenceFieldName.YEAR_TO}:
        return _canonical_year(raw_value=raw_value, excerpt=excerpt)
    return _canonical_literal(raw_value=raw_value, excerpt=excerpt)


def _canonical_oe(
    *, raw_value: str, excerpt: str
) -> tuple[str | None, list[CitationRefusal]]:
    """Our normalization of the *raw* value, and only if the excerpt prints it.

    ``normalized_value`` from the model is never an input here.  ``normalize_oe``
    strips separators, so ``1K0 615 301`` and ``1K0-615-301`` both canonicalize
    to ``1K0615301`` -- and that token has to appear, contiguously, in the
    separator-stripped excerpt.  A model that answers with a part number the
    listing never printed fails this even when its excerpt is genuine.
    """

    canonical = normalize_oe(raw_value)
    if canonical is None:
        return None, [CitationRefusal.OE_NORMALIZATION_REJECTED]
    # Equality with one complete token is load-bearing.  A substring check
    # would accept ``061`` from ``1K0615301`` and turn a fragment into an OE
    # claim.  Separators used by catalogues are allowed *inside* the token, but
    # alphanumeric boundaries on both sides are mandatory.
    separator = r"[\s._/\\-]*"
    token_pattern = separator.join(re.escape(char) for char in canonical)
    # NFKC closes full-width-letter/digit evasions, while folding the same
    # Cyrillic homoglyph vocabulary used by the canonical OE normalizer closes
    # mixed-script evasions.  The look-arounds intentionally use Unicode word
    # characters (minus underscore): ``061`` is not a complete identifier in
    # ``061А``, ``061１``, ``061K`` or ``061Α`` even when the adjacent
    # character is not ASCII.
    normalized_excerpt = (
        unicodedata.normalize("NFKC", excerpt)
        .upper()
        .translate(str.maketrans(dict(OEM_HOMOGLYPHS)))
    )
    if (
        re.search(
            rf"(?<![^\W_]){token_pattern}(?![^\W_])",
            normalized_excerpt,
        )
        is None
    ):
        return None, [CitationRefusal.OE_NOT_SUPPORTED_BY_EXCERPT]
    return canonical, []


def _canonical_literal(
    *, raw_value: str, excerpt: str
) -> tuple[str | None, list[CitationRefusal]]:
    """Free-text fields: the value must be printed, not concluded."""

    value = raw_value.strip()
    if not value:
        return None, [CitationRefusal.UNSUPPORTED_INFERENCE]
    if _compare_key(value) not in _compare_key(excerpt):
        return None, [CitationRefusal.UNSUPPORTED_INFERENCE]
    return _fold(value), []


_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


def _canonical_year(
    *, raw_value: str, excerpt: str
) -> tuple[str | None, list[CitationRefusal]]:
    match = _YEAR_RE.search(raw_value)
    if match is None:
        return None, [CitationRefusal.UNSUPPORTED_INFERENCE]
    year = match.group(1)
    if year not in {found.group(1) for found in _YEAR_RE.finditer(excerpt)}:
        return None, [CitationRefusal.UNSUPPORTED_INFERENCE]
    return year, []


_QUANTITY_UNIT_WORDS = (
    "шт",
    "штук",
    "штуки",
    "штука",
    "pcs",
    "pc",
    "piece",
    "pieces",
    "units",
    "unit",
    "ед",
    "комплект",
    "компл",
    "к-т",
    "set",
    "sets",
    "kit",
    "набор",
    "набір",
)
_QUANTITY_RE = re.compile(
    r"(?<![\d.,])(\d{1,3})\s*(?:x\s*)?(?:"
    + "|".join(re.escape(word) for word in _QUANTITY_UNIT_WORDS)
    + r")\b",
    re.IGNORECASE,
)


def _canonical_quantity(
    *, raw_value: str, excerpt: str
) -> tuple[str | None, list[CitationRefusal]]:
    """A quantity is a number *next to a unit word*, not a number in the text.

    ``2`` inside ``BMW E36 2.0`` is not a package quantity, and a model that
    concludes "brake pads come in fours" without the listing saying so gets
    :attr:`CitationRefusal.LEXICON_UNSUPPORTED` -- manual review, not a verified
    package size.
    """

    digits = re.sub(r"\D", "", raw_value)
    if not digits:
        return None, [CitationRefusal.LEXICON_UNSUPPORTED]
    claimed = str(int(digits))
    found = {
        str(int(match.group(1))) for match in _QUANTITY_RE.finditer(_fold(excerpt))
    }
    if not found:
        return None, [CitationRefusal.LEXICON_UNSUPPORTED]
    if claimed not in found:
        return None, [CitationRefusal.LEXICON_UNSUPPORTED]
    if len(found) > 1:
        return None, [CitationRefusal.LEXICON_AMBIGUOUS]
    return claimed, []


#: Deterministic wording -> canonical token.  Every pattern is matched against
#: the NFKC-casefolded excerpt.  Two different canonical tokens in one excerpt is
#: an ambiguity we refuse, not a tie we break.
_CONDITION_LEXICON: Mapping[str, tuple[str, ...]] = {
    "USED_OR_REFURBISHED": (
        r"\bб\s*[/\\.]?\s*у\b",
        r"\bбу\b",
        r"\bused\b",
        r"\bsecond\s*hand\b",
        r"вживан",
        r"бывш\w*\s+в\s+(?:употреблении|использовании)",
        r"відновлен",
        r"восстановлен",
        r"refurbish",
        r"\bпідбитий\b",
    ),
    "NEW": (
        r"\bнов(?:ый|ая|ое|ые|ый!|ий|а|е|і|ого|ой|ої)\b",
        r"\bновый\b",
        r"\bновий\b",
        r"\bnew\b",
        r"\bbrand\s*new\b",
    ),
}
_SIDE_LEXICON: Mapping[str, tuple[str, ...]] = {
    "LEFT": (
        r"\bлев(?:ый|ая|ое|ые|ого|ой)\b",
        r"\bлів(?:ий|а|е|і|ого|ої)\b",
        r"\bleft\b",
        r"\bl\.?h\.?\b",
    ),
    "RIGHT": (
        r"\bправ(?:ый|ая|ое|ые|ого|ой)\b",
        r"\bправ(?:ий|а|е|і|ого|ої)\b",
        r"\bright\b",
        r"\br\.?h\.?\b",
    ),
}
_POSITION_LEXICON: Mapping[str, tuple[str, ...]] = {
    "FRONT": (
        r"\bперед(?:ний|няя|нее|ние|него|ней)\b",
        r"\bперед(?:ній|ня|нє|ні|нього|ньої)\b",
        r"\bfront\b",
        r"\bпередн\b",
    ),
    "REAR": (
        r"\bзад(?:ний|няя|нее|ние|него|ней)\b",
        r"\bзад(?:ній|ня|нє|ні|нього|ньої)\b",
        r"\brear\b",
        r"\bback\s+axle\b",
    ),
}
#: Unit basis is a precedence, not an ambiguity: "комплект на ось" is an axle
#: set, so the more specific basis wins deterministically.
_UNIT_BASIS_LEXICON: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "PER_AXLE",
        (r"на\s+ось", r"на\s+вісь", r"\bper\s+axle\b", r"\baxle\s+set\b", r"\bось\b"),
    ),
    (
        "PER_SET",
        (
            r"комплект",
            r"\bкомпл\b",
            r"\bк-т\b",
            r"\bset\b",
            r"\bkit\b",
            r"набор",
            r"набір",
        ),
    ),
    (
        "PER_PIECE",
        (
            r"\bшт\b",
            r"штук",
            r"\bpcs?\b",
            r"\bpiece\b",
            r"поштучно",
            r"за\s+штуку",
            r"\beach\b",
        ),
    ),
)

_LEXICON_FIELDS = frozenset(
    {
        EvidenceFieldName.CONDITION,
        EvidenceFieldName.SIDE,
        EvidenceFieldName.INSTALLATION_POSITION,
        EvidenceFieldName.UNIT_BASIS,
    }
)


def _canonical_lexicon(
    field_name: EvidenceFieldName,
    *,
    raw_value: str,
    excerpt: str,
) -> tuple[str | None, list[CitationRefusal]]:
    folded_excerpt = _fold(excerpt)
    folded_raw = _fold(raw_value)

    if field_name is EvidenceFieldName.UNIT_BASIS:
        from_excerpt = _first_lexicon_hit(_UNIT_BASIS_LEXICON, folded_excerpt)
        from_raw = _first_lexicon_hit(_UNIT_BASIS_LEXICON, folded_raw)
        if from_excerpt is None:
            return None, [CitationRefusal.LEXICON_UNSUPPORTED]
        if from_raw is not None and from_raw != from_excerpt:
            return None, [CitationRefusal.LEXICON_UNSUPPORTED]
        return from_excerpt, []

    lexicon = {
        EvidenceFieldName.CONDITION: _CONDITION_LEXICON,
        EvidenceFieldName.SIDE: _SIDE_LEXICON,
        EvidenceFieldName.INSTALLATION_POSITION: _POSITION_LEXICON,
    }[field_name]
    hits = _lexicon_hits(lexicon, folded_excerpt)
    if not hits:
        return None, [CitationRefusal.LEXICON_UNSUPPORTED]
    if len(hits) > 1:
        return None, [CitationRefusal.LEXICON_AMBIGUOUS]
    canonical = hits.pop()
    raw_hits = _lexicon_hits(lexicon, folded_raw)
    if raw_hits and raw_hits != {canonical}:
        # The cited wording says one thing and the reported value another.
        return None, [CitationRefusal.LEXICON_UNSUPPORTED]
    return canonical, []


def _lexicon_hits(lexicon: Mapping[str, tuple[str, ...]], text: str) -> set[str]:
    return {
        token
        for token, patterns in lexicon.items()
        if any(re.search(pattern, text) for pattern in patterns)
    }


def _first_lexicon_hit(
    lexicon: tuple[tuple[str, tuple[str, ...]], ...], text: str
) -> str | None:
    for token, patterns in lexicon:
        if any(re.search(pattern, text) for pattern in patterns):
            return token
    return None


# ---------------------------------------------------------------------------
# Applying a verified result (shadow, bounded, never authoritative)
# ---------------------------------------------------------------------------

#: AI-verified facts may fill only these comparison dimensions.  ``oe_reference``
#: is an identity dimension and ``currency_presence`` is commerce; both are
#: excluded outright so no model output can ever reach the automatic-eligibility
#: predicate through a side door.
AI_FILLABLE_DIMENSIONS: Mapping[EvidenceFieldName, str] = {
    EvidenceFieldName.PART_TYPE: "part_type",
    EvidenceFieldName.BRAND: "brand_manufacturer",
    EvidenceFieldName.CONDITION: "condition",
    EvidenceFieldName.PACKAGE_QUANTITY: "package_quantity",
    EvidenceFieldName.SIDE: "side",
    EvidenceFieldName.INSTALLATION_POSITION: "position",
    EvidenceFieldName.VEHICLE_GENERATION: "vehicle_generation",
    EvidenceFieldName.ENGINE: "engine",
    EvidenceFieldName.BODY_VARIANT: "body_variant",
    EvidenceFieldName.FITMENT: "fitment",
}

AI_EVIDENCE_FILL_REASON_CODE = "AI_EVIDENCE_SHADOW_FILL"


class FillRefusal(StrEnum):
    NOT_BOUND = "NOT_BOUND"
    NOT_VERIFIED = "NOT_VERIFIED"
    NOT_FILLABLE_DIMENSION = "NOT_FILLABLE_DIMENSION"
    DETERMINISTIC_CONFLICT = "DETERMINISTIC_CONFLICT"
    ALREADY_DETERMINED = "ALREADY_DETERMINED"


@dataclass(frozen=True, slots=True)
class EvidenceFillProposal:
    evidence: ComparisonEvidence | None
    filled_dimensions: tuple[str, ...] = ()
    refusals: tuple[tuple[str, FillRefusal], ...] = ()
    #: Always empty.  Present so callers can assert the invariant cheaply.
    authority_changes: Mapping[str, Any] = field(default_factory=dict)


def propose_evidence_fill(
    evidence: ComparisonEvidence | None,
    report: AiEvidenceVerificationReport,
    *,
    our_values: Mapping[str, str | None] | None = None,
) -> EvidenceFillProposal:
    """Fill only UNKNOWN dimensions from verified findings, in shadow.

    Three invariants, each enforced here rather than trusted upstream:

    * A dimension that is already ``CONFLICT`` or ``MATCH`` is untouched.  A
      deterministic contradiction outranks any model output, however confident.
    * The comparison itself is computed by
      :func:`metis.pricing.comparability.categorical_dimension` from *our* value
      and the *verifier's* canonical value.  The AI supplies a candidate-side
      fact; it never supplies a verdict.
    * ``hard_gate_result``, provenance and seller identity are copied through
      unchanged.  Shadow mode may not move eligibility, so the gate is not
      re-evaluated here at all.
    """

    if evidence is None:
        return EvidenceFillProposal(evidence=None)
    if not report.bound:
        return EvidenceFillProposal(
            evidence=evidence,
            refusals=(("*", FillRefusal.NOT_BOUND),),
        )

    lookup = {key: value for key, value in (our_values or {}).items()}
    dimensions = dict(evidence.dimensions)
    filled: list[str] = []
    refusals: list[tuple[str, FillRefusal]] = []

    for item in report.fields:
        dimension = AI_FILLABLE_DIMENSIONS.get(item.field_name)
        if dimension is None:
            if item.status is VerificationStatus.VERIFIED:
                refusals.append(
                    (item.field_name.value, FillRefusal.NOT_FILLABLE_DIMENSION)
                )
            continue
        if item.status is not VerificationStatus.VERIFIED or not item.canonical_values:
            refusals.append((dimension, FillRefusal.NOT_VERIFIED))
            continue
        current = dimensions.get(dimension)
        if current is not None and current.state is EvidenceState.CONFLICT:
            refusals.append((dimension, FillRefusal.DETERMINISTIC_CONFLICT))
            continue
        if current is not None and current.state is not EvidenceState.UNKNOWN:
            refusals.append((dimension, FillRefusal.ALREADY_DETERMINED))
            continue
        candidate_value = item.canonical_values[0]
        computed = normalized_categorical_dimension(
            dimension,
            lookup.get(dimension),
            candidate_value,
            evidence_refs=_evidence_refs(report, item),
        )
        dimensions[dimension] = replace(
            computed, reason_code=AI_EVIDENCE_FILL_REASON_CODE
        )
        filled.append(dimension)

    filled_evidence = replace(
        evidence,
        dimensions=dimensions,
        # Untouched on purpose: shadow mode observes, it does not decide.
        hard_gate_result=evidence.hard_gate_result,
        reason_codes=evidence.reason_codes,
        provenance=evidence.provenance,
        seller_identity=evidence.seller_identity,
    )
    return EvidenceFillProposal(
        evidence=filled_evidence,
        filled_dimensions=tuple(filled),
        refusals=tuple(refusals),
    )


def _evidence_refs(
    report: AiEvidenceVerificationReport, item: VerifiedField
) -> tuple[str, ...]:
    binding = report.binding
    prefix = (
        f"ai_evidence:{binding.input_sha256[:16]}"
        if binding is not None
        else "ai_evidence"
    )
    refs = [f"{prefix}:{item.field_name.value}"]
    refs.extend(
        f"{prefix}:{item.field_name.value}:{citation.source_path}"
        for citation in item.citations
        if citation.accepted
    )
    return tuple(dict.fromkeys(refs))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _resolve_pointer(document: Any, pointer: str) -> tuple[Any, bool]:
    """RFC 6901 resolution.  A pointer that does not resolve is a refusal."""

    if pointer == "":
        return document, True
    if not pointer.startswith("/"):
        return None, False
    current = document
    for token in pointer.split("/")[1:]:
        key = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if key not in current:
                return None, False
            current = current[key]
            continue
        if isinstance(current, Sequence) and not isinstance(
            current, str | bytes | bytearray
        ):
            if not key.isdigit():
                return None, False
            index = int(key)
            if index >= len(current):
                return None, False
            current = current[index]
            continue
        return None, False
    return current, True


def _structured_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _fold(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _compare_key(value: str) -> str:
    """Whitespace-insensitive, case-insensitive comparison key."""

    return re.sub(r"\s+", " ", _fold(value)).strip()


def _alnum_upper(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).upper()
    return "".join(character for character in normalized if character.isalnum())


__all__ = [
    "AI_EVIDENCE_FILL_REASON_CODE",
    "AI_EVIDENCE_VERIFIER_VERSION",
    "AI_FILLABLE_DIMENSIONS",
    "AiEvidenceVerificationReport",
    "BindingFailure",
    "CitationRefusal",
    "EvidenceFillProposal",
    "FillRefusal",
    "ReportStatus",
    "VerificationStatus",
    "VerifiedCitation",
    "VerifiedField",
    "propose_evidence_fill",
    "verify_ai_evidence",
]
