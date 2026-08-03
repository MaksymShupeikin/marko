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
from marko.services.offer_processing import (
    ACQUISITION_METHOD_OE_PAGE_LISTING,
    ACQUISITION_SOURCE_OE_PAGE,
    ASSERTING_RETRIEVAL_KINDS,
    WIDENED_RETRIEVAL_KINDS,
    AcquisitionLineage,
)


OE_EXTRACTOR_VERSION = "oe-extractor-v1"
OE_VERIFICATION_THRESHOLD = Decimal("0.90")
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
    r"АРТИКУЛ|КОД\s+(?:ВИРОБНИКА|ПРОИЗВОДИТЕЛЯ)|КРОС[- ]?КОД)"
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


class OeEvidenceSourceKind(StrEnum):
    STRUCTURED_OE_FIELD = "STRUCTURED_OE_FIELD"
    LABELED_CHARACTERISTIC = "LABELED_CHARACTERISTIC"
    SKU = "SKU"
    TITLE = "TITLE"
    DESCRIPTION = "DESCRIPTION"
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
    confidence: Decimal = Decimal("0.90")
    cross_link_id: str | None = None


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


def extract_oe_evidence(
    raw_offer: Mapping[str, Any],
    raw_capture_manifest: Mapping[str, Any],
) -> tuple[OeEvidenceItem, ...]:
    """Extract provenance-bearing OE candidates without consulting search intent."""

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
    ) -> None:
        if raw_value is None:
            return
        text = str(raw_value).strip()
        normalized = _valid_normalized_oe(text)
        if normalized is None:
            return
        effective_confidence = confidence if provenance_complete else Decimal("0")
        group_digest = hashlib.sha256(
            correlation_source.strip().casefold().encode("utf-8")
        ).hexdigest()[:20]
        items.append(
            OeEvidenceItem(
                raw_value=text,
                normalized_value=normalized,
                source_kind=source_kind,
                source_record_id=source_record_id,
                raw_capture_id=raw_capture_id,
                raw_content_sha256=raw_hash,
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
            )

    for label, value, path in _iter_characteristics(raw_offer.get("characteristics")):
        if not _is_oe_label(label):
            continue
        for candidate in _split_structured_values(value):
            add(
                candidate,
                source_kind=OeEvidenceSourceKind.LABELED_CHARACTERISTIC,
                json_path=path,
                char_span=None,
                context_label=label,
                method="structured_field",
                confidence=Decimal("0.97"),
                correlation_source=f"{path}:{candidate}",
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
    *,
    legacy_without_reenrichment: bool = False,
    source_assertion: SourceAssertion | None = None,
) -> OeVerification:
    query = normalize_oe(search_oe_norm)
    evidence = tuple(evidence_items)

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
            reason_codes=("OE_EVIDENCE_BELOW_THRESHOLD",),
        )

    cross_by_candidate = {
        cross.candidate_oe_norm: cross
        for cross in confirmed_crosses
        if cross.search_oe_norm == query
    }
    exact = {value for value in eligible if value == query}
    cross_values = {value for value in eligible if value in cross_by_candidate}
    incompatible = eligible - exact - cross_values
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
    identity_key = str(
        getattr(observation, "comparison_identity_key", None) or ""
    ).strip()
    via_cross = bool(getattr(observation, "via_cross", False))
    cross_link_id = getattr(observation, "cross_link_id", None)

    if status == OeVerificationStatus.VERIFIED_EXACT:
        return bool(
            query
            and verified == query
            and verified in extracted
            and identity_key == verified
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


def _valid_normalized_oe(value: str) -> str | None:
    normalized = normalize_oe(value)
    if normalized is None or not 4 <= len(normalized) <= 32:
        return None
    if not any(character.isdigit() for character in normalized):
        return None
    if normalized.isdigit():
        if len(normalized) >= 10:
            return None
        if len(normalized) == 4 and 1900 <= int(normalized) <= 2100:
            return None
    return normalized


def _split_structured_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list | tuple | set):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return ()
    values = tuple(item.strip() for item in re.split(r"[,;|]", text) if item.strip())
    return values or (text,)


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
    compact = re.sub(r"[^A-ZА-ЯІЇЄ]", "", value.upper())
    return compact in {
        "OE",
        "OEM",
        "OEMNO",
        "OEНОМЕР",
        "АРТИКУЛ",
        "КОДВИРОБНИКА",
        "КОДПРОИЗВОДИТЕЛЯ",
    }


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
    "OE_EXTRACTOR_VERSION",
    "OE_VERIFICATION_THRESHOLD",
    "OeEvidenceItem",
    "OeEvidenceSourceKind",
    "OeVerification",
    "OeVerificationStatus",
    "bind_oe_verification",
    "canonical_cross_identity_key",
    "evidence_items_to_dicts",
    "evidence_strength",
    "extract_oe_evidence",
    "persisted_identity_fields_consistent",
    "verify_offer_identity",
]
