from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from marko.services.ai_evidence_extraction import EvidenceFieldName
from marko.services.ai_evidence_shadow import open_ai_evidence_fields
from marko.services import market_collection
from metis.pricing import DimensionEvidence, EvidenceState, verified_comparison_evidence


def _observation(*, extracted_oe_norms=("1K0615301",)):
    return SimpleNamespace(extracted_oe_norms=list(extracted_oe_norms))


def test_known_deterministic_dimensions_buy_no_ai_work() -> None:
    evidence = verified_comparison_evidence(
        stable_seller_id="seller-1",
        source_record_id="listing-1",
    )

    assert open_ai_evidence_fields(_observation(), evidence) == frozenset()


def test_only_unknown_dimensions_become_targets() -> None:
    evidence = verified_comparison_evidence(
        stable_seller_id="seller-1",
        source_record_id="listing-1",
    )
    dimensions = dict(evidence.dimensions)
    dimensions["condition"] = DimensionEvidence(state=EvidenceState.UNKNOWN)
    dimensions["package_quantity"] = DimensionEvidence(state=EvidenceState.UNKNOWN)
    evidence = replace(evidence, dimensions=dimensions)

    assert open_ai_evidence_fields(_observation(), evidence) == frozenset(
        {
            EvidenceFieldName.CONDITION,
            EvidenceFieldName.PACKAGE_QUANTITY,
            EvidenceFieldName.UNIT_BASIS,
        }
    )


def test_known_oe_dimension_never_becomes_ai_target_from_empty_identity_column() -> (
    None
):
    evidence = verified_comparison_evidence(
        stable_seller_id="seller-1",
        source_record_id="listing-1",
    )

    assert EvidenceFieldName.OE_NUMBERS not in open_ai_evidence_fields(
        _observation(extracted_oe_norms=()), evidence
    )


@pytest.mark.asyncio
async def test_post_persistence_handoff_uses_transactional_outbox(monkeypatch) -> None:
    enqueue = AsyncMock()
    monkeypatch.setattr(market_collection, "enqueue_dispatch", enqueue)
    monkeypatch.setattr(
        market_collection,
        "get_settings",
        lambda: SimpleNamespace(
            pricing_ai_evidence_mode="shadow",
            pricing_ai_evidence_model="gpt-5.6-luna",
            pricing_ai_evidence_reasoning_effort="medium",
            pricing_ai_evidence_max_output_tokens=1200,
            pricing_ai_evidence_max_input_chars=20_000,
            pricing_ai_evidence_max_calls_per_position=4,
            pricing_ai_evidence_max_candidates_per_position=4,
            pricing_ai_evidence_max_concurrency=2,
            pricing_ai_evidence_api_key="test-key",
        ),
    )
    run_id = uuid4()
    item_id = uuid4()
    workspace_id = uuid4()
    session = object()

    await market_collection._enqueue_ai_evidence_shadow(
        session,
        run=SimpleNamespace(id=run_id, workspace_id=workspace_id),
        run_item=SimpleNamespace(id=item_id),
        capture=SimpleNamespace(content_sha256="a" * 64),
    )

    enqueue.assert_awaited_once()
    assert enqueue.await_args.args == (session,)
    kwargs = enqueue.await_args.kwargs
    assert kwargs["task_name"] == "marko.worker.process_ai_evidence_position"
    assert kwargs["task_args"] == [str(item_id)]
    assert kwargs["queue"] == "pricing-calculation"
