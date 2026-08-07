from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from marko.infrastructure.db.models import PricingRun
from marko.services.fitment_cross_bridge import (
    FitmentCrossBridgeError,
    fitment_cross_authority_sha256,
    fitment_cross_snapshot_sha256,
    fitment_cross_snapshots_by_candidate,
    validate_fitment_cross_snapshot,
)
from marko.services.fitment_intelligence import FITMENT_CROSS_METHOD_VERSION
from marko.services.pricing_runs import _frozen_catalog_cross_rows

NOW = datetime(2026, 8, 4, tzinfo=UTC)


def _record(**overrides) -> SimpleNamespace:
    values = {
        "id": uuid4(),
        "brand": "JP Group",
        "article": "1145200500",
        "normalized_article": "1145200500",
        "oe": "330422371",
        "normalized_oe": "330422371",
        "installation_position": None,
        "vehicle_key": None,
        "relation_status": "source_confirmed",
        "confidence": Decimal("0.90"),
        "evidence_ids": [str(uuid4()), str(uuid4())],
        "source_count": 2,
        "human_feedback_count": 0,
        "method_version": FITMENT_CROSS_METHOD_VERSION,
        "last_verified_at": NOW,
        "supersedes_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _snapshots(
    records,
    *,
    queries: dict[UUID, str] | None = None,
    include_authority: bool = True,
):
    item_id = UUID("00000000-0000-0000-0000-000000000001")
    authorities = {
        record.id: _authority(record)
        for record in records
        if include_authority and record.evidence_ids
    }
    return fitment_cross_snapshots_by_candidate(
        candidate_queries=queries or {item_id: "330422371"},
        records=records,
        authorities=authorities,
    )


def _authority(record: SimpleNamespace) -> dict:
    payload = {
        "fitment_cross_reference_id": str(record.id),
        "normalized_pair": [record.normalized_article, record.normalized_oe],
        "evidence_claim_ids": sorted(set(record.evidence_ids)),
        "assessment_ids": [str(uuid4())],
        "source_group_count": (
            str(record.source_count)
            if isinstance(record.source_count, Decimal)
            else record.source_count
        ),
        "source_evidence": (
            [{"synthetic_unit_authority": True}]
            if record.relation_status == "source_confirmed"
            else []
        ),
        "human_review_ids": (
            [str(uuid4())]
            if record.relation_status == "human_confirmed"
            and record.human_feedback_count
            else []
        ),
        "checked_at": NOW.isoformat(),
    }
    payload["authority_sha256"] = fitment_cross_authority_sha256(payload)
    return payload


def test_source_confirmed_cross_is_bound_to_one_primary_catalog_query() -> None:
    item_id = UUID("00000000-0000-0000-0000-000000000001")

    result = _snapshots([_record()])

    snapshot = result[item_id][0]
    assert snapshot["our_oem_norm"] == "330422371"
    assert snapshot["extracted_oem_norm"] == "1145200500"
    assert snapshot["validation_details"]["source_count"] == 2
    assert snapshot["config_sha256"]
    assert (
        validate_fitment_cross_snapshot(
            snapshot,
            catalog_item_id=item_id,
            customer_query="330 422 371",
        )
        == snapshot
    )


def test_confirmation_without_reloaded_primary_evidence_fails_closed() -> None:
    assert _snapshots([_record()], include_authority=False) == {}


@pytest.mark.parametrize(
    "overrides",
    (
        {"relation_status": "machine_discovered"},
        {"confidence": Decimal("0.7499")},
        {"installation_position": "rear-right"},
        {"vehicle_key": "VW:PASSAT:B3"},
        {"method_version": "fitment-cross-stale-v0"},
        {"source_count": 0},
        {"source_count": Decimal("1.5")},
        {"evidence_ids": []},
    ),
)
def test_unproven_or_context_limited_cross_never_widens_pricing(overrides) -> None:
    assert _snapshots([_record(**overrides)]) == {}


def test_human_confirmation_requires_persisted_human_feedback() -> None:
    assert (
        _snapshots(
            [
                _record(
                    relation_status="human_confirmed",
                    source_count=1,
                    human_feedback_count=0,
                )
            ]
        )
        == {}
    )

    admitted = _snapshots(
        [
            _record(
                relation_status="human_confirmed",
                source_count=1,
                human_feedback_count=1,
            )
        ]
    )
    assert admitted


def test_live_rejection_blocks_an_unsuperseded_confirmation_of_the_same_pair() -> None:
    confirmed = _record()
    rejected = _record(
        relation_status="human_rejected",
        confidence=Decimal("1"),
        human_feedback_count=1,
    )

    assert _snapshots([confirmed, rejected]) == {}


def test_superseding_rejection_disables_the_old_confirmation() -> None:
    confirmed = _record()
    rejected = _record(
        relation_status="human_rejected",
        confidence=Decimal("1"),
        human_feedback_count=1,
        supersedes_id=confirmed.id,
    )

    assert _snapshots([confirmed, rejected]) == {}


def test_new_confirmation_can_supersede_an_old_rejection() -> None:
    rejected = _record(
        relation_status="human_rejected",
        confidence=Decimal("1"),
        human_feedback_count=1,
    )
    confirmed = _record(supersedes_id=rejected.id)

    assert _snapshots([rejected, confirmed])


def test_duplicate_catalog_query_is_fanout_and_fails_closed() -> None:
    first = UUID("00000000-0000-0000-0000-000000000001")
    second = UUID("00000000-0000-0000-0000-000000000002")

    assert (
        _snapshots(
            [_record()],
            queries={first: "330422371", second: "330422371"},
        )
        == {}
    )


def test_relation_between_two_current_catalog_rows_fails_closed() -> None:
    first = UUID("00000000-0000-0000-0000-000000000001")
    second = UUID("00000000-0000-0000-0000-000000000002")

    assert (
        _snapshots(
            [_record()],
            queries={first: "330422371", second: "1145200500"},
        )
        == {}
    )


def test_private_catalog_code_cannot_become_external_cross_identity() -> None:
    assert (
        _snapshots([_record(normalized_article="77643352", article="77643352")]) == {}
    )


def test_frozen_cross_hash_detects_any_post_preview_mutation() -> None:
    item_id = UUID("00000000-0000-0000-0000-000000000001")
    snapshot = dict(_snapshots([_record()])[item_id][0])
    details = dict(snapshot["validation_details"])
    details["confidence"] = "1.00"
    snapshot["validation_details"] = details

    with pytest.raises(FitmentCrossBridgeError, match="hash mismatch"):
        validate_fitment_cross_snapshot(
            snapshot,
            catalog_item_id=item_id,
            customer_query="330422371",
        )


def test_nested_authority_hash_detects_forgery_even_if_outer_hash_is_recomputed() -> (
    None
):
    item_id = UUID("00000000-0000-0000-0000-000000000001")
    snapshot = deepcopy(_snapshots([_record()])[item_id][0])
    snapshot["validation_details"]["authority"]["source_evidence"].append(
        {"forged": True}
    )
    snapshot["config_sha256"] = fitment_cross_snapshot_sha256(snapshot)

    with pytest.raises(FitmentCrossBridgeError, match="authority hash mismatch"):
        validate_fitment_cross_snapshot(
            snapshot,
            catalog_item_id=item_id,
            customer_query="330422371",
        )


def test_frozen_cross_cannot_be_rebound_to_another_catalog_query() -> None:
    item_id = UUID("00000000-0000-0000-0000-000000000001")
    snapshot = _snapshots([_record()])[item_id][0]

    with pytest.raises(FitmentCrossBridgeError, match="customer query"):
        validate_fitment_cross_snapshot(
            snapshot,
            catalog_item_id=item_id,
            customer_query="93818439",
        )


def test_verified_fitment_cross_becomes_run_owned_immutable_cross_evidence() -> None:
    item_id = UUID("00000000-0000-0000-0000-000000000001")
    snapshot = _snapshots([_record()])[item_id][0]
    candidate = SimpleNamespace(
        catalog_item_id=item_id,
        confirmed_identity_links=(snapshot,),
        oe_norm="330422371",
        mpn_norm="",
        part_numbers_norm=(),
        identity_status="OE_CONFIRMED",
    )

    rows = _frozen_catalog_cross_rows(
        run=PricingRun(id=uuid4(), workspace_id=uuid4()),
        candidates=(candidate,),
    )

    assert len(rows) == 1
    frozen = rows[0]
    assert frozen.our_oem_norm == "330422371"
    assert frozen.extracted_oem_norm == "1145200500"
    assert frozen.validation_status == "CONFIRMED"
    assert frozen.source_seller == "VERIFIED_IDENTITY_GRAPH"
    assert frozen.validation_details["evidence_kind"] == ("FROZEN_VERIFIED_IDENTITY")
    assert frozen.validation_details["fitment_cross_reference_ids"] == [
        snapshot["fitment_cross_reference_id"]
    ]
