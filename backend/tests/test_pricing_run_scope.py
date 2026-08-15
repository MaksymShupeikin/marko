"""Контракт ограниченного неизменяемого прогона ценообразования (Finding 1).

Проверяется без базы: чистые функции области прогона, схемы запросов/ответов,
объявленные в модели атомарные гарантии и проводка HTTP-слоя.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import Index, UniqueConstraint

from marko.api.dependencies import get_current_user
from marko.api.main import app
from marko.api.schemas.pricing import (
    PricingRunCreateRequest,
    PricingRunPreviewRequest,
)
from marko.infrastructure.db.models import (
    PricingRun,
    PricingRunItem,
    User,
    WorkspaceRole,
)
from marko.infrastructure.db.session import get_session
from marko.services.auth import AuthContext
from marko.services.catalog_identity_safety import (
    active_identity_graph_config,
    active_identity_runtime_sha256,
)
from marko.services.pricing_runs import (
    uses_frozen_start_inputs,
    ACTIVE_RUN_STATUSES,
    ACTOR_TYPE_SERVICE,
    ACTOR_TYPE_USER,
    CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
    CONFIRMATION_SOURCE_OPERATOR,
    CONFIRMATION_SOURCE_SYSTEM_REPLAY,
    EXPLICIT_ITEMS_SCOPE,
    FULL_CATALOG_SCOPE,
    IssuedPreviewContract,
    PREVIEW_CONTRACT_TTL_SECONDS,
    PREVIEW_CONTRACT_VERSION,
    PRICING_RUN_SCOPE_CONTRACT_VERSION,
    PRICING_RUN_START_PERMISSION,
    RUN_START_LANE_OPERATOR,
    RUN_START_LANE_TRUSTED,
    RunStartIdentity,
    SCOPE_MANIFEST_ADVISORY_SECTION,
    SCOPE_MANIFEST_EXECUTION_SECTION,
    OperatorRunStart,
    PreviewActor,
    PricingRunActiveScopeConflictError,
    PricingRunError,
    PricingRunIdempotencyConflictError,
    PricingRunReplayError,
    PricingRunScopeConflictError,
    PricingRunStartContractError,
    ScopeCandidate,
    TrustedRunStart,
    _catalog_item_snapshot,
    _frozen_catalog_cross_rows,
    _replayed_run_or_conflict,
    _reused_active_run_or_conflict,
    build_pricing_run_scope,
    canonical_manifest_bytes,
    canonical_start_request_hash,
    catalog_snapshot_fingerprint,
    customer_identity_available,
    customer_identity_query,
    customer_search_context,
    frozen_catalog_item_from_snapshot,
    membership_digest,
    plan_pricing_run_replay,
    policy_fingerprint,
    policy_from_dict,
    resolve_execution_catalog_item,
    run_start_identity,
    scope_input_key,
    scope_manifest_hash,
    start_snapshot_fingerprint,
)

# Актор и отпечаток запроса, которыми размечены строки в этом наборе: важны не
# сами значения, а то, что они сравниваются целиком.
_OPERATOR_ACTOR_ID = "00000000-0000-0000-0000-0000000000ff"
_REQUEST_HASH = "a" * 64


def _candidate(
    *,
    catalog_item_id: UUID | None = None,
    source_row: int = 2,
    sku: str = "SKU-1",
    oe_norm: str = "1K0121251",
    product_url: str | None = None,
    is_available: bool | None = True,
    override_id: UUID | None = None,
    override_values: dict | None = None,
    cost_record_id: UUID | None = None,
    cost_record_sequence_no: int | None = None,
    **field_overrides,
) -> ScopeCandidate:
    kwargs: dict = {
        "catalog_item_id": catalog_item_id or uuid4(),
        "source_row": source_row,
        "sku": sku,
        "oe_norm": oe_norm,
        "mpn_norm": "",
        "name": f"Позиция {sku}",
        "brand": "KEMP",
        "category": "brakes",
        "current_price": Decimal("800.00"),
        "currency": "UAH",
        "stock_status": "unknown",
        "product_url": product_url,
        "is_available": is_available,
        "stock_qty": None,
        "stock_age_days": None,
        "expected_units_sold": None,
        "units_sold_30d": None,
        "units_sold_60d": None,
        "units_sold_90d": None,
        "days_since_last_sale": None,
        "historical_monthly_units": None,
        "views_30d": None,
        "conversion_rate_proxy": None,
        "manual_priority": Decimal("1"),
        "identity_status": "OE_CONFIRMED",
        "override_id": override_id,
        "override_values": override_values,
        "cost_record_id": cost_record_id,
        "cost_record_sequence_no": cost_record_sequence_no,
    }
    kwargs.update(field_overrides)
    return ScopeCandidate(**kwargs)


def _confirmed_identity_link(
    catalog_item_id: UUID,
    *,
    link_id: UUID | None = None,
    our_oem: str = "1K0121251",
    extracted_oem: str = "7L6121253C",
    status: str = "CONFIRMED",
    anomaly: str | None = None,
) -> dict:
    return {
        "catalog_identity_link_id": str(link_id or uuid4()),
        "catalog_item_id": str(catalog_item_id),
        "our_oem_norm": our_oem,
        "extracted_oem_norm": extracted_oem,
        "extracted_raw": extracted_oem,
        "raw_context": f"reference row for {extracted_oem}",
        "extraction_method": "KEMP_REFERENCE_MAP_V2",
        "validation_status": status,
        "anomaly": anomaly,
        "corroborating_sources": ["KEMP_REFERENCE_MAP_V2"],
        "validation_details": {
            "source": "customer_reference",
            "confidence": "0.90",
            "automatic_eligible": True,
        },
        "method_version": active_identity_graph_config().method_version,
        "config_sha256": active_identity_runtime_sha256(),
    }


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        pricing_collection_worker_count=2,
        pricing_collection_item_deadline_seconds=1800,
        pricing_collection_min_interval_seconds=2.0,
    )


def test_customer_search_context_is_stable_retrieval_context_not_identity() -> None:
    candidate = _candidate(
        oe_norm="25307",
        brand="GKN-Spidan",
        name="Шрус VW Polo Golf Octavia Fabia",
    )

    assert customer_identity_query(candidate) == "25307"
    assert customer_search_context(candidate) == (
        "GKN-Spidan Шрус VW Polo Golf Octavia Fabia"
    )


def test_oe_confirmed_query_uses_original_oe_not_supplier_mpn() -> None:
    """The public market query is the vehicle OE, never KEMP's MPN."""

    candidate = _candidate(
        oe_norm="06A121012X",
        mpn_norm="77641360",
        identity_status="oe_confirmed",  # legacy casing must not change namespace
        part_numbers_norm=("TH652688J",),
    )

    assert customer_identity_query(candidate) == "06A121012X"


def test_oe_confirmed_without_public_oe_is_identity_blocked() -> None:
    """An invalid OE namespace must not fall through to a supplier MPN."""

    candidate = _candidate(
        oe_norm="77641360",
        mpn_norm="TH652688J",
        identity_status="OE_CONFIRMED",
    )

    assert customer_identity_query(candidate) == ""
    assert customer_identity_available(candidate) is False


def test_unrecognized_identity_status_does_not_promote_oe_to_confirmed_query() -> None:
    """Only an explicit graph status may promote a raw catalog OE field."""

    candidate = _candidate(
        oe_norm="06A121012X",
        mpn_norm="TH652688J",
        identity_status="legacy_unknown",
    )

    # The unresolved/legacy namespace remains a public MPN fallback; it does
    # not silently claim that the raw ``oe_norm`` is an original OE.
    assert customer_identity_query(candidate) == "TH652688J"


def test_customer_search_context_is_bounded_for_long_catalog_names() -> None:
    candidate = _candidate(name="x" * 400)

    context = customer_search_context(candidate)

    assert len(context) == 255


def _scope(candidates, **overrides):
    kwargs = {
        "workspace_id": UUID("00000000-0000-0000-0000-0000000000aa"),
        "import_batch_id": UUID("00000000-0000-0000-0000-0000000000bb"),
        "scope_mode": FULL_CATALOG_SCOPE,
        "requested_item_ids": (),
        "catalog_candidates": tuple(candidates),
        "policy_version": "pricing-v2",
        "policy_hash": "c" * 64,
        "settings": _settings(),
    }
    kwargs.update(overrides)
    return build_pricing_run_scope(**kwargs)


def _actor(**overrides) -> PreviewActor:
    kwargs = {
        "actor_id": "00000000-0000-0000-0000-0000000000ff",
        "actor_type": ACTOR_TYPE_USER,
        "workspace_role": "admin",
        "permissions": (PRICING_RUN_START_PERMISSION,),
    }
    kwargs.update(overrides)
    return PreviewActor(**kwargs)


def _start(**overrides):
    kwargs = {
        "idempotency_key": "operator-key-0001",
        "preview_token": "mrp1_" + "A" * 43,
        "actor": _actor(),
    }
    kwargs.update(overrides)
    return OperatorRunStart(**kwargs)


# --- чистые функции области прогона -----------------------------------------


def test_catalog_snapshot_hash_is_order_independent_and_sha256() -> None:
    first = _candidate(sku="SKU-A", source_row=2)
    second = _candidate(sku="SKU-B", source_row=3)

    forward = catalog_snapshot_fingerprint((first, second))
    backward = catalog_snapshot_fingerprint((second, first))

    assert forward == backward
    assert len(forward) == 64
    assert set(forward) <= set("0123456789abcdef")


def test_catalog_snapshot_hash_changes_when_the_start_time_override_changes() -> None:
    item_id = uuid4()
    before = catalog_snapshot_fingerprint((_candidate(catalog_item_id=item_id),))
    after = catalog_snapshot_fingerprint(
        (_candidate(catalog_item_id=item_id, override_id=uuid4()),)
    )

    assert before != after


def test_catalog_snapshot_hash_changes_when_the_start_time_cost_changes() -> None:
    item_id = uuid4()
    before = catalog_snapshot_fingerprint(
        (_candidate(catalog_item_id=item_id, cost_record_sequence_no=4),)
    )
    after = catalog_snapshot_fingerprint(
        (_candidate(catalog_item_id=item_id, cost_record_sequence_no=5),)
    )

    assert before != after


def test_catalog_snapshot_hash_changes_when_confirmed_identity_graph_changes() -> None:
    item_id = uuid4()
    before = catalog_snapshot_fingerprint((_candidate(catalog_item_id=item_id),))
    after = catalog_snapshot_fingerprint(
        (
            _candidate(
                catalog_item_id=item_id,
                confirmed_identity_links=(_confirmed_identity_link(item_id),),
            ),
        )
    )

    assert before != after


def test_catalog_snapshot_freezes_semantic_comparability_inputs() -> None:
    item_id = uuid4()
    frozen_candidate = _candidate(
        catalog_item_id=item_id,
        oe_raw="1K0 121 251",
        mpn_raw="KEMP-RAD-1",
        description="Радіатор 625x440, нижній патрубок праворуч",
        applicability_brands=("IVECO",),
        applicability_models=("DAILY",),
        characteristics_raw={"width_mm": 625, "height_mm": 440},
    )
    edited_live_candidate = _candidate(
        catalog_item_id=item_id,
        oe_raw="DIFFERENT-OE",
        mpn_raw="DIFFERENT-MPN",
        description="Інша деталь після старту прогона",
        applicability_brands=("FORD",),
        applicability_models=("FOCUS",),
        characteristics_raw={"width_mm": 500, "height_mm": 300},
    )

    assert catalog_snapshot_fingerprint(
        (frozen_candidate,)
    ) != catalog_snapshot_fingerprint((edited_live_candidate,))

    frozen = frozen_catalog_item_from_snapshot(_catalog_item_snapshot(frozen_candidate))
    assert frozen.oe_raw == "1K0 121 251"
    assert frozen.mpn_raw == "KEMP-RAD-1"
    assert frozen.description == "Радіатор 625x440, нижній патрубок праворуч"
    assert frozen.applicability_brands == ("IVECO",)
    assert frozen.applicability_models == ("DAILY",)
    assert frozen.characteristics_raw == {"width_mm": 625, "height_mm": 440}


@pytest.mark.parametrize(
    "semantic_change",
    [
        {"oe_raw": "CHANGED-OE"},
        {"mpn_raw": "CHANGED-MPN"},
        {"description": "Змінений опис"},
        {"applicability_brands": ("FORD",)},
        {"applicability_models": ("FOCUS",)},
        {"characteristics_raw": {"pins": 4}},
    ],
)
def test_each_semantic_comparability_input_changes_scope_hash(
    semantic_change: dict,
) -> None:
    item_id = uuid4()
    baseline = _candidate(
        catalog_item_id=item_id,
        oe_raw="BASE-OE",
        mpn_raw="BASE-MPN",
        description="Базовий опис",
        applicability_brands=("VW",),
        applicability_models=("GOLF",),
        characteristics_raw={"pins": 6},
    )
    changed_fields = {
        "oe_raw": "BASE-OE",
        "mpn_raw": "BASE-MPN",
        "description": "Базовий опис",
        "applicability_brands": ("VW",),
        "applicability_models": ("GOLF",),
        "characteristics_raw": {"pins": 6},
        **semantic_change,
    }
    changed = _candidate(catalog_item_id=item_id, **changed_fields)

    assert catalog_snapshot_fingerprint((baseline,)) != catalog_snapshot_fingerprint(
        (changed,)
    )


def test_the_frozen_snapshot_carries_the_listing_unit() -> None:
    """The seed's commercial basis is an execution input, so it must freeze.

    It did not, and the consequence was invisible: ``characteristics_raw`` rode
    the snapshot so ``condition`` arrived, while ``Одиниця_виміру`` sits in
    ``raw_row`` which the snapshot never carried.  A whole run of reviews
    compared UNKNOWN unit basis on our side and admitted nothing.
    """

    candidate = _candidate(measure_unit="шт.")
    snapshot = _catalog_item_snapshot(candidate)

    assert snapshot["measure_unit"] == "шт."
    assert frozen_catalog_item_from_snapshot(snapshot).measure_unit == "шт."


def test_a_snapshot_frozen_before_the_unit_existed_still_loads() -> None:
    snapshot = dict(_catalog_item_snapshot(_candidate()))
    snapshot.pop("measure_unit", None)

    assert frozen_catalog_item_from_snapshot(snapshot).measure_unit is None


def test_bounded_execution_does_not_read_live_semantic_catalog_edits() -> None:
    candidate = _candidate(
        description="Заморожений опис",
        applicability_brands=("VW",),
        characteristics_raw={"pins": 6},
    )
    snapshot = _catalog_item_snapshot(candidate)
    run = SimpleNamespace(scope_contract_version=PRICING_RUN_SCOPE_CONTRACT_VERSION)
    run_item = SimpleNamespace(
        id=uuid4(),
        start_snapshot=snapshot,
        start_snapshot_hash=start_snapshot_fingerprint(snapshot),
    )
    live_item = SimpleNamespace(
        description="Змінений живий опис",
        applicability_brands=["FORD"],
        characteristics_raw={"pins": 4},
    )

    resolved = resolve_execution_catalog_item(run, run_item, live_item)

    assert resolved.description == "Заморожений опис"
    assert resolved.applicability_brands == ("VW",)
    assert resolved.characteristics_raw == {"pins": 6}


def test_confirmed_identity_edges_are_frozen_once_per_run_pair() -> None:
    low = UUID("00000000-0000-0000-0000-00000000000a")
    high = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    run = PricingRun(id=uuid4(), workspace_id=uuid4())
    rows = _frozen_catalog_cross_rows(
        run=run,
        candidates=(
            _candidate(
                catalog_item_id=high,
                confirmed_identity_links=(_confirmed_identity_link(high),),
            ),
            _candidate(
                catalog_item_id=low,
                confirmed_identity_links=(_confirmed_identity_link(low),),
            ),
        ),
    )

    assert len(rows) == 1
    frozen = rows[0]
    assert frozen.catalog_item_id == low
    assert frozen.validation_status == "CONFIRMED"
    assert frozen.extraction_method == "CATALOG_IDENTITY_SNAPSHOT"
    assert len(frozen.source_evidence) == 2
    assert frozen.validation_details["evidence_kind"] == "FROZEN_CATALOG_IDENTITY"
    assert len(frozen.config_sha256) == 64


@pytest.mark.parametrize(
    ("status", "anomaly"),
    (("REVIEW", None), ("CONFIRMED", "SHARED_ARTICLE_FANOUT")),
)
def test_unapproved_identity_edge_cannot_enter_a_pricing_run(
    status: str, anomaly: str | None
) -> None:
    item_id = uuid4()
    candidate = _candidate(
        catalog_item_id=item_id,
        confirmed_identity_links=(
            _confirmed_identity_link(item_id, status=status, anomaly=anomaly),
        ),
    )

    with pytest.raises(
        PricingRunStartContractError, match="IDENTITY_GRAPH_NOT_CONFIRMED"
    ):
        _frozen_catalog_cross_rows(
            run=PricingRun(id=uuid4(), workspace_id=uuid4()),
            candidates=(candidate,),
        )


@pytest.mark.parametrize(
    "overrides",
    (
        {"method_version": "identity-graph-v1"},
        {"config_sha256": "0" * 64},
    ),
)
def test_stale_identity_edge_cannot_enter_a_pricing_run(overrides: dict) -> None:
    item_id = uuid4()
    link = _confirmed_identity_link(item_id)
    link.update(overrides)

    with pytest.raises(PricingRunStartContractError, match="IDENTITY_GRAPH_STALE"):
        _frozen_catalog_cross_rows(
            run=PricingRun(id=uuid4(), workspace_id=uuid4()),
            candidates=(
                _candidate(
                    catalog_item_id=item_id,
                    confirmed_identity_links=(link,),
                ),
            ),
        )


@pytest.mark.parametrize("confidence", (None, "invalid", "NaN", "0", "1.01"))
def test_confirmed_identity_edge_requires_explicit_valid_confidence(
    confidence: str | None,
) -> None:
    item_id = uuid4()
    link = _confirmed_identity_link(item_id)
    link["validation_details"]["confidence"] = confidence

    with pytest.raises(
        PricingRunStartContractError,
        match="IDENTITY_GRAPH_CONFIDENCE_INVALID",
    ):
        _frozen_catalog_cross_rows(
            run=PricingRun(id=uuid4(), workspace_id=uuid4()),
            candidates=(
                _candidate(
                    catalog_item_id=item_id,
                    confirmed_identity_links=(link,),
                ),
            ),
        )


def test_private_catalog_code_cannot_enter_a_pricing_run() -> None:
    item_id = uuid4()
    link = _confirmed_identity_link(item_id, extracted_oem="77643352C")

    with pytest.raises(PricingRunStartContractError, match="IDENTITY_GRAPH_CORRUPT"):
        _frozen_catalog_cross_rows(
            run=PricingRun(id=uuid4(), workspace_id=uuid4()),
            candidates=(
                _candidate(
                    catalog_item_id=item_id,
                    confirmed_identity_links=(link,),
                ),
            ),
        )


def test_full_catalog_scope_manifest_records_selection_estimates_and_hashes() -> None:
    candidates = (
        _candidate(sku="SKU-A", source_row=2, oe_norm="1K0121251"),
        _candidate(sku="SKU-B", source_row=3, oe_norm="1K0121251"),
        _candidate(sku="SKU-C", source_row=4, oe_norm="8K0615121"),
    )

    scope = _scope(candidates)

    assert scope.contract_version == PRICING_RUN_SCOPE_CONTRACT_VERSION
    assert scope.scope_mode == FULL_CATALOG_SCOPE
    assert scope.requires_full_catalog_confirmation is True
    assert len(scope.items) == 3
    assert scope.estimate.requested_items == 3
    assert scope.estimate.eligible_items == 3
    assert scope.estimate.excluded_items == 0
    # Две позиции делят один поисковый ввод, поэтому сетевых входов два.
    assert scope.estimate.unique_scrape_inputs == 2
    assert scope.estimate.duplicate_items == 1
    assert scope.estimate.network_eligible_items == 3
    assert scope.estimate.identity_blocked_items == 0
    assert scope.estimate.worst_case_duration_seconds == 1800
    manifest = scope.manifest
    execution = manifest[SCOPE_MANIFEST_EXECUTION_SECTION]
    advisory = manifest[SCOPE_MANIFEST_ADVISORY_SECTION]
    assert manifest["contract_version"] == PRICING_RUN_SCOPE_CONTRACT_VERSION
    assert manifest["scope_hash"] == scope.scope_hash
    assert execution["catalog_snapshot_hash"] == scope.catalog_snapshot_hash
    assert execution["selection"]["materialized_in"] == "pricing_run_items"
    assert execution["membership"]["count"] == 3
    assert execution["membership"]["digest"] == membership_digest(
        [item.catalog_item_id for item in scope.items]
    )
    assert advisory["estimate"]["eligible_items"] == 3
    assert advisory["exclusions"] == []


def test_scope_counts_missing_identity_without_counting_a_network_input() -> None:
    shared_url = "https://example.com/catalog/shared"
    identified = _candidate(
        sku="SKU-WITH-MPN",
        source_row=2,
        oe_norm="",
        mpn_norm="1K0121251",
        identity_status="MPN_ONLY",
        product_url=shared_url,
    )
    unidentified = _candidate(
        sku="SKU-INTERNAL-CODE",
        source_row=3,
        oe_norm="776435",
        mpn_norm="",
        identity_status="UNRESOLVED",
        identity_reason="CUSTOMER_IDENTITY_MISSING",
        product_url=shared_url,
    )

    scope = _scope((identified, unidentified))

    # Both source rows remain in the immutable run membership, but neither can
    # create a pricing network input: the first has only an MPN and the second
    # is unresolved.
    assert scope.estimate.eligible_items == 2
    assert scope.estimate.network_eligible_items == 0
    assert scope.estimate.identity_blocked_items == 2
    assert scope.estimate.unique_scrape_inputs == 0
    assert scope.estimate.duplicate_items == 0
    assert scope.manifest[SCOPE_MANIFEST_ADVISORY_SECTION]["estimate"] == {
        "requested_items": 2,
        "eligible_items": 2,
        "excluded_items": 0,
        "unique_scrape_inputs": 0,
        "duplicate_items": 0,
        "worst_case_duration_seconds": 0,
        "network_eligible_items": 0,
        "identity_blocked_items": 2,
        "oem_items": 0,
        "no_oem_items": 2,
        "kemp_linked_items": 0,
        "kemp_unlinked_items": 2,
        "kemp_ambiguous_items": 0,
        "expected_prom_queries": 2,
        "luna_item_limit": 20,
        "max_provider_calls": 20,
        "estimated_ai_cost": None,
    }


def test_explicit_scope_is_bounded_to_the_requested_items() -> None:
    wanted = uuid4()
    candidates = (
        _candidate(catalog_item_id=wanted, sku="SKU-A", source_row=2),
        _candidate(sku="SKU-B", source_row=3),
        _candidate(sku="SKU-C", source_row=4),
    )

    scope = _scope(
        candidates,
        scope_mode=EXPLICIT_ITEMS_SCOPE,
        requested_item_ids=(wanted,),
    )

    assert [item.catalog_item_id for item in scope.items] == [wanted]
    assert scope.requires_full_catalog_confirmation is False
    assert scope.estimate.requested_items == 1
    assert scope.estimate.eligible_items == 1
    execution = scope.manifest[SCOPE_MANIFEST_EXECUTION_SECTION]
    assert execution["membership"]["catalog_item_ids"] == [str(wanted)]
    assert execution["selection"]["requested_catalog_item_ids"] == [str(wanted)]
    # Полный каталог всё равно захеширован: дрейф соседних позиций виден.
    assert scope.catalog_snapshot_hash == catalog_snapshot_fingerprint(candidates)


def test_scope_hash_differs_between_full_catalog_and_the_same_items_explicitly() -> (
    None
):
    candidates = (_candidate(sku="SKU-A", source_row=2),)
    full = _scope(candidates)
    explicit = _scope(
        candidates,
        scope_mode=EXPLICIT_ITEMS_SCOPE,
        requested_item_ids=(candidates[0].catalog_item_id,),
    )

    assert full.catalog_snapshot_hash == explicit.catalog_snapshot_hash
    assert full.scope_hash != explicit.scope_hash


def test_unavailable_items_are_excluded_with_a_stable_reason_code() -> None:
    live = _candidate(sku="SKU-A", source_row=2)
    dead = _candidate(sku="SKU-B", source_row=3, is_available=False)

    scope = _scope((live, dead))

    assert [item.sku for item in scope.items] == ["SKU-A"]
    assert [exclusion.reason_code for exclusion in scope.exclusions] == [
        "ITEM_UNAVAILABLE"
    ]
    assert scope.estimate.excluded_items == 1
    advisory = scope.manifest[SCOPE_MANIFEST_ADVISORY_SECTION]
    execution = scope.manifest[SCOPE_MANIFEST_EXECUTION_SECTION]
    assert advisory["exclusion_counts"] == {"ITEM_UNAVAILABLE": 1}
    # Исключение — часть исполняемой семантики, а не только пояснение для глаз.
    assert execution["exclusions"]["counts_by_reason_code"] == {"ITEM_UNAVAILABLE": 1}
    assert execution["exclusions"]["count"] == 1


def test_unresolved_customer_code_is_not_a_scrape_identity() -> None:
    unresolved = _candidate(
        identity_status="UNRESOLVED",
        identity_reason="CUSTOMER_IDENTITY_MISSING",
        oe_norm="776435",
        mpn_norm="",
        part_numbers_norm=(),
    )
    supplied_mpn = _candidate(
        identity_status="UNRESOLVED",
        oe_norm="776436",
        mpn_norm="LM11749",
    )

    assert customer_identity_available(unresolved) is False
    assert scope_input_key(unresolved).startswith("identity-missing:")
    assert customer_identity_available(supplied_mpn) is False
    assert scope_input_key(supplied_mpn).startswith("identity-missing:")


def test_private_catalog_codes_never_become_market_queries() -> None:
    public_after_private = _candidate(
        identity_status="MPN_ONLY",
        oe_norm="4256839",
        mpn_norm="77646059",
        part_numbers_norm=("7764 6059", "A6383240604"),
    )
    private_only = _candidate(
        identity_status="MPN_ONLY",
        oe_norm="77646059",
        mpn_norm="77646059",
        part_numbers_norm=("7764 6059",),
    )

    assert customer_identity_query(public_after_private) == "A6383240604"
    assert customer_identity_available(public_after_private) is False
    assert customer_identity_query(private_only) == ""
    assert customer_identity_available(private_only) is False


def test_mpn_only_uses_full_public_part_number_when_mpn_field_is_truncated() -> None:
    # In the canonical workbook ``Код_товару`` may be a private KEMP shelf code
    # in ``oe_norm`` and the MPN column may contain only a short prefix.  The
    # full public number from the characteristics block is the safe query.
    candidate = _candidate(
        oe_norm="776414",
        mpn_norm="115",
        part_numbers_norm=("115070",),
        identity_status="MPN_ONLY",
    )

    assert customer_identity_query(candidate) == "115070"


def test_mpn_only_falls_back_to_secondary_mpn_when_primary_code_is_private() -> None:
    candidate = _candidate(
        oe_norm="77646059",
        mpn_norm="LM11749",
        identity_status="MPN_ONLY",
    )

    assert customer_identity_query(candidate) == "LM11749"


def test_mpn_only_never_promotes_unverified_oe_field_to_market_query() -> None:
    """A raw ``oe_norm`` in the MPN namespace is not original-OE evidence."""

    candidate = _candidate(
        identity_status="MPN_ONLY",
        oe_norm="93818439",
        mpn_norm="",
        part_numbers_norm=(),
    )

    assert customer_identity_query(candidate) == ""
    assert customer_identity_available(candidate) is False


def test_short_numeric_mpn_is_not_a_market_identity_without_full_number() -> None:
    """A truncated numeric prefix must not trigger a broad Prom search."""

    candidate = _candidate(
        identity_status="MPN_ONLY",
        oe_norm="776414",
        mpn_norm="115",
        part_numbers_norm=(),
    )

    assert customer_identity_query(candidate) == ""
    assert customer_identity_available(candidate) is False


def test_short_alphanumeric_mpn_remains_discovery_fallback_only() -> None:
    candidate = _candidate(
        identity_status="MPN_ONLY",
        oe_norm="776414",
        mpn_norm="A1",
        part_numbers_norm=(),
    )

    assert customer_identity_query(candidate) == "A1"
    assert customer_identity_available(candidate) is False


def test_requesting_an_unknown_item_is_a_hard_scope_error() -> None:
    candidates = (_candidate(sku="SKU-A", source_row=2),)
    stranger = uuid4()

    with pytest.raises(PricingRunError, match="SCOPE_ITEM_NOT_FOUND"):
        _scope(
            candidates,
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            requested_item_ids=(stranger,),
        )


def test_empty_resulting_scope_is_rejected() -> None:
    with pytest.raises(PricingRunError, match="SCOPE_EMPTY"):
        _scope((_candidate(is_available=False),))


# --- Finding 3: канонические байты манифеста и их хеш ------------------------


def test_scope_hash_is_the_hash_of_the_persisted_canonical_manifest() -> None:
    """Хеш области обязан быть хешем сохраняемого документа, а не отдельным отпечатком."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))

    assert scope.scope_hash == scope_manifest_hash(scope.manifest)
    assert scope.manifest["scope_hash"] == scope.scope_hash
    assert scope.manifest[SCOPE_MANIFEST_EXECUTION_SECTION]["contract_version"] == (
        PRICING_RUN_SCOPE_CONTRACT_VERSION
    )


def test_canonical_manifest_bytes_are_deterministic_and_key_order_independent() -> None:
    candidates = (
        _candidate(sku="SKU-A", source_row=2),
        _candidate(sku="SKU-B", source_row=3, oe_norm="8K0615121"),
    )
    first = _scope(candidates)
    again = _scope(candidates)

    # Один и тот же вход — те же байты и тот же хеш.
    assert canonical_manifest_bytes(
        first.manifest[SCOPE_MANIFEST_EXECUTION_SECTION]
    ) == canonical_manifest_bytes(again.manifest[SCOPE_MANIFEST_EXECUTION_SECTION])
    assert first.scope_hash == again.scope_hash

    # Перетасованный словарь — те же байты: порядок ключей не значим.
    execution = first.manifest[SCOPE_MANIFEST_EXECUTION_SECTION]
    shuffled = dict(reversed(list(execution.items())))
    assert list(shuffled) != list(execution)
    assert canonical_manifest_bytes(shuffled) == canonical_manifest_bytes(execution)
    assert scope_manifest_hash({SCOPE_MANIFEST_EXECUTION_SECTION: shuffled}) == (
        first.scope_hash
    )


def test_manifest_without_a_versioned_execution_section_has_no_hash() -> None:
    with pytest.raises(PricingRunError, match="SCOPE_MANIFEST_UNVERSIONED"):
        scope_manifest_hash({"contract_version": "pricing-run-scope-v1"})


def test_changed_policy_content_changes_the_scope_hash_under_one_version_label() -> (
    None
):
    """Хеш обязан связывать содержимое политики, а не ярлык её версии."""

    lenient = policy_from_dict({"version": "pricing-v2", "max_age_hours": 72})
    strict = policy_from_dict({"version": "pricing-v2", "max_age_hours": 24})
    assert lenient.version == strict.version

    candidates = (_candidate(sku="SKU-A", source_row=2),)
    first = _scope(candidates, policy_hash=policy_fingerprint(lenient))
    second = _scope(candidates, policy_hash=policy_fingerprint(strict))

    assert policy_fingerprint(lenient) != policy_fingerprint(strict)
    assert first.scope_hash != second.scope_hash


def test_advisory_estimates_do_not_invalidate_an_already_confirmed_scope() -> None:
    """Оценки советуют, но не исполняют: их дрейф не отменяет предпросмотр."""

    candidates = (
        _candidate(sku="SKU-A", source_row=2),
        _candidate(sku="SKU-B", source_row=3, oe_norm="8K0615121"),
    )
    fast = _scope(candidates)
    slow = _scope(
        candidates,
        settings=SimpleNamespace(
            pricing_collection_worker_count=1,
            pricing_collection_item_deadline_seconds=1800,
            pricing_collection_min_interval_seconds=2.0,
        ),
    )

    assert (
        fast.estimate.worst_case_duration_seconds
        != slow.estimate.worst_case_duration_seconds
    )
    assert (
        fast.manifest[SCOPE_MANIFEST_ADVISORY_SECTION]
        != slow.manifest[SCOPE_MANIFEST_ADVISORY_SECTION]
    )
    assert fast.scope_hash == slow.scope_hash
    assert (
        fast.manifest[SCOPE_MANIFEST_EXECUTION_SECTION]
        == slow.manifest[SCOPE_MANIFEST_EXECUTION_SECTION]
    )


def test_membership_order_is_part_of_the_scope_hash() -> None:
    first, second = uuid4(), uuid4()

    forward = membership_digest([first, second])
    backward = membership_digest([second, first])

    assert forward != backward
    assert len(forward) == 64


def test_reordered_membership_changes_the_bounded_scope_hash() -> None:
    left = _candidate(sku="SKU-A", source_row=2)
    right = _candidate(sku="SKU-B", source_row=3, oe_norm="8K0615121")
    candidates = (left, right)

    forward = _scope(
        candidates,
        scope_mode=EXPLICIT_ITEMS_SCOPE,
        requested_item_ids=(left.catalog_item_id, right.catalog_item_id),
    )
    backward = _scope(
        candidates,
        scope_mode=EXPLICIT_ITEMS_SCOPE,
        requested_item_ids=(right.catalog_item_id, left.catalog_item_id),
    )

    assert forward.scope_hash != backward.scope_hash


def test_a_changed_exclusion_changes_the_scope_hash() -> None:
    live = _candidate(sku="SKU-A", source_row=2)
    other = _candidate(sku="SKU-B", source_row=3, oe_norm="8K0615121")
    dead = _candidate(
        catalog_item_id=other.catalog_item_id,
        sku="SKU-B",
        source_row=3,
        oe_norm="8K0615121",
        is_available=False,
    )

    without = _scope((live, other))
    with_exclusion = _scope((live, dead))

    assert without.scope_hash != with_exclusion.scope_hash


# --- Finding 4: активный прогон по чужой области ------------------------------


def _identity(
    scope,
    *,
    idempotency_key=None,
    confirmation_source=CONFIRMATION_SOURCE_OPERATOR,
    actor_id=_OPERATOR_ACTOR_ID,
    actor_type=ACTOR_TYPE_USER,
    lane=RUN_START_LANE_OPERATOR,
    request_hash=_REQUEST_HASH,
):
    """Личность старта под область ``scope`` — ровно та, что попала бы в строку."""

    return RunStartIdentity(
        workspace_id=scope.workspace_id,
        lane=lane,
        actor_id=actor_id,
        actor_type=actor_type,
        confirmation_source=confirmation_source,
        canonical_start_request_hash=request_hash,
        scope_hash=scope.scope_hash,
        policy_snapshot_hash=scope.policy_hash,
        catalog_snapshot_hash=scope.catalog_snapshot_hash,
        idempotency_key=idempotency_key,
    )


def _persisted_run(
    scope,
    *,
    idempotency_key=None,
    status="running",
    confirmation_source=CONFIRMATION_SOURCE_OPERATOR,
    actor_id=_OPERATOR_ACTOR_ID,
    actor_type=ACTOR_TYPE_USER,
    lane=RUN_START_LANE_OPERATOR,
    request_hash=_REQUEST_HASH,
):
    return PricingRun(
        id=uuid4(),
        workspace_id=scope.workspace_id,
        import_batch_id=scope.import_batch_id,
        status=status,
        policy_version=scope.policy_version,
        policy_config={},
        policy_snapshot_hash=scope.policy_hash,
        parser_version="p",
        scope_contract_version=PRICING_RUN_SCOPE_CONTRACT_VERSION,
        scope_mode=scope.scope_mode,
        scope_confirmation_source=confirmation_source,
        full_catalog_confirmed=scope.requires_full_catalog_confirmation,
        catalog_snapshot_hash=scope.catalog_snapshot_hash,
        scope_hash=scope.scope_hash,
        scope_manifest=scope.manifest,
        idempotency_key=idempotency_key,
        scope_frozen_at=datetime.now(UTC),
        canonical_start_request_hash=request_hash,
        start_lane=lane,
        start_actor_id=actor_id,
        start_actor_type=actor_type,
    )


def test_an_active_run_is_reused_only_for_the_same_request_identity() -> None:
    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    existing = _persisted_run(scope, idempotency_key="operator-key-0001")

    reused = _reused_active_run_or_conflict(
        existing, identity=_identity(scope, idempotency_key="operator-key-0001")
    )

    assert reused is existing


def test_an_active_run_with_a_foreign_scope_is_a_typed_conflict() -> None:
    """Совпадение импорта — не совпадение запроса: чужой прогон возвращать нельзя."""

    wanted = _candidate(sku="SKU-A", source_row=2)
    mine = _scope(
        (wanted, _candidate(sku="SKU-B", source_row=3, oe_norm="8K0615121")),
        scope_mode=EXPLICIT_ITEMS_SCOPE,
        requested_item_ids=(wanted.catalog_item_id,),
    )
    theirs = _scope(
        (wanted, _candidate(sku="SKU-B", source_row=3, oe_norm="8K0615121")),
    )
    foreign = _persisted_run(theirs)

    with pytest.raises(
        PricingRunActiveScopeConflictError, match="ACTIVE_RUN_SCOPE_CONFLICT"
    ):
        _reused_active_run_or_conflict(foreign, identity=_identity(mine))


def test_an_active_run_with_a_foreign_idempotency_key_is_a_typed_conflict() -> None:
    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    existing = _persisted_run(scope, idempotency_key="someone-else-0001")

    with pytest.raises(
        PricingRunActiveScopeConflictError, match="ACTIVE_RUN_SCOPE_CONFLICT"
    ):
        _reused_active_run_or_conflict(
            existing, identity=_identity(scope, idempotency_key="operator-key-0001")
        )


def test_an_unkeyed_trusted_start_cannot_adopt_a_keyed_operator_run() -> None:
    """F1: доверенная полоса не вправе получить активный прогон оператора.

    Повтор ревью: безключевой ``TrustedRunStart`` возвращал keyed-прогон
    оператора, потому что «ключ не назван» проверялось только в одну сторону, а
    источник подтверждения не сравнивался вовсе.  Совпала область — совпал, мол,
    и запрос.  Это два разных утверждения: одно про то, ЧТО исполняется, другое
    про то, КТО и по какому праву это начал.
    """

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    operator_run = _persisted_run(
        scope,
        idempotency_key="operator-key-0001",
        confirmation_source=CONFIRMATION_SOURCE_OPERATOR,
    )

    with pytest.raises(
        PricingRunActiveScopeConflictError, match="ACTIVE_RUN_SCOPE_CONFLICT"
    ):
        _reused_active_run_or_conflict(
            operator_run,
            identity=_identity(
                scope,
                confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
                lane=RUN_START_LANE_TRUSTED,
                actor_id=f"system:{CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY}",
                actor_type=ACTOR_TYPE_SERVICE,
            ),
        )


def test_an_operator_start_cannot_adopt_an_active_trusted_run() -> None:
    """И обратно: оператор не получает системный повтор как свой прогон."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    replay_run = _persisted_run(
        scope,
        idempotency_key="dead-letter-replay:1",
        confirmation_source=CONFIRMATION_SOURCE_SYSTEM_REPLAY,
        lane=RUN_START_LANE_TRUSTED,
        actor_id=f"system:{CONFIRMATION_SOURCE_SYSTEM_REPLAY}",
        actor_type=ACTOR_TYPE_SERVICE,
    )

    with pytest.raises(
        PricingRunActiveScopeConflictError, match="ACTIVE_RUN_SCOPE_CONFLICT"
    ):
        _reused_active_run_or_conflict(
            replay_run,
            identity=_identity(scope, idempotency_key="dead-letter-replay:1"),
        )


def test_the_same_lane_and_the_same_request_still_reuse_one_run() -> None:
    """Разделение полос не должно ломать законный повтор одной попытки."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    existing = _persisted_run(
        scope,
        idempotency_key=None,
        confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
        lane=RUN_START_LANE_TRUSTED,
        actor_id=f"system:{CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY}",
        actor_type=ACTOR_TYPE_SERVICE,
    )

    reused = _reused_active_run_or_conflict(
        existing,
        identity=_identity(
            scope,
            confirmation_source=CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY,
            lane=RUN_START_LANE_TRUSTED,
            actor_id=f"system:{CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY}",
            actor_type=ACTOR_TYPE_SERVICE,
        ),
    )

    assert reused is existing


# --- F1 (2026-08-02): личность старта, а не только область --------------------


def test_the_idempotent_winner_needs_the_same_canonical_request() -> None:
    """Ровно репро: одна область, два канонически РАЗНЫХ тела старта.

    ``policy: null`` и ``policy: {"version": "pricing-v2"}`` нормализуются в одну
    политику и одну область, но это два разных утверждения оператора.  Прежняя
    проверка сравнивала только хеш области и потому отвечала на второе первым.
    """

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    existing = _persisted_run(scope, idempotency_key="same-key-0001")

    with pytest.raises(
        PricingRunIdempotencyConflictError, match="canonical_start_request_hash"
    ):
        _replayed_run_or_conflict(
            existing,
            identity=_identity(
                scope, idempotency_key="same-key-0001", request_hash="b" * 64
            ),
        )


def test_the_idempotent_winner_is_never_handed_to_another_actor() -> None:
    """Второй актор со своим законным контрактом не получает чужой прогон."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    existing = _persisted_run(scope, idempotency_key="shared-key-0001")

    with pytest.raises(PricingRunIdempotencyConflictError) as failure:
        _replayed_run_or_conflict(
            existing,
            identity=_identity(
                scope,
                idempotency_key="shared-key-0001",
                actor_id="00000000-0000-0000-0000-0000000000bb",
            ),
        )

    message = str(failure.value)
    assert "IDEMPOTENCY_KEY_REUSED" in message
    # Отказ не должен становиться каналом утечки: ни идентификатора чужого
    # прогона, ни его области, ни его актора в сообщении нет.
    assert str(existing.id) not in message
    assert existing.scope_hash not in message
    assert _OPERATOR_ACTOR_ID not in message


def test_the_idempotent_winner_is_never_handed_to_another_lane() -> None:
    """Доверенная полоса не открывает ключ, выданный оператору."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    existing = _persisted_run(scope, idempotency_key="operator-key-0001")

    with pytest.raises(PricingRunIdempotencyConflictError) as failure:
        _replayed_run_or_conflict(
            existing,
            identity=_identity(
                scope,
                idempotency_key="operator-key-0001",
                confirmation_source=CONFIRMATION_SOURCE_SYSTEM_REPLAY,
                lane=RUN_START_LANE_TRUSTED,
                actor_id=f"system:{CONFIRMATION_SOURCE_SYSTEM_REPLAY}",
                actor_type=ACTOR_TYPE_SERVICE,
            ),
        )

    assert str(existing.id) not in str(failure.value)


def test_the_exact_retry_of_the_same_attempt_still_returns_the_same_run() -> None:
    """Строгая привязка не должна ломать законный повтор одной и той же попытки."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    existing = _persisted_run(scope, idempotency_key="operator-key-0001")

    replayed = _replayed_run_or_conflict(
        existing, identity=_identity(scope, idempotency_key="operator-key-0001")
    )

    assert replayed is existing


def test_a_run_without_a_bound_start_identity_cannot_win_a_replay() -> None:
    """Строка до миграции 0038 личности не несёт — и повтором по ней быть не может.

    Отказ здесь и есть правильный ответ: подставить ей личность нового запроса
    значило бы объявить, что она этот запрос и исполняла.
    """

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    legacy = _persisted_run(scope, idempotency_key="operator-key-0001")
    legacy.canonical_start_request_hash = None
    legacy.start_lane = None
    legacy.start_actor_id = None
    legacy.start_actor_type = None

    with pytest.raises(PricingRunIdempotencyConflictError):
        _replayed_run_or_conflict(
            existing := legacy,
            identity=_identity(scope, idempotency_key="operator-key-0001"),
        )
    assert existing is legacy


def test_a_tampered_manifest_cannot_pass_as_the_same_request() -> None:
    """Хеш области сравнивается и с колонкой, и с пересчитанным манифестом.

    Совпадение одной колонки перестаёт что-либо означать, как только манифест
    можно подменить отдельно, поэтому сверяются оба утверждения.
    """

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    existing = _persisted_run(scope, idempotency_key="operator-key-0001")
    smuggled = dict(existing.scope_manifest)
    smuggled["execution"] = {**smuggled["execution"], "scope_mode": "EXPLICIT_ITEMS"}
    existing.scope_manifest = smuggled

    with pytest.raises(PricingRunIdempotencyConflictError, match="scope_manifest_hash"):
        _replayed_run_or_conflict(
            existing, identity=_identity(scope, idempotency_key="operator-key-0001")
        )


def test_the_trusted_lane_names_its_service_actor_and_not_a_person() -> None:
    """Полоса без человека не остаётся безымянной: носителем власти зовётся служба."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    identity = run_start_identity(
        workspace_id=scope.workspace_id,
        import_batch_id=scope.import_batch_id,
        scope_mode=scope.scope_mode,
        catalog_item_ids=None,
        policy_config=None,
        start=TrustedRunStart(
            confirmation_source=CONFIRMATION_SOURCE_SYSTEM_REPLAY,
            reason="dead letter replay",
            full_catalog_confirmed=True,
        ),
        scope_hash=scope.scope_hash,
        policy_snapshot_hash=scope.policy_hash,
        catalog_snapshot_hash=scope.catalog_snapshot_hash,
        confirmation_source=CONFIRMATION_SOURCE_SYSTEM_REPLAY,
    )

    assert identity.lane == RUN_START_LANE_TRUSTED
    assert identity.actor_type == ACTOR_TYPE_SERVICE
    assert identity.actor_id == f"system:{CONFIRMATION_SOURCE_SYSTEM_REPLAY}"
    assert len(identity.canonical_start_request_hash) == 64


def test_two_trusted_sources_are_two_different_start_identities() -> None:
    """Системный повтор и подстановка фикстур — разные основания под одной полосой."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))

    def _for(source):
        return run_start_identity(
            workspace_id=scope.workspace_id,
            import_batch_id=scope.import_batch_id,
            scope_mode=scope.scope_mode,
            catalog_item_ids=None,
            policy_config=None,
            start=TrustedRunStart(
                confirmation_source=source,
                reason="reason",
                full_catalog_confirmed=True,
            ),
            scope_hash=scope.scope_hash,
            policy_snapshot_hash=scope.policy_hash,
            catalog_snapshot_hash=scope.catalog_snapshot_hash,
            confirmation_source=source,
        )

    replay = _for(CONFIRMATION_SOURCE_SYSTEM_REPLAY)
    fixture = _for(CONFIRMATION_SOURCE_E2E_FIXTURE_REPLAY)

    assert replay.actor_id != fixture.actor_id
    assert replay.confirmation_source != fixture.confirmation_source


def test_a_normalized_policy_body_is_a_different_canonical_request() -> None:
    """Именно эта эквивалентность и ломала прежнюю проверку — она обязана быть видна."""

    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    shared = {
        "workspace_id": scope.workspace_id,
        "import_batch_id": scope.import_batch_id,
        "scope_mode": scope.scope_mode,
        "catalog_item_ids": None,
        "confirm_full_catalog": True,
    }

    bare = canonical_start_request_hash(policy_config=None, **shared)
    named = canonical_start_request_hash(
        policy_config={"version": "pricing-v2"}, **shared
    )

    assert bare != named
    # И обе дают ОДНУ И ТУ ЖЕ политику, то есть одну и ту же область.
    assert policy_from_dict(None) == policy_from_dict({"version": "pricing-v2"})


# --- Finding 2: системный повтор наследует область ---------------------------


def test_replay_of_a_bounded_run_keeps_its_ordered_membership() -> None:
    """Упавшая позиция ограниченного прогона не повторяется как весь каталог."""

    first = _candidate(sku="SKU-A", source_row=2)
    second = _candidate(sku="SKU-B", source_row=3, oe_norm="8K0615121")
    scope = _scope(
        (first, second),
        scope_mode=EXPLICIT_ITEMS_SCOPE,
        requested_item_ids=(first.catalog_item_id, second.catalog_item_id),
    )
    failed = _persisted_run(scope, status="failed")

    plan = plan_pricing_run_replay(
        failed, reason="dead-letter replay", idempotency_key="dead-letter-replay:1"
    )

    assert plan.scope_mode == EXPLICIT_ITEMS_SCOPE
    assert plan.scope_mode != FULL_CATALOG_SCOPE
    assert list(plan.catalog_item_ids) == [item.catalog_item_id for item in scope.items]
    assert plan.start.confirmation_source == CONFIRMATION_SOURCE_SYSTEM_REPLAY
    assert plan.start.expected_scope_hash == scope.scope_hash
    assert plan.start.expected_catalog_snapshot_hash == scope.catalog_snapshot_hash
    assert plan.start.idempotency_key == "dead-letter-replay:1"
    assert plan.start.source_run_id == failed.id


def test_replay_of_a_full_catalog_run_stays_a_full_catalog_run() -> None:
    scope = _scope((_candidate(sku="SKU-A", source_row=2),))
    failed = _persisted_run(scope, status="failed")

    plan = plan_pricing_run_replay(
        failed, reason="dead-letter replay", idempotency_key="dead-letter-replay:2"
    )

    assert plan.scope_mode == FULL_CATALOG_SCOPE
    assert plan.catalog_item_ids == ()
    assert plan.start.full_catalog_confirmed is True


def test_a_run_without_a_versioned_manifest_is_never_replayed() -> None:
    """Невосстановимая область — отказ, а не молчаливое расширение до каталога."""

    legacy = PricingRun(
        id=uuid4(),
        workspace_id=uuid4(),
        import_batch_id=uuid4(),
        status="failed",
        policy_version="pricing-v2",
        policy_config={},
        parser_version="p",
        scope_contract_version=None,
        scope_mode=FULL_CATALOG_SCOPE,
        scope_confirmation_source="LEGACY_UNBOUNDED",
        full_catalog_confirmed=False,
        catalog_snapshot_hash=None,
        scope_hash=None,
        scope_manifest={},
        idempotency_key=None,
        scope_frozen_at=None,
    )

    with pytest.raises(PricingRunReplayError, match="REPLAY_SCOPE_UNRECOVERABLE"):
        plan_pricing_run_replay(
            legacy, reason="dead-letter replay", idempotency_key="dead-letter-replay:3"
        )


def test_a_tampered_membership_is_never_replayed() -> None:
    first = _candidate(sku="SKU-A", source_row=2)
    second = _candidate(sku="SKU-B", source_row=3, oe_norm="8K0615121")
    scope = _scope(
        (first, second),
        scope_mode=EXPLICIT_ITEMS_SCOPE,
        requested_item_ids=(first.catalog_item_id, second.catalog_item_id),
    )
    failed = _persisted_run(scope, status="failed")
    manifest = {
        key: (dict(value) if isinstance(value, dict) else value)
        for key, value in failed.scope_manifest.items()
    }
    execution = dict(manifest[SCOPE_MANIFEST_EXECUTION_SECTION])
    execution["membership"] = {
        **execution["membership"],
        "catalog_item_ids": [str(uuid4())],
    }
    manifest[SCOPE_MANIFEST_EXECUTION_SECTION] = execution
    failed.scope_manifest = manifest

    with pytest.raises(PricingRunReplayError, match="REPLAY_SCOPE_UNRECOVERABLE"):
        plan_pricing_run_replay(
            failed, reason="dead-letter replay", idempotency_key="dead-letter-replay:4"
        )


# --- контракты запроса/ответа -----------------------------------------------


def test_preview_request_requires_items_for_explicit_scope() -> None:
    with pytest.raises(ValidationError, match="EXPLICIT_ITEMS"):
        PricingRunPreviewRequest(
            import_batch_id=uuid4(), scope_mode=EXPLICIT_ITEMS_SCOPE
        )


def test_preview_request_rejects_items_for_full_catalog_scope() -> None:
    with pytest.raises(ValidationError, match="FULL_CATALOG"):
        PricingRunPreviewRequest(
            import_batch_id=uuid4(),
            scope_mode=FULL_CATALOG_SCOPE,
            catalog_item_ids=[uuid4()],
        )


def test_preview_request_rejects_repeated_items() -> None:
    duplicate = uuid4()
    with pytest.raises(ValidationError, match="repeat"):
        PricingRunPreviewRequest(
            import_batch_id=uuid4(),
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            catalog_item_ids=[duplicate, duplicate],
        )


PREVIEW_TOKEN = "mrp1_" + "A" * 43


def _create_request(**overrides):
    payload = {
        "import_batch_id": uuid4(),
        "scope_mode": FULL_CATALOG_SCOPE,
        "confirm_full_catalog": True,
        "idempotency_key": "operator-key-0001",
        "preview_token": PREVIEW_TOKEN,
    }
    payload.update(overrides)
    return PricingRunCreateRequest(**payload)


def test_full_catalog_run_request_requires_an_explicit_confirmation() -> None:
    with pytest.raises(ValidationError, match="confirm_full_catalog"):
        _create_request(confirm_full_catalog=False)

    confirmed = _create_request()
    assert confirmed.confirm_full_catalog is True


def test_explicit_scope_run_request_rejects_a_full_catalog_confirmation() -> None:
    with pytest.raises(ValidationError, match="only to FULL_CATALOG"):
        _create_request(
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            catalog_item_ids=[uuid4()],
            confirm_full_catalog=True,
        )


def test_run_request_rejects_unknown_fields_and_malformed_tokens() -> None:
    with pytest.raises(ValidationError):
        _create_request(unexpected="x")
    with pytest.raises(ValidationError):
        _create_request(preview_token="abc")
    with pytest.raises(ValidationError):
        _create_request(idempotency_key="short")
    # Хеши больше не являются частью старта: сервер сам их публикует, и клиент
    # присылал их обратно как «подтверждение».
    with pytest.raises(ValidationError):
        _create_request(expected_scope_hash="a" * 64)


# --- Finding 1: старт без контракта предпросмотра ----------------------------


@pytest.mark.parametrize("missing", ["idempotency_key", "preview_token"])
def test_run_request_refuses_a_start_without_the_server_issued_contract(
    missing: str,
) -> None:
    """Отсутствующее поле — это отсутствие контракта, а не разрешение стартовать."""

    payload = {
        "import_batch_id": uuid4(),
        "scope_mode": FULL_CATALOG_SCOPE,
        "confirm_full_catalog": True,
        "idempotency_key": "operator-key-0001",
        "preview_token": PREVIEW_TOKEN,
    }
    payload.pop(missing)

    with pytest.raises(ValidationError, match=missing):
        PricingRunCreateRequest(**payload)


def test_run_request_refuses_a_blank_key_and_a_forged_token() -> None:
    with pytest.raises(ValidationError, match="blank"):
        _create_request(idempotency_key="        ")
    # Токен обязан быть выданного вида: «похоже на токен» — не контракт.
    with pytest.raises(ValidationError):
        _create_request(preview_token="z" * 48)
    with pytest.raises(ValidationError):
        _create_request(preview_token="mrp1_" + "A" * 10)


def test_operator_start_contract_rejects_an_empty_or_malformed_contract() -> None:
    """Тот же отказ на уровне службы: HTTP-схема — не единственная защита."""

    with pytest.raises(PricingRunStartContractError, match="idempotency_key"):
        _start(idempotency_key="   ")
    with pytest.raises(PricingRunStartContractError, match="preview token"):
        _start(preview_token="not-a-token")
    with pytest.raises(PricingRunStartContractError, match="preview token"):
        _start(preview_token="")
    with pytest.raises(PricingRunStartContractError, match="actor"):
        _start(actor=None)
    with pytest.raises(PricingRunStartContractError, match="actor"):
        PreviewActor(
            actor_id="  ",
            actor_type=ACTOR_TYPE_USER,
            workspace_role="admin",
            permissions=(PRICING_RUN_START_PERMISSION,),
        )


def test_a_pricing_run_cannot_be_started_without_a_typed_start_contract() -> None:
    """``start`` — обязательный аргумент, а не необязательная опция."""

    import inspect

    from marko.services.pricing_runs import create_pricing_run

    parameter = inspect.signature(create_pricing_run).parameters["start"]
    assert parameter.default is inspect.Parameter.empty
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    # Старые «поля не передали» больше не существуют как способ старта.
    for retired in (
        "idempotency_key",
        "expected_scope_hash",
        "expected_catalog_snapshot_hash",
        "confirm_full_catalog",
        "preview_token",
    ):
        assert retired not in inspect.signature(create_pricing_run).parameters


def test_a_trusted_start_must_name_itself() -> None:
    with pytest.raises(PricingRunStartContractError, match="confirmation source"):
        TrustedRunStart(confirmation_source=CONFIRMATION_SOURCE_OPERATOR, reason="x")
    with pytest.raises(PricingRunStartContractError, match="reason"):
        TrustedRunStart(
            confirmation_source=CONFIRMATION_SOURCE_SYSTEM_REPLAY, reason="  "
        )


# --- модель и миграция ------------------------------------------------------


def test_pricing_run_declares_an_atomic_active_run_guard() -> None:
    """Дедупликация активного прогона обязана быть в БД, а не в SELECT'е."""

    indexes = {index.name: index for index in PricingRun.__table__.indexes}
    guard = indexes.get("uq_pricing_run_active_import_batch")

    assert guard is not None, sorted(indexes)
    assert guard.unique is True
    assert [column.name for column in guard.columns] == [
        "workspace_id",
        "import_batch_id",
    ]
    predicate = str(guard.dialect_options["postgresql"]["where"])
    for active_status in ACTIVE_RUN_STATUSES:
        assert f"'{active_status}'" in predicate
    for terminal_status in ("completed", "partial", "failed", "cancelled"):
        assert f"'{terminal_status}'" not in predicate


def test_pricing_run_declares_a_client_idempotency_constraint() -> None:
    unique = {
        constraint.name
        for constraint in PricingRun.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "uq_pricing_run_workspace_idempotency" in unique


def test_pricing_run_persists_the_scope_contract_columns() -> None:
    columns = PricingRun.__table__.columns

    for name in (
        "scope_contract_version",
        "scope_mode",
        "scope_confirmation_source",
        "full_catalog_confirmed",
        "catalog_snapshot_hash",
        "scope_hash",
        "scope_manifest",
        "idempotency_key",
        "scope_frozen_at",
    ):
        assert name in columns, name
    assert columns["catalog_snapshot_hash"].type.length == 64
    assert columns["scope_hash"].type.length == 64


def test_pricing_run_item_persists_the_start_time_replay_inputs() -> None:
    columns = PricingRunItem.__table__.columns

    for name in ("catalog_item_override_id", "cost_record_id", "start_snapshot"):
        assert name in columns, name
    override_targets = {
        foreign_key.target_fullname
        for foreign_key in columns["catalog_item_override_id"].foreign_keys
    }
    cost_targets = {
        foreign_key.target_fullname
        for foreign_key in columns["cost_record_id"].foreign_keys
    }
    assert override_targets == {"catalog_item_overrides.id"}
    assert cost_targets == {"catalog_item_cost_records.id"}


def test_scope_indexes_are_not_silently_dropped_by_a_partial_index_helper() -> None:
    """Индекс-страж обязан быть привязан к таблице, а не висеть отдельно."""

    assert any(
        isinstance(index, Index)
        and index.name == "uq_pricing_run_active_import_batch"
        and index.table is PricingRun.__table__
        for index in PricingRun.__table__.indexes
    )


# --- HTTP-слой ---------------------------------------------------------------


def _admin_override(workspace_id: UUID):
    user = User(id=uuid4(), email="admin@example.com", is_active=True)

    async def current_user_override() -> AuthContext:
        return AuthContext(
            user=user,
            workspace_id=workspace_id,
            workspace_role=WorkspaceRole.owner,
        )

    return current_user_override


class _NoopSession:
    """Сессия-заглушка: маршрут коммитит выданный контракт, база здесь не нужна."""

    async def commit(self) -> None:
        return None


async def _noop_session():
    yield _NoopSession()


def test_openapi_exposes_the_bounded_pricing_run_contract() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    schemas = schema["components"]["schemas"]

    assert "/api/v1/pricing/runs/preview" in paths
    create = schemas["PricingRunCreateRequest"]["properties"]
    assert {
        "scope_mode",
        "catalog_item_ids",
        "confirm_full_catalog",
        "idempotency_key",
        "preview_token",
    } <= set(create)
    # Контракт предпросмотра объявлен обязательным и в самой схеме, а не только
    # в коде: клиент видит отказ раньше, чем сервер начнёт исполнять область.
    assert {
        "idempotency_key",
        "preview_token",
    } <= set(schemas["PricingRunCreateRequest"]["required"])
    # Хеши, которые сервер публикует сам, больше не являются входом старта:
    # «подтверждение» из возвращённого себе же значения контрактом не было.
    assert "expected_scope_hash" not in create
    assert "expected_catalog_snapshot_hash" not in create
    preview = schemas["PricingRunPreviewResponse"]["properties"]
    assert {
        "scope_contract_version",
        "scope_mode",
        "catalog_snapshot_hash",
        "scope_hash",
        "policy_snapshot_hash",
        "requires_full_catalog_confirmation",
        "estimate",
        "exclusions",
        "scope_manifest",
        "preview_token",
        "preview_expires_at",
        "preview_contract_version",
        "preview_request_hash",
    } <= set(preview)
    run = schemas["PricingRunResponse"]["properties"]
    assert {
        "scope_contract_version",
        "scope_mode",
        "scope_hash",
        "catalog_snapshot_hash",
        "scope_manifest",
        "full_catalog_confirmed",
        "scope_confirmation_source",
        "idempotency_key",
        "scope_frozen_at",
    } <= set(run)


@pytest.mark.asyncio
async def test_preview_endpoint_returns_the_scope_without_creating_a_run(
    monkeypatch,
) -> None:
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    seen: dict[str, object] = {}

    async def fake_preview(session, **kwargs):
        seen.update(kwargs)
        scope = _scope(
            (_candidate(catalog_item_id=item_id, sku="SKU-A", source_row=2),),
            workspace_id=workspace_id,
            import_batch_id=batch_id,
        )
        issued_at = datetime.now(UTC)
        return scope, IssuedPreviewContract(
            token=PREVIEW_TOKEN,
            contract_id=uuid4(),
            contract_version=PREVIEW_CONTRACT_VERSION,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=PREVIEW_CONTRACT_TTL_SECONDS),
            request_hash="d" * 64,
            scope_hash=scope.scope_hash,
            catalog_snapshot_hash=scope.catalog_snapshot_hash,
            policy_snapshot_hash=scope.policy_hash,
        )

    monkeypatch.setattr(
        "marko.api.routers.v1.pricing.preview_pricing_run_for_operator", fake_preview
    )
    app.dependency_overrides[get_current_user] = _admin_override(workspace_id)
    app.dependency_overrides[get_session] = _noop_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/pricing/runs/preview",
                json={
                    "import_batch_id": str(batch_id),
                    "scope_mode": FULL_CATALOG_SCOPE,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope_contract_version"] == PRICING_RUN_SCOPE_CONTRACT_VERSION
    assert body["requires_full_catalog_confirmation"] is True
    assert body["estimate"]["eligible_items"] == 1
    assert len(body["scope_hash"]) == 64
    # Ответ предпросмотра несёт настоящий контракт: непрозрачный токен и срок.
    assert body["preview_token"] == PREVIEW_TOKEN
    assert body["preview_contract_version"] == PREVIEW_CONTRACT_VERSION
    assert body["preview_expires_at"]
    assert seen["scope_mode"] == FULL_CATALOG_SCOPE
    assert seen["workspace_id"] == workspace_id
    # Контракт запоминает актора, его роль и права — без них он не привязан ни
    # к кому и предъявить его может кто угодно.
    actor = seen["actor"]
    assert isinstance(actor, PreviewActor)
    assert actor.actor_type == ACTOR_TYPE_USER
    assert actor.workspace_role == WorkspaceRole.owner.value
    assert PRICING_RUN_START_PERMISSION in actor.canonical_permissions


@pytest.mark.asyncio
async def test_run_endpoint_forwards_the_bounded_scope_and_idempotency_key(
    monkeypatch,
) -> None:
    workspace_id = uuid4()
    batch_id = uuid4()
    item_id = uuid4()
    seen: dict[str, object] = {}

    async def fake_create(session, **kwargs):
        seen.update(kwargs)
        return PricingRun(
            id=uuid4(),
            workspace_id=workspace_id,
            import_batch_id=batch_id,
            status="queued",
            policy_version="pricing-v2",
            policy_config={},
            parser_version="p",
            classifier_version="c",
            coefficient_model="shrinkage",
            coefficient_version=None,
            calibration_dataset_hash=None,
            calibration_accounting={},
            calibration_started_at=None,
            calibration_completed_at=None,
            total_items=1,
            completed_items=0,
            failed_items=0,
            manual_review_items=0,
            cancel_requested=False,
            finalizer_task_id=None,
            error=None,
            started_at=None,
            finished_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            scope_contract_version=PRICING_RUN_SCOPE_CONTRACT_VERSION,
            scope_mode=EXPLICIT_ITEMS_SCOPE,
            scope_confirmation_source="OPERATOR",
            full_catalog_confirmed=False,
            catalog_snapshot_hash="a" * 64,
            scope_hash="b" * 64,
            scope_manifest={"contract_version": PRICING_RUN_SCOPE_CONTRACT_VERSION},
            idempotency_key="client-key-0001",
            scope_frozen_at=datetime.now(UTC),
        )

    monkeypatch.setattr("marko.api.routers.v1.pricing.create_pricing_run", fake_create)
    app.dependency_overrides[get_current_user] = _admin_override(workspace_id)
    app.dependency_overrides[get_session] = _noop_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/pricing/runs",
                json={
                    "import_batch_id": str(batch_id),
                    "scope_mode": EXPLICIT_ITEMS_SCOPE,
                    "catalog_item_ids": [str(item_id)],
                    "idempotency_key": "client-key-0001",
                    "preview_token": PREVIEW_TOKEN,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["scope_mode"] == EXPLICIT_ITEMS_SCOPE
    assert body["scope_hash"] == "b" * 64
    assert body["idempotency_key"] == "client-key-0001"
    assert seen["catalog_item_ids"] == [item_id]
    start = seen["start"]
    assert isinstance(start, OperatorRunStart)
    assert start.idempotency_key == "client-key-0001"
    assert start.preview_token == PREVIEW_TOKEN
    assert start.actor.workspace_role == WorkspaceRole.owner.value
    assert start.confirm_full_catalog is False


@pytest.mark.asyncio
async def test_run_endpoint_refuses_a_start_without_a_preview_contract(
    monkeypatch,
) -> None:
    """API-старт без выданного сервером контракта не доходит до службы."""

    workspace_id = uuid4()
    calls: list[dict[str, object]] = []

    async def fake_create(session, **kwargs):
        calls.append(kwargs)
        raise AssertionError("служба не должна быть вызвана без контракта")

    monkeypatch.setattr("marko.api.routers.v1.pricing.create_pricing_run", fake_create)
    app.dependency_overrides[get_current_user] = _admin_override(workspace_id)
    app.dependency_overrides[get_session] = _noop_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/pricing/runs",
                json={
                    "import_batch_id": str(uuid4()),
                    "scope_mode": FULL_CATALOG_SCOPE,
                    "confirm_full_catalog": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422, response.text
    missing = {tuple(error["loc"])[-1] for error in response.json()["detail"]}
    assert {"idempotency_key", "preview_token"} <= missing
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (PricingRunScopeConflictError("CATALOG_SNAPSHOT_CHANGED"), 409),
        (PricingRunIdempotencyConflictError("IDEMPOTENCY_KEY_REUSED"), 409),
        (PricingRunActiveScopeConflictError("ACTIVE_RUN_SCOPE_CONFLICT"), 409),
        (PricingRunStartContractError("PREVIEW_CONTRACT_EXPIRED"), 403),
        (PricingRunStartContractError("PREVIEW_CONTRACT_UNKNOWN"), 403),
        (PricingRunStartContractError("PREVIEW_CONTRACT_ACTOR_MISMATCH"), 403),
        (PricingRunError("SCOPE_EMPTY"), 422),
    ],
)
async def test_run_endpoint_maps_scope_failures_to_explicit_status_codes(
    monkeypatch, error, expected_status
) -> None:
    workspace_id = uuid4()

    async def fake_create(session, **kwargs):
        raise error

    monkeypatch.setattr("marko.api.routers.v1.pricing.create_pricing_run", fake_create)
    app.dependency_overrides[get_current_user] = _admin_override(workspace_id)
    app.dependency_overrides[get_session] = _noop_session
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/pricing/runs",
                json={
                    "import_batch_id": str(uuid4()),
                    "scope_mode": FULL_CATALOG_SCOPE,
                    "confirm_full_catalog": True,
                    "idempotency_key": "operator-key-0001",
                    "preview_token": PREVIEW_TOKEN,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == expected_status, response.text


def test_a_bounded_run_reads_its_frozen_inputs_not_the_current_ones() -> None:
    """Правка, поданная во время расчёта, не должна попадать в идущий прогон.

    Без этого один и тот же прогон невоспроизводим: часть позиций посчитана по
    данным на старте, часть по данным, изменившимся на середине.
    """

    bounded = PricingRun(scope_contract_version=PRICING_RUN_SCOPE_CONTRACT_VERSION)
    legacy = PricingRun(scope_contract_version=None)
    unbounded = PricingRun(scope_contract_version="LEGACY_UNBOUNDED")
    bare = PricingRunItem()
    with_override = PricingRunItem(catalog_item_override_id=uuid4())
    with_cost = PricingRunItem(cost_record_id=uuid4())

    assert uses_frozen_start_inputs(bounded, bare) is True
    assert uses_frozen_start_inputs(bounded, with_override) is True

    # Замороженная ссылка сама по себе обязывает читать её, каким бы ни был
    # контракт области: ссылка есть — значит вход был зафиксирован.
    assert uses_frozen_start_inputs(legacy, with_override) is True
    assert uses_frozen_start_inputs(legacy, with_cost) is True
    assert uses_frozen_start_inputs(unbounded, with_cost) is True

    # Прогоны, начатые до контракта области, ссылок не имеют — их досчитываем
    # по прежнему пути, иначе они не завершатся никогда.
    assert uses_frozen_start_inputs(legacy, bare) is False
    assert uses_frozen_start_inputs(unbounded, bare) is False
