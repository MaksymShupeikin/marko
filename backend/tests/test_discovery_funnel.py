from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from marko.api.main import create_app
from marko.services.discovery_funnel import (
    aggregate_discovery_funnel,
    render_discovery_funnel_prometheus,
)
from marko.services.semantic_candidate_gate import SEMANTIC_PRICING_GATE_VERSION
from metis.pricing import CANDIDATE_GATE_ORDER


def _offer(
    *,
    status: str,
    reason: str,
    passed: tuple[str, ...],
    stopped: str | None = None,
):
    return SimpleNamespace(
        selection_status=status,
        selection_reason=reason,
        passed_gates=list(passed),
        selection_details=(
            {
                "stopped_gate": stopped,
            }
            if stopped
            else (
                {
                    "semantic_gate": {
                        "status": "PRICING_EVIDENCE",
                        "reason": "OK",
                        "gate_version": SEMANTIC_PRICING_GATE_VERSION,
                    }
                }
                if status == "PRICING_EVIDENCE"
                else {}
            )
        ),
    )


def test_discovery_funnel_exposes_conditional_pass_and_absolute_ceiling() -> None:
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        status="completed",
        reference_category="Brakes",
        prom_reported_total=10,
        retrieved_count=3,
        persisted_count=3,
        rejected_count=0,
        owned_excluded_count=0,
        unfetched_count=7,
    )
    all_gates = tuple(CANDIDATE_GATE_ORDER)
    offers = [
        _offer(
            status="PRICING_EVIDENCE",
            reason="ELIGIBLE",
            passed=all_gates,
        ),
        _offer(
            status="REJECTED",
            reason="OEM_MISMATCH",
            passed=("own_seller",),
            stopped="oem_identity",
        ),
        _offer(
            status="REJECTED",
            reason="INVALID_SOURCE",
            passed=(),
            stopped="own_seller",
        ),
    ]

    snapshot = aggregate_discovery_funnel(
        [run],
        {run_id: offers},
        generated_at=datetime(2026, 7, 30, tzinfo=UTC),
    )

    assert snapshot.total_candidates == 3
    assert snapshot.coverage["retrieval_coverage_ratio"] == "0.300000"
    assert snapshot.gates["own_seller"] == {
        "reached": 3,
        "terminal": 1,
        "survived": 2,
        "conditional_pass_rate": "0.666667",
        "conditional_terminal_rate": "0.333333",
        "survival_ceiling_ratio": "0.666667",
        "single_gate_unlock_upper_bound": 1,
        "single_gate_unlock_upper_bound_ratio": "0.333333",
        "counterfactual_ceiling_method": "SHORT_CIRCUIT_UPPER_BOUND",
    }
    assert snapshot.gates["oem_identity"]["reached"] == 2
    assert snapshot.gates["oem_identity"]["survival_ceiling_ratio"] == "0.333333"
    assert snapshot.categories[0]["category"] == "Brakes"


def test_discovery_funnel_quarantines_historical_pricing_evidence() -> None:
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        status="completed",
        reference_category="Brakes",
        prom_reported_total=1,
        retrieved_count=1,
        persisted_count=1,
        rejected_count=0,
        owned_excluded_count=0,
        unfetched_count=0,
    )
    historical = _offer(
        status="PRICING_EVIDENCE",
        reason="OK",
        passed=tuple(CANDIDATE_GATE_ORDER),
    )
    historical.selection_details = {}

    snapshot = aggregate_discovery_funnel([run], {run_id: [historical]})

    assert snapshot.status_counts == {"REFERENCE_ONLY": 1}
    assert snapshot.selection_reasons == {"DISCOVERY_ONLY_NOT_PRICING_EVIDENCE": 1}
    assert snapshot.gates["own_seller"]["single_gate_unlock_upper_bound"] == 0


def test_discovery_funnel_prometheus_is_low_cardinality() -> None:
    snapshot = aggregate_discovery_funnel([], {})

    rendered = render_discovery_funnel_prometheus(snapshot)

    assert "marko_discovery_funnel_snapshot_available 0" in rendered
    assert 'gate="oem_identity"' in rendered
    assert "marko_discovery_gate_unlock_upper_bound_ratio" in rendered
    assert "category=" not in rendered


def test_discovery_funnel_route_is_authenticated_and_documented() -> None:
    schema = create_app().openapi()

    operation = schema["paths"]["/api/v1/operations/discovery-funnel"]["get"]

    assert operation["responses"]["200"]["content"]["application/json"]
    assert operation["security"]
