"""Versioned scraper admission, idempotency, output, and error contracts.

This module deliberately sits outside the Prom parser.  It turns untrusted
submission data into a trusted acquisition decision and validates the
multi-axis result contract required by Metis evidence ingestion.  No parser
selector or extraction behaviour lives here.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from marko.core.config import Settings
from marko.services.scraper_contract import (
    AcquisitionInput,
    PROM_ADAPTER_VERSION,
    PROM_OUTPUT_SCHEMA_VERSION,
    QueryInput,
    ScrapeInput,
)
from marko.services.source_access import source_access_status


SCRAPE_REQUEST_CONTRACT_VERSION = "scrape-request.v2"
SCRAPE_RESULT_CONTRACT_VERSION = "scrape-result.v2"
SCRAPER_ERROR_CONTRACT_VERSION = "scraper-error.v2"
ADMISSION_POLICY_VERSION = "prom-admission.v2"
PARSER_CONFIG_HASH_VERSION = "prom-parser-config.v1"


class SourceType(StrEnum):
    PROM_PUBLIC = "prom_public"
    PROM_OWNED_API = "prom_owned_api"
    MANUAL_URL = "manual_url"
    REPLAY = "replay"
    OTHER = "other"


class SourceLane(StrEnum):
    OWNED_STOREFRONT = "OWNED_STOREFRONT"
    PUBLIC_COMPETITOR = "PUBLIC_COMPETITOR"
    REPLAY = "REPLAY"
    CLIENT_EXPORT = "CLIENT_EXPORT"


class SourcePolicyState(StrEnum):
    PERMITTED = "PERMITTED"
    OWNER_RISK_ACCEPTED = "OWNER_RISK_ACCEPTED"
    NOT_PERMITTED = "NOT_PERMITTED"
    UNKNOWN = "UNKNOWN"


class AcquisitionMode(StrEnum):
    SINGLE_URL = "single_url"
    URL_BATCH = "url_batch"
    STORE_SYNC = "store_sync"
    COMPARISON_JOB = "comparison_job"
    QUERY_BATCH = "query_batch"
    SCHEDULED = "scheduled"
    REPLAY = "replay"


class InputKind(StrEnum):
    URL = "url"
    QUERY = "query"
    PRODUCT_SEED = "product_seed"
    RAW_CAPTURE_ID = "raw_capture_id"


class ActorType(StrEnum):
    USER = "user"
    SERVICE = "service"
    SYSTEM = "system"
    TEST = "test"


class ExecutionStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRY_WAIT = "RETRY_WAIT"
    SUCCEEDED = "SUCCEEDED"
    TERMINAL_FAILED = "TERMINAL_FAILED"
    CANCELLED = "CANCELLED"
    DEAD_LETTERED = "DEAD_LETTERED"


class AcquisitionStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ParseStatus(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    SUCCEEDED = "SUCCEEDED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceStatus(StrEnum):
    NONE = "NONE"
    RAW_AVAILABLE = "RAW_AVAILABLE"
    STRUCTURED_AVAILABLE = "STRUCTURED_AVAILABLE"
    INGESTED = "INGESTED"
    INTEGRITY_FAILED = "INTEGRITY_FAILED"


class DownstreamEligibility(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    UNKNOWN = "UNKNOWN"


class OperatorAction(StrEnum):
    NONE = "NONE"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    REPLAY_REQUIRED = "REPLAY_REQUIRED"
    NO_RECOMMENDATION = "NO_RECOMMENDATION"


class PipelineStage(StrEnum):
    ADMISSION = "admission"
    ENQUEUE = "enqueue"
    LEASE = "lease"
    FETCH = "fetch"
    RAW_PERSIST = "raw_persist"
    PARSE = "parse"
    VALIDATE = "validate"
    STRUCTURED_PERSIST = "structured_persist"
    EVIDENCE_INGEST = "evidence_ingest"
    ACK = "ack"
    UNKNOWN = "unknown"


class ErrorClass(StrEnum):
    INPUT_ERROR = "input_error"
    FETCH_ERROR = "fetch_error"
    SOURCE_ACCESS_ERROR = "source_access_error"
    TIMEOUT_ERROR = "timeout_error"
    PARSE_ERROR = "parse_error"
    SCHEMA_ERROR = "schema_error"
    SEMANTIC_VALIDATION_ERROR = "semantic_validation_error"
    STORAGE_ERROR = "storage_error"
    QUEUE_ERROR = "queue_error"
    WORKER_ERROR = "worker_error"
    DOWNSTREAM_MAPPING_ERROR = "downstream_mapping_error"
    UNKNOWN_ERROR = "unknown_error"


class ErrorDisposition(StrEnum):
    RETRYABLE = "retryable"
    TERMINAL = "terminal"
    BLOCKED = "blocked"
    MANUAL_REVIEW = "manual_review"
    CANCELLED = "cancelled"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScrapeRequestItem(_StrictModel):
    item_id: str = Field(min_length=1, max_length=160)
    input_kind: InputKind
    input_value: str = Field(min_length=1, max_length=4096)
    priority: int = Field(ge=-100, le=100)
    client_item_reference: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_metadata_budget(self) -> Self:
        if len(_canonical_bytes(self.metadata)) > 16_384:
            raise ValueError("item metadata exceeds 16 KiB")
        return self


class ScrapeRequest(_StrictModel):
    contract_version: str = SCRAPE_REQUEST_CONTRACT_VERSION
    request_id: str = Field(min_length=1, max_length=160)
    client_idempotency_token: str | None = Field(default=None, max_length=255)
    tenant_id: str | None = Field(default=None, max_length=160)
    workspace_id: str | None = Field(default=None, max_length=160)
    source_type: SourceType
    acquisition_mode: AcquisitionMode
    submitted_by_actor_id: str = Field(min_length=1, max_length=160)
    submitted_by_actor_type: ActorType
    submitted_at: datetime
    deadline_at: datetime | None = None
    requested_freshness_seconds: int | None = Field(default=None, ge=0)
    items: list[ScrapeRequestItem] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        if self.contract_version != SCRAPE_REQUEST_CONTRACT_VERSION:
            raise ValueError("unsupported scrape request contract version")
        ids = [item.item_id for item in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("item_id values must be unique within a request")
        if self.deadline_at is not None and _utc(self.deadline_at) <= _utc(
            self.submitted_at
        ):
            raise ValueError("deadline_at must be later than submitted_at")
        if self.source_type == SourceType.REPLAY:
            if self.acquisition_mode != AcquisitionMode.REPLAY:
                raise ValueError("replay source requires replay acquisition mode")
            if any(item.input_kind != InputKind.RAW_CAPTURE_ID for item in self.items):
                raise ValueError("replay items must reference raw_capture_id")
        return self


class IdempotencyNamespaces(_StrictModel):
    submission_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    acquisition_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    parse_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observation_key: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class AdmissionDecision(_StrictModel):
    policy_decision_id: str = Field(min_length=1, max_length=160)
    source_policy_version: str = Field(min_length=1, max_length=160)
    source_policy_state: SourcePolicyState
    source_lane: SourceLane
    canonical_input: str = Field(min_length=1, max_length=4096)
    server_idempotency_keys: IdempotencyNamespaces
    admitted_at: datetime | None
    rejection_reason_code: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        admitted = self.admitted_at is not None
        if admitted == (self.rejection_reason_code is not None):
            raise ValueError(
                "exactly one of admitted_at or rejection_reason_code is required"
            )
        if admitted and self.source_policy_state not in {
            SourcePolicyState.PERMITTED,
            SourcePolicyState.OWNER_RISK_ACCEPTED,
        }:
            raise ValueError("blocked or unknown source policy cannot be admitted")
        return self


class ScraperError(_StrictModel):
    contract_version: str = SCRAPER_ERROR_CONTRACT_VERSION
    code: str = Field(min_length=1, max_length=160)
    pipeline_stage: PipelineStage
    error_class: ErrorClass
    disposition: ErrorDisposition
    evidence_available: bool
    raw_capture_id: str | None = None
    source_http_status: int | None = Field(default=None, ge=100, le=599)
    retry_after_seconds: float | None = Field(default=None, ge=0)
    message_public: str = Field(min_length=1, max_length=1000)
    message_internal: str = Field(min_length=1, max_length=4000)
    first_seen_at: datetime
    last_seen_at: datetime
    count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_error(self) -> Self:
        if self.contract_version != SCRAPER_ERROR_CONTRACT_VERSION:
            raise ValueError("unsupported scraper error contract version")
        if _utc(self.last_seen_at) < _utc(self.first_seen_at):
            raise ValueError("last_seen_at cannot precede first_seen_at")
        return self


class OfferEvidence(_StrictModel):
    source_url: str = Field(min_length=1, max_length=4096)
    raw_capture_id: str = Field(min_length=1, max_length=160)
    raw_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: datetime
    parsed_at: datetime
    extraction_method: str = Field(min_length=1, max_length=80)


class OfferValidation(_StrictModel):
    schema_valid: bool
    semantic_valid: bool
    completeness_score: float = Field(ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class StructuredOffer(_StrictModel):
    offer_id: str = Field(min_length=1, max_length=255)
    title: str | None = None
    price_amount_decimal: str | None = None
    price_raw_text: str | None = None
    price_currency: str | None = Field(default=None, min_length=3, max_length=3)
    seller_name: str | None = None
    seller_id: str | None = None
    availability: str | None = None
    brand: str | None = None
    condition: str | None = None
    product_identifiers: list[str] = Field(default_factory=list)
    evidence_fields: OfferEvidence
    validation: OfferValidation

    @model_validator(mode="after")
    def validate_money_and_identity(self) -> Self:
        if (self.price_amount_decimal is None) != (self.price_currency is None):
            raise ValueError("price amount and currency must be present together")
        if self.price_amount_decimal is not None:
            try:
                amount = Decimal(self.price_amount_decimal)
            except InvalidOperation as exc:
                raise ValueError("price must be a decimal string") from exc
            if not amount.is_finite() or amount <= 0:
                raise ValueError("price must be finite and positive")
            if self.price_amount_decimal != format(amount, "f"):
                raise ValueError("price must use canonical non-exponent decimal form")
        if self.seller_id is None and self.seller_name is None:
            raise ValueError("seller identity must be present or explicitly unknown")
        return self


class ResultMetrics(_StrictModel):
    queue_wait_ms: int | None = Field(default=None, ge=0)
    service_latency_ms: int | None = Field(default=None, ge=0)
    end_to_end_latency_ms: int | None = Field(default=None, ge=0)
    physical_attempts: int = Field(ge=0)
    logical_http_requests: int = Field(ge=0)
    raw_bytes: int = Field(ge=0)
    structured_bytes: int = Field(ge=0)


class ScrapeResult(_StrictModel):
    contract_version: str = SCRAPE_RESULT_CONTRACT_VERSION
    result_id: str = Field(min_length=1, max_length=160)
    request_id: str = Field(min_length=1, max_length=160)
    item_id: str = Field(min_length=1, max_length=160)
    job_id: str = Field(min_length=1, max_length=160)
    attempt_group_id: str = Field(min_length=1, max_length=160)
    winning_attempt_id: str | None = Field(default=None, max_length=160)
    source_type: SourceType
    source_lane: SourceLane
    source_url: str = Field(min_length=1, max_length=4096)
    requested_at: datetime
    fetched_at: datetime | None = None
    captured_at: datetime | None = None
    parsed_at: datetime | None = None
    raw_capture_id: str | None = Field(default=None, max_length=160)
    raw_content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parser_name: str = Field(min_length=1, max_length=160)
    parser_version: str = Field(min_length=1, max_length=160)
    parser_config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_schema_version: str = Field(min_length=1, max_length=160)
    execution_status: ExecutionStatus
    acquisition_status: AcquisitionStatus
    parse_status: ParseStatus
    evidence_status: EvidenceStatus
    downstream_eligibility: DownstreamEligibility
    operator_action: OperatorAction
    reason_codes: list[str] = Field(default_factory=list)
    offers: list[StructuredOffer] = Field(default_factory=list)
    errors: list[ScraperError] = Field(default_factory=list)
    metrics: ResultMetrics

    @model_validator(mode="after")
    def validate_cross_field_invariants(self) -> Self:
        if self.contract_version != SCRAPE_RESULT_CONTRACT_VERSION:
            raise ValueError("unsupported scrape result contract version")
        raw_present = (
            self.raw_capture_id is not None and self.raw_content_sha256 is not None
        )
        if (self.raw_capture_id is None) != (self.raw_content_sha256 is None):
            raise ValueError("raw capture id and hash must be present together")
        if self.acquisition_status == AcquisitionStatus.SUCCEEDED and not raw_present:
            raise ValueError("successful acquisition requires immutable raw evidence")
        if (
            self.evidence_status
            in {
                EvidenceStatus.RAW_AVAILABLE,
                EvidenceStatus.STRUCTURED_AVAILABLE,
                EvidenceStatus.INGESTED,
            }
            and not raw_present
        ):
            raise ValueError("evidence status requires raw evidence identity")
        if self.parse_status in {ParseStatus.SUCCEEDED, ParseStatus.PARTIAL}:
            if not raw_present or self.parsed_at is None:
                raise ValueError("parsed output requires raw evidence and parsed_at")
        if self.execution_status == ExecutionStatus.SUCCEEDED:
            if self.winning_attempt_id is None:
                raise ValueError("successful execution requires winning_attempt_id")
            if self.acquisition_status != AcquisitionStatus.SUCCEEDED:
                raise ValueError("successful execution requires successful acquisition")
        if self.downstream_eligibility == DownstreamEligibility.ELIGIBLE:
            if self.evidence_status != EvidenceStatus.INGESTED:
                raise ValueError("eligible output must be ingested into evidence layer")
            if self.parse_status != ParseStatus.SUCCEEDED or not self.offers:
                raise ValueError("eligible output requires complete parsed offers")
            if self.operator_action != OperatorAction.NONE:
                raise ValueError("eligible output cannot require operator intervention")
            if any(
                not offer.validation.schema_valid
                or not offer.validation.semantic_valid
                or offer.price_amount_decimal is None
                for offer in self.offers
            ):
                raise ValueError(
                    "invalid or price-less offer cannot be downstream eligible"
                )
        if self.parse_status in {ParseStatus.PARTIAL, ParseStatus.FAILED}:
            if self.downstream_eligibility == DownstreamEligibility.ELIGIBLE:
                raise ValueError("partial or failed parse must abstain downstream")
            if self.operator_action == OperatorAction.NONE:
                raise ValueError(
                    "partial or failed parse requires review/replay/abstention"
                )
        for offer in self.offers:
            if raw_present and (
                offer.evidence_fields.raw_capture_id != self.raw_capture_id
                or offer.evidence_fields.raw_content_sha256 != self.raw_content_sha256
            ):
                raise ValueError("offer evidence must point to the result raw capture")
        return self

    def canonical_sha256(self) -> str:
        return hashlib.sha256(
            _canonical_bytes(self.model_dump(mode="json"))
        ).hexdigest()


def build_parser_config_hash(config: dict[str, Any]) -> str:
    return _sha256(
        {
            "contract": PARSER_CONFIG_HASH_VERSION,
            "config": config,
        }
    )


def build_parse_key(
    *,
    raw_content_sha256: str,
    parser_name: str,
    parser_version: str,
    parser_config_hash: str,
    output_schema_version: str,
) -> str:
    return _sha256(
        {
            "namespace": "parse",
            "raw_content_sha256": raw_content_sha256,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "parser_config_hash": parser_config_hash,
            "output_schema_version": output_schema_version,
        }
    )


def build_observation_key(
    *,
    source_identity: str,
    external_listing_identity: str,
    raw_capture_id: str,
    observation_schema_version: str,
) -> str:
    return _sha256(
        {
            "namespace": "observation",
            "source_identity": source_identity,
            "external_listing_identity": external_listing_identity,
            "raw_capture_id": raw_capture_id,
            "observation_schema_version": observation_schema_version,
        }
    )


def build_idempotency_namespaces(
    request: ScrapeRequest,
    item: ScrapeRequestItem,
    *,
    canonical_input: str,
    source_lane: SourceLane,
    policy_version: str,
    freshness_generation: int = 0,
) -> IdempotencyNamespaces:
    tenant_scope = request.tenant_id or request.workspace_id or "global"
    normalized_shape = {
        "contract_version": request.contract_version,
        "source_type": request.source_type.value,
        "acquisition_mode": request.acquisition_mode.value,
        "item_kind": item.input_kind.value,
        "item_value": canonical_input,
        "metadata": item.metadata,
    }
    submission_key = _sha256(
        {
            "namespace": "submission",
            "tenant_scope": tenant_scope,
            "client_token": request.client_idempotency_token,
            "request_shape": normalized_shape,
        }
    )
    acquisition_key = _sha256(
        {
            "namespace": "acquisition",
            "source_type": request.source_type.value,
            "source_lane": source_lane.value,
            "input_kind": item.input_kind.value,
            "canonical_input": canonical_input,
            "tenant_scope": tenant_scope,
            "policy_version": policy_version,
            "freshness_generation": freshness_generation,
        }
    )
    return IdempotencyNamespaces(
        submission_key=submission_key,
        acquisition_key=acquisition_key,
    )


def admit_prom_public_item(
    request: ScrapeRequest,
    item: ScrapeRequestItem,
    *,
    settings: Settings,
    freshness_generation: int = 0,
    now: datetime | None = None,
) -> tuple[AdmissionDecision, AcquisitionInput | None]:
    """Evaluate a public Prom item entirely on the trusted server side."""

    if request.source_type != SourceType.PROM_PUBLIC:
        raise ValueError("public Prom admission requires source_type=prom_public")
    if request.acquisition_mode not in {
        AcquisitionMode.SINGLE_URL,
        AcquisitionMode.URL_BATCH,
        AcquisitionMode.COMPARISON_JOB,
        AcquisitionMode.QUERY_BATCH,
        AcquisitionMode.SCHEDULED,
    }:
        raise ValueError("unsupported acquisition mode for public Prom admission")
    if item.input_kind == InputKind.QUERY:
        if request.acquisition_mode not in {
            AcquisitionMode.COMPARISON_JOB,
            AcquisitionMode.QUERY_BATCH,
        }:
            raise ValueError("query input requires comparison_job or query_batch mode")
        language = item.metadata.get("language", "ua")
        if not isinstance(language, str):
            raise ValueError("public Prom query metadata.language must be a string")
        search_context = item.metadata.get("search_context")
        if search_context is not None and not isinstance(search_context, str):
            raise ValueError(
                "public Prom query metadata.search_context must be a string"
            )
        declared_widenings = item.metadata.get("fallback_queries")
        if declared_widenings is not None and not (
            isinstance(declared_widenings, list)
            and all(isinstance(value, str) for value in declared_widenings)
        ):
            raise ValueError(
                "public Prom query metadata.fallback_queries must be strings"
            )
        declared_discovery = item.metadata.get("discovery_queries")
        if declared_discovery is not None and not (
            isinstance(declared_discovery, list)
            and all(isinstance(value, str) for value in declared_discovery)
        ):
            raise ValueError(
                "public Prom query metadata.discovery_queries must be strings"
            )
        scrape_input: AcquisitionInput = QueryInput.build(
            item.input_value,
            language=language,
            search_context=search_context,
            fallback_queries=declared_widenings,
            discovery_queries=declared_discovery,
            adapter_version=PROM_ADAPTER_VERSION,
        )
        canonical_input = scrape_input.query_key
    elif item.input_kind in {InputKind.URL, InputKind.PRODUCT_SEED}:
        query = item.metadata.get("query")
        if not isinstance(query, str):
            raise ValueError("public Prom item metadata.query is required")
        scrape_input = ScrapeInput.build(
            item.input_value,
            query,
            adapter_version=PROM_ADAPTER_VERSION,
        )
        canonical_input = scrape_input.canonical_url
    else:
        raise ValueError("public Prom admission requires a URL, product seed, or query")
    access = source_access_status(settings)
    state = (
        SourcePolicyState.PERMITTED
        if access.live_collection_allowed
        else SourcePolicyState.NOT_PERMITTED
    )
    policy_fingerprint = _sha256(
        {
            "version": ADMISSION_POLICY_VERSION,
            "source": access.source,
            "verdict": access.verdict,
            "reference": access.reference,
        }
    )
    keys = build_idempotency_namespaces(
        request,
        item,
        canonical_input=canonical_input,
        source_lane=SourceLane.PUBLIC_COMPETITOR,
        policy_version=policy_fingerprint,
        freshness_generation=freshness_generation,
    )
    admitted_at = (
        _utc(now or datetime.now(UTC)) if access.live_collection_allowed else None
    )
    decision = AdmissionDecision(
        policy_decision_id=f"policy-{uuid4()}",
        source_policy_version=policy_fingerprint,
        source_policy_state=state,
        source_lane=SourceLane.PUBLIC_COMPETITOR,
        canonical_input=canonical_input,
        server_idempotency_keys=keys,
        admitted_at=admitted_at,
        rejection_reason_code=(None if admitted_at else "SOURCE_ACCESS_BLOCKED"),
    )
    return decision, scrape_input if admitted_at else None


def parser_contract_defaults() -> dict[str, str]:
    return {
        "parser_name": "marko.parsers.prom",
        "parser_version": PROM_ADAPTER_VERSION,
        "parser_config_hash": build_parser_config_hash(
            {"adapter": PROM_ADAPTER_VERSION}
        ),
        "output_schema_version": PROM_OUTPUT_SCHEMA_VERSION,
    }


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode()


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "ADMISSION_POLICY_VERSION",
    "AcquisitionMode",
    "AcquisitionStatus",
    "ActorType",
    "AdmissionDecision",
    "DownstreamEligibility",
    "ErrorClass",
    "ErrorDisposition",
    "EvidenceStatus",
    "ExecutionStatus",
    "IdempotencyNamespaces",
    "InputKind",
    "OfferEvidence",
    "OfferValidation",
    "OperatorAction",
    "ParseStatus",
    "PipelineStage",
    "ResultMetrics",
    "SCRAPE_REQUEST_CONTRACT_VERSION",
    "SCRAPE_RESULT_CONTRACT_VERSION",
    "ScrapeRequest",
    "ScrapeRequestItem",
    "ScrapeResult",
    "ScraperError",
    "SourceLane",
    "SourcePolicyState",
    "SourceType",
    "StructuredOffer",
    "admit_prom_public_item",
    "build_idempotency_namespaces",
    "build_observation_key",
    "build_parse_key",
    "build_parser_config_hash",
    "parser_contract_defaults",
]
