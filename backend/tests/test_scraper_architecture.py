from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from marko.core.config import Settings
from marko.services.scraper_architecture import (
    AcquisitionMode,
    AcquisitionStatus,
    ActorType,
    DownstreamEligibility,
    EvidenceStatus,
    ExecutionStatus,
    InputKind,
    OfferEvidence,
    OfferValidation,
    OperatorAction,
    ParseStatus,
    ResultMetrics,
    ScrapeRequest,
    ScrapeRequestItem,
    ScrapeResult,
    SourcePolicyState,
    SourceType,
    StructuredOffer,
    admit_prom_public_item,
    build_observation_key,
    build_parse_key,
    parser_contract_defaults,
)
from marko.services.scraper_contract import ScrapeInput, ScraperBoundaryError


def _request(**overrides) -> ScrapeRequest:
    now = datetime.now(UTC)
    values = {
        "request_id": "request-1",
        "client_idempotency_token": "client-token-1",
        "workspace_id": str(uuid4()),
        "source_type": SourceType.PROM_PUBLIC,
        "acquisition_mode": AcquisitionMode.COMPARISON_JOB,
        "submitted_by_actor_id": "user-1",
        "submitted_by_actor_type": ActorType.USER,
        "submitted_at": now,
        "deadline_at": now + timedelta(minutes=5),
        "items": [
            ScrapeRequestItem(
                item_id="item-1",
                input_kind=InputKind.PRODUCT_SEED,
                input_value="https://prom.ua/ua/p123-test-product.html",
                priority=0,
                metadata={"query": "OE 123"},
            )
        ],
    }
    values.update(overrides)
    return ScrapeRequest(**values)


def _settings(*, permitted: bool) -> Settings:
    return Settings(
        prom_marketplace_source_access_verdict=(
            "PERMITTED_LIMITED" if permitted else "NOT_PERMITTED"
        ),
        prom_marketplace_source_access_reference=("ADR-42" if permitted else ""),
    )


def test_untrusted_request_cannot_supply_source_policy_authority() -> None:
    payload = _request().model_dump()
    payload["source_policy_state"] = "PERMITTED"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ScrapeRequest.model_validate(payload)


def test_trusted_admission_is_fail_closed_and_keeps_server_keys() -> None:
    request = _request()
    blocked, blocked_input = admit_prom_public_item(
        request,
        request.items[0],
        settings=_settings(permitted=False),
    )
    assert blocked.source_policy_state == SourcePolicyState.NOT_PERMITTED
    assert blocked.rejection_reason_code == "SOURCE_ACCESS_BLOCKED"
    assert blocked_input is None

    admitted, scrape_input = admit_prom_public_item(
        request,
        request.items[0],
        settings=_settings(permitted=True),
    )
    assert admitted.source_policy_state == SourcePolicyState.PERMITTED
    assert admitted.admitted_at is not None
    assert scrape_input is not None
    assert admitted.server_idempotency_keys.submission_key != (
        admitted.server_idempotency_keys.acquisition_key
    )


def test_idempotency_namespaces_do_not_collapse_parse_and_observation() -> None:
    parse_key = build_parse_key(
        raw_content_sha256="a" * 64,
        parser_name="prom",
        parser_version="v2",
        parser_config_hash="b" * 64,
        output_schema_version="v1",
    )
    observation_key = build_observation_key(
        source_identity="prom",
        external_listing_identity="listing-1",
        raw_capture_id="capture-1",
        observation_schema_version="v1",
    )
    assert parse_key != observation_key
    assert len(parse_key) == len(observation_key) == 64


def test_scrape_input_rejects_embedded_credentials() -> None:
    with pytest.raises(ScraperBoundaryError, match="Credentials embedded"):
        ScrapeInput.build(
            "https://user:secret@prom.ua/ua/p123-test-product.html",
            "OE 123",
        )


def _offer(*, raw_capture_id: str, raw_hash: str) -> StructuredOffer:
    now = datetime.now(UTC)
    return StructuredOffer(
        offer_id="offer-1",
        title="Product",
        price_amount_decimal="123.45",
        price_currency="UAH",
        seller_name="Seller",
        evidence_fields=OfferEvidence(
            source_url="https://prom.ua/ua/p123-test-product.html",
            raw_capture_id=raw_capture_id,
            raw_content_sha256=raw_hash,
            captured_at=now,
            parsed_at=now,
            extraction_method="html_selector",
        ),
        validation=OfferValidation(
            schema_valid=True,
            semantic_valid=True,
            completeness_score=1,
        ),
    )


def _result(**overrides) -> ScrapeResult:
    now = datetime.now(UTC)
    raw_id = "capture-1"
    raw_hash = "c" * 64
    parser = parser_contract_defaults()
    values = {
        "result_id": "result-1",
        "request_id": "request-1",
        "item_id": "item-1",
        "job_id": "job-1",
        "attempt_group_id": "attempt-group-1",
        "winning_attempt_id": "attempt-1",
        "source_type": SourceType.PROM_PUBLIC,
        "source_lane": "PUBLIC_COMPETITOR",
        "source_url": "https://prom.ua/ua/p123-test-product.html",
        "requested_at": now,
        "fetched_at": now,
        "captured_at": now,
        "parsed_at": now,
        "raw_capture_id": raw_id,
        "raw_content_sha256": raw_hash,
        **parser,
        "execution_status": ExecutionStatus.SUCCEEDED,
        "acquisition_status": AcquisitionStatus.SUCCEEDED,
        "parse_status": ParseStatus.SUCCEEDED,
        "evidence_status": EvidenceStatus.INGESTED,
        "downstream_eligibility": DownstreamEligibility.ELIGIBLE,
        "operator_action": OperatorAction.NONE,
        "offers": [_offer(raw_capture_id=raw_id, raw_hash=raw_hash)],
        "metrics": ResultMetrics(
            queue_wait_ms=1,
            service_latency_ms=2,
            end_to_end_latency_ms=3,
            physical_attempts=1,
            logical_http_requests=1,
            raw_bytes=100,
            structured_bytes=50,
        ),
    }
    values.update(overrides)
    return ScrapeResult(**values)


def test_multi_axis_result_requires_raw_lineage_and_abstention() -> None:
    result = _result()
    assert result.canonical_sha256() == result.canonical_sha256()

    with pytest.raises(ValidationError, match="immutable raw evidence"):
        _result(raw_capture_id=None, raw_content_sha256=None)

    with pytest.raises(ValidationError, match="eligible output|partial"):
        _result(
            parse_status=ParseStatus.PARTIAL,
            downstream_eligibility=DownstreamEligibility.ELIGIBLE,
        )


def test_money_contract_rejects_amount_without_currency() -> None:
    payload = _offer(
        raw_capture_id="capture-1",
        raw_hash="d" * 64,
    ).model_dump()
    payload["price_currency"] = None
    with pytest.raises(ValidationError, match="present together"):
        StructuredOffer.model_validate(payload)
