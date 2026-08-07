from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from metis.pricing import (
    comparison_evidence_to_dict,
    verified_comparison_evidence,
)
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.oe_reenrichment import (
    OeReenrichmentDataError,
    _classification_allows_automatic,
    _persisted_semantic_gate_allowed,
    build_reenrichment_patch,
)
from marko.services.offer_identity import (
    ConfirmedCross,
    OeVerificationStatus,
    canonical_cross_identity_key,
)
from marko.services.scraper_contract import (
    PROM_ADAPTER_VERSION,
    PROM_OUTPUT_SCHEMA_VERSION,
    QueryInput,
)
from marko.services.semantic_candidate_features import (
    SEMANTIC_FEATURE_EXTRACTOR_VERSION,
)
from marko.services.semantic_candidate_gate import SEMANTIC_PRICING_GATE_VERSION


Q = "1K0121251"
Y = "8K0615121"


def _capture(product: dict[str, object]) -> SimpleNamespace:
    query = QueryInput.build(Q, language="ua", adapter_version=PROM_ADAPTER_VERSION)
    raw_evidence = [
        {
            "logical_request_id": "request-1",
            "raw_content_sha256": "b" * 64,
        }
    ]
    payload = {
        "schema_version": PROM_OUTPUT_SCHEMA_VERSION,
        "adapter_version": PROM_ADAPTER_VERSION,
        "input": query.as_dict(),
        "output": {
            "acquisition_outcome": "RESULTS",
            "candidates_scanned": 1,
            "records": [
                {
                    "raw_offer_index": 0,
                    "retrieval_kind": "search_query",
                    "retrieval_score": None,
                    "product": product,
                    "upstream_comparison_evidence": None,
                }
            ],
        },
        "raw_evidence": raw_evidence,
        "raw_manifest_sha256": canonical_sha256(raw_evidence),
    }
    return SimpleNamespace(id=uuid4(), payload=payload)


def _observation(
    *,
    listing_id: str = "42",
    source_assertion_retrieval_kind: str | None = None,
    source_assertion_capture_sha256: str | None = None,
    source_assertion_confidence: Decimal | None = None,
    via_oe_number: str | None = None,
) -> SimpleNamespace:
    evidence = verified_comparison_evidence(
        stable_seller_id="seller-1",
        source_record_id=listing_id,
    )
    return SimpleNamespace(
        source_listing_id=listing_id,
        search_oe_norm=Q,
        source_assertion_retrieval_kind=source_assertion_retrieval_kind,
        source_assertion_capture_sha256=source_assertion_capture_sha256,
        source_assertion_confidence=source_assertion_confidence,
        via_oe_number=via_oe_number,
        comparison_evidence=comparison_evidence_to_dict(evidence),
        seller_id="seller-1",
        currency_raw="UAH",
        currency="UAH",
        seller_identity_verified=True,
        source_provenance_verified=True,
        source_confidence=Decimal("1"),
    )


def _product(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "product_id": "42",
        "name": "Помпа KEMP",
        "price": "850.00",
        "currency": "UAH",
        "seller_id": "seller-1",
        "url": "https://prom.ua/ua/p42-pompa.html",
        "is_available": True,
    }
    value.update(overrides)
    return value


def _frozen_item(oe: str = Q):
    return SimpleNamespace(
        category="water_pumps",
        oe_norm=oe,
        mpn_norm="",
        identity_status="OE_CONFIRMED",
        part_numbers_norm=(),
    )


def _build(product: dict[str, object], *, crosses=()):
    return build_reenrichment_patch(
        observation=_observation(),
        frozen_item=_frozen_item(),
        capture=_capture(product),
        run=SimpleNamespace(policy_config={}),
        confirmed_crosses=crosses,
    )


@pytest.mark.parametrize(
    ("classification", "expected"),
    (
        (None, False),
        (
            SimpleNamespace(
                is_owned=False,
                is_kemp=False,
                is_used=False,
                cohort_role="TARGET_MARKET",
            ),
            True,
        ),
        (
            SimpleNamespace(
                is_owned=True,
                is_kemp=False,
                is_used=False,
                cohort_role="TARGET_MARKET",
            ),
            False,
        ),
        (
            SimpleNamespace(
                is_owned=False,
                is_kemp=True,
                is_used=False,
                cohort_role="KEMP_REFERENCE",
            ),
            False,
        ),
        (
            SimpleNamespace(
                is_owned=False,
                is_kemp=False,
                is_used=True,
                cohort_role="USED_REJECTED",
            ),
            False,
        ),
        (
            SimpleNamespace(
                is_owned=False,
                is_kemp=False,
                is_used=False,
                cohort_role="MANUAL_REVIEW",
            ),
            False,
        ),
    ),
)
def test_reenrichment_automatic_admission_requires_target_market_classification(
    classification, expected
) -> None:
    assert _classification_allows_automatic(classification) is expected


def test_reenrichment_exact_oe_is_deterministic_and_network_free() -> None:
    capture = _capture(_product(oe_raw=Q))
    observation = _observation()
    inputs = {
        "observation": observation,
        "frozen_item": _frozen_item(),
        "capture": capture,
        "run": SimpleNamespace(policy_config={}),
    }

    first = build_reenrichment_patch(**inputs)
    second = build_reenrichment_patch(**deepcopy(inputs))

    assert first.deterministic_dict() == second.deterministic_dict()
    assert first.oe_verification_status == OeVerificationStatus.VERIFIED_EXACT.value
    assert first.verified_matched_oe_norm == Q
    assert first.comparison_identity_key == Q


def test_reenrichment_never_promotes_query_without_candidate_evidence() -> None:
    patch = _build(_product())

    assert patch.oe_verification_status == OeVerificationStatus.UNKNOWN.value
    assert patch.extracted_oe_norms == ()
    assert patch.verified_matched_oe_norm is None
    assert patch.comparison_identity_key is None
    assert patch.automatic_eligible is False


def test_reenrichment_never_promotes_without_the_persisted_semantic_gate() -> None:
    """Identity replay must not bypass the category-aware pricing boundary."""

    patch = _build(_product(oe_raw=Q))

    assert patch.oe_verification_status == OeVerificationStatus.VERIFIED_EXACT.value
    assert patch.automatic_eligible is False
    assert patch.comparability_hard_gate_result == "MANUAL_REVIEW"
    assert (
        "REENRICHMENT_SEMANTIC_GATE_REQUIRED"
        in patch.comparison_evidence["reason_codes"]
    )


def test_reenrichment_rejects_gate_snapshot_without_identity_admission_proof() -> None:
    """A current gate version alone cannot authorize identity replay."""

    observation = SimpleNamespace(
        candidate_snapshot={
            "semantic_gate": {
                "status": "PRICING_EVIDENCE",
                "reason": "OK",
                "gate_version": SEMANTIC_PRICING_GATE_VERSION,
                "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
            }
        }
    )

    assert _persisted_semantic_gate_allowed(observation) is False

    observation.candidate_snapshot["identity_admission"] = {
        "automatic_evidence_sufficient": True,
    }
    assert _persisted_semantic_gate_allowed(observation) is True


def test_reenrichment_binds_gate_to_listing_and_capture() -> None:
    """A valid gate copied from another retained offer must be rejected."""

    capture_id = uuid4()
    observation = SimpleNamespace(
        source_listing_id="42",
        raw_capture_id=capture_id,
        candidate_snapshot={
            "source_locator": {
                "source_listing_id": "42",
                "raw_capture_id": str(capture_id),
            },
            "semantic_gate": {
                "status": "PRICING_EVIDENCE",
                "reason": "OK",
                "gate_version": SEMANTIC_PRICING_GATE_VERSION,
                "extractor_version": SEMANTIC_FEATURE_EXTRACTOR_VERSION,
            },
            "identity_admission": {
                "automatic_evidence_sufficient": True,
            },
        },
    )

    assert _persisted_semantic_gate_allowed(observation) is True
    observation.source_listing_id = "other-listing"
    assert _persisted_semantic_gate_allowed(observation) is False
    observation.source_listing_id = "42"
    observation.raw_capture_id = uuid4()
    assert _persisted_semantic_gate_allowed(observation) is False


def test_reenrichment_uses_only_confirmed_one_hop_cross() -> None:
    cross_id = uuid4()
    cross = ConfirmedCross(
        search_oe_norm=Q,
        candidate_oe_norm=Y,
        canonical_identity_key=canonical_cross_identity_key(Q, Y),
        confidence=Decimal("0.94"),
        cross_link_id=str(cross_id),
    )

    patch = _build(_product(oe_raw=Y), crosses=(cross,))

    assert patch.oe_verification_status == OeVerificationStatus.VERIFIED_CROSS.value
    assert patch.verified_matched_oe_norm == Y
    assert patch.comparison_identity_key == f"XREF:{Q}|{Y}"
    assert patch.cross_link_id == cross_id


def test_reenrichment_records_missing_source_record_as_typed_failure() -> None:
    with pytest.raises(
        OeReenrichmentDataError,
        match="REENRICHMENT_SOURCE_RECORD_NOT_FOUND",
    ):
        build_reenrichment_patch(
            observation=_observation(listing_id="missing"),
            frozen_item=_frozen_item(),
            capture=_capture(_product()),
            run=SimpleNamespace(policy_config={}),
        )


def test_reenrichment_reads_target_output_through_capture_reference() -> None:
    structured = _capture(_product(oe_raw=Q))
    reference_capture = SimpleNamespace(
        id=structured.id,
        payload={
            "schema_version": "metis-scrape-target-ref-v2",
            "raw_evidence": structured.payload["raw_evidence"],
            "raw_manifest_sha256": structured.payload["raw_manifest_sha256"],
        },
    )

    patch = build_reenrichment_patch(
        observation=_observation(),
        frozen_item=_frozen_item(),
        capture=reference_capture,
        run=SimpleNamespace(policy_config={}),
        structured_payload=structured.payload,
    )

    assert patch.oe_verification_status == OeVerificationStatus.VERIFIED_EXACT.value
    assert patch.verified_matched_oe_norm == Q
