"""Scalable run adapter around the existing frozen Prom parser.

This module treats ``PromGateway`` as a black box.  It persists the gateway's
structured output before deriving observations, so retries can resume without
repeating a successful network collection.
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import math
import traceback
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, or_, select

from marko.core.config import Settings, get_settings
from marko.infrastructure.db.models import (
    BrandTierRule,
    CandidateComparabilityReview,
    CatalogItem,
    CrossLink,
    MarketObservation,
    MarketplaceStore,
    ObservationTierClassification,
    OfferProcessingOutcome,
    PricingRecommendation,
    PricingRun,
    PricingRunItem,
    RawMarketCapture,
    ScrapeAttempt,
    ScrapeEvidenceBlob,
    ScrapeHttpRequest,
    ScrapeTarget,
    StoreKind,
    WorkspaceStore,
)
from marko.infrastructure.db.session import async_session_factory
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.exceptions import is_self_describing_pagination_redirect
from marko.parsers.prom.gateway import PROM_PRODUCT_DETAIL_SCHEMA_VERSION, PromGateway
from marko.services.ai_evidence_extraction import (
    AI_EVIDENCE_SELECTION_VERSION,
    resolve_ai_evidence_config,
)
from marko.services.calibration_eligibility import (
    CALIBRATION_ELIGIBILITY_VERSION,
    calibration_identity_record,
    evaluate_calibration_eligibility,
)
from marko.services.catalog_costs import (
    decrypt_cost_record,
    get_decrypted_catalog_cost,
)
from marko.services.catalog_identity_safety import (
    catalog_identity_pair_has_safe_shape,
    is_internal_catalog_code,
)
from marko.services.collection_guard import DistributedCollectionGuard
from marko.services.decision_fingerprint import (
    DECISION_FINGERPRINT_VERSION,
    build_decision_fingerprint_payload,
    canonical_sha256,
)
from marko.services.llm_comparability import (
    ComparabilityMatchLevel,
    EffectiveComparabilityReview,
    apply_effective_review_to_evidence,
    current_review_runtime_identity,
    ensure_run_item_comparability_reviews,
    ensure_target_comparability_reviews,
    load_effective_review_map,
)
from marko.services.comparability_activation import (
    comparability_activation_artifact_verified,
)
from marko.services.matching import PriceComparison
from marko.services.market_price import effective_observation_price
from marko.services.offer_identity import (
    IdentityNamespace,
    IDENTITY_NAMESPACE_VERSION,
    OE_EXTRACTOR_VERSION,
    SOURCE_PAGE_ASSERTION_CONFIDENCE,
    automatic_identity_evidence_sufficient,
    customer_identity_namespace,
    ConfirmedCross,
    OeVerificationStatus,
    SourceAssertion,
    bind_oe_verification,
    canonical_cross_identity_key,
    evidence_items_to_dicts,
    extract_oe_evidence,
    extract_prom_motors_cross_proposals,
    namespace_bound_verification,
    namespace_identity_admission,
    persisted_identity_fields_consistent,
    verified_identity_namespace,
    verify_offer_identity,
)
from marko.services.offer_processing import (
    ACQUISITION_CONTRACT_VERSION,
    AcceptedCandidate,
    AcquisitionLineage,
    EvidenceAccountingError,
    OfferAccounting,
    OfferOutcomeCode,
    RejectedOffer,
    assess_candidate_source,
    process_offer_candidate,
    safe_offer_sample,
)
from marko.services.offer_integrity import (
    OfferIntegrityStatus,
    assess_offer_integrity,
)
from marko.services.pricing_runs import (
    FrozenCatalogItem,
    PricingRunSnapshotError,
    activation_artifact_verified,
    build_pricing_context,
    calibrate_tier_coefficients,
    customer_identity_available,
    customer_identity_query,
    customer_search_context,
    declared_widenings,
    frozen_catalog_item_from_snapshot,
    get_latest_override,
    load_run_execution_policy,
    load_run_item_start_cost_record,
    load_target_tier_coefficients,
    persist_run_calibration_pairs,
    require_activated_run_policy,
    resolve_catalog_measure_unit,
    resolve_execution_override,
    retrieval_only_queries,
    run_is_bounded,
    uses_frozen_start_inputs,
    verified_start_snapshot,
    verify_run_membership,
)
from marko.services.scrape_journal import (
    evidence_coverage_ratio,
    load_detail_replay_cache,
    load_replay_cache,
    persist_http_traces,
    retained_raw_evidence_bytes,
)
from marko.services.scrape_coverage import (
    coverage_summary,
    reported_total_from_search_pages,
)
from marko.services.scrape_runtime import (
    LogicalRequestTrace,
    ScrapeExecutionTrace,
    scrape_execution,
)
from marko.services.scraper_contract import (
    PROM_ADAPTER_VERSION,
    PROM_OUTPUT_SCHEMA_VERSION,
    RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED,
    AcquisitionInput,
    AttemptMeasurement,
    AttemptResourceProbe,
    FrozenPromScraperAdapter,
    ScrapeInput,
    ScrapeOutput,
    ScraperBoundaryError,
    ScraperErrorCode,
    build_acquisition_input,
    classify_scraper_exception,
    declared_discovery_queries_from_payload,
    retrieval_kind_is_widened,
)
from marko.services.scraper_outbox import enqueue_dispatch
from marko.services.source_access import require_live_prom_marketplace_collection
from marko.services.semantic_candidate_gate import (
    apply_semantic_pricing_gate,
    semantic_gate_snapshot_is_current,
)
from metis.pricing import (
    COMPARABILITY_CONTRACT_VERSION,
    CandidateItem,
    CandidateSelectionConfig,
    CandidateStatus,
    CandidateVerdict,
    CalibrationPair,
    CoefficientModel,
    CohortRole,
    ComparisonEvidence,
    CompetitorOffer,
    HardGateResult,
    PricingResult,
    ProductTier,
    ReferenceItem,
    RecommendationAction,
    TierClassification,
    bind_persisted_provenance,
    calibration_dataset_hash,
    category_comparability_rule,
    check_candidate,
    classify_condition,
    classify_tier,
    cluster_diagnostic_to_dict,
    comparison_evidence_from_dict,
    comparison_evidence_to_dict,
    extract_description_cross_candidates,
    load_approved_brand_rules,
    load_candidate_selection_config,
    normalize_brand,
    normalize_oe,
    recommend_price,
    robust_dispersion_trace,
)
from metis.pricing.numeric import (
    TRANSCENDENTAL_PROFILE_VERSION,
    TRANSCENDENTAL_RELATIVE_TOLERANCE,
)
from metis.pricing.observability import pricing_event
from metis.pricing.raise_policy import RaisePolicy, RaiseStrategy
from metis.pricing.statistics import median as decimal_median
from metis.pricing.statistics import round_down_to_tick


class PricingItemNotFoundError(LookupError):
    pass


class PermanentCollectionError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# F4: одна авторитетная точка разрешения замороженных входов позиции
# ---------------------------------------------------------------------------


class FrozenBindingError(PricingRunSnapshotError):
    """Снимок не привязан к той строке членства, в которой лежит."""


#: Поля снимка, отсутствие которых раньше подменялось значением по умолчанию.
#: ``source_row`` становился нулём, ``mpn_norm``/``name`` — пустой строкой,
#: ``identity_status`` — ``UNRESOLVED``. Каждое из них влияет на отождествление
#: и на отчётность, поэтому дырка в снимке обязана быть отказом, а не догадкой.
_REQUIRED_SNAPSHOT_FIELDS: tuple[tuple[str, type | tuple[type, ...]], ...] = (
    ("catalog_item_id", str),
    ("source_row", int),
    ("sku", str),
    ("oe_norm", str),
    ("mpn_norm", str),
    ("name", str),
    ("category", str),
    ("current_price", str),
    ("currency", str),
    ("stock_status", str),
    ("identity_status", str),
    ("membership_position", int),
)


def _snapshot_binding_value(value: Any) -> str | None:
    """Каноническая форма ссылки из снимка/строки для точного сравнения."""

    if value is None:
        return None
    text_value = str(value).strip()
    return text_value or None


def resolve_bound_execution_item(
    run: PricingRun,
    run_item: PricingRunItem,
    live_item: CatalogItem | None = None,
) -> CatalogItem | FrozenCatalogItem:
    """Единственная авторитетная точка чтения «позиции каталога» исполнением.

    Самоподписанный снимок доказывает лишь то, что его не правили: он ничего не
    говорит о том, ТУ ЛИ строку членства он описывает. Пересчитать честный хеш
    поверх снимка позиции B и положить его в ``PricingRunItem`` позиции A было
    достаточно, чтобы прогон считал по чужому товару. Поэтому здесь проверяется
    не только отпечаток, но и совпадение всех связей: прогон, позиция каталога,
    место в замороженном членстве, правка оператора и запись себестоимости.

    Живая строка ``CatalogItem`` после этого используется ТОЛЬКО как
    неавторитетные данные отображения (см. :func:`display_catalog_item`);
    ничего, что попадает в цену, отождествление или коэффициенты, из неё не
    читается.
    """

    if getattr(run_item, "pricing_run_id", None) != getattr(run, "id", None):
        raise FrozenBindingError(
            "START_SNAPSHOT_UNBOUND: run item "
            f"{getattr(run_item, 'id', None)} belongs to run "
            f"{getattr(run_item, 'pricing_run_id', None)}, not "
            f"{getattr(run, 'id', None)}"
        )
    if live_item is not None and _snapshot_binding_value(
        getattr(live_item, "id", None)
    ) != _snapshot_binding_value(getattr(run_item, "catalog_item_id", None)):
        raise FrozenBindingError(
            "START_SNAPSHOT_UNBOUND: the live catalog row handed to execution is "
            "not the row this membership names"
        )
    if not run_is_bounded(run):
        # Прогон без контракта области — историческая, явно помеченная ветка.
        if live_item is None:
            raise FrozenBindingError(
                "START_SNAPSHOT_UNBOUND: a legacy unbounded run needs its live row"
            )
        return live_item

    snapshot = verified_start_snapshot(run_item)
    _require_complete_snapshot(run_item, snapshot)
    _require_snapshot_bindings(run_item, snapshot)
    return frozen_catalog_item_from_snapshot(snapshot)


def _require_complete_snapshot(
    run_item: PricingRunItem, snapshot: Mapping[str, Any]
) -> None:
    """Ни одно обязательное поле не подменяется значением по умолчанию."""

    for name, expected in _REQUIRED_SNAPSHOT_FIELDS:
        if name not in snapshot:
            raise FrozenBindingError(
                f"START_SNAPSHOT_INCOMPLETE: run item {run_item.id} snapshot has "
                f"no {name}; refusing to substitute a default"
            )
        value = snapshot[name]
        if expected is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise FrozenBindingError(
                    f"START_SNAPSHOT_CORRUPT: {name} is not an integer"
                )
            continue
        if not isinstance(value, str):
            raise FrozenBindingError(f"START_SNAPSHOT_CORRUPT: {name} is not a string")
        # General Prom catalogs are not automotive-only. Both normalized part
        # numbers can legitimately be absent; their absence is preserved so
        # downstream identity gates fail closed instead of inventing an OEM.
        if name not in {"oe_norm", "mpn_norm"} and not value.strip():
            raise FrozenBindingError(f"START_SNAPSHOT_INCOMPLETE: {name} is empty")


def _require_snapshot_bindings(
    run_item: PricingRunItem, snapshot: Mapping[str, Any]
) -> None:
    """Снимок обязан описывать именно эту строку членства."""

    bindings = (
        ("catalog_item_id", snapshot.get("catalog_item_id"), run_item.catalog_item_id),
        (
            "membership_position",
            snapshot.get("membership_position"),
            run_item.membership_position,
        ),
        (
            "catalog_item_override_id",
            snapshot.get("catalog_item_override_id"),
            run_item.catalog_item_override_id,
        ),
        ("cost_record_id", snapshot.get("cost_record_id"), run_item.cost_record_id),
    )
    for name, frozen_value, row_value in bindings:
        if _snapshot_binding_value(frozen_value) != _snapshot_binding_value(row_value):
            raise FrozenBindingError(
                f"START_SNAPSHOT_MISBOUND: run item {run_item.id} names "
                f"{name}={row_value!r} while its frozen snapshot names "
                f"{frozen_value!r}"
            )


def display_catalog_item(live_item: CatalogItem | None) -> CatalogItem | None:
    """Живая строка каталога — исключительно для отображения.

    Существует, чтобы каждое обращение к живому каталогу внутри исполнения было
    названо явно. Читать отсюда что-либо, что влияет на цену, отождествление
    или подбор коэффициентов, нельзя: для этого есть
    :func:`resolve_bound_execution_item`.
    """

    return live_item


_ADVISORY_HARD_EXCLUDE_ROLES = frozenset(
    {
        CohortRole.HARD_REJECTED,
        CohortRole.USED_REJECTED,
        CohortRole.OWNED_STORE,
        CohortRole.DUMPING_DIAGNOSTIC,
    }
)
_ADVISORY_HARD_EXCLUDE_REASONS = frozenset(
    {
        "USED_OR_REFURBISHED",
        "PRICE_ON_REQUEST",
        "SERVICE_NOT_PART",
        "PARTS_DONOR",
        "DEPOSIT_OR_EXCHANGE_AMOUNT",
        "WHOLESALE_OR_MINIMUM_QUANTITY",
        "DAMAGED_OR_INCOMPLETE",
        "OWNED_SELLER",
        "KEMP_DUMPING",
    }
)
_ADVISORY_NO_COHORT_ACTIONS = frozenset(
    {
        RecommendationAction.INSUFFICIENT_DATA,
        RecommendationAction.MANUAL_REVIEW,
    }
)
_ADVISORY_NO_COHORT_REASONS = frozenset(
    {
        "TOO_FEW_COMPETITORS",
        "TOO_FEW_COMPETITORS_AFTER_CLEANING",
        "INSUFFICIENT_DATA",
        "MANUAL_REVIEW",
        "MANUAL_REVIEW_REQUIRED",
    }
)
_ADVISORY_MISSING_DIMENSION_REASONS = {
    "MANUAL_MISSING_CONDITION": "condition",
    "MANUAL_MISSING_PACKAGE_QUANTITY": "package_quantity",
    "MANUAL_MISSING_UNIT_BASIS": "unit_basis",
}
_ADVISORY_COMMERCIAL_DIMENSIONS = ("condition", "package_quantity", "unit_basis")


def _advisory_visible_offer_prices(
    result: PricingResult,
) -> tuple[tuple[Decimal, str | None], ...]:
    """Offers that survived hard reject, including incomplete commercial facts.

    ``result.evidence`` is the admitted cohort. On TOO_FEW_COMPETITORS that
    set is empty; the prices the operator can still see live on excluded
    rows with MANUAL_* / incomplete-dimension reasons and ``raw_price``.
    Unknown condition is not used: silence about newness is ordinary on Prom.
    """

    visible: list[tuple[Decimal, str | None]] = []
    seen: set[tuple[str, str]] = set()

    def add(price: Decimal, seller_id: str | None, key: str) -> None:
        if price <= Decimal("0"):
            return
        identity = (key, str(seller_id or ""), str(price))
        if identity in seen:
            return
        seen.add(identity)
        visible.append((price, seller_id))

    for offer in result.evidence:
        add(offer.normalized_price, offer.seller_id, offer.observation_id)
    for offer in result.excluded:
        if offer.cohort_role in _ADVISORY_HARD_EXCLUDE_ROLES:
            continue
        if offer.reason in _ADVISORY_HARD_EXCLUDE_REASONS:
            continue
        if offer.raw_price is None:
            continue
        add(offer.raw_price, offer.seller_id, offer.observation_id)
    return tuple(visible)


def _advisory_missing_pricing_dimensions(result: PricingResult) -> tuple[str, ...]:
    missing: list[str] = []
    for field in result.unknown_hard_fields:
        name = str(field).strip()
        if name in _ADVISORY_COMMERCIAL_DIMENSIONS and name not in missing:
            missing.append(name)
    for offer in result.excluded:
        mapped = _ADVISORY_MISSING_DIMENSION_REASONS.get(offer.reason)
        if mapped and mapped not in missing:
            missing.append(mapped)
        if offer.reason == "SEMANTIC_PRICING_EVIDENCE_INCOMPLETE":
            for name in _ADVISORY_COMMERCIAL_DIMENSIONS:
                if name not in missing:
                    missing.append(name)
    return tuple(missing)


def _incomplete_evidence_advisory(
    *,
    policy: RaisePolicy,
    result: PricingResult,
    operator_cost_warning: str,
) -> dict[str, Any] | None:
    if result.recommended_price is not None:
        return None
    if result.action not in _ADVISORY_NO_COHORT_ACTIONS:
        return None
    if not any(reason in _ADVISORY_NO_COHORT_REASONS for reason in result.reasons):
        if result.action is not RecommendationAction.INSUFFICIENT_DATA:
            return None
    visible = _advisory_visible_offer_prices(result)
    if not visible:
        return None
    market_minimum = min(price for price, _seller in visible)
    target = market_minimum * (Decimal("1") - policy.minimum_discount)
    recommended = round_down_to_tick(target, policy.psychological_step)
    if recommended <= Decimal("0"):
        return None
    sellers = {
        str(seller_id).strip()
        for _price, seller_id in visible
        if seller_id and str(seller_id).strip()
    }
    missing = _advisory_missing_pricing_dimensions(result)
    if recommended > result.current_price:
        action = RecommendationAction.RAISE.value
    elif recommended < result.current_price:
        action = RecommendationAction.LOWER.value
    else:
        action = RecommendationAction.HOLD.value
    absolute_change = abs(recommended - result.current_price)
    percentage_change = (
        absolute_change / result.current_price
        if result.current_price > Decimal("0")
        else None
    )
    return {
        "status": "INCOMPLETE_EVIDENCE_REVIEW_REQUIRED",
        "action": action,
        "current_price": str(result.current_price),
        "recommended_price": str(recommended),
        "absolute_change": str(absolute_change),
        "percentage_change": (
            None if percentage_change is None else str(percentage_change)
        ),
        "minimum_comparable_price": str(market_minimum),
        "target_band_low": str(recommended),
        "target_band_high": str(recommended),
        "automatic_price_application": False,
        "operator_cost_warning": operator_cost_warning,
        "reason": "ADVISORY_FROM_UNVERIFIED_VISIBLE_OFFERS",
        "basis_offer_count": len(visible),
        "basis_independent_sellers": len(sellers),
        "missing_pricing_dimensions": list(missing),
        "check_package_unit": any(
            name in {"condition", "package_quantity", "unit_basis"} for name in missing
        ),
    }


def customer_budget_floor_trace(
    *,
    policy: RaisePolicy | None,
    result: PricingResult,
    comparability_activation_verified: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return audit policy and a safe advisory when automatic release is gated."""

    if policy is None or policy.strategy is not RaiseStrategy.BUDGET_FLOOR:
        return None, None
    plausibility_floor = (
        result.current_price * policy.target_floor_ratio
        if policy.target_floor_ratio > Decimal("0")
        else None
    )
    excluded_implausible_count = (
        sum(offer.normalized_price < plausibility_floor for offer in result.evidence)
        if plausibility_floor is not None
        else 0
    )
    policy_trace = {
        "strategy": policy.strategy.value,
        "method_version": policy.method_version,
        "source_sha256": policy.source_sha256,
        "owner_decision_reference": policy.owner_decision_reference,
        "market_basis": "minimum_verified_comparable_price",
        "minimum_discount": str(policy.minimum_discount),
        "maximum_discount": str(policy.maximum_discount),
        "selected_discount": str(policy.minimum_discount),
        "psychological_step": str(policy.psychological_step),
        "target_floor_ratio": str(policy.target_floor_ratio),
        "floor_corroboration_sellers": policy.floor_corroboration_sellers,
        "floor_gap_review_ratio": str(policy.floor_gap_review_ratio),
        "plausibility_floor": (
            None if plausibility_floor is None else str(plausibility_floor)
        ),
        "excluded_implausible_count": excluded_implausible_count,
        "brand_tier_handling": "ignored_for_price",
        "stock_status_handling": "ignored_for_price",
        # Avoid a `cost`-labelled API key: the cost-privacy boundary correctly
        # strips every such key, even when it carries policy metadata only.
        "procurement_basis_handling": "ignored_for_price",
        "automatic_price_application": False,
        "operator_cost_warning": (
            "Before accepting the recommendation, account for procurement, "
            "Prom commission, payment fees, taxes, packaging, delivery, returns, "
            "warranty, and the minimum acceptable margin. These expenses do not "
            "change the competitor-minus-5-percent formula automatically."
        ),
    }
    if (
        not comparability_activation_verified
        and result.automatic_eligible
        and result.action in {RecommendationAction.RAISE, RecommendationAction.LOWER}
        and result.recommended_price is not None
    ):
        absolute_change = abs(result.recommended_price - result.current_price)
        percentage_change = (
            absolute_change / result.current_price
            if result.current_price > Decimal("0")
            else None
        )
        advisory = {
            "status": "COMPARABILITY_REVIEW_REQUIRED",
            "action": result.action.value,
            "current_price": str(result.current_price),
            "recommended_price": str(result.recommended_price),
            "absolute_change": str(absolute_change),
            "percentage_change": (
                None if percentage_change is None else str(percentage_change)
            ),
            "minimum_comparable_price": (
                None if result.fair_price is None else str(result.fair_price)
            ),
            "target_band_low": (
                None if result.lower_bound is None else str(result.lower_bound)
            ),
            "target_band_high": (
                None if result.upper_bound is None else str(result.upper_bound)
            ),
            "automatic_price_application": False,
            "operator_cost_warning": policy_trace["operator_cost_warning"],
            "reason": "COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED",
        }
        return policy_trace, advisory
    return policy_trace, _incomplete_evidence_advisory(
        policy=policy,
        result=result,
        operator_cost_warning=policy_trace["operator_cost_warning"],
    )


# Mirrors the transport HTTPS rule's explicit environment set (config.py):
# an unrecognized environment name is treated as production, so a typo in
# ``ENVIRONMENT`` leaves the release gate closed instead of opening it.
_COMPARABILITY_ARTIFACT_OPTIONAL_ENVIRONMENTS = frozenset(
    {"development", "test", "e2e"}
)


def resolve_comparability_activation(settings: Settings) -> tuple[bool, str]:
    """Decide whether automatic comparability release is authorized.

    Returns ``(verified, basis)`` where ``basis`` names the evidence:
    ``"artifact"`` for the signed acceptance artifact, ``"owner_flag"`` for
    the non-production owner switch, ``"closed"`` otherwise.

    Production always demands the artifact (the config validator additionally
    refuses to boot with the flag set and no artifact).  Outside production
    the owner's ``pricing_comparability_v1_automatic_enabled`` flag alone
    opens the gate — the owner's 2026-08-16 decision to run the budget-floor
    recommendations without the full acceptance evaluation.  The v3 robust
    gate has no such bypass; this one is deliberate and dev-only.  If artifact
    fields are configured in a dev environment they are validated rather than
    ignored, so a broken artifact fails closed everywhere.
    """

    if not settings.pricing_comparability_v1_automatic_enabled:
        return False, "closed"
    artifact_configured = bool(
        settings.pricing_comparability_activation_artifact.strip()
        or settings.pricing_comparability_activation_sha256.strip()
    )
    environment = settings.environment.strip().casefold()
    if (
        not artifact_configured
        and environment in _COMPARABILITY_ARTIFACT_OPTIONAL_ENVIRONMENTS
    ):
        return True, "owner_flag"
    verified = comparability_activation_artifact_verified(
        settings.pricing_comparability_activation_artifact,
        settings.pricing_comparability_activation_sha256,
        expected_runtime_identity=current_review_runtime_identity(settings),
    )
    return verified, "artifact" if verified else "closed"


def apply_comparability_activation_gate(
    result: PricingResult,
    *,
    activation_verified: bool,
) -> PricingResult:
    """Apply the persisted release gate identically in calculation and replay."""

    if not result.automatic_eligible or activation_verified:
        return result
    return replace(
        result,
        action=RecommendationAction.MANUAL_REVIEW,
        recommended_price=None,
        absolute_recommended_change=None,
        percentage_recommended_change=None,
        action_gates_passed=False,
        automatic_eligible=False,
        confidence_grade="MANUAL",
        reasons=tuple(
            dict.fromkeys(
                result.reasons
                + (
                    "COMPARABILITY_AUTOMATIC_ACTIVATION_BLOCKED",
                    "MANUAL_REVIEW_REQUIRED",
                )
            )
        ),
    )


CollectionAction = Literal[
    "legacy_collect",
    "target_collect",
    "target_materialize",
    "target_terminal",
    "target_busy",
]


@dataclass(frozen=True)
class CollectionClaim:
    action: CollectionAction
    run_id: UUID
    run_item_id: UUID
    catalog_item_id: UUID
    product_url: str | None
    search_identity: str
    scrape_target_id: UUID | None = None
    scrape_attempt_id: UUID | None = None
    delivery_no: int = 0
    fencing_token: int = 0
    execution_no: int = 0
    task_id: str | None = None
    scrape_input: AcquisitionInput | None = None
    stored_output: ScrapeOutput | None = None
    terminal_error: ScraperBoundaryError | None = None
    #: Every storefront the run's workspace owns.  Carried on the claim so
    #: acquisition can drop them before ``max_sellers`` is applied instead of
    #: only recognizing them once the evidence is already materialized.
    excluded_seller_ids: frozenset[str] = frozenset()


async def prepare_run_dispatch(run_id: UUID) -> list[UUID]:
    """Move a run to collecting and durably enqueue one item per target."""
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            raise PricingItemNotFoundError(f"Pricing run {run_id} does not exist")
        if run.status in {"completed", "partial", "failed", "cancelled"}:
            return []
        if run.cancel_requested:
            items = list(
                (
                    await session.scalars(
                        select(PricingRunItem).where(
                            PricingRunItem.pricing_run_id == run_id,
                            PricingRunItem.status.not_in(
                                ("calculated", "manual_review", "failed", "cancelled")
                            ),
                        )
                    )
                ).all()
            )
            now = datetime.now(UTC)
            for item in items:
                item.status = "cancelled"
                item.finished_at = now
            targets = list(
                (
                    await session.scalars(
                        select(ScrapeTarget).where(
                            ScrapeTarget.pricing_run_id == run_id,
                            ScrapeTarget.status.not_in(
                                ("succeeded", "terminal_failure", "cancelled")
                            ),
                        )
                    )
                ).all()
            )
            for target in targets:
                target.status = "cancelled"
                target.finished_at = now
                target.owner_task_id = None
                target.lease_expires_at = None
            run.status = "cancelled"
            run.finished_at = now
            await session.commit()
            return []
        if run.started_at is None:
            run.started_at = datetime.now(UTC)
        run.status = "collecting"
        discovering_ids = list(
            (
                await session.scalars(
                    select(PricingRunItem.id).where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status == "discovering",
                    )
                )
            ).all()
        )
        rows = list(
            (
                await session.execute(
                    select(PricingRunItem.id, PricingRunItem.scrape_target_id)
                    .where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status.in_(
                            ("queued", "collecting", "collected")
                        ),
                    )
                    .order_by(PricingRunItem.created_at, PricingRunItem.id)
                )
            ).all()
        )
        ids: list[UUID] = []
        dispatched_targets: set[UUID] = set()
        for item_id, target_id in rows:
            if target_id is None:
                ids.append(item_id)
                continue
            if target_id in dispatched_targets:
                continue
            dispatched_targets.add(target_id)
            ids.append(item_id)
        event_ids: list[UUID] = []
        for item_id in discovering_ids:
            event = await enqueue_dispatch(
                session,
                event_key=f"pricing-run:{run.id}:no-oe-discovery:{item_id}:v1",
                aggregate_type="pricing_run_item",
                aggregate_id=item_id,
                workspace_id=run.workspace_id,
                task_name="marko.worker.process_no_oe_discovery_item",
                task_args=[str(item_id)],
                queue="pricing",
            )
            event_ids.append(event.id)
        for item_id in ids:
            event = await enqueue_dispatch(
                session,
                event_key=f"pricing-run:{run.id}:collect:{item_id}:v1",
                aggregate_type="pricing_run_item",
                aggregate_id=item_id,
                workspace_id=run.workspace_id,
                task_name="marko.worker.process_pricing_item",
                task_args=[str(item_id)],
                queue="pricing",
            )
            event_ids.append(event.id)
        await session.commit()
        return event_ids


async def enqueue_collection_finalizer_dispatch(
    run_id: UUID,
    *,
    trigger_key: str,
) -> UUID:
    """Durably enqueue one idempotent finalizer probe for a completed trigger."""

    async with async_session_factory() as session:
        run = await session.get(PricingRun, run_id)
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        event = await enqueue_dispatch(
            session,
            event_key=f"pricing-run:{run.id}:finalize:{trigger_key}:v1",
            aggregate_type="pricing_run",
            aggregate_id=run.id,
            workspace_id=run.workspace_id,
            task_name="marko.worker.finalize_pricing_collection",
            task_args=[str(run.id)],
            queue="celery",
        )
        await session.commit()
        return event.id


async def process_pricing_item(
    run_item_id: UUID,
    *,
    task_id: str | None = None,
    is_redelivery: bool = False,
) -> UUID | None:
    claim = await _claim_item(
        run_item_id,
        task_id=task_id,
        is_redelivery=is_redelivery,
    )
    if claim is None:
        run_id = await _run_id_for_statuses(run_item_id, ("classified",))
        if run_id is not None:
            await ensure_run_item_comparability_reviews(run_item_id)
        return run_id
    if claim.action == "target_busy":
        pricing_event(
            "scrape_target_duplicate_delivery",
            pricing_run_id=str(claim.run_id),
            scrape_target_id=str(claim.scrape_target_id),
            pricing_run_item_id=str(claim.run_item_id),
        )
        return claim.run_id
    if claim.action == "target_terminal":
        if claim.scrape_target_id is None or claim.terminal_error is None:
            raise RuntimeError("Invalid terminal target claim")
        await _mark_target_group_classified(
            claim.scrape_target_id,
            reason=claim.terminal_error.code.value,
            error=claim.terminal_error,
        )
        return claim.run_id
    if claim.action == "target_materialize":
        if claim.scrape_target_id is None:
            raise RuntimeError("Target materialization claim has no target")
        await _materialize_target_evidence(claim.scrape_target_id)
        await ensure_target_comparability_reviews(claim.scrape_target_id)
        return claim.run_id
    if claim.action == "target_collect":
        if (
            claim.scrape_target_id is None
            or claim.scrape_attempt_id is None
            or claim.scrape_input is None
        ):
            raise RuntimeError("Target collection claim is incomplete")
        settings = get_settings()
        if (
            settings.environment.strip().casefold() == "e2e"
            and settings.e2e_task_hold_seconds > 0
        ):
            await asyncio.sleep(settings.e2e_task_hold_seconds)
        run_id = await _process_target_collection(claim)
        await ensure_target_comparability_reviews(claim.scrape_target_id)
        return run_id

    if await _has_capture(run_item_id):
        await _mark_classified(run_item_id, reason="resumed_from_capture")
        await ensure_run_item_comparability_reviews(run_item_id)
        return claim.run_id
    if not claim.product_url:
        await _mark_classified(run_item_id, reason="missing_product_url")
        return claim.run_id
    try:
        comparison = await asyncio.to_thread(
            functools.partial(
                _collect_comparison,
                claim.product_url,
                claim.search_identity,
                excluded_seller_ids=claim.excluded_seller_ids,
            )
        )
    except ValueError as exc:
        raise PermanentCollectionError(str(exc)) from exc
    await _persist_comparison(
        run_id=claim.run_id,
        run_item_id=run_item_id,
        catalog_item_id=claim.catalog_item_id,
        product_url=claim.product_url,
        comparison=comparison,
    )
    await ensure_run_item_comparability_reviews(run_item_id)
    return claim.run_id


async def _process_target_collection(claim: CollectionClaim) -> UUID:
    if (
        claim.scrape_target_id is None
        or claim.scrape_attempt_id is None
        or claim.scrape_input is None
    ):
        raise RuntimeError("Target collection claim is incomplete")
    scrape_target_id = claim.scrape_target_id
    scrape_input = claim.scrape_input
    settings = get_settings()
    probe = AttemptResourceProbe()
    trace: ScrapeExecutionTrace | None = None
    try:
        async with async_session_factory() as session:
            # Cards shared across positions first, this target's own evidence
            # on top: a replay bound to this target must always win over the
            # same URL captured for another one.
            replay_cache = await load_detail_replay_cache(
                session,
                max_age_hours=settings.pricing_detail_replay_max_age_hours,
            )
            replay_cache.update(
                await load_replay_cache(
                    session,
                    scrape_target_id=scrape_target_id,
                )
            )
        trace = ScrapeExecutionTrace(
            item_kind="comparison_job",
            execution_no=claim.delivery_no,
            replay_cache=replay_cache,
            guard=DistributedCollectionGuard(settings, namespace="prom"),
            live_request_gate=require_live_prom_marketplace_collection,
        )
        output = await asyncio.to_thread(
            functools.partial(
                _collect_target_output,
                scrape_input,
                trace,
                excluded_seller_ids=claim.excluded_seller_ids,
            )
        )
    except Exception as exc:
        measurement = probe.finish()
        error = (
            exc
            if isinstance(exc, ScraperBoundaryError)
            else classify_scraper_exception(exc)
        )
        if trace is None:
            trace = ScrapeExecutionTrace(
                item_kind="comparison_job",
                execution_no=claim.delivery_no,
            )
        persisted = await _persist_target_failure(
            claim,
            trace,
            measurement,
            error,
        )
        if not persisted:
            return claim.run_id
        if error.retryable:
            raise error
        await _mark_target_group_classified(
            scrape_target_id,
            reason=error.code.value,
            error=error,
        )
        return claim.run_id
    else:
        measurement = probe.finish()
        persisted = await _persist_target_success(
            claim,
            trace,
            measurement,
            output,
        )
        if persisted:
            await _materialize_target_evidence(scrape_target_id)
        return claim.run_id
    finally:
        try:
            await _refresh_target_attempt_measurement(
                claim,
                probe.finish(),
            )
        except Exception as measurement_error:
            pricing_event(
                "scrape_measurement_persistence_failed",
                item_kind="comparison_job",
                pricing_run_id=str(claim.run_id),
                scrape_target_id=str(claim.scrape_target_id),
                delivery_no=claim.delivery_no,
                error_type=type(measurement_error).__name__,
            )
        if trace is not None:
            trace.close()


def _collect_target_output(
    scrape_input: AcquisitionInput,
    trace: ScrapeExecutionTrace,
    *,
    excluded_seller_ids: frozenset[str] = frozenset(),
) -> ScrapeOutput:
    settings = get_settings()
    config = ScrapeConfig(
        delay=settings.pricing_scraper_request_delay_seconds,
        delay_jitter=settings.pricing_scraper_request_jitter_seconds,
        timeout=settings.pricing_scraper_http_timeout_seconds,
        max_attempts=max(1, settings.pricing_scraper_http_max_attempts),
        max_sellers=max(1, settings.pricing_scraper_max_sellers),
        max_detail_cards=max(0, settings.pricing_scraper_max_detail_cards),
        max_search_pages=max(1, settings.pricing_scraper_max_search_pages),
        max_oe_page_pages=max(1, settings.pricing_scraper_max_oe_page_pages),
    )
    with scrape_execution(trace):
        output = FrozenPromScraperAdapter(
            config,
            excluded_seller_ids=excluded_seller_ids,
            min_independent_sellers=(settings.pricing_scraper_min_independent_sellers),
        ).extract(scrape_input)
    _raise_on_required_request_failure(trace)
    return output


def _required_request_failures(
    trace: ScrapeExecutionTrace,
) -> tuple[LogicalRequestTrace, ...]:
    """Failures that leave the target without the evidence it came for.

    A competitor's product card is not a required request.  ``PromGateway``
    already degrades a broken card to ``detail_status=FAILED`` and keeps the
    listing, and ``_detail_evidence_automatic_safe`` refuses to price it, so
    failing the whole target here discarded every search page and every other
    candidate that did complete — one 404 on one competitor made the position
    permanently uncollected, because ``upstream_4xx`` is not retryable.  The
    seed card is not affected: its fetch raises out of ``extract`` before this
    check runs.  A target where *no* card completed is still fatal, because
    search rows alone can never become automatically priceable.

    A search page that fails is fatal unless it is Prom's canonical
    end-of-pagination redirect, which ``_collect_candidates`` deliberately
    stops on while keeping everything already collected.  The catalog-discovery
    path has tolerated the same probe since 2026-07-26; the pricing path had
    not, so a reported total larger than the served one discarded the position.
    """

    fatal = tuple(
        failure
        for failure in trace.failed_requests(request_kinds={"search_page"})
        if not is_self_describing_pagination_redirect(
            status_code=failure.response_status_code,
            request_url=failure.prepared_url,
            redirect_location=failure.response_redirect_location,
        )
    )
    card_failures = trace.failed_requests(request_kinds={"product_page"})
    if card_failures and not trace.succeeded_requests(request_kinds={"product_page"}):
        fatal += (card_failures[0],)
    return fatal


def _raise_on_required_request_failure(trace: ScrapeExecutionTrace) -> None:
    failures = _required_request_failures(trace)
    if not failures:
        return
    failure = failures[0]
    mapping = {
        "rate_limited": (ScraperErrorCode.RATE_LIMITED, True),
        "timeout": (ScraperErrorCode.TIMEOUT, True),
        "connect_timeout": (ScraperErrorCode.TIMEOUT, True),
        "read_timeout": (ScraperErrorCode.TIMEOUT, True),
        "upstream_5xx": (ScraperErrorCode.UPSTREAM_5XX, True),
        "retry_exhausted": (ScraperErrorCode.RETRY_EXHAUSTED, True),
        "upstream_3xx": (ScraperErrorCode.UPSTREAM_3XX, False),
        "upstream_4xx": (ScraperErrorCode.UPSTREAM_4XX, False),
        "parse_contract": (ScraperErrorCode.PARSE_CONTRACT, False),
    }
    code, retryable = mapping.get(
        failure.error_category or "",
        (ScraperErrorCode.NETWORK, failure.outcome == "retryable_failure"),
    )
    raise ScraperBoundaryError(
        code,
        "Required comparison request did not complete: "
        f"{failure.request_kind} {failure.error_detail or failure.outcome}",
        retryable=retryable,
    )


def _verified_target_output(target: ScrapeTarget) -> ScrapeOutput:
    if target.payload is None:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Succeeded target has no structured payload",
            retryable=False,
        )
    output = ScrapeOutput.from_payload(target.payload)
    if target.content_sha256 is None:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Succeeded target has no structured content identity",
            retryable=False,
        )
    if target.content_sha256 != output.content_sha256:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Stored target payload SHA-256 does not match its content identity",
            retryable=False,
        )
    if output.payload.get("schema_version") != PROM_OUTPUT_SCHEMA_VERSION:
        return output
    bindings = {
        "input kind": (
            str(target.input_kind or ""),
            str(output.input_payload.get("input_kind") or ""),
        ),
        "input hash": (str(target.input_hash or ""), str(output.input_hash or "")),
        "query": (str(target.query or ""), str(output.requested_query or "")),
        "adapter version": (
            str(target.adapter_version or ""),
            str(output.payload.get("adapter_version") or ""),
        ),
    }
    if target.input_kind == "product_seed":
        bindings.update(
            {
                "canonical URL": (
                    str(target.canonical_url or ""),
                    str(output.input_payload.get("canonical_url") or ""),
                ),
                "product key": (
                    str(target.product_key or ""),
                    str(output.input_payload.get("product_key") or ""),
                ),
            }
        )
    mismatches = [
        name for name, (expected, actual) in bindings.items() if expected != actual
    ]
    if mismatches:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Stored target payload is not bound to its target: "
            + ", ".join(mismatches),
            retryable=False,
        )
    return output


def _collect_comparison(
    product_url: str,
    oe_norm: str,
    *,
    excluded_seller_ids: frozenset[str] = frozenset(),
) -> PriceComparison:
    settings = get_settings()
    require_live_prom_marketplace_collection(settings)
    with DistributedCollectionGuard(settings) as guard:
        guard.wait_for_slot()
        try:
            comparison = PromGateway().compare(
                product_url,
                query=oe_norm,
                excluded_seller_ids=excluded_seller_ids,
            )
        except Exception:
            guard.record_failure()
            raise
        guard.record_success()
        return comparison


async def _claim_item(
    run_item_id: UUID,
    *,
    task_id: str | None,
    is_redelivery: bool,
) -> CollectionClaim | None:
    async with async_session_factory() as session:
        preview = (
            await session.execute(
                select(
                    PricingRunItem.id,
                    PricingRunItem.scrape_target_id,
                ).where(PricingRunItem.id == run_item_id)
            )
        ).one_or_none()
        if preview is None:
            raise PricingItemNotFoundError(
                f"Pricing run item {run_item_id} does not exist"
            )

        target: ScrapeTarget | None = None
        if preview.scrape_target_id is not None:
            # All target-backed paths use the same lock order as evidence
            # materialization: target first, dependent item second.  Locking
            # the item first can deadlock when a redelivery races a worker
            # that already owns the target and is inserting item-scoped rows.
            target = await session.scalar(
                select(ScrapeTarget)
                .where(ScrapeTarget.id == preview.scrape_target_id)
                .with_for_update()
            )
            if target is None:
                raise PricingItemNotFoundError("Scrape target dependency is missing")

        item = await session.scalar(
            select(PricingRunItem)
            .where(PricingRunItem.id == run_item_id)
            .with_for_update()
        )
        if item is None:
            raise PricingItemNotFoundError(
                f"Pricing run item {run_item_id} does not exist"
            )
        if item.scrape_target_id != preview.scrape_target_id:
            raise RuntimeError("Pricing run item target changed while acquiring locks")
        if item.status in {"calculated", "manual_review", "failed", "cancelled"}:
            return None
        if item.status not in {"queued", "collecting", "collected"}:
            return None
        run = await session.get(PricingRun, item.pricing_run_id)
        live_catalog_item = await session.get(CatalogItem, item.catalog_item_id)
        if run is None or live_catalog_item is None:
            raise PricingItemNotFoundError("Pricing run item dependencies are missing")
        # Сбор идёт по замороженным URL и OE: смена ссылки или артикула после
        # старта не должна увести идущий прогон на другой товар.
        catalog_item = resolve_bound_execution_item(run, item, live_catalog_item)
        if run.cancel_requested:
            item.status = "cancelled"
            item.finished_at = datetime.now(UTC)
            await session.commit()
            await finalize_pricing_run(run.id)
            return None
        if target is not None:
            # A stale/replayed target can outlive the identity state that was
            # present when it was created.  Re-check the frozen customer
            # namespace before *any* target status (including ``succeeded``)
            # can materialize evidence.  This keeps old MPN-only targets from
            # becoming priceable through a direct worker redelivery.
            if not customer_identity_available(catalog_item):
                error = ScraperBoundaryError(
                    ScraperErrorCode.CUSTOMER_IDENTITY_MISSING,
                    "Pricing collection requires a confirmed vehicle OE",
                    retryable=False,
                )
                now = datetime.now(UTC)
                if target.status != "terminal_failure":
                    target.status = "terminal_failure"
                    _set_terminal_target_contract(
                        target,
                        reason=error.code.value,
                        raw_available=target.raw_size_bytes > 0,
                    )
                    target.error_category = error.code.value
                    target.error_detail = str(error)[:4000]
                    target.finished_at = target.finished_at or now
                target.owner_task_id = None
                target.lease_expires_at = None
                item.status = "classified"
                item.error = str(error)[:4000]
                item.checkpoint = {
                    "stage": "classified_without_evidence",
                    "scrape_target_id": str(target.id),
                    "reason": error.code.value,
                    "at": now.isoformat(),
                }
                await session.commit()
                return None
            return await _claim_target_item(
                session,
                item=item,
                run=run,
                catalog_item=catalog_item,
                target=target,
                task_id=task_id,
                is_redelivery=is_redelivery,
            )
        if item.status == "collecting" and item.task_id and item.task_id != task_id:
            return None
        # Legacy/unbounded runs predate the materialized target boundary and
        # therefore have no ``ScrapeTarget`` to carry the start-time identity
        # admission.  Do not let that compatibility path turn an MPN-only
        # customer row into a live Prom query.  The current run creator blocks
        # this earlier; this guard closes the historical worker path as well.
        if not customer_identity_available(catalog_item):
            item.status = "classified"
            item.error = (
                "CUSTOMER_IDENTITY_MISSING: pricing collection requires "
                "a confirmed vehicle OE"
            )[:4000]
            item.checkpoint = {
                "stage": "classified_without_evidence",
                "reason": "customer_identity_missing",
                "at": datetime.now(UTC).isoformat(),
            }
            await session.commit()
            return None
        excluded_seller_ids = frozenset(
            await _owned_seller_external_ids(session, run.workspace_id)
        )
        item.status = "collecting"
        item.task_id = task_id or item.task_id
        item.attempts += 1
        item.started_at = item.started_at or datetime.now(UTC)
        item.error = None
        item.checkpoint = {"stage": "collecting", "at": datetime.now(UTC).isoformat()}
        await session.commit()
        return CollectionClaim(
            action="legacy_collect",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            search_identity=customer_identity_query(catalog_item),
            excluded_seller_ids=excluded_seller_ids,
        )


async def _claim_target_item(
    session,
    *,
    item: PricingRunItem,
    run: PricingRun,
    catalog_item: CatalogItem,
    target: ScrapeTarget,
    task_id: str | None,
    is_redelivery: bool,
) -> CollectionClaim:
    now = datetime.now(UTC)

    if target.status == "succeeded" and target.payload is not None:
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        try:
            output = _verified_target_output(target)
        except ScraperBoundaryError as exc:
            target.status = "terminal_failure"
            _set_terminal_target_contract(
                target,
                reason=exc.code.value,
                raw_available=target.raw_size_bytes > 0,
                parse_failed=True,
            )
            target.error_category = exc.code.value
            target.error_detail = str(exc)[:4000]
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = now
            attempt.status = "terminal_failure"
            attempt.error_category = exc.code.value
            attempt.error_detail = str(exc)[:4000]
            attempt.finished_at = now
            await session.commit()
            return CollectionClaim(
                action="target_terminal",
                run_id=run.id,
                run_item_id=item.id,
                catalog_item_id=catalog_item.id,
                product_url=catalog_item.product_url,
                search_identity=target.query,
                scrape_target_id=target.id,
                scrape_attempt_id=attempt.id,
                delivery_no=attempt.delivery_no,
                terminal_error=exc,
            )
        attempt.status = "duplicate"
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_materialize",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            search_identity=target.query,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
            stored_output=output,
        )

    if target.status == "terminal_failure":
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        try:
            error_code = ScraperErrorCode(
                target.error_category or ScraperErrorCode.UNEXPECTED.value
            )
        except ValueError:
            error_code = ScraperErrorCode.UNEXPECTED
        error = ScraperBoundaryError(
            error_code,
            target.error_detail or "Scrape target is terminal",
            retryable=False,
        )
        attempt.status = "duplicate"
        attempt.error_category = error.code.value
        attempt.error_detail = str(error)[:4000]
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_terminal",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            search_identity=target.query,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
            terminal_error=error,
        )

    if _target_delivery_is_busy(
        target,
        now,
        is_redelivery=is_redelivery,
    ):
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        attempt.status = "duplicate"
        attempt.error_category = ScraperErrorCode.TARGET_BUSY.value
        attempt.error_detail = "Another delivery owns the unexpired target lease"
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_busy",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            search_identity=target.query,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
        )

    superseded_owner = target.status == "collecting"
    if superseded_owner:
        lost_attempts = list(
            (
                await session.scalars(
                    select(ScrapeAttempt).where(
                        ScrapeAttempt.scrape_target_id == target.id,
                        ScrapeAttempt.status == "running",
                    )
                )
            ).all()
        )
        for lost_attempt in lost_attempts:
            lost_attempt.status = "worker_lost"
            lost_attempt.error_category = "worker_lost"
            lost_attempt.error_detail = (
                "Target execution was superseded by a broker redelivery, "
                "bounded retry, or expired lease"
            )
            lost_attempt.finished_at = now
            if lost_attempt.wall_time_ms == 0:
                lost_attempt.wall_time_ms = max(
                    0,
                    round(
                        (now - _aware_datetime(lost_attempt.started_at)).total_seconds()
                        * 1000
                    ),
                )

    # A per-item execution budget must not include time spent waiting in the
    # broker.  Older queued rows may still carry the submission-time deadline,
    # so reset it on their first real claim as well as for newly-created rows.
    if target.network_attempts == 0 and target.first_started_at is None:
        target.deadline_at = now + timedelta(
            seconds=max(1, get_settings().pricing_collection_item_deadline_seconds)
        )

    deadline_expired = (
        target.deadline_at is not None and _aware_datetime(target.deadline_at) <= now
    )
    if target.network_attempts >= target.max_task_executions or deadline_expired:
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        error = ScraperBoundaryError(
            ScraperErrorCode.RETRY_EXHAUSTED,
            "Comparison-job retry budget or item deadline is exhausted",
            retryable=False,
        )
        target.status = "terminal_failure"
        _set_terminal_target_contract(
            target,
            reason=error.code.value,
            raw_available=target.raw_size_bytes > 0,
        )
        target.error_category = error.code.value
        target.error_detail = str(error)
        target.owner_task_id = None
        target.lease_expires_at = None
        target.finished_at = now
        attempt.status = "terminal_failure"
        attempt.error_category = error.code.value
        attempt.error_detail = str(error)
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_terminal",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            search_identity=target.query,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
            terminal_error=error,
        )

    try:
        scrape_input = build_acquisition_input(
            target.input_kind,
            target.query if target.input_kind == "query" else target.original_url,
            query=target.query,
            search_context=(
                customer_search_context(catalog_item)
                if target.input_kind == "query"
                else None
            ),
            fallback_queries=(
                declared_widenings(catalog_item)
                if target.input_kind == "query"
                else None
            ),
            discovery_queries=(
                retrieval_only_queries(catalog_item)
                if target.input_kind == "query"
                else None
            ),
            language="ua",
            adapter_version=target.adapter_version,
        )
    except ScraperBoundaryError as exc:
        attempt = await _create_target_delivery_attempt(
            session,
            target=target,
            item=item,
            task_id=task_id,
            now=now,
        )
        target.status = "terminal_failure"
        _set_terminal_target_contract(
            target,
            reason=exc.code.value,
            raw_available=target.raw_size_bytes > 0,
        )
        target.error_category = exc.code.value
        target.error_detail = str(exc)[:4000]
        target.finished_at = now
        target.owner_task_id = None
        target.lease_expires_at = None
        attempt.status = "terminal_failure"
        attempt.error_category = exc.code.value
        attempt.error_detail = str(exc)[:4000]
        attempt.finished_at = now
        await session.commit()
        return CollectionClaim(
            action="target_terminal",
            run_id=run.id,
            run_item_id=item.id,
            catalog_item_id=catalog_item.id,
            product_url=catalog_item.product_url,
            search_identity=target.query,
            scrape_target_id=target.id,
            scrape_attempt_id=attempt.id,
            delivery_no=attempt.delivery_no,
            terminal_error=exc,
        )

    attempt = await _create_target_delivery_attempt(
        session,
        target=target,
        item=item,
        task_id=task_id,
        now=now,
        advance_fence=True,
    )
    # Read inside the claim transaction so acquisition can drop our own
    # storefronts before the seller cap rather than after it.
    excluded_seller_ids = frozenset(
        await _owned_seller_external_ids(session, run.workspace_id)
    )
    settings = get_settings()
    target.status = "collecting"
    target.execution_status = "RUNNING"
    target.acquisition_status = "NOT_STARTED"
    target.parse_status = "NOT_STARTED"
    target.evidence_status = "NONE"
    target.downstream_eligibility = "UNKNOWN"
    target.operator_action = "NO_RECOMMENDATION"
    target.reason_codes = []
    target.owner_task_id = task_id
    target.lease_expires_at = now + timedelta(
        seconds=max(1, settings.pricing_collection_lease_seconds)
    )
    target.network_attempts += 1
    execution_no = target.network_attempts
    target.first_started_at = target.first_started_at or now
    target.error_category = None
    target.error_detail = None
    attempt.network_attempted = True
    item.status = "collecting"
    item.task_id = task_id or item.task_id
    item.attempts += 1
    item.started_at = item.started_at or now
    item.error = None
    item.checkpoint = {
        "stage": "collecting",
        "scrape_target_id": str(target.id),
        "delivery_no": attempt.delivery_no,
        "execution_no": execution_no,
        "at": now.isoformat(),
    }
    await session.commit()
    return CollectionClaim(
        action="target_collect",
        run_id=run.id,
        run_item_id=item.id,
        catalog_item_id=catalog_item.id,
        product_url=catalog_item.product_url,
        search_identity=target.query,
        scrape_target_id=target.id,
        scrape_attempt_id=attempt.id,
        delivery_no=attempt.delivery_no,
        fencing_token=attempt.fencing_token,
        execution_no=execution_no,
        task_id=task_id,
        scrape_input=scrape_input,
        excluded_seller_ids=excluded_seller_ids,
    )


async def _create_target_delivery_attempt(
    session,
    *,
    target: ScrapeTarget,
    item: PricingRunItem,
    task_id: str | None,
    now: datetime,
    advance_fence: bool = False,
) -> ScrapeAttempt:
    target.delivery_count += 1
    if advance_fence:
        target.fencing_token += 1
    attempt_fencing_token = max(1, target.fencing_token)
    attempt = ScrapeAttempt(
        scrape_target_id=target.id,
        pricing_run_item_id=item.id,
        task_id=task_id,
        delivery_no=target.delivery_count,
        fencing_token=attempt_fencing_token,
        network_attempted=False,
        status="running",
        started_at=now,
    )
    session.add(attempt)
    await session.flush()
    return attempt


async def _persist_target_success(
    claim: CollectionClaim,
    trace: ScrapeExecutionTrace,
    measurement: AttemptMeasurement,
    output: ScrapeOutput,
) -> bool:
    completed_requests = trace.drain_completed_requests()
    try:
        async with async_session_factory() as session:
            target = await session.scalar(
                select(ScrapeTarget)
                .where(ScrapeTarget.id == claim.scrape_target_id)
                .with_for_update()
            )
            attempt = await session.get(ScrapeAttempt, claim.scrape_attempt_id)
            if target is None or attempt is None:
                raise PricingItemNotFoundError("Scrape target attempt disappeared")
            if not _target_claim_is_current(target, attempt, claim):
                _mark_stale_target_attempt(
                    attempt,
                    measurement,
                    "Target success rejected by execution fence",
                )
                await session.commit()
                pricing_event(
                    "scrape_stale_execution_rejected",
                    item_kind="comparison_job",
                    pricing_run_id=str(claim.run_id),
                    scrape_target_id=str(claim.scrape_target_id),
                    delivery_no=claim.delivery_no,
                    execution_no=claim.execution_no,
                )
                return False
            await persist_http_traces(
                session,
                completed_requests,
                execution_no=claim.delivery_no,
                scrape_target_id=target.id,
            )
            raw_bytes = await retained_raw_evidence_bytes(
                session,
                scrape_target_id=target.id,
            )
            if raw_bytes <= 0:
                raise ScraperBoundaryError(
                    ScraperErrorCode.EVIDENCE_PERSISTENCE,
                    "Structured scraper output has no retained raw HTTP evidence",
                    retryable=False,
                )
            now = datetime.now(UTC)
            target.status = "succeeded"
            target.execution_status = "SUCCEEDED"
            target.acquisition_status = "SUCCEEDED"
            target.parse_status = "SUCCEEDED"
            target.evidence_status = "STRUCTURED_AVAILABLE"
            target.downstream_eligibility = "UNKNOWN"
            target.operator_action = "NO_RECOMMENDATION"
            target.reason_codes = []
            target.winning_attempt_id = attempt.id
            target.payload = output.payload
            target.content_sha256 = output.content_sha256
            target.raw_size_bytes = raw_bytes
            target.structured_size_bytes = output.structured_size_bytes
            target.metadata_size_bytes = output.metadata_size_bytes
            target.structured_completeness = Decimal(
                str(output.structured_completeness)
            )
            target.error_category = None
            target.error_detail = None
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = now
            attempt.status = "succeeded"
            attempt.wall_time_ms = measurement.wall_time_ms
            attempt.cpu_time_ms = measurement.cpu_time_ms
            attempt.memory_peak_bytes = measurement.memory_peak_bytes
            attempt.raw_size_bytes = raw_bytes
            attempt.structured_size_bytes = output.structured_size_bytes
            attempt.metadata_size_bytes = output.metadata_size_bytes
            attempt.structured_completeness = Decimal(
                str(output.structured_completeness)
            )
            attempt.finished_at = now
            await session.commit()
            coverage = await _target_evidence_coverage(
                target.id,
                execution_no=claim.delivery_no,
            )
            # What the page cap cost, measured rather than assumed.  Catalog
            # discovery has reported this since 2026-07-26; without it the
            # pricing path could not say whether a thin market was the market
            # or the cap.
            reported_total, pages_fetched = reported_total_from_search_pages(
                completed_requests
            )
            unfetched_count, coverage_ratio, coverage_reason = coverage_summary(
                reported_total=reported_total,
                retrieved_count=len(output.comparison_payload.get("offers") or ()),
                request_count=pages_fetched,
                search_page_limit=max(
                    1,
                    get_settings().pricing_scraper_max_search_pages,
                ),
            )
            pricing_event(
                "scrape_items_terminal",
                status="success",
                item_kind="comparison_job",
                pricing_run_id=str(claim.run_id),
                scrape_target_id=str(target.id),
                delivery_no=claim.delivery_no,
                evidence_coverage=str(coverage),
                structured_completeness=str(output.structured_completeness),
                prom_reported_total=reported_total,
                search_pages_fetched=pages_fetched,
                unfetched_count=unfetched_count,
                coverage_ratio=(
                    None if coverage_ratio is None else str(coverage_ratio)
                ),
                coverage_reason=coverage_reason,
            )
            return True
    except Exception:
        trace.restore_completed_requests(completed_requests)
        raise


async def _persist_target_failure(
    claim: CollectionClaim,
    trace: ScrapeExecutionTrace,
    measurement: AttemptMeasurement,
    error: ScraperBoundaryError,
) -> bool:
    completed_requests = trace.drain_completed_requests()
    try:
        async with async_session_factory() as session:
            target = await session.scalar(
                select(ScrapeTarget)
                .where(ScrapeTarget.id == claim.scrape_target_id)
                .with_for_update()
            )
            attempt = await session.get(ScrapeAttempt, claim.scrape_attempt_id)
            item = await session.get(PricingRunItem, claim.run_item_id)
            if target is None or attempt is None or item is None:
                return False
            if not _target_claim_is_current(target, attempt, claim):
                _mark_stale_target_attempt(
                    attempt,
                    measurement,
                    "Target failure rejected by execution fence",
                )
                await session.commit()
                pricing_event(
                    "scrape_stale_execution_rejected",
                    item_kind="comparison_job",
                    pricing_run_id=str(claim.run_id),
                    scrape_target_id=str(claim.scrape_target_id),
                    delivery_no=claim.delivery_no,
                    execution_no=claim.execution_no,
                )
                return False
            await persist_http_traces(
                session,
                completed_requests,
                execution_no=claim.delivery_no,
                scrape_target_id=target.id,
            )
            raw_bytes = await retained_raw_evidence_bytes(
                session,
                scrape_target_id=target.id,
            )
            now = datetime.now(UTC)
            target.status = (
                "retryable_failure" if error.retryable else "terminal_failure"
            )
            raw_parse_failure = raw_bytes > 0 and error.code in {
                ScraperErrorCode.PARSE_CONTRACT,
                ScraperErrorCode.PARSER_SCHEMA_CHANGED,
                ScraperErrorCode.SERIALIZATION,
            }
            target.execution_status = (
                "RETRY_WAIT" if error.retryable else "TERMINAL_FAILED"
            )
            target.acquisition_status = (
                "BLOCKED"
                if error.code == ScraperErrorCode.SOURCE_ACCESS_BLOCKED
                else ("SUCCEEDED" if raw_parse_failure else "FAILED")
            )
            target.parse_status = "FAILED" if raw_parse_failure else "NOT_STARTED"
            target.evidence_status = "RAW_AVAILABLE" if raw_bytes > 0 else "NONE"
            target.downstream_eligibility = (
                "UNKNOWN" if error.retryable else "INELIGIBLE"
            )
            target.operator_action = (
                "REPLAY_REQUIRED" if raw_parse_failure else "NO_RECOMMENDATION"
            )
            target.reason_codes = [error.code.value]
            target.error_category = error.code.value
            target.error_detail = str(error)[:4000]
            target.raw_size_bytes = raw_bytes
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = None if error.retryable else now
            attempt.status = (
                "retryable_failure" if error.retryable else "terminal_failure"
            )
            attempt.error_category = error.code.value
            attempt.error_detail = str(error)[:4000]
            attempt.wall_time_ms = measurement.wall_time_ms
            attempt.cpu_time_ms = measurement.cpu_time_ms
            attempt.memory_peak_bytes = measurement.memory_peak_bytes
            attempt.raw_size_bytes = raw_bytes
            attempt.finished_at = now
            item.error = f"{error.code.value}: {error}"[:4000]
            item.checkpoint = {
                "stage": ("retry_wait" if error.retryable else "terminal_failure"),
                "scrape_target_id": str(target.id),
                "delivery_no": claim.delivery_no,
                "error_category": error.code.value,
                "at": now.isoformat(),
            }
            await session.commit()
            pricing_event(
                (
                    "scrape_task_retry_wait"
                    if error.retryable
                    else "scrape_items_terminal"
                ),
                status="retry_wait" if error.retryable else "failed",
                item_kind="comparison_job",
                pricing_run_id=str(claim.run_id),
                scrape_target_id=str(target.id),
                delivery_no=claim.delivery_no,
                error_category=error.code.value,
            )
            if error.code == ScraperErrorCode.PARSER_SCHEMA_CHANGED:
                pricing_event(
                    "prom_parser_schema_changed_total",
                    pricing_run_id=str(claim.run_id),
                    scrape_target_id=str(target.id),
                    source_type=target.source_type,
                    value=1,
                )
            return True
    except Exception:
        trace.restore_completed_requests(completed_requests)
        raise


def _target_claim_is_current(
    target: ScrapeTarget,
    attempt: ScrapeAttempt,
    claim: CollectionClaim,
) -> bool:
    explicit_fence_matches = claim.fencing_token == 0 or (
        getattr(target, "fencing_token", None) == claim.fencing_token
        and getattr(attempt, "fencing_token", None) == claim.fencing_token
    )
    return bool(
        claim.scrape_attempt_id is not None
        and attempt.id == claim.scrape_attempt_id
        and target.status == "collecting"
        and target.owner_task_id == claim.task_id
        and target.network_attempts == claim.execution_no
        and explicit_fence_matches
        and attempt.status == "running"
        and attempt.delivery_no == claim.delivery_no
        and attempt.task_id == claim.task_id
    )


def _target_lease_is_active(target: ScrapeTarget, now: datetime) -> bool:
    return bool(
        target.status == "collecting"
        and target.lease_expires_at is not None
        and _aware_datetime(target.lease_expires_at) > _aware_datetime(now)
    )


def _target_delivery_is_busy(
    target: ScrapeTarget,
    now: datetime,
    *,
    is_redelivery: bool,
) -> bool:
    return _target_lease_is_active(target, now) and not is_redelivery


def _mark_stale_target_attempt(
    attempt: ScrapeAttempt,
    measurement: AttemptMeasurement,
    detail: str,
) -> None:
    if attempt.status != "running":
        return
    attempt.status = "worker_lost"
    attempt.error_category = "stale_execution"
    attempt.error_detail = detail
    attempt.wall_time_ms = measurement.wall_time_ms
    attempt.cpu_time_ms = measurement.cpu_time_ms
    attempt.memory_peak_bytes = measurement.memory_peak_bytes
    attempt.finished_at = datetime.now(UTC)


def _set_terminal_target_contract(
    target: ScrapeTarget,
    *,
    reason: str,
    raw_available: bool,
    parse_failed: bool = False,
) -> None:
    """Keep legacy target state and the v2 multi-axis contract consistent."""

    target.execution_status = "TERMINAL_FAILED"
    target.acquisition_status = (
        "SUCCEEDED" if raw_available and parse_failed else "FAILED"
    )
    target.parse_status = "FAILED" if parse_failed else "NOT_STARTED"
    target.evidence_status = "RAW_AVAILABLE" if raw_available else "NONE"
    target.downstream_eligibility = "INELIGIBLE"
    target.operator_action = "REPLAY_REQUIRED" if parse_failed else "NO_RECOMMENDATION"
    target.reason_codes = [reason]


async def _refresh_target_attempt_measurement(
    claim: CollectionClaim,
    measurement: AttemptMeasurement,
) -> None:
    """Persist full worker occupancy after evidence fan-out or failure handling."""

    if claim.scrape_attempt_id is None:
        return
    async with async_session_factory() as session:
        attempt = await session.get(ScrapeAttempt, claim.scrape_attempt_id)
        if attempt is None:
            return
        attempt.wall_time_ms = measurement.wall_time_ms
        attempt.cpu_time_ms = measurement.cpu_time_ms
        attempt.memory_peak_bytes = max(
            attempt.memory_peak_bytes,
            measurement.memory_peak_bytes,
        )
        if attempt.status != "running":
            attempt.finished_at = datetime.now(UTC)
        await session.commit()


async def _materialize_target_evidence(scrape_target_id: UUID) -> None:
    """Atomically materialize evidence and persist a typed accounting failure."""

    try:
        await _materialize_target_evidence_transaction(scrape_target_id)
    except EvidenceAccountingError as exc:
        await _mark_evidence_accounting_error(scrape_target_id, exc)
        raise


async def _materialize_target_evidence_transaction(scrape_target_id: UUID) -> None:
    """Fan one immutable target output into item-scoped Metis evidence."""

    async with async_session_factory() as session:
        target = await session.scalar(
            select(ScrapeTarget)
            .where(ScrapeTarget.id == scrape_target_id)
            .with_for_update()
        )
        if target is None or target.payload is None or target.status != "succeeded":
            raise PricingItemNotFoundError(
                f"Succeeded scrape target {scrape_target_id} is unavailable"
            )
        output = _verified_target_output(target)
        raw_manifest = await _verified_raw_evidence_manifest(session, target.id)
        raw_manifest_sha256 = canonical_sha256(raw_manifest)
        run = await session.get(PricingRun, target.pricing_run_id)
        if run is None:
            raise PricingItemNotFoundError("Pricing run disappeared")
        # Отождествление и материализация наблюдений тоже читают позицию
        # каталога (OE, категория). Для прогона с контрактом сюда обязан
        # приехать замороженный вид, иначе часть прогона сравнивается с одним
        # артикулом, часть — с другим, и следа об этом не остаётся.
        rows = [
            (run_item, resolve_bound_execution_item(run, run_item, live_item))
            for run_item, live_item in (
                await session.execute(
                    select(PricingRunItem, CatalogItem)
                    .join(
                        CatalogItem,
                        CatalogItem.id == PricingRunItem.catalog_item_id,
                    )
                    .where(PricingRunItem.scrape_target_id == target.id)
                    .order_by(PricingRunItem.created_at, PricingRunItem.id)
                )
            ).all()
        ]
        # Defence in depth.  Acquisition already drops these before the seller
        # cap; this second pass still has to run, because a target collected
        # before a store was registered — or by an older worker — can carry our
        # own storefronts into materialization.
        owned_sellers = await _owned_seller_external_ids(session, run.workspace_id)
        brand_tiers, brand_confidence = await _load_brand_rules(
            session,
            run.workspace_id,
        )
        records = output.candidate_records
        observed_at = target.finished_at or datetime.now(UTC)
        materialized = 0
        materialized_capture_ids: list[UUID] = []
        aggregate_accounting = OfferAccounting(
            retrieved=0,
            observations_persisted=0,
            rejected=0,
            internal_failures=0,
        )
        for run_item, catalog_item in rows:
            if run_item.status in {
                "calculated",
                "manual_review",
                "failed",
                "cancelled",
            }:
                continue
            item_accounting: OfferAccounting | None = None
            existing_capture = await session.scalar(
                select(RawMarketCapture).where(
                    RawMarketCapture.pricing_run_item_id == run_item.id,
                    RawMarketCapture.content_sha256 == target.content_sha256,
                )
            )
            if existing_capture is None:
                capture = RawMarketCapture(
                    pricing_run_item_id=run_item.id,
                    scrape_target_id=target.id,
                    source=target.source_type,
                    capture_kind="parser_output_ref",
                    payload={
                        "schema_version": "metis-scrape-target-ref-v2",
                        "scrape_target_id": str(target.id),
                        "canonical_output_sha256": target.content_sha256,
                        "raw_manifest_sha256": raw_manifest_sha256,
                        "raw_evidence": raw_manifest,
                        "adapter_version": target.adapter_version,
                        "parser_name": target.parser_name,
                        "parser_config_hash": target.parser_config_hash,
                        "output_schema_version": target.output_schema_version,
                        "source_policy_decision_id": target.source_policy_decision_id,
                        "source_policy_version": target.source_policy_version,
                        "source_lane": target.source_lane,
                    },
                    content_sha256=target.content_sha256 or output.content_sha256,
                    parser_version=target.adapter_version,
                    raw_size_bytes=target.raw_size_bytes,
                    structured_size_bytes=target.structured_size_bytes,
                    metadata_size_bytes=target.metadata_size_bytes,
                    structured_completeness=target.structured_completeness,
                    captured_at=observed_at,
                )
                session.add(capture)
                await session.flush()
                materialized_capture_ids.append(capture.id)
                confirmed_crosses = await _load_confirmed_crosses(
                    session,
                    run=run,
                    search_identity=target.query,
                )
                accounting = await _persist_payload_observations(
                    session,
                    run=run,
                    run_item=run_item,
                    catalog_item=catalog_item,
                    capture=capture,
                    offers=list(records),
                    owned_sellers=owned_sellers,
                    brand_tiers=brand_tiers,
                    brand_confidence=brand_confidence,
                    observed_at=observed_at,
                    source_type=target.source_type,
                    confirmed_crosses=confirmed_crosses,
                    # Ключи только-извлечения, замороженные тем же входом. Без
                    # них строка, найденная по ним, роняла бы прогон как
                    # незаявленное расширение.
                    declared_discovery_queries=(
                        declared_discovery_queries_from_payload(output.input_payload)
                    ),
                    # Конверт приобретения: подготовленный URL, идентичность
                    # запроса и запрошенный номер приезжают из самого payload-а,
                    # а не восстанавливаются из каталога.
                    prepared_url=output.prepared_url,
                    acquisition_input_hash=output.input_hash,
                    acquisition_query=output.acquisition_query,
                    requested_query=output.requested_query,
                )
                _validate_offer_accounting(
                    accounting,
                    pricing_run_id=run.id,
                    pricing_run_item_id=run_item.id,
                )
                item_accounting = accounting
                await _enqueue_ai_evidence_shadow(
                    session,
                    run=run,
                    run_item=run_item,
                    capture=capture,
                )
                aggregate_accounting = OfferAccounting(
                    retrieved=aggregate_accounting.retrieved + accounting.retrieved,
                    observations_persisted=(
                        aggregate_accounting.observations_persisted
                        + accounting.observations_persisted
                    ),
                    rejected=aggregate_accounting.rejected + accounting.rejected,
                    internal_failures=(
                        aggregate_accounting.internal_failures
                        + accounting.internal_failures
                    ),
                )
                materialized += 1
            item_failed = bool(
                item_accounting is not None and item_accounting.internal_failures > 0
            )
            run_item.status = "failed" if item_failed else "classified"
            run_item.error = (
                "FAILED_INTERNAL_PROCESSING in retained offer batch"
                if item_failed
                else None
            )
            run_item.finished_at = datetime.now(UTC) if item_failed else None
            run_item.checkpoint = {
                "stage": (
                    "partial_materialization_failed" if item_failed else "classified"
                ),
                "scrape_target_id": str(target.id),
                "content_sha256": target.content_sha256,
                "offers": len(records),
                "offer_accounting": accounting.as_dict()
                if existing_capture is None
                else {},
                "at": datetime.now(UTC).isoformat(),
            }
        target.evidence_status = "INGESTED"
        if aggregate_accounting.internal_failures:
            target.status = "terminal_failure"
            target.execution_status = "TERMINAL_FAILED"
            target.downstream_eligibility = "INELIGIBLE"
            target.operator_action = "MANUAL_REVIEW_REQUIRED"
            target.reason_codes = ["OFFER_INTERNAL_FAILURE_PARTIAL"]
            target.error_category = "OFFER_INTERNAL_FAILURE_PARTIAL"
            target.error_detail = (
                f"{aggregate_accounting.internal_failures} candidate(s) failed "
                "inside enrichment"
            )
        else:
            target.downstream_eligibility = "UNKNOWN"
            target.operator_action = "NO_RECOMMENDATION"
        _validate_offer_accounting(
            aggregate_accounting,
            pricing_run_id=run.id,
            pricing_run_item_id=None,
        )
        await session.commit()
        if materialized_capture_ids:
            outcome_rows = list(
                (
                    await session.execute(
                        select(
                            OfferProcessingOutcome.outcome_code,
                            func.count(OfferProcessingOutcome.id),
                        )
                        .where(
                            OfferProcessingOutcome.raw_market_capture_id.in_(
                                materialized_capture_ids
                            )
                        )
                        .group_by(OfferProcessingOutcome.outcome_code)
                    )
                ).all()
            )
            for outcome_code, count in outcome_rows:
                pricing_event(
                    "offer_outcomes_total",
                    pricing_run_id=str(run.id),
                    scrape_target_id=str(target.id),
                    outcome_code=outcome_code,
                    value=int(count),
                )
                if outcome_code == OfferOutcomeCode.OBSERVATION_PERSISTED.value:
                    pricing_event(
                        "offer_observation_persisted_total",
                        pricing_run_id=str(run.id),
                        value=int(count),
                    )
                elif outcome_code == OfferOutcomeCode.FAILED_INTERNAL_PROCESSING.value:
                    pricing_event(
                        "offer_internal_failure_total",
                        pricing_run_id=str(run.id),
                        reason=outcome_code,
                        value=int(count),
                    )
                else:
                    pricing_event(
                        "offer_rejected_total",
                        pricing_run_id=str(run.id),
                        reason=outcome_code,
                        value=int(count),
                    )
            observation_rows = list(
                (
                    await session.execute(
                        select(
                            MarketObservation.oe_verification_status,
                            MarketObservation.automatic_eligible,
                            MarketObservation.source_confidence,
                            MarketObservation.oe_evidence,
                        ).where(
                            MarketObservation.raw_capture_id.in_(
                                materialized_capture_ids
                            )
                        )
                    )
                ).all()
            )
            for (
                oe_status,
                automatic_eligible,
                source_confidence,
                oe_evidence,
            ) in observation_rows:
                pricing_event(
                    "oe_verification_total",
                    pricing_run_id=str(run.id),
                    status=oe_status,
                    value=1,
                )
                status_metric = {
                    OeVerificationStatus.VERIFIED_EXACT.value: (
                        "oe_verified_exact_total"
                    ),
                    OeVerificationStatus.VERIFIED_CROSS.value: (
                        "oe_verified_cross_total"
                    ),
                    OeVerificationStatus.UNKNOWN.value: "oe_unknown_total",
                    OeVerificationStatus.CONFLICT.value: "oe_conflict_total",
                    OeVerificationStatus.AMBIGUOUS.value: "oe_ambiguous_total",
                }.get(oe_status)
                if status_metric is not None:
                    pricing_event(
                        status_metric,
                        pricing_run_id=str(run.id),
                        value=1,
                    )
                for evidence_item in (
                    oe_evidence if isinstance(oe_evidence, list) else []
                ):
                    if isinstance(evidence_item, Mapping):
                        pricing_event(
                            "oe_extraction_total",
                            pricing_run_id=str(run.id),
                            source_kind=str(
                                evidence_item.get("source_kind") or "UNKNOWN"
                            ),
                            value=1,
                        )
                pricing_event(
                    (
                        "automatic_eligible_total"
                        if automatic_eligible
                        else "automatic_ineligible_total"
                    ),
                    pricing_run_id=str(run.id),
                    value=1,
                )
                pricing_event(
                    "source_confidence_bucket",
                    pricing_run_id=str(run.id),
                    bucket=_source_confidence_bucket(source_confidence),
                    value=1,
                )
        if not records:
            pricing_event(
                "prom_empty_search_result_total",
                pricing_run_id=str(run.id),
                scrape_target_id=str(target.id),
                input_kind=target.input_kind,
                value=1,
            )
        pricing_event(
            "offer_retrieved_total",
            pricing_run_id=str(run.id),
            scrape_target_id=str(target.id),
            value=aggregate_accounting.retrieved,
        )
        pricing_event(
            "scrape_target_materialized",
            pricing_run_id=str(run.id),
            scrape_target_id=str(target.id),
            dependent_items=len(rows),
            newly_materialized_items=materialized,
            offers=len(records),
            offer_retrieved_total=aggregate_accounting.retrieved,
            offer_observation_persisted_total=(
                aggregate_accounting.observations_persisted
            ),
            offer_rejected_total=aggregate_accounting.rejected,
            offer_internal_failure_total=aggregate_accounting.internal_failures,
        )


async def _mark_evidence_accounting_error(
    scrape_target_id: UUID,
    error: EvidenceAccountingError,
) -> None:
    """Fail closed after the materialization transaction has rolled back."""

    async with async_session_factory() as session:
        target = await session.scalar(
            select(ScrapeTarget)
            .where(ScrapeTarget.id == scrape_target_id)
            .with_for_update()
        )
        if target is None:
            return
        now = datetime.now(UTC)
        target.status = "terminal_failure"
        target.execution_status = "TERMINAL_FAILED"
        target.acquisition_status = "SUCCEEDED"
        target.parse_status = "SUCCEEDED"
        target.evidence_status = "RAW_AVAILABLE"
        target.downstream_eligibility = "INELIGIBLE"
        target.operator_action = "REPLAY_REQUIRED"
        target.reason_codes = ["EVIDENCE_ACCOUNTING_ERROR"]
        target.error_category = "EVIDENCE_ACCOUNTING_ERROR"
        target.error_detail = str(error)[:4000]
        target.owner_task_id = None
        target.lease_expires_at = None
        target.finished_at = now
        items = list(
            (
                await session.scalars(
                    select(PricingRunItem).where(
                        PricingRunItem.scrape_target_id == target.id,
                        PricingRunItem.status.notin_(
                            ("calculated", "manual_review", "cancelled")
                        ),
                    )
                )
            ).all()
        )
        for item in items:
            item.status = "failed"
            item.error = f"EVIDENCE_ACCOUNTING_ERROR: {error}"[:4000]
            item.finished_at = now
            item.checkpoint = {
                "stage": "evidence_accounting_failed",
                "scrape_target_id": str(target.id),
                "reason": "EVIDENCE_ACCOUNTING_ERROR",
                "at": now.isoformat(),
            }
        await session.commit()


async def _verified_raw_evidence_manifest(
    session,
    scrape_target_id: UUID,
) -> list[dict[str, Any]]:
    """Return a hash-verified, ordered HTTP evidence manifest for Metis lineage."""

    await load_replay_cache(session, scrape_target_id=scrape_target_id)
    rows = list(
        (
            await session.execute(
                select(ScrapeHttpRequest, ScrapeEvidenceBlob)
                .join(
                    ScrapeEvidenceBlob,
                    ScrapeEvidenceBlob.id == ScrapeHttpRequest.evidence_blob_id,
                )
                .where(
                    ScrapeHttpRequest.scrape_target_id == scrape_target_id,
                    ScrapeHttpRequest.outcome.in_(("success", "replayed")),
                )
                .order_by(
                    ScrapeHttpRequest.execution_no,
                    ScrapeHttpRequest.sequence_no,
                    ScrapeHttpRequest.id,
                )
            )
        ).all()
    )
    if not rows:
        raise ScraperBoundaryError(
            ScraperErrorCode.EVIDENCE_PERSISTENCE,
            "Metis evidence ingestion requires retained raw HTTP captures",
            retryable=False,
        )
    return [
        {
            "logical_request_id": str(request.id),
            "request_key": request.request_key,
            "request_kind": request.request_kind,
            "prepared_url": request.prepared_url,
            "execution_no": request.execution_no,
            "sequence_no": request.sequence_no,
            "evidence_blob_id": str(blob.id),
            "raw_content_sha256": blob.content_sha256,
            "raw_size_bytes": blob.raw_size_bytes,
            "stored_size_bytes": blob.stored_size_bytes,
        }
        for request, blob in rows
    ]


async def _load_confirmed_crosses(
    session,
    *,
    run: PricingRun,
    search_identity: str,
) -> tuple[ConfirmedCross, ...]:
    """Load explicit one-hop CONFIRMED run evidence in either orientation."""

    normalized_search_identity = normalize_oe(search_identity)
    if normalized_search_identity is None:
        return ()

    rows = list(
        (
            await session.scalars(
                select(CrossLink)
                .where(
                    CrossLink.workspace_id == run.workspace_id,
                    CrossLink.pricing_run_id == run.id,
                    CrossLink.validation_status == "CONFIRMED",
                    or_(
                        CrossLink.our_oem_norm == normalized_search_identity,
                        CrossLink.extracted_oem_norm == normalized_search_identity,
                    ),
                )
                .order_by(
                    CrossLink.our_oem_norm,
                    CrossLink.extracted_oem_norm,
                    CrossLink.id,
                )
            )
        ).all()
    )
    # A public OE may occur on more than one owned catalog item.  The global
    # catalog reader already quarantines that fan-out; the run-local CrossLink
    # reader must enforce the same rule or a single ambiguous edge can widen a
    # different SKU's market.  First collect the candidate endpoints from the
    # query, then fetch only rows touching those endpoints (not the whole run).
    candidate_endpoints: set[str] = set()
    for row in rows:
        if not catalog_identity_pair_has_safe_shape(
            row.our_oem_norm, row.extracted_oem_norm
        ):
            continue
        left = normalize_oe(row.our_oem_norm)
        right = normalize_oe(row.extracted_oem_norm)
        if left != normalized_search_identity and right != normalized_search_identity:
            continue
        details = (
            row.validation_details
            if isinstance(row.validation_details, Mapping)
            else {}
        )
        if details.get("automatic_eligible") is True and left and right:
            candidate_endpoints.add(
                right if left == normalized_search_identity else left
            )
    related_rows: list[CrossLink] = []
    if candidate_endpoints:
        related_rows = list(
            (
                await session.scalars(
                    select(CrossLink)
                    .where(
                        CrossLink.workspace_id == run.workspace_id,
                        CrossLink.pricing_run_id == run.id,
                        CrossLink.validation_status == "CONFIRMED",
                        or_(
                            CrossLink.our_oem_norm.in_(candidate_endpoints),
                            CrossLink.extracted_oem_norm.in_(candidate_endpoints),
                        ),
                    )
                    .order_by(
                        CrossLink.our_oem_norm,
                        CrossLink.extracted_oem_norm,
                        CrossLink.id,
                    )
                )
            ).all()
        )
    all_rows: list[CrossLink] = []
    seen_row_ids: set[str] = set()
    for row in (*rows, *related_rows):
        row_id = str(row.id)
        if row_id in seen_row_ids:
            continue
        seen_row_ids.add(row_id)
        all_rows.append(row)

    memberships: dict[str, set[str]] = {}
    for row in all_rows:
        if not catalog_identity_pair_has_safe_shape(
            row.our_oem_norm, row.extracted_oem_norm
        ):
            continue
        details = (
            row.validation_details
            if isinstance(row.validation_details, Mapping)
            else {}
        )
        if details.get("automatic_eligible") is not True:
            continue
        try:
            confidence = Decimal(str(details.get("confidence")))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not confidence.is_finite() or not Decimal("0") < confidence <= Decimal("1"):
            continue
        left = normalize_oe(row.our_oem_norm)
        right = normalize_oe(row.extracted_oem_norm)
        item_id = str(row.catalog_item_id)
        if left and right and item_id:
            memberships.setdefault(left, set()).add(item_id)
            memberships.setdefault(right, set()).add(item_id)
    ambiguous_endpoints = {
        number for number, item_ids in memberships.items() if len(item_ids) > 1
    }
    result: list[ConfirmedCross] = []
    seen_candidates: set[str] = set()
    for row in rows:
        if not catalog_identity_pair_has_safe_shape(
            row.our_oem_norm, row.extracted_oem_norm
        ):
            continue
        row_our = normalize_oe(row.our_oem_norm)
        row_extracted = normalize_oe(row.extracted_oem_norm)
        if normalized_search_identity not in {row_our, row_extracted}:
            # Defense in depth for alternate dialects, replay fakes, and a
            # future query refactor: only an edge incident to this search may
            # leave the reader.
            continue
        validation_details = (
            row.validation_details
            if isinstance(row.validation_details, Mapping)
            else {}
        )
        # Both the customer identity snapshot and the description-cross
        # snapshot must carry the explicit admission decision that produced
        # them.  The catalog snapshot is a stronger source, but its method
        # name alone is not a proof: a partially written/review-only row must
        # never widen the one-hop graph into a pricing run.
        if validation_details.get("automatic_eligible") is not True:
            continue
        raw_confidence = validation_details.get("confidence")
        try:
            confidence = Decimal(str(raw_confidence))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if not confidence.is_finite() or not Decimal("0") < confidence <= Decimal("1"):
            continue
        candidate_identity = (
            row.extracted_oem_norm
            if row_our == normalized_search_identity
            else row.our_oem_norm
        )
        candidate_identity = normalize_oe(candidate_identity)
        if candidate_identity is None or candidate_identity in seen_candidates:
            continue
        if candidate_identity in ambiguous_endpoints:
            # Keep the row visible in raw evidence, but never let a public
            # number shared by multiple catalog items become a pricing cross.
            continue
        seen_candidates.add(candidate_identity)
        result.append(
            ConfirmedCross(
                search_oe_norm=normalized_search_identity,
                candidate_oe_norm=candidate_identity,
                canonical_identity_key=canonical_cross_identity_key(
                    row.our_oem_norm,
                    row.extracted_oem_norm,
                ),
                confidence=confidence,
                cross_link_id=str(row.id),
            )
        )
    return tuple(result)


def _offer_payload_sha256(raw_offer: Any) -> str | None:
    """Return a deterministic identity for one candidate without hiding bad JSON."""

    try:
        payload = json.dumps(
            raw_offer,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(payload).hexdigest()


def _verified_capture_raw_evidence(
    capture: RawMarketCapture,
) -> tuple[Mapping[str, Any], ...]:
    """Return the capture manifest only when its canonical hash still matches."""

    capture_payload = getattr(capture, "payload", None)
    payload = capture_payload if isinstance(capture_payload, Mapping) else {}
    raw_evidence = payload.get("raw_evidence")
    expected_hash = str(payload.get("raw_manifest_sha256") or "").casefold()
    if isinstance(raw_evidence, list) and raw_evidence:
        actual_hash = canonical_sha256(raw_evidence)
        entries_valid = all(
            isinstance(entry, Mapping)
            and len(str(entry.get("raw_content_sha256") or "")) == 64
            and set(str(entry.get("raw_content_sha256") or "").casefold()).issubset(
                set("0123456789abcdef")
            )
            for entry in raw_evidence
        )
        if entries_valid and actual_hash == expected_hash:
            return tuple(raw_evidence)
    return ()


def _candidate_raw_manifest(
    capture: RawMarketCapture,
    *,
    source_record_id: str,
) -> dict[str, str]:
    """Bind a candidate to the verified retained-HTTP manifest for its capture.

    The current parser output does not expose a page number for every product.
    Therefore the smallest truthful immutable lineage unit is the complete,
    ordered HTTP manifest stored by ``_materialize_target_evidence``.  Its hash
    is recomputed here; a missing or inconsistent manifest deliberately yields
    an empty hash and can never verify OE identity or source provenance.
    """

    raw_evidence = _verified_capture_raw_evidence(capture)
    return {
        "source_record_id": source_record_id,
        "raw_capture_id": str(capture.id),
        "raw_content_sha256": (
            canonical_sha256(list(raw_evidence)) if raw_evidence else ""
        ),
    }


def _offer_outcome(
    *,
    run_item: PricingRunItem,
    capture: RawMarketCapture,
    raw_offer_index: int,
    outcome_code: OfferOutcomeCode,
    stage: str,
    reason_codes: tuple[str, ...],
    payload_sha256: str | None,
    safe_sample: dict[str, Any],
    market_observation_id: UUID | None = None,
    source_listing_id: str | None = None,
) -> OfferProcessingOutcome:
    return OfferProcessingOutcome(
        pricing_run_item_id=run_item.id,
        raw_market_capture_id=capture.id,
        market_observation_id=market_observation_id,
        source_listing_id=source_listing_id,
        raw_offer_index=raw_offer_index,
        outcome_code=outcome_code.value,
        stage=stage,
        reason_codes=list(reason_codes),
        payload_sha256=payload_sha256,
        safe_sample=safe_sample,
    )


def _internal_offer_error_diagnostic(
    error: Exception,
) -> tuple[str, str, tuple[str, ...]]:
    """Return a stable root-cause fingerprint without logging source payloads."""

    stack_frames = tuple(
        f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}:{frame.name}"
        for frame in traceback.extract_tb(error.__traceback__)[-8:]
    )
    message_sha256 = hashlib.sha256(
        str(error).encode("utf-8", errors="replace")
    ).hexdigest()
    fingerprint = canonical_sha256(
        {
            "exception_type": type(error).__name__,
            "message_sha256": message_sha256,
            "stack_frames": stack_frames,
        }
    )
    return fingerprint, message_sha256, stack_frames


def _validate_offer_accounting(
    accounting: OfferAccounting,
    *,
    pricing_run_id: UUID,
    pricing_run_item_id: UUID | None,
) -> None:
    try:
        accounting.validate()
    except ValueError:
        pricing_event(
            "evidence_accounting_error_total",
            pricing_run_id=str(pricing_run_id),
            pricing_run_item_id=(
                str(pricing_run_item_id)
                if pricing_run_item_id is not None
                else "aggregate"
            ),
            value=1,
        )
        raise


def _record_acquisition(raw_offer: Any) -> Mapping[str, Any] | None:
    """The origin block the acquisition boundary attached to one candidate."""

    if not isinstance(raw_offer, Mapping):
        return None
    value = raw_offer.get("acquisition")
    return value if isinstance(value, Mapping) else None


def _persisted_retrieval_kind(raw_offer: Any, candidate: AcceptedCandidate) -> str:
    """Retrieval kind stored on the observation, widening never lost.

    ``retrieval_kind`` is the only origin field that survives the
    ``comparison_evidence_from_dict``/``_to_dict`` round trip OE re-enrichment
    performs, so it carries the widening.  A payload whose provenance block and
    retrieval kind disagree is resolved towards the widened reading: claiming
    our own part code's market when the offers came from a related number's is
    the failure that must not be storable.
    """

    acquisition = _record_acquisition(raw_offer)
    if acquisition is not None and bool(acquisition.get("is_widened")):
        return RETRIEVAL_KIND_PROM_OE_PAGE_WIDENED
    return candidate.retrieval_kind


#: Колонки первого класса, в которых живёт родословная приобретения.
#: ``via_oe_number`` и три ``source_assertion_*`` уже есть в схеме; остальные
#: перечислены здесь, чтобы миграция и код называли один и тот же набор.
ACQUISITION_LINEAGE_COLUMNS: tuple[str, ...] = (
    "source_assertion_source",
    "source_assertion_method",
    "source_assertion_queried_oe_norm",
    "source_assertion_source_url",
    "source_assertion_input_hash",
)


def _acquisition_capture_binding(
    raw_manifest: Mapping[str, Any],
    lineage: AcquisitionLineage,
) -> str:
    """Привязать проверенный манифест к самому запросу, а не только к байтам.

    Голый хеш блоба доказывает лишь то, что какие-то байты сохранены. Он не
    называет ни подготовленный URL, ни запрошенный номер, ни идентичность
    запроса — то есть два разных приобретения с одинаковым манифестом
    неразличимы, и заявление одного можно предъявить за другое. Отпечаток
    считается только для приобретения, которое действительно что-то утверждает.
    """

    manifest_hash = str(raw_manifest.get("raw_content_sha256") or "").strip()
    if not manifest_hash or not lineage.asserts_identity:
        return ""
    return canonical_sha256(
        {
            "binding_version": ACQUISITION_CONTRACT_VERSION,
            "raw_capture_id": str(raw_manifest.get("raw_capture_id") or ""),
            "raw_content_sha256": manifest_hash,
            "source_record_id": str(raw_manifest.get("source_record_id") or ""),
            "acquisition_source": lineage.source,
            "acquisition_method": lineage.method,
            "retrieval_kind": lineage.retrieval_kind,
            "queried_oe_norm": lineage.queried_oe_norm,
            "via_oe_number": lineage.via_oe_number,
            "source_url": lineage.source_url,
            "input_hash": lineage.input_hash,
        }
    )


def _bind_acquisition_lineage(
    observation: MarketObservation,
    lineage: AcquisitionLineage,
    *,
    asserted: bool,
) -> None:
    """Записать родословную приобретения на наблюдение первым классом.

    Внутри ``comparison_evidence`` её переживал только ``retrieval_kind``:
    кодек повторного обогащения выбрасывает незнакомые ключи, поэтому источник,
    способ, запрошенный номер и URL терялись ровно там, где их потом нужно
    перепроверять.
    """

    values = {
        "source_assertion_source": lineage.source if asserted else None,
        "source_assertion_method": lineage.method if asserted else None,
        "source_assertion_queried_oe_norm": (
            lineage.queried_oe_norm if asserted else None
        ),
        "source_assertion_source_url": lineage.source_url if asserted else None,
        "source_assertion_input_hash": lineage.input_hash if asserted else None,
    }
    for name, value in values.items():
        setattr(observation, name, value)


def _market_candidate_selection_config() -> tuple[
    CandidateSelectionConfig | None,
    str | None,
]:
    """Load the deterministic semantic policy once per persistence batch.

    ``market_collection`` is the pricing path, not the discovery path.  It
    therefore cannot rely on discovery having already loaded
    ``comparability.yaml``.  A missing or invalid policy is a manual-review
    condition: collection remains observable, but no observation from that
    batch may enter an automatic pricing cohort.
    """

    raw_path = str(get_settings().pricing_candidate_selection_path or "").strip()
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        backend_root = Path(__file__).resolve().parents[3]
        candidate = backend_root / path
        if candidate.is_file():
            path = candidate
    try:
        return load_candidate_selection_config(path), None
    except Exception as exc:  # noqa: BLE001 - fail closed at the pricing boundary
        return None, f"SEMANTIC_GATE_CONFIG_UNAVAILABLE:{type(exc).__name__}"


def _category_path_from_product(product: Mapping[str, Any]) -> tuple[int, ...]:
    """Read Prom's root-to-leaf category path without inventing taxonomy."""

    raw = product.get("category_ids")
    if not isinstance(raw, (list, tuple)):
        return ()
    path: list[int] = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            return ()
        try:
            path.append(int(value))
        except (TypeError, ValueError):
            return ()
    return tuple(path)


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _catalog_semantic_reference_payload(
    catalog_item: CatalogItem,
) -> dict[str, Any]:
    """Project the frozen catalog row into the semantic extractor boundary.

    ``ReferenceItem`` intentionally stays small for candidate-selection.  The
    semantic pricing gate, however, must be able to compare package/unit and
    category-specific facts against the owned seed instead of treating a
    missing seed field as an implicit match.  Only fields already present in
    the frozen catalog snapshot are copied; this helper never invents a
    condition, quantity, or physical specification.
    """

    identity_status = (
        str(getattr(catalog_item, "identity_status", "UNRESOLVED") or "UNRESOLVED")
        .strip()
        .upper()
    )

    def public_identity(value: Any) -> str | None:
        normalized = normalize_oe(str(value or ""))
        if not normalized or is_internal_catalog_code(normalized):
            return None
        return normalized

    # ``CatalogItem.oe_norm`` is overloaded on legacy MPN_ONLY rows: it may
    # contain KEMP's private 776... join key rather than a vehicle OE.  The
    # semantic gate is not allowed to interpret that value as an OE and then
    # manufacture a conflict/admission from it.  The retrieval identity is
    # still frozen by ``customer_identity_query`` and remains available as a
    # separately named field.
    public_oe = (
        public_identity(getattr(catalog_item, "oe_norm", None))
        if identity_status == "OE_CONFIRMED"
        else None
    )
    public_mpn = public_identity(getattr(catalog_item, "mpn_norm", None))
    payload: dict[str, Any] = {
        "name": str(getattr(catalog_item, "name", "") or ""),
        "description": getattr(catalog_item, "description", None),
        "brand": getattr(catalog_item, "brand", None),
        "category": getattr(catalog_item, "category", None),
        "sku": getattr(catalog_item, "sku", None),
        "oe": public_oe,
        "mpn": public_mpn,
        "search_identity": customer_identity_query(catalog_item),
        "identity_status": identity_status,
        "applicability_brands": list(
            getattr(catalog_item, "applicability_brands", ()) or ()
        ),
        "applicability_models": list(
            getattr(catalog_item, "applicability_models", ()) or ()
        ),
    }
    # The unit the seed is priced in decides ``unit_basis``, and through it
    # ``package_quantity``.  A bounded run reads a ``FrozenCatalogItem``, which
    # resolved the unit at scope time and carries no ``raw_row`` at all, so the
    # extractor below cannot rediscover it from the raw import columns.  Without
    # this line the gate reports ``unit_basis``/``package_quantity`` missing on
    # every candidate while the same fact is plainly present in the review
    # payload, which reads the frozen field directly.
    measure_unit = getattr(catalog_item, "measure_unit", None)
    if measure_unit is None or not str(measure_unit).strip():
        measure_unit = resolve_catalog_measure_unit(catalog_item)
    if measure_unit and str(measure_unit).strip():
        payload["measure_unit"] = str(measure_unit).strip()
    characteristics = getattr(catalog_item, "characteristics_raw", None)
    if isinstance(characteristics, Mapping):
        payload["characteristics"] = dict(characteristics)
    raw_row = getattr(catalog_item, "raw_row", None)
    if isinstance(raw_row, Mapping):
        # Keep raw import fields nested so the semantic extractor can use
        # their provenance without allowing this projection to become a
        # second identity source.
        payload["raw_row"] = dict(raw_row)
    return payload


def _market_semantic_candidate_verdict(
    *,
    reference: ReferenceItem,
    product: Mapping[str, Any],
    price: Decimal,
    selection_config: CandidateSelectionConfig,
    owned_sellers: set[str],
    confirmed_crosses: tuple[ConfirmedCross, ...],
    brand_tiers: dict[str, ProductTier],
    authoritative_identity: bool,
    verified_oe_identity: bool = False,
    reference_payload: Mapping[str, Any] | None = None,
    require_pricing_completeness: bool = False,
    require_analogue_dimensions: bool = False,
) -> CandidateVerdict:
    """Apply the same semantic safety gate to the persisted pricing path.

    The ordinary market collector already has a separate, provenance-bound OE
    verifier.  This helper deliberately does *not* replace that verifier and
    does not make a search hit an identity match.  Candidate selection is used
    only to supply category/identity context to the semantic extractor; its
    tier/calibration outcome is not allowed to override the existing pricing
    policy here.  The final result is consequently a semantic admission
    decision only: ``PRICING_EVIDENCE`` or a visible ``REFERENCE_ONLY`` hold.
    """

    title = str(product.get("name") or product.get("title") or "").strip()
    description = _optional_string(product.get("description"))
    seller_id = str(product.get("seller_id") or "").strip()[:255]
    seller_name = str(product.get("seller_name") or "Unknown seller").strip()
    article_field = _optional_string(product.get("sku"))
    article_fields_list = [
        (label, value)
        for label, key in (("SKU", "sku"), ("MPN", "mpn"), ("OE", "oe_raw"))
        if (value := _optional_string(product.get(key))) is not None
    ]
    raw_part_numbers = product.get("part_numbers")
    if isinstance(raw_part_numbers, (list, tuple)):
        article_fields_list.extend(
            ("PART_NUMBER", value)
            for item in raw_part_numbers
            if (value := _optional_string(item)) is not None
        )
    article_fields = tuple(article_fields_list)
    candidate = CandidateItem(
        seller_id=seller_id,
        seller_name=seller_name,
        title=title,
        description=description,
        article_field=article_field,
        article_fields=article_fields,
        brand=_optional_string(product.get("brand")),
        price=price,
        condition=_optional_string(
            product.get("condition") or product.get("condition_raw")
        ),
        category_id=_optional_int(product.get("category_id")),
        category_path=_category_path_from_product(product),
    )
    selection = check_candidate(
        reference,
        candidate,
        selection_config,
        owned_seller_ids=owned_sellers,
        confirmed_cross_oems=frozenset(
            cross.candidate_oe_norm for cross in confirmed_crosses
        ),
        brand_tiers=brand_tiers,
        tier_agnostic=True,
        identity_source="PROM_OE_PAGE" if authoritative_identity else None,
    )
    # The collector has already established OE identity with
    # ``verify_offer_identity``.  Only the *strategy* gates are intentionally
    # not duplicated here.  Identity/domain/condition/package/applicability
    # gates remain hard stops: replacing them with PRICING_EVIDENCE would let
    # a blocked category, used/damaged offer, dismantler, or variant conflict
    # reach the semantic gate and potentially re-enter the pricing cohort.
    #
    # ``OWN_BRAND`` is retained as a strategy-only exception because the
    # persisted path assigns KEMP/reference rows their own cohort role and the
    # calibration lane needs the semantic snapshot.  It can never make
    # ``automatic_eligible`` true.  The other two reasons are defensive
    # compatibility for callers that do not enable ``tier_agnostic``.
    strategy_only_reasons = {
        "OWN_BRAND",
        "TIER_UNKNOWN",
        "PREMIUM_NOT_CALIBRATED",
    }
    if (
        selection.status is not CandidateStatus.PRICING_EVIDENCE
        and selection.reason in strategy_only_reasons
    ):
        selection = replace(
            selection,
            status=CandidateStatus.PRICING_EVIDENCE,
            reason="MARKET_VERIFIED_IDENTITY",
        )
    return apply_semantic_pricing_gate(
        selection,
        reference=reference,
        candidate=dict(product),
        authoritative_identity=authoritative_identity,
        verified_oe_identity=verified_oe_identity,
        reference_payload=reference_payload,
        require_pricing_completeness=require_pricing_completeness,
        require_analogue_dimensions=require_analogue_dimensions,
    )


async def _persist_payload_observations(
    session,
    *,
    run: PricingRun,
    run_item: PricingRunItem,
    catalog_item: CatalogItem,
    capture: RawMarketCapture,
    offers: list[Any],
    owned_sellers: set[str],
    brand_tiers: dict[str, ProductTier],
    brand_confidence: dict[str, Decimal],
    observed_at: datetime,
    source_type: str,
    confirmed_crosses: tuple[ConfirmedCross, ...] = (),
    declared_discovery_queries: tuple[str, ...] = (),
    prepared_url: str | None = None,
    acquisition_input_hash: str | None = None,
    acquisition_query: str | None = None,
    requested_query: str | None = None,
) -> OfferAccounting:
    policy = load_run_execution_policy(run) if hasattr(run, "policy_config") else None
    # Read from the run's own frozen policy, never from the deployment file, so
    # a replayed run keeps the partition it was actually computed with.
    run_raise_policy = getattr(policy, "raise_policy", None) if policy else None
    tier_agnostic_pricing = bool(
        run_raise_policy is not None
        and run_raise_policy.strategy is RaiseStrategy.BUDGET_FLOOR
        and run_raise_policy.tier_agnostic
    )
    semantic_selection_config, semantic_config_error = (
        _market_candidate_selection_config()
    )
    if semantic_config_error is not None:
        pricing_event(
            "market_semantic_gate_config_unavailable",
            pricing_run_id=str(run.id),
            pricing_run_item_id=str(run_item.id),
            reason=semantic_config_error,
        )
    expected_search_identity = normalize_oe(customer_identity_query(catalog_item))
    seed_identity_namespace = customer_identity_namespace(catalog_item)
    # Bind the *input* query — the number this run item asked Prom for — to the
    # frozen catalog identity. ``acquisition_query`` is the marketplace page
    # number. On a seed motors listing that can be a compatible OE (canary
    # 578128 vs VAG 4A0412249) and is retrieval, not a rewrite of identity.
    requested_identity = normalize_oe(requested_query)
    acquired_identity = normalize_oe(acquisition_query)
    bound_identity = requested_identity or acquired_identity
    if (
        expected_search_identity is None
        or bound_identity is None
        or bound_identity != expected_search_identity
    ):
        raise EvidenceAccountingError(
            "ACQUISITION_QUERY_BINDING_ERROR: retained acquisition query does not "
            "match the catalog identity frozen for this run item"
        )
    search_identity = expected_search_identity
    persisted = 0
    rejected = 0
    failed = 0
    persisted_listing_ids: set[str] = set()
    retained_raw_evidence = _verified_capture_raw_evidence(capture)
    for raw_offer_index, raw_offer in enumerate(offers):
        payload_sha256 = _offer_payload_sha256(raw_offer)
        processed = process_offer_candidate(
            raw_offer,
            fallback_index=raw_offer_index,
            prepared_url=prepared_url,
            input_hash=acquisition_input_hash,
            fallback_queried_oe=acquisition_query,
        )
        if isinstance(processed, RejectedOffer):
            session.add(
                _offer_outcome(
                    run_item=run_item,
                    capture=capture,
                    raw_offer_index=processed.raw_offer_index,
                    outcome_code=processed.outcome_code,
                    stage="validation",
                    reason_codes=processed.reason_codes,
                    payload_sha256=payload_sha256,
                    safe_sample=dict(processed.safe_sample),
                )
            )
            rejected += 1
            continue

        candidate = processed
        if candidate.source_listing_id in persisted_listing_ids:
            session.add(
                _offer_outcome(
                    run_item=run_item,
                    capture=capture,
                    raw_offer_index=candidate.raw_offer_index,
                    outcome_code=OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
                    stage="validation",
                    reason_codes=("DUPLICATE_SOURCE_LISTING_ID",),
                    payload_sha256=payload_sha256,
                    safe_sample=safe_offer_sample(
                        raw_offer,
                        raw_offer_index=candidate.raw_offer_index,
                    ),
                    source_listing_id=candidate.source_listing_id,
                )
            )
            rejected += 1
            continue
        product = candidate.product
        try:
            upstream_evidence = comparison_evidence_from_dict(
                candidate.upstream_comparison_evidence
            )
        except (TypeError, ValueError):
            session.add(
                _offer_outcome(
                    run_item=run_item,
                    capture=capture,
                    raw_offer_index=candidate.raw_offer_index,
                    outcome_code=OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
                    stage="validation",
                    reason_codes=("COMPARISON_EVIDENCE_SCHEMA_INVALID",),
                    payload_sha256=payload_sha256,
                    safe_sample=safe_offer_sample(
                        raw_offer,
                        raw_offer_index=candidate.raw_offer_index,
                    ),
                )
            )
            rejected += 1
            continue

        try:
            seller_id = str(product.get("seller_id") or "").strip()[:255]
            title = str(product.get("name") or product.get("title") or "")
            brand = _optional_string(product.get("brand"))
            source_listing_id = candidate.source_listing_id
            description = _optional_string(product.get("description"))
            condition_raw = _optional_string(
                product.get("condition") or product.get("condition_raw")
            )
            condition_assessment = classify_condition(
                title=title,
                description=description,
                explicit_condition=condition_raw,
            )
            classification = classify_tier(
                brand=brand,
                title=title,
                description=description,
                condition=condition_raw,
                brand_tiers=brand_tiers,
            )
            normalized_brand = normalize_brand(brand)
            if (
                normalized_brand in brand_confidence
                and "EXACT_BRAND_RULE" in classification.reasons
            ):
                classification = TierClassification(
                    tier=classification.tier,
                    confidence=brand_confidence[normalized_brand],
                    is_used=classification.is_used,
                    is_kemp=classification.is_kemp,
                    exclusion_reason=classification.exclusion_reason,
                    reasons=classification.reasons + ("WORKSPACE_BRAND_CONFIDENCE",),
                    method_version=classification.method_version,
                )
            currency_raw = _optional_string(product.get("currency"))
            currency = _currency_code(currency_raw)
            raw_manifest = _candidate_raw_manifest(
                capture,
                source_record_id=source_listing_id,
            )
            detail_evidence_safe = _detail_evidence_automatic_safe(
                product,
                seller_id=seller_id,
                retained_raw_evidence=retained_raw_evidence,
            )
            availability = _availability(
                _optional_bool(product.get("is_available")),
                _optional_string(product.get("presence")),
            )
            offer_integrity = assess_offer_integrity(
                title=title,
                description=description,
                condition=condition_raw,
                characteristics=product.get("characteristics"),
                measure_unit=product.get("measure_unit"),
                is_available=availability,
                detail_evidence_safe=detail_evidence_safe,
            )
            detail = product.get("detail_evidence")
            verified_detail_manifest = (
                {
                    "source_record_id": str(detail.get("source_url") or ""),
                    "raw_capture_id": str(capture.id),
                    "raw_content_sha256": str(
                        detail.get("content_sha256") or ""
                    ).casefold(),
                }
                if detail_evidence_safe and isinstance(detail, Mapping)
                else None
            )
            evidence_source = dict(product)
            if candidate.upstream_comparison_evidence is not None:
                evidence_source["comparison_evidence"] = dict(
                    candidate.upstream_comparison_evidence
                )
            # Which number actually retrieved this row.  Everything that asks
            # "was the search identity found here" must ask about that number:
            # a row off a declared cross does not carry the primary OE, and
            # checking it against the primary either loses the evidence or
            # credits it with evidence it never had.
            offer_search_identity = _offer_search_identity(
                detail,
                primary=search_identity,
                confirmed_crosses=confirmed_crosses,
                discovery_queries=declared_discovery_queries,
            )
            oe_items = extract_oe_evidence(
                evidence_source,
                raw_manifest,
                verified_detail_manifest=verified_detail_manifest,
            )
            proposed_crosses = extract_prom_motors_cross_proposals(
                evidence_source,
                verified_detail_manifest,
                search_oe_norm=offer_search_identity,
            )
            lineage = candidate.acquisition
            effective_retrieval_kind = _persisted_retrieval_kind(raw_offer, candidate)
            # Что именно утверждает источник. Продавцы на странице кода детали
            # номер в заголовке не повторяют, поэтому без этого предложение с
            # готового рынка площадки становится UNKNOWN и в цену не попадает.
            #
            # Заявление собирается ТОЛЬКО из родословной приобретения. Раньше
            # запрошенный номер брался из ``catalog_item.oe_norm`` — то есть из
            # НАШЕГО намерения, — и поэтому запись с ``retrieval_kind``
            # страницы кода, но приобретённая поиском, доезжала до
            # ``VERIFIED_EXACT``. Родословная, которая ничего не утверждает,
            # даёт ``None``, и проверяющий работает по одним уликам карточки.
            source_assertion = SourceAssertion.from_lineage(
                lineage,
                capture_sha256=_acquisition_capture_binding(raw_manifest, lineage),
                confidence=SOURCE_PAGE_ASSERTION_CONFIDENCE,
            )
            # Заявление хранится только когда источник действительно
            # авторитетен ДЛЯ НАШЕГО номера. Обычный поиск авторитетом не
            # является, поэтому у него все поля пусты: иначе строка выглядит
            # как утверждение площадки, которого никто не делал.
            asserted = source_assertion is not None and (
                source_assertion.authoritative_for(offer_search_identity)
            )
            verification = verify_offer_identity(
                offer_search_identity,
                oe_items,
                confirmed_crosses,
                proposed_crosses,
                legacy_without_reenrichment=bool(
                    isinstance(raw_offer, Mapping)
                    and raw_offer.get("legacy_unverified")
                ),
                source_assertion=source_assertion,
                allow_short_numeric_native=(
                    seed_identity_namespace is IdentityNamespace.MPN
                ),
            )
            verification = namespace_bound_verification(
                verification,
                seed_identity_namespace,
            )
            # A title/description OE can support discovery and manual review,
            # but it is not an independent identity assertion for the
            # persisted pricing cohort.  Require a structured/detail source
            # or the provenance-bound Prom grouping before automatic
            # admission; the verifier's broader review semantics stay intact.
            base_automatic_identity_evidence = automatic_identity_evidence_sufficient(
                verification,
                oe_items,
                # ``asserts_identity`` is only a method-level claim.  The
                # source assertion must also bind to this query and retained
                # capture before it can bypass seller-side text evidence.
                authoritative_identity=bool(asserted),
                # A candidate MPN/SKU pair is still one seller's namespace;
                # pricing requires an explicit OE/cross/detail source.
                require_oe_namespace=True,
            )
            automatic_identity_evidence, identity_namespace_reason = (
                namespace_identity_admission(
                    seed_namespace=seed_identity_namespace,
                    verification=verification,
                    evidence_items=oe_items,
                    base_automatic_evidence=base_automatic_identity_evidence,
                )
            )
            parser_contract_verified = bool(
                str(run.parser_version).strip() == PROM_ADAPTER_VERSION
                and str(getattr(capture, "parser_version", "")).strip()
                == PROM_ADAPTER_VERSION
            )
            source_assessment = assess_candidate_source(
                candidate,
                raw_capture_verified=bool(raw_manifest["raw_content_sha256"]),
                parser_contract_verified=parser_contract_verified,
            )
            comparison_evidence = bind_persisted_provenance(
                upstream_evidence,
                stable_seller_id=seller_id or None,
                source_type=source_type,
                source_record_id=source_listing_id,
                raw_evidence_sha256=str(raw_manifest["raw_content_sha256"]),
                parser_contract_version=(
                    run.parser_version if parser_contract_verified else ""
                ),
                currency_raw=currency_raw,
                currency_normalized=currency,
                required_currency="UAH",
                category=catalog_item.category,
                condition_state=condition_assessment.state.value,
            )
            comparison_evidence = replace(
                comparison_evidence,
                retrieval_kind=effective_retrieval_kind,
            )
            comparison_evidence = bind_oe_verification(
                comparison_evidence,
                verification,
                seller_id=seller_id or None,
                currency_raw=currency_raw,
                currency_normalized=currency,
                required_currency="UAH",
                category=catalog_item.category,
            )
            if not automatic_identity_evidence:
                identity_reasons = [
                    *comparison_evidence.reason_codes,
                    "OE_AUTOMATIC_IDENTITY_EVIDENCE_INSUFFICIENT",
                ]
                if identity_namespace_reason not in {
                    None,
                    "IDENTITY_EVIDENCE_INSUFFICIENT",
                }:
                    identity_reasons.append(identity_namespace_reason)
                comparison_evidence = replace(
                    comparison_evidence,
                    hard_gate_result=HardGateResult.MANUAL_REVIEW,
                    reason_codes=tuple(dict.fromkeys(identity_reasons)),
                )
            semantic_verdict: CandidateVerdict | None = None
            semantic_gate_error = semantic_config_error
            if semantic_selection_config is not None:
                try:
                    # Keep two different facts separate.  A retained Prom
                    # part-code page is an acquisition-level assertion and
                    # may replace a missing seller-side OE.  A candidate OE
                    # verified from ordinary search text/fields is evidence
                    # about the card, not permission to bypass the semantic
                    # anti-stuffing/description-only boundary.
                    authoritative_identity = bool(
                        asserted and seed_identity_namespace is IdentityNamespace.OE
                    )
                    verified_oe_identity = bool(
                        seed_identity_namespace is IdentityNamespace.OE
                        and verification.status
                        in {
                            OeVerificationStatus.VERIFIED_EXACT,
                            OeVerificationStatus.VERIFIED_CROSS,
                        }
                    )
                    semantic_verdict = _market_semantic_candidate_verdict(
                        reference=ReferenceItem(
                            oem=search_identity,
                            title=str(catalog_item.name or search_identity),
                            price=catalog_item.current_price,
                            brand=_optional_string(catalog_item.brand),
                            category=_optional_string(catalog_item.category),
                        ),
                        product=product,
                        price=candidate.price,
                        selection_config=semantic_selection_config,
                        owned_sellers=owned_sellers,
                        confirmed_crosses=confirmed_crosses,
                        brand_tiers=brand_tiers,
                        reference_payload=_catalog_semantic_reference_payload(
                            catalog_item
                        ),
                        # A verified cross needs category-specific physical
                        # evidence in addition to the base package/unit facts.
                        # Exact OE still requires the base facts and any
                        # explicitly asserted seed configuration.
                        require_pricing_completeness=True,
                        require_analogue_dimensions=(
                            verification.status is OeVerificationStatus.VERIFIED_CROSS
                        ),
                        # A Prom part-code page is an explicit marketplace
                        # grouping.  Ordinary text/search acquisition is not
                        # an identity assertion and stays fail-closed.
                        authoritative_identity=authoritative_identity,
                        verified_oe_identity=verified_oe_identity,
                    )
                except Exception as exc:  # noqa: BLE001 - manual-review fallback
                    semantic_gate_error = (
                        f"SEMANTIC_GATE_EVALUATION_FAILED:{type(exc).__name__}"
                    )
            semantic_gate_details = (
                semantic_verdict.details.get("semantic_gate")
                if semantic_verdict is not None
                and isinstance(semantic_verdict.details, Mapping)
                and isinstance(semantic_verdict.details.get("semantic_gate"), Mapping)
                else None
            )
            semantic_gate_reason = (
                str(semantic_gate_details.get("reason") or "")
                if semantic_gate_details is not None
                else ""
            )
            semantic_gate_allowed = bool(
                semantic_verdict is not None
                and semantic_verdict.status is CandidateStatus.PRICING_EVIDENCE
                and semantic_gate_reason == "OK"
                and semantic_gate_error is None
            )
            if not semantic_gate_allowed:
                semantic_reason = (
                    semantic_gate_error
                    or semantic_gate_reason
                    or "SEMANTIC_GATE_REVIEW_REQUIRED"
                )
                comparison_evidence = replace(
                    comparison_evidence,
                    hard_gate_result=HardGateResult.MANUAL_REVIEW,
                    reason_codes=tuple(
                        dict.fromkeys(
                            (*comparison_evidence.reason_codes, semantic_reason)
                        )
                    ),
                )
            url, url_absence_reason = _validated_listing_url(product.get("url"))
            is_owned = seller_id in owned_sellers
            cohort_role = _initial_cohort_role(
                classification,
                is_owned=is_owned,
                tier_agnostic=tier_agnostic_pricing,
            )
            if (
                not is_owned
                and cohort_role is not CohortRole.USED_REJECTED
                and offer_integrity.status is OfferIntegrityStatus.REJECT
            ):
                cohort_role = CohortRole.HARD_REJECTED
            elif (
                not is_owned
                and cohort_role is CohortRole.TARGET_MARKET
                and offer_integrity.status is OfferIntegrityStatus.MANUAL_REVIEW
            ):
                cohort_role = CohortRole.MANUAL_REVIEW
            cross_candidates = [
                asdict(cross_candidate)
                for cross_candidate in extract_description_cross_candidates(
                    description,
                    source_observation_id=source_listing_id,
                )
            ] + [
                proposal.as_dict(source_observation_id=source_listing_id)
                for proposal in proposed_crosses
            ]
            seller_verified = bool(
                seller_id and comparison_evidence.seller_identity.verified
            )
            provenance_verified = bool(
                raw_manifest["raw_content_sha256"]
                and comparison_evidence.provenance.verified
                and parser_contract_verified
            )
            source_threshold = (
                policy.source_confidence_min if policy is not None else Decimal("0.50")
            )
            automatic_eligible = bool(
                # ``automatic_eligible`` describes a candidate that may enter
                # the target-market pricing cohort, not merely an observation
                # whose individual fields look complete.  Owned storefronts,
                # KEMP references, used listings and explicit tier/manual
                # exclusions are persisted for diagnostics but can never be
                # marked automatically eligible.
                not is_owned
                and cohort_role == CohortRole.TARGET_MARKET
                and verification.verified
                and comparison_evidence.hard_gate_result == HardGateResult.PASS
                and seller_verified
                and provenance_verified
                # The listing can discover a candidate, but automatic pricing
                # now requires its exact product-card bytes. Missing, failed,
                # not-selected or conflicting detail remains review-only.
                and detail_evidence_safe
                and automatic_identity_evidence
                and currency_raw
                and currency == "UAH"
                and source_assessment.value >= source_threshold
                and semantic_gate_allowed
                and offer_integrity.status is OfferIntegrityStatus.PASS
            )
            selected_cross = next(
                (
                    cross
                    for cross in confirmed_crosses
                    if verification.status == OeVerificationStatus.VERIFIED_CROSS
                    and cross.candidate_oe_norm == verification.verified_matched_oe_norm
                ),
                None,
            )
            cross_link_id = (
                UUID(selected_cross.cross_link_id)
                if selected_cross is not None and selected_cross.cross_link_id
                else None
            )
            candidate_snapshot = _candidate_review_snapshot(
                product,
                raw_capture_id=capture.id,
                capture_content_sha256=capture.content_sha256,
                raw_offer_index=candidate.raw_offer_index,
                raw_offer_sha256=payload_sha256,
                source_listing_id=source_listing_id,
            )
            candidate_snapshot["identity_admission"] = {
                "automatic_evidence_sufficient": automatic_identity_evidence,
                "authoritative_identity": bool(
                    asserted and seed_identity_namespace is IdentityNamespace.OE
                ),
                "namespace_version": IDENTITY_NAMESPACE_VERSION,
                "seed_identity_namespace": seed_identity_namespace.value,
                "verified_identity_namespace": verified_identity_namespace(
                    seed_identity_namespace, verification.status
                ).value,
                "comparison_identity_key": verification.comparison_identity_key,
                "verification_status": verification.status.value,
                "namespace_reason": identity_namespace_reason,
                "reason": (
                    None
                    if automatic_identity_evidence
                    else (
                        identity_namespace_reason
                        or "OE_AUTOMATIC_IDENTITY_EVIDENCE_INSUFFICIENT"
                    )
                ),
            }
            candidate_snapshot["offer_integrity"] = offer_integrity.as_dict()
            if semantic_gate_details is not None:
                candidate_snapshot["semantic_gate"] = dict(semantic_gate_details)
            elif semantic_gate_error is not None:
                candidate_snapshot["semantic_gate"] = {
                    "status": "REFERENCE_ONLY",
                    "reason": semantic_gate_error,
                    "gate_version": "unavailable",
                }
            candidate_snapshot = _json_safe(candidate_snapshot)
            semantic_exclusion_codes = []
            if not semantic_gate_allowed:
                semantic_exclusion_codes.append(
                    semantic_gate_error
                    or semantic_gate_reason
                    or "SEMANTIC_GATE_REVIEW_REQUIRED"
                )
            observation = MarketObservation(
                # Заявление источника — первым классом, вместе с происхождением.
                # Внутри ``comparison_evidence`` его переживал только
                # ``retrieval_kind``: кодек повторного обогащения выбрасывает
                # незнакомые ключи.
                via_oe_number=candidate.via_oe_number if asserted else None,
                # Заявление пишется целиком или не пишется вовсе: способ
                # извлечения без захвата — это заявление без основания, и
                # ``ck_market_observation_source_assertion_provenance`` такую
                # строку отвергает. Захват бывает неполным (см.
                # ``extract_oe_evidence``), поэтому условие обязательно.
                source_assertion_retrieval_kind=(
                    effective_retrieval_kind if asserted else None
                ),
                source_assertion_capture_sha256=(
                    source_assertion.capture_sha256.strip()
                    if asserted and source_assertion is not None
                    else None
                ),
                source_assertion_confidence=(
                    source_assertion.confidence
                    if asserted and source_assertion is not None
                    else None
                ),
                pricing_run_item_id=run_item.id,
                catalog_item_id=catalog_item.id,
                raw_capture_id=capture.id,
                source=source_type,
                source_listing_id=source_listing_id,
                seller_id=seller_id,
                seller_name=str(product.get("seller_name") or "Unknown seller")[:255],
                url=url,
                url_absence_reason=url_absence_reason,
                title=title,
                description=description,
                description_available=description is not None,
                condition_raw=condition_raw,
                condition_state=condition_assessment.state.value,
                condition_reason_codes=list(condition_assessment.reason_codes),
                cross_candidates=_json_safe(cross_candidates),
                candidate_snapshot=candidate_snapshot,
                brand_raw=brand,
                matched_oe_norm=verification.verified_matched_oe_norm,
                search_oe_norm=offer_search_identity,
                extracted_oe_norms=list(verification.extracted_oe_norms),
                verified_matched_oe_norm=verification.verified_matched_oe_norm,
                comparison_identity_key=verification.comparison_identity_key,
                oe_verification_status=verification.status.value,
                oe_evidence=_json_safe(evidence_items_to_dicts(oe_items)),
                oe_extractor_version=OE_EXTRACTOR_VERSION,
                oe_reenriched_at=None,
                oe_reenrichment_error_code=None,
                canonical_category_id=category_comparability_rule(
                    catalog_item.category
                ).policy_key,
                price=candidate.price,
                sale_price=candidate.price,
                reference_price=candidate.reference_price,
                currency=currency,
                currency_raw=currency_raw,
                currency_inferred=False,
                is_available=availability,
                match_confidence=verification.confidence,
                source_confidence=source_assessment.value,
                source_confidence_factors=_json_safe(dict(source_assessment.factors)),
                source_confidence_method_version=source_assessment.method_version,
                parser_version=run.parser_version,
                evidence_contract_version=COMPARABILITY_CONTRACT_VERSION,
                comparability_policy_id=comparison_evidence.policy_id,
                comparability_policy_hash=comparison_evidence.policy_hash,
                comparison_evidence=_json_safe(
                    comparison_evidence_to_dict(comparison_evidence)
                ),
                comparability_hard_gate_result=(
                    comparison_evidence.hard_gate_result.value
                ),
                calibration_exclusion_codes=semantic_exclusion_codes,
                seller_identity_verified=seller_verified,
                source_provenance_verified=provenance_verified,
                automatic_eligible=automatic_eligible,
                via_cross=(verification.status == OeVerificationStatus.VERIFIED_CROSS),
                cross_link_id=cross_link_id,
                observed_at=observed_at,
            )
            # Источник, способ, запрошенный номер и подготовленный URL —
            # рядом с захватом, на который они опираются.
            _bind_acquisition_lineage(observation, lineage, asserted=asserted)
            tier_record = ObservationTierClassification(
                market_observation_id=observation.id,
                tier=classification.tier.value,
                tier_confidence=classification.confidence,
                is_used=classification.is_used,
                is_kemp=classification.is_kemp,
                is_owned=is_owned,
                is_dumping=False,
                cohort_role=cohort_role.value,
                exclusion_reason=(
                    classification.exclusion_reason
                    or (
                        offer_integrity.reason_codes[0]
                        if offer_integrity.status is not OfferIntegrityStatus.PASS
                        else None
                    )
                ),
                reason_codes=list(
                    dict.fromkeys(
                        (*classification.reasons, *offer_integrity.reason_codes)
                    )
                ),
                method_version=classification.method_version,
            )
            async with session.begin_nested():
                session.add(observation)
                await session.flush()
                tier_record.market_observation_id = observation.id
                session.add(tier_record)
                session.add(
                    _offer_outcome(
                        run_item=run_item,
                        capture=capture,
                        raw_offer_index=candidate.raw_offer_index,
                        outcome_code=OfferOutcomeCode.OBSERVATION_PERSISTED,
                        stage="persistence",
                        reason_codes=(
                            verification.status.value,
                            *source_assessment.reason_codes,
                            *(
                                ("ACQUIRED_VIA_WIDENED_OE",)
                                if retrieval_kind_is_widened(effective_retrieval_kind)
                                else ()
                            ),
                            # Почему родословную нельзя было принять целиком: рынок
                            # сохранён, заявление — нет, и причина названа.
                            *candidate.acquisition_reason_codes,
                        ),
                        payload_sha256=payload_sha256,
                        safe_sample=safe_offer_sample(
                            raw_offer,
                            raw_offer_index=candidate.raw_offer_index,
                        ),
                        market_observation_id=observation.id,
                        source_listing_id=source_listing_id,
                    )
                )
            persisted_listing_ids.add(source_listing_id)
            persisted += 1
        except Exception as exc:
            error_fingerprint, message_sha256, stack_frames = (
                _internal_offer_error_diagnostic(exc)
            )
            safe_sample = safe_offer_sample(
                raw_offer,
                raw_offer_index=candidate.raw_offer_index,
            )
            safe_sample["internal_error_fingerprint"] = error_fingerprint
            failed_outcome = _offer_outcome(
                run_item=run_item,
                capture=capture,
                raw_offer_index=candidate.raw_offer_index,
                outcome_code=OfferOutcomeCode.FAILED_INTERNAL_PROCESSING,
                stage="internal",
                reason_codes=(f"INTERNAL_{type(exc).__name__.upper()}",),
                payload_sha256=payload_sha256,
                safe_sample=safe_sample,
            )
            session.add(failed_outcome)
            pricing_event(
                "offer_internal_processing_failed",
                pricing_run_id=str(run.id),
                pricing_run_item_id=str(run_item.id),
                raw_market_capture_id=str(capture.id),
                raw_offer_index=candidate.raw_offer_index,
                exception_type=type(exc).__name__,
                exception_message_sha256=message_sha256,
                error_fingerprint=error_fingerprint,
                stack_frames=stack_frames,
            )
            failed += 1
            continue

    accounting = OfferAccounting(
        retrieved=len(offers),
        observations_persisted=persisted,
        rejected=rejected,
        internal_failures=failed,
    )
    _validate_offer_accounting(
        accounting,
        pricing_run_id=run.id,
        pricing_run_item_id=run_item.id,
    )
    return accounting


async def _mark_target_group_classified(
    scrape_target_id: UUID,
    *,
    reason: str,
    error: Exception,
) -> None:
    async with async_session_factory() as session:
        target = await session.scalar(
            select(ScrapeTarget)
            .where(ScrapeTarget.id == scrape_target_id)
            .with_for_update()
        )
        if target is None:
            return
        now = datetime.now(UTC)
        if target.status != "succeeded":
            target.status = "terminal_failure"
            _set_terminal_target_contract(
                target,
                reason=reason[:50],
                raw_available=target.raw_size_bytes > 0,
                parse_failed=target.raw_size_bytes > 0,
            )
            target.error_category = reason[:50]
            target.error_detail = str(error)[:4000]
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = target.finished_at or now
        items = list(
            (
                await session.scalars(
                    select(PricingRunItem).where(
                        PricingRunItem.scrape_target_id == target.id,
                        PricingRunItem.status.in_(
                            ("queued", "collecting", "collected", "classified")
                        ),
                    )
                )
            ).all()
        )
        for item in items:
            item.status = "classified"
            item.error = f"{reason}: {error}"[:4000]
            item.checkpoint = {
                "stage": "classified_without_evidence",
                "scrape_target_id": str(target.id),
                "reason": reason,
                "at": now.isoformat(),
            }
        await session.commit()


async def _target_evidence_coverage(
    scrape_target_id: UUID,
    *,
    execution_no: int | None = None,
) -> Decimal:
    async with async_session_factory() as session:
        return await evidence_coverage_ratio(
            session,
            scrape_target_id=scrape_target_id,
            execution_no=execution_no,
        )


async def _has_capture(run_item_id: UUID) -> bool:
    async with async_session_factory() as session:
        return (
            await session.scalar(
                select(func.count(RawMarketCapture.id)).where(
                    RawMarketCapture.pricing_run_item_id == run_item_id
                )
            )
            or 0
        ) > 0


async def _mark_classified(run_item_id: UUID, *, reason: str) -> None:
    async with async_session_factory() as session:
        item = await session.get(PricingRunItem, run_item_id)
        if item is None:
            raise PricingItemNotFoundError(str(run_item_id))
        if item.status in {"calculated", "manual_review", "failed", "cancelled"}:
            return
        item.status = "classified"
        item.checkpoint = {
            "stage": "classified",
            "reason": reason,
            "at": datetime.now(UTC).isoformat(),
        }
        await session.commit()


async def get_pricing_item_run_id(run_item_id: UUID) -> UUID | None:
    async with async_session_factory() as session:
        return await session.scalar(
            select(PricingRunItem.pricing_run_id).where(
                PricingRunItem.id == run_item_id
            )
        )


async def _run_id_for_statuses(
    run_item_id: UUID, statuses: tuple[str, ...]
) -> UUID | None:
    async with async_session_factory() as session:
        return await session.scalar(
            select(PricingRunItem.pricing_run_id).where(
                PricingRunItem.id == run_item_id,
                PricingRunItem.status.in_(statuses),
            )
        )


async def _persist_comparison(
    *,
    run_id: UUID,
    run_item_id: UUID,
    catalog_item_id: UUID,
    product_url: str,
    comparison: PriceComparison,
) -> None:
    observed_at = datetime.now(UTC)
    async with async_session_factory() as session:
        run = await session.get(PricingRun, run_id)
        item = await session.get(CatalogItem, catalog_item_id)
        run_item = await session.get(PricingRunItem, run_item_id)
        if run is None or item is None or run_item is None:
            raise PricingItemNotFoundError("Pricing run dependencies disappeared")
        scrape_input = ScrapeInput.build(
            product_url,
            comparison.query,
            adapter_version=run.parser_version,
        )
        output = ScrapeOutput.from_comparison(scrape_input, comparison)
        existing = await session.scalar(
            select(RawMarketCapture).where(
                RawMarketCapture.pricing_run_item_id == run_item_id,
                RawMarketCapture.content_sha256 == output.content_sha256,
            )
        )
        if existing is not None:
            return
        capture = RawMarketCapture(
            pricing_run_item_id=run_item_id,
            source="prom",
            capture_kind="parser_output",
            payload=output.payload,
            content_sha256=output.content_sha256,
            parser_version=run.parser_version,
            raw_size_bytes=0,
            structured_size_bytes=output.structured_size_bytes,
            metadata_size_bytes=output.metadata_size_bytes,
            structured_completeness=Decimal(str(output.structured_completeness)),
            captured_at=observed_at,
        )
        session.add(capture)
        await session.flush()
        # Defence in depth, as in target materialization above.
        owned_sellers = await _owned_seller_external_ids(session, run.workspace_id)
        brand_tiers, brand_confidence = await _load_brand_rules(
            session, run.workspace_id
        )
        records = [
            (
                {**record, "legacy_unverified": True}
                if isinstance(record, Mapping)
                else record
            )
            for record in output.candidate_records
        ]
        accounting = await _persist_payload_observations(
            session,
            run=run,
            run_item=run_item,
            catalog_item=item,
            capture=capture,
            offers=records,
            owned_sellers=owned_sellers,
            brand_tiers=brand_tiers,
            brand_confidence=brand_confidence,
            observed_at=observed_at,
            source_type="prom_legacy_untraced",
            confirmed_crosses=(),
            acquisition_query=output.requested_query,
            requested_query=output.requested_query,
        )
        _validate_offer_accounting(
            accounting,
            pricing_run_id=run.id,
            pricing_run_item_id=run_item.id,
        )
        await _enqueue_ai_evidence_shadow(
            session,
            run=run,
            run_item=run_item,
            capture=capture,
        )
        run_item.status = "classified"
        run_item.checkpoint = {
            "stage": "classified",
            "capture_id": str(capture.id),
            "offers": len(records),
            "offer_accounting": accounting.as_dict(),
            "legacy_unverified": True,
            "at": observed_at.isoformat(),
        }
        await session.commit()


async def _enqueue_ai_evidence_shadow(
    session,
    *,
    run: PricingRun,
    run_item: PricingRunItem,
    capture: RawMarketCapture,
) -> None:
    """Transactional outbox handoff after deterministic rows have been flushed."""

    if not resolve_ai_evidence_config(get_settings()).enabled:
        return
    await enqueue_dispatch(
        session,
        event_key=(
            f"pricing-run:{run.id}:ai-evidence:{run_item.id}:"
            f"{capture.content_sha256}:{AI_EVIDENCE_SELECTION_VERSION}"
        ),
        aggregate_type="pricing_run_item_ai_evidence",
        aggregate_id=run_item.id,
        workspace_id=run.workspace_id,
        task_name="marko.worker.process_ai_evidence_position",
        task_args=[str(run_item.id)],
        queue="pricing-calculation",
    )


async def _owned_seller_external_ids(session, workspace_id: UUID) -> set[str]:
    """Marketplace ids of every storefront this workspace owns.

    KEMP runs four on prom.ua with identical cards, so they resemble our own
    product better than any competitor does.  The same list is read twice on
    purpose: once before acquisition, so they never spend a slot of the seller
    cap, and again during materialization, so one that slipped through is still
    filed as ours rather than as the market.
    """

    rows = (
        await session.scalars(
            select(MarketplaceStore.external_id)
            .join(
                WorkspaceStore,
                WorkspaceStore.store_id == MarketplaceStore.id,
            )
            .where(
                WorkspaceStore.workspace_id == workspace_id,
                WorkspaceStore.kind == StoreKind.owned,
            )
        )
    ).all()
    # ``None`` must not become the string "None": that would exclude a seller
    # nobody owns and, worse, read as a populated exclusion list.
    return {
        str(value).strip() for value in rows if value is not None and str(value).strip()
    }


async def _load_brand_rules(
    session, workspace_id: UUID
) -> tuple[dict[str, ProductTier], dict[str, Decimal]]:
    configured = load_approved_brand_rules(get_settings().pricing_brand_tiers_path)
    tiers = dict(configured.tiers)
    confidence = dict(configured.confidence)
    records = list(
        (
            await session.scalars(
                select(BrandTierRule)
                .where(
                    BrandTierRule.is_active.is_(True),
                    or_(
                        BrandTierRule.workspace_id.is_(None),
                        BrandTierRule.workspace_id == workspace_id,
                    ),
                )
                .order_by(
                    BrandTierRule.workspace_id.asc().nullsfirst(),
                    BrandTierRule.updated_at,
                )
            )
        ).all()
    )
    for record in records:
        tiers[record.brand_normalized] = ProductTier(record.tier)
        confidence[record.brand_normalized] = record.confidence
    return tiers, confidence


async def claim_collection_finalization(run_id: UUID, *, task_id: str | None) -> bool:
    """Claim the single run-level calibration barrier once collection is done."""
    settings = get_settings()
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        if run.status in {"completed", "partial", "failed", "cancelled", "calculating"}:
            return False
        if run.status == "calibrating":
            return run.finalizer_task_id == task_id
        active = int(
            await session.scalar(
                select(func.count(PricingRunItem.id)).where(
                    PricingRunItem.pricing_run_id == run_id,
                    PricingRunItem.status.in_(("queued", "collecting", "collected")),
                )
            )
            or 0
        )
        if active:
            return False
        awaiting_review = int(
            await session.scalar(
                select(func.count(PricingRunItem.id)).where(
                    PricingRunItem.pricing_run_id == run_id,
                    PricingRunItem.status.in_(
                        ("discovering", "awaiting_discovery_review", "review_frozen")
                    ),
                )
            )
            or 0
        )
        if awaiting_review:
            run.status = "awaiting_review"
            run.finalizer_task_id = None
            await session.commit()
            return False
        if settings.pricing_llm_comparability_mode != "off":
            observation_count = int(
                await session.scalar(
                    select(func.count(MarketObservation.id))
                    .join(
                        PricingRunItem,
                        PricingRunItem.id == MarketObservation.pricing_run_item_id,
                    )
                    .where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status == "classified",
                    )
                )
                or 0
            )
            runtime_identity = current_review_runtime_identity(settings)
            reviewed_count = int(
                await session.scalar(
                    select(
                        func.count(
                            func.distinct(
                                CandidateComparabilityReview.market_observation_id
                            )
                        )
                    )
                    .join(
                        MarketObservation,
                        MarketObservation.id
                        == CandidateComparabilityReview.market_observation_id,
                    )
                    .join(
                        PricingRunItem,
                        PricingRunItem.id == MarketObservation.pricing_run_item_id,
                    )
                    .where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status == "classified",
                        CandidateComparabilityReview.contract_version
                        == runtime_identity["contract_version"],
                        CandidateComparabilityReview.schema_version
                        == runtime_identity["schema_version"],
                        CandidateComparabilityReview.prompt_version
                        == runtime_identity["prompt_version"],
                        CandidateComparabilityReview.provider
                        == runtime_identity["provider"],
                        CandidateComparabilityReview.model_id
                        == runtime_identity["model_id"],
                        CandidateComparabilityReview.model_settings_hash
                        == runtime_identity["model_settings_hash"],
                    )
                )
                or 0
            )
            # A run item becomes "classified" before its potentially slow LLM
            # calls are persisted.  A finalizer from another item must not race
            # past that semantic-review barrier.
            if reviewed_count < observation_count:
                return False
        run.status = "calibrating"
        run.finalizer_task_id = task_id
        run.calibration_started_at = datetime.now(UTC)
        run.error = None
        await session.commit()
        return True


async def fail_collection_finalization(
    run_id: UUID, *, task_id: str | None, error: Exception
) -> None:
    """Fail undispatched items after the barrier exhausts its retries."""
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if (
            run is None
            or run.status != "calibrating"
            or run.finalizer_task_id != task_id
        ):
            return
        now = datetime.now(UTC)
        items = list(
            (
                await session.scalars(
                    select(PricingRunItem).where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status == "classified",
                    )
                )
            ).all()
        )
        for item in items:
            item.status = "failed"
            item.error = f"{type(error).__name__}: {error}"[:4000]
            item.finished_at = now
            item.checkpoint = {"stage": "barrier_failed", "at": now.isoformat()}
        run.status = "failed"
        run.finished_at = now
        run.error = f"{type(error).__name__}: {error}"[:4000]
        await session.commit()
    await finalize_pricing_run(run_id)


async def calibrate_run_and_prepare_calculations(run_id: UUID) -> list[UUID]:
    """Freeze pairs and both coefficient models before releasing calculations."""
    async with async_session_factory() as session:
        run = await session.get(PricingRun, run_id)
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        workspace_id = run.workspace_id
        # Калибровка — тоже вход расчёта: она обязана идти по снимку прогона.
        await verify_run_membership(session, run)
        policy = load_run_execution_policy(run)
        settings = get_settings()
        require_activated_run_policy(
            policy,
            robust_v3_enabled=settings.pricing_v3_robust_dispersion_enabled,
            activation_artifact_verified=activation_artifact_verified(
                settings.pricing_v3_activation_artifact,
                settings.pricing_v3_activation_sha256,
            ),
        )
        pairs = await _derive_calibration_pairs(session, run_id, policy)
        _, dataset_hash = await persist_run_calibration_pairs(
            session,
            workspace_id=workspace_id,
            pricing_run_id=run_id,
            pairs=pairs,
        )
        selected_records = []
        if pairs:
            simple_records = await calibrate_tier_coefficients(
                session,
                workspace_id=workspace_id,
                pairs=pairs,
                model=CoefficientModel.SIMPLE_MEDIAN,
                min_category_pairs=policy.min_category_pairs,
                min_global_pairs=policy.min_global_pairs,
                min_effective_pairs=policy.min_effective_pairs,
                max_interval_ratio=policy.max_allowed_interval_width,
                pricing_run_id=run_id,
                policy_version=policy.version,
                selected=policy.coefficient_model == CoefficientModel.SIMPLE_MEDIAN,
            )
            shrinkage_records = await calibrate_tier_coefficients(
                session,
                workspace_id=workspace_id,
                pairs=pairs,
                model=CoefficientModel.SHRINKAGE,
                shrinkage_k=policy.shrinkage_k,
                min_category_pairs=policy.min_category_pairs,
                min_global_pairs=policy.min_global_pairs,
                min_effective_pairs=policy.min_effective_pairs,
                max_interval_ratio=policy.max_allowed_interval_width,
                pricing_run_id=run_id,
                policy_version=policy.version,
                selected=policy.coefficient_model == CoefficientModel.SHRINKAGE,
            )
            selected_records = (
                simple_records
                if policy.coefficient_model == CoefficientModel.SIMPLE_MEDIAN
                else shrinkage_records
            )
            for record in simple_records + shrinkage_records:
                pricing_event(
                    "coefficient_calibrated"
                    if record.validated
                    else "coefficient_unvalidated",
                    pricing_run_id=str(run_id),
                    category=record.category,
                    tier=record.tier,
                    model=record.model,
                    sample_size=record.sample_size,
                    effective_sample_size=str(record.effective_sample_size),
                )
        run = await session.get(PricingRun, run_id)
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        run.calibration_dataset_hash = dataset_hash
        run.coefficient_model = policy.coefficient_model.value
        run.coefficient_version = (
            selected_records[0].coefficient_version if selected_records else None
        )
        run.calibration_completed_at = datetime.now(UTC)
        await session.commit()

    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        if run.cancel_requested:
            items = list(
                (
                    await session.scalars(
                        select(PricingRunItem).where(
                            PricingRunItem.pricing_run_id == run_id,
                            PricingRunItem.status == "classified",
                        )
                    )
                ).all()
            )
            now = datetime.now(UTC)
            for item in items:
                item.status = "cancelled"
                item.finished_at = now
            run.status = "cancelled"
            run.finished_at = now
            await session.commit()
            return []
        item_ids = list(
            (
                await session.scalars(
                    select(PricingRunItem.id)
                    .where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status == "classified",
                    )
                    .order_by(PricingRunItem.created_at, PricingRunItem.id)
                )
            ).all()
        )
        event_ids: list[UUID] = []
        for item_id in item_ids:
            event = await enqueue_dispatch(
                session,
                event_key=f"pricing-run:{run.id}:calculate:{item_id}:v1",
                aggregate_type="pricing_run_item",
                aggregate_id=item_id,
                workspace_id=run.workspace_id,
                task_name="marko.worker.calculate_pricing_item",
                task_args=[str(item_id)],
                queue="pricing-calculation",
            )
            event_ids.append(event.id)
        await session.commit()
        return event_ids


async def mark_run_calculating(run_id: UUID, *, task_id: str | None) -> None:
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            raise PricingItemNotFoundError(str(run_id))
        if run.status == "calibrating" and run.finalizer_task_id == task_id:
            run.status = "calculating"
            await session.commit()


async def _derive_calibration_pairs(
    session, run_id: UUID, policy
) -> list[CalibrationPair]:
    # Market observations are append-only. The database trigger permits this
    # transaction to update only the derived exclusion-code trace.
    await session.execute(
        select(
            func.set_config(
                "marko.calibration_evaluation",
                CALIBRATION_ELIGIBILITY_VERSION,
                True,
            )
        )
    )
    rows = list(
        (
            await session.execute(
                select(
                    CatalogItem,
                    MarketObservation,
                    ObservationTierClassification,
                )
                .join(PricingRunItem, PricingRunItem.catalog_item_id == CatalogItem.id)
                .join(
                    MarketObservation,
                    MarketObservation.pricing_run_item_id == PricingRunItem.id,
                )
                .join(
                    ObservationTierClassification,
                    ObservationTierClassification.market_observation_id
                    == MarketObservation.id,
                )
                .where(PricingRunItem.pricing_run_id == run_id)
                .order_by(
                    MarketObservation.id,
                    ObservationTierClassification.classified_at.desc(),
                    ObservationTierClassification.id.desc(),
                )
            )
        ).all()
    )
    latest: dict[
        UUID, tuple[CatalogItem, MarketObservation, ObservationTierClassification]
    ] = {}
    for item, observation, classification in rows:
        latest.setdefault(observation.id, (item, observation, classification))
    now = datetime.now(UTC)
    llm_settings = get_settings()
    llm_mode = llm_settings.pricing_llm_comparability_mode
    review_required_observation_ids = {
        observation.id
        for _item, observation, _classification in latest.values()
        if _semantic_review_required_for_observation(
            observation,
            global_required=llm_mode == "required",
        )
    }
    effective_reviews = await load_effective_review_map(
        session,
        list(latest),
        as_of=now,
        current_runtime_only=bool(review_required_observation_ids),
        settings=llm_settings,
    )
    grouped: dict[
        tuple[str, str],
        list[tuple[CatalogItem, MarketObservation, ObservationTierClassification]],
    ] = {}
    exclusion_counts: dict[str, int] = {}
    exact_groups: set[tuple[str, str]] = set()
    confirmed_cross_groups: set[tuple[str, str]] = set()
    eligible_count = 0
    for item, observation, classification in latest.values():
        semantic_review = effective_reviews.get(observation.id)
        review_required = observation.id in review_required_observation_ids
        if review_required and (
            semantic_review is None or not semantic_review.comparable
        ):
            if llm_mode == "required":
                reason = (
                    "CAL_LLM_COMPARABILITY_MISSING"
                    if semantic_review is None
                    else "CAL_LLM_NOT_COMPARABLE"
                    if semantic_review.verdict.value == "NOT_COMPARABLE"
                    else "CAL_LLM_COMPARABILITY_INSUFFICIENT"
                )
            else:
                reason = (
                    "CAL_CROSS_REVIEW_MISSING"
                    if semantic_review is None
                    else "CAL_CROSS_PRICING_NOT_ADMITTED"
                )
            observation.calibration_exclusion_codes = [reason]
            exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
            pricing_event(
                "calibration_observation_excluded_total",
                pricing_run_id=str(run_id),
                reason=reason,
                value=1,
            )
            continue
        decision = evaluate_calibration_eligibility(
            item,
            observation,
            classification,
            policy,
            now,
        )
        observation.calibration_exclusion_codes = list(decision.exclusion_codes)
        if not decision.eligible:
            for reason in decision.exclusion_codes:
                exclusion_counts[reason] = exclusion_counts.get(reason, 0) + 1
                pricing_event(
                    "calibration_observation_excluded_total",
                    pricing_run_id=str(run_id),
                    reason=reason,
                    value=1,
                )
            continue
        eligible_count += 1
        group_key = (
            (observation.canonical_category_id or "").strip(),
            (observation.comparison_identity_key or "").strip(),
        )
        grouped.setdefault(group_key, []).append((item, observation, classification))
        if (
            observation.oe_verification_status
            == OeVerificationStatus.VERIFIED_EXACT.value
        ):
            exact_groups.add(group_key)
        elif (
            observation.oe_verification_status
            == OeVerificationStatus.VERIFIED_CROSS.value
        ):
            confirmed_cross_groups.add(group_key)

    result: list[CalibrationPair] = []
    for (category, identity_key), observations in grouped.items():
        representatives: dict[
            tuple[ProductTier, str],
            tuple[CatalogItem, MarketObservation, ObservationTierClassification],
        ] = {}
        for row in observations:
            _, observation, classification = row
            tier = ProductTier(classification.tier)
            seller_key = (
                observation.seller_id.strip() or observation.seller_name.casefold()
            )
            key = (tier, seller_key)
            current = representatives.get(key)
            observation_price = effective_observation_price(observation)
            if current is None or (observation_price, observation.id) < (
                effective_observation_price(current[1]),
                current[1].id,
            ):
                representatives[key] = row
        deduplicated = list(representatives.values())
        reference_rows = [
            row
            for row in deduplicated
            if ProductTier(row[2].tier) == ProductTier.KEMP and not row[2].is_dumping
        ]
        direct_kemp_rows = [
            row
            for row in reference_rows
            if ProductTier(row[2].tier) == ProductTier.KEMP
        ]
        if len(direct_kemp_rows) >= 3:
            direct_kemp_center = decimal_median(
                effective_observation_price(row[1]) for row in direct_kemp_rows
            )
            dumping_ids = {
                row[1].id
                for row in direct_kemp_rows
                if effective_observation_price(row[1])
                < direct_kemp_center * policy.kemp_dumping_ratio
            }
            reference_rows = [
                row for row in reference_rows if row[1].id not in dumping_ids
            ]
        if not reference_rows:
            continue
        reference_price = decimal_median(
            effective_observation_price(row[1]) for row in reference_rows
        )
        reference_quality = decimal_median(
            _calibration_quality(row[1], row[2], now, policy) for row in reference_rows
        )
        tier_groups: dict[
            ProductTier,
            list[tuple[CatalogItem, MarketObservation, ObservationTierClassification]],
        ] = {}
        for row in deduplicated:
            tier = ProductTier(row[2].tier)
            if tier in {
                ProductTier.KEMP,
                ProductTier.BUDGET,
                ProductTier.USED,
                ProductTier.UNKNOWN,
            }:
                continue
            tier_groups.setdefault(tier, []).append(row)
        for tier, tier_rows in sorted(
            tier_groups.items(), key=lambda value: value[0].value
        ):
            tier_price = decimal_median(
                effective_observation_price(row[1]) for row in tier_rows
            )
            tier_quality = decimal_median(
                _calibration_quality(row[1], row[2], now, policy) for row in tier_rows
            )
            result.append(
                CalibrationPair(
                    oe_norm=identity_key,
                    category=category,
                    tier=tier,
                    tier_price=tier_price,
                    reference_price=reference_price,
                    quality_weight=min(reference_quality, tier_quality),
                    tier_observation_ids=tuple(
                        sorted(str(row[1].id) for row in tier_rows)
                    ),
                    reference_observation_ids=tuple(
                        sorted(str(row[1].id) for row in reference_rows)
                    ),
                    identity_evidence=tuple(
                        sorted(
                            (
                                *(
                                    calibration_identity_record(
                                        row[1], row[2], role="tier"
                                    )
                                    for row in tier_rows
                                ),
                                *(
                                    calibration_identity_record(
                                        row[1], row[2], role="reference"
                                    )
                                    for row in reference_rows
                                ),
                            ),
                            key=lambda value: (
                                value["observation_id"],
                                value["role"],
                            ),
                        )
                    ),
                )
            )
    dataset_hash = calibration_dataset_hash(result)
    run = await session.get(PricingRun, run_id)
    if run is None:
        raise PricingItemNotFoundError(str(run_id))
    considered = len(latest)
    excluded = considered - eligible_count
    if considered != eligible_count + excluded:
        raise RuntimeError("CALIBRATION_ACCOUNTING_ERROR")
    correlation_id = (run.calibration_accounting or {}).get("correlation_id")
    run.calibration_accounting = {
        **({"correlation_id": correlation_id} if correlation_id else {}),
        "observations_considered": considered,
        "eligible_observations": eligible_count,
        "excluded_observations": excluded,
        "exclusion_counts_by_reason": dict(sorted(exclusion_counts.items())),
        "exact_oe_groups": len(exact_groups),
        "confirmed_cross_groups": len(confirmed_cross_groups),
        "llm_comparability_mode": llm_mode,
        "semantic_review_required_observations": len(review_required_observation_ids),
        "llm_reviews_available": len(effective_reviews),
        "llm_positive_reviews": sum(
            review.comparable for review in effective_reviews.values()
        ),
        "category_tier_pairs": len(result),
        "dataset_hash": dataset_hash,
    }
    pricing_event(
        "calibration_accounting",
        pricing_run_id=str(run_id),
        observations_considered=considered,
        eligible_observations=eligible_count,
        excluded_observations=excluded,
        category_tier_pairs=len(result),
        dataset_hash=dataset_hash,
        correlation_id=correlation_id,
    )
    return result


def _calibration_quality(
    observation: MarketObservation,
    classification: ObservationTierClassification,
    now: datetime,
    policy,
) -> Decimal:
    age_hours = Decimal(
        str(max(0.0, (now - observation.observed_at).total_seconds()) / 3600)
    )
    freshness = Decimal(
        str(math.pow(2, -float(age_hours / policy.freshness_half_life_hours)))
    )
    return min(
        Decimal("1"),
        observation.match_confidence
        * classification.tier_confidence
        * observation.source_confidence
        * freshness,
    )


async def calculate_pricing_item(
    run_item_id: UUID, *, task_id: str | None = None
) -> UUID | None:
    run_id = await _claim_calculation(run_item_id, task_id=task_id)
    if run_id is None:
        terminal_run_id = await _run_id_for_statuses(
            run_item_id, ("calculated", "manual_review", "failed", "cancelled")
        )
        if terminal_run_id is not None:
            await finalize_pricing_run(terminal_run_id)
        return terminal_run_id
    await _calculate_and_persist(run_item_id)
    return run_id


async def _claim_calculation(run_item_id: UUID, *, task_id: str | None) -> UUID | None:
    async with async_session_factory() as session:
        item = await session.scalar(
            select(PricingRunItem)
            .where(PricingRunItem.id == run_item_id)
            .with_for_update(skip_locked=True)
        )
        if item is None:
            raise PricingItemNotFoundError(str(run_item_id))
        if item.status in {"calculated", "manual_review", "failed", "cancelled"}:
            return None
        if item.status == "calculating":
            return item.pricing_run_id if item.task_id == task_id else None
        if item.status != "classified":
            return None
        run = await session.get(PricingRun, item.pricing_run_id)
        if (
            run is None
            or run.status != "calculating"
            or run.calibration_completed_at is None
            or run.calibration_dataset_hash is None
        ):
            return None
        item.status = "calculating"
        item.task_id = task_id
        item.checkpoint = {
            "stage": "calculating",
            "at": datetime.now(UTC).isoformat(),
        }
        await session.commit()
        return item.pricing_run_id


async def _calculate_and_persist(run_item_id: UUID) -> None:
    async with async_session_factory() as session:
        existing = await session.scalar(
            select(PricingRecommendation).where(
                PricingRecommendation.pricing_run_item_id == run_item_id
            )
        )
        run_item = await session.get(PricingRunItem, run_item_id)
        if run_item is None:
            raise PricingItemNotFoundError(str(run_item_id))
        if existing is not None:
            if run_item.status not in {"calculated", "manual_review"}:
                run_item.status = (
                    "manual_review"
                    if existing.action
                    in {
                        RecommendationAction.MANUAL_REVIEW.value,
                        RecommendationAction.INSUFFICIENT_DATA.value,
                    }
                    else "calculated"
                )
                run_item.finished_at = datetime.now(UTC)
                await session.commit()
            await finalize_pricing_run(run_item.pricing_run_id)
            return
        run = await session.get(PricingRun, run_item.pricing_run_id)
        live_catalog_item = await session.get(CatalogItem, run_item.catalog_item_id)
        if run is None or live_catalog_item is None:
            raise PricingItemNotFoundError(
                "Pricing calculation dependencies are missing"
            )
        if run.cancel_requested:
            run_item.status = "cancelled"
            run_item.finished_at = datetime.now(UTC)
            await session.commit()
            await finalize_pricing_run(run.id)
            return
        # Ограниченный прогон считает по замороженному виду позиции. Живая
        # строка каталога дальше не используется: она нужна была только чтобы
        # убедиться, что позиция ещё существует.
        await verify_run_membership(session, run)
        catalog_item = resolve_bound_execution_item(run, run_item, live_catalog_item)

        rows = list(
            (
                await session.execute(
                    select(MarketObservation, ObservationTierClassification)
                    .join(
                        ObservationTierClassification,
                        ObservationTierClassification.market_observation_id
                        == MarketObservation.id,
                    )
                    .where(MarketObservation.pricing_run_item_id == run_item_id)
                    .order_by(
                        MarketObservation.id,
                        ObservationTierClassification.classified_at.desc(),
                        ObservationTierClassification.id.desc(),
                    )
                )
            ).all()
        )
        latest: dict[UUID, tuple[MarketObservation, ObservationTierClassification]] = {}
        for observation, classification in rows:
            latest.setdefault(observation.id, (observation, classification))
        now = datetime.now(UTC)
        settings = get_settings()
        llm_mode = settings.pricing_llm_comparability_mode
        semantic_review_required = llm_mode == "required"
        review_required_observation_ids = {
            observation.id
            for observation, _classification in latest.values()
            if _semantic_review_required_for_observation(
                observation,
                global_required=semantic_review_required,
            )
        }
        effective_reviews = await load_effective_review_map(
            session,
            list(latest),
            as_of=now,
            current_runtime_only=bool(review_required_observation_ids),
            settings=settings,
        )
        offers = [
            _domain_offer(
                observation,
                classification,
                now,
                semantic_review=effective_reviews.get(observation.id),
                semantic_review_required=(
                    observation.id in review_required_observation_ids
                ),
            )
            for observation, classification in latest.values()
        ]
        # Прогон считает по входам, замороженным на старте, а не по текущим.
        # Иначе правка каталога или себестоимости, поданная оператором уже во
        # время расчёта, попадала бы в идущий прогон, и один и тот же прогон
        # нельзя было бы воспроизвести: часть позиций посчитана по старым
        # данным, часть по новым, а в отчёте об этом ни следа.
        #
        # Прогоны, начатые до появления замороженной области
        # (``scope_contract_version`` пуст или ``LEGACY_UNBOUNDED``), таких
        # ссылок не имеют, поэтому для них сохраняется прежнее поведение —
        # это единственный способ досчитать их без переписывания истории.
        if not uses_frozen_start_inputs(run, run_item):
            override = await get_latest_override(session, catalog_item.id)
            configured_cost = await get_decrypted_catalog_cost(
                session,
                workspace_id=run.workspace_id,
                catalog_item_id=catalog_item.id,
                settings=settings,
            )
        else:
            # Значения правки берутся из проверенного снимка, а не из строки,
            # на которую он ссылается: ссылка ведёт в живые данные.
            override = resolve_execution_override(run, run_item)
            configured_cost = decrypt_cost_record(
                await load_run_item_start_cost_record(session, run_item),
                workspace_id=run.workspace_id,
                catalog_item_id=catalog_item.id,
                settings=settings,
            )
        context = build_pricing_context(catalog_item, override)
        identity_missing = not customer_identity_available(catalog_item)
        if identity_missing:
            # This is a hard acquisition boundary, not merely weak evidence.
            # Even a stale or accidentally retained observation must not make
            # an unidentified customer row priceable.
            offers = []
        # Политика читается ТОЛЬКО из снимка прогона с пересчётом отпечатка:
        # файл развёртывания — источник для нового предпросмотра, а не для уже
        # принятого расчёта.
        policy = load_run_execution_policy(run)
        require_activated_run_policy(
            policy,
            robust_v3_enabled=settings.pricing_v3_robust_dispersion_enabled,
            activation_artifact_verified=activation_artifact_verified(
                settings.pricing_v3_activation_artifact,
                settings.pricing_v3_activation_sha256,
            ),
        )
        coefficients = await load_target_tier_coefficients(
            session,
            run=run,
            category=catalog_item.category,
            oe_norm=customer_identity_query(catalog_item),
            policy=policy,
            comparison_identity_keys={
                observation.comparison_identity_key
                for observation, _classification in latest.values()
                if observation.comparison_identity_key
            },
        )
        result = recommend_price(context, offers, coefficients, policy=policy)
        if identity_missing:
            result = replace(
                result,
                reasons=tuple(
                    dict.fromkeys(("CUSTOMER_IDENTITY_MISSING", *result.reasons))
                ),
            )
        (
            comparability_activation_verified,
            comparability_activation_basis,
        ) = resolve_comparability_activation(settings)
        customer_policy_trace, advisory_decision = customer_budget_floor_trace(
            policy=policy.raise_policy,
            result=result,
            comparability_activation_verified=comparability_activation_verified,
        )
        result = apply_comparability_activation_gate(
            result,
            activation_verified=comparability_activation_verified,
        )
        recommended_price_below_cost = (
            result.recommended_price < configured_cost
            if result.recommended_price is not None and configured_cost is not None
            else None
        )
        applied_versions = sorted(
            {
                coefficient.coefficient_version or coefficient.method_version
                for coefficient in coefficients.values()
            }
        )
        tier_agnostic_pricing = bool(
            policy.raise_policy is not None
            and policy.raise_policy.strategy is RaiseStrategy.BUDGET_FLOOR
            and policy.raise_policy.tier_agnostic
        )
        applied_coefficient_version = (
            "owner-tier-agnostic-v1"
            if tier_agnostic_pricing
            else applied_versions[0]
            if applied_versions
            else None
        )
        context_snapshot = {
            "sku": context.sku,
            "category": context.category,
            "currency": context.currency,
            "current_price": str(context.current_price),
            "stock_status": context.stock_status.value,
            "cost_privacy_mode": settings.cost_privacy_mode,
            "cost_configured": configured_cost is not None,
            "recommended_price_below_cost": recommended_price_below_cost,
            "stock_qty": str(context.stock_qty)
            if context.stock_qty is not None
            else None,
            "stock_age_days": str(context.stock_age_days)
            if context.stock_age_days is not None
            else None,
            "expected_units_sold": str(context.expected_units_sold)
            if context.expected_units_sold is not None
            else None,
            "units_sold_30d": str(context.units_sold_30d)
            if context.units_sold_30d is not None
            else None,
            "units_sold_60d": str(context.units_sold_60d)
            if context.units_sold_60d is not None
            else None,
            "units_sold_90d": str(context.units_sold_90d)
            if context.units_sold_90d is not None
            else None,
            "days_since_last_sale": str(context.days_since_last_sale)
            if context.days_since_last_sale is not None
            else None,
            "historical_monthly_units": str(context.historical_monthly_units)
            if context.historical_monthly_units is not None
            else None,
            "views_30d": str(context.views_30d)
            if context.views_30d is not None
            else None,
            "conversion_rate_proxy": str(context.conversion_rate_proxy)
            if context.conversion_rate_proxy is not None
            else None,
            "liquidity_target": str(context.liquidity_target),
            "urgency": str(context.urgency),
            "manual_priority": str(context.manual_priority),
            "comparability_contract_version": COMPARABILITY_CONTRACT_VERSION,
            "llm_comparability_mode": llm_mode,
        }
        robust_diagnostic = cluster_diagnostic_to_dict(result.cluster_diagnostic)
        calculation_trace = {
            "replay_contract_version": "recommendation-replay-v6",
            "decision_fingerprint_version": DECISION_FINGERPRINT_VERSION,
            "numeric_precision": {
                "profile_version": TRANSCENDENTAL_PROFILE_VERSION,
                "relative_tolerance": str(TRANSCENDENTAL_RELATIVE_TOLERANCE),
            },
            "calculated_at": now.isoformat(),
            "catalog_snapshot_id": str(run.import_batch_id),
            "pricing_run_id": str(run.id),
            "fair_price_estimator": (
                "minimum_verified_comparable_price"
                if tier_agnostic_pricing
                else "median"
            ),
            "outlier_filter": result.outlier_method,
            "customer_pricing_policy": customer_policy_trace,
            "advisory_decision": advisory_decision,
            "robust_dispersion": robust_dispersion_trace(
                selected_method=result.dispersion_method,
                pre_clean=result.pre_clean_dispersion_profile,
                post_clean=result.dispersion_profile,
                profile_version=policy.robust_dispersion_profile_version,
                correction_profile_version=(
                    policy.robust_scale_correction_profile_version
                ),
                finite_sample_correction=(policy.finite_sample_scale_correction),
            ),
            "robust_diagnostic": robust_diagnostic,
            "robust_policy_fingerprint": dict(result.robust_policy_fingerprint),
            "comparability": {
                "contract_version": COMPARABILITY_CONTRACT_VERSION,
                "policy_id": result.comparability_policy_id,
                "policy_hash": result.comparability_policy_hash,
                "automatic_eligible": result.automatic_eligible,
                "activation_verified": comparability_activation_verified,
                "activation_basis": comparability_activation_basis,
                "verified_seller_count": result.verified_seller_count,
                "hard_gates": dict(result.hard_gate_results),
                "failed_hard_gates": list(result.failed_hard_gates),
                "unknown_hard_fields": list(result.unknown_hard_fields),
            },
            "llm_comparability": {
                "mode": llm_mode,
                "required": semantic_review_required,
                "required_observation_ids": sorted(
                    str(observation_id)
                    for observation_id in review_required_observation_ids
                ),
                "reviewed_observation_count": len(effective_reviews),
                "positive_observation_count": sum(
                    review.comparable for review in effective_reviews.values()
                ),
                "reviews": [
                    review.as_dict()
                    for review in sorted(
                        effective_reviews.values(),
                        key=lambda value: str(value.market_observation_id),
                    )
                ],
                "automatic_price_publication": False,
            },
            "confidence_aggregation": policy.confidence_aggregation.value,
            "factor_scores": {
                key: str(value) for key, value in result.factor_scores.items()
            },
            "hard_factor_floors": {
                key: str(value) for key, value in policy.factor_floors.items()
            },
            "action_gates_passed": result.action_gates_passed,
            "sensitivity": str(result.sensitivity)
            if result.sensitivity is not None
            else None,
            "winsorized_fair_price": str(result.winsorized_fair_price)
            if result.winsorized_fair_price is not None
            else None,
            "market_counts": {
                "raw": result.raw_competitor_count,
                "target_market": result.target_market_count,
                "kemp_reference": result.kemp_reference_count,
                "owned_store": result.owned_store_count,
                "rejected": result.rejected_count,
                "unique_sellers": result.unique_seller_count,
                "clean": result.clean_competitor_count,
                "effective": str(result.effective_competitor_count),
                "outliers": result.outlier_count,
            },
            "normalized_offers": [
                {
                    "observation_id": offer.observation_id,
                    "seller_id": offer.seller_id,
                    "seller_name": offer.seller_name,
                    "category": catalog_item.category,
                    "tier": offer.tier.value,
                    "raw_price": str(offer.raw_price),
                    "coefficient": str(offer.multiplier),
                    "multiplier": str(offer.multiplier),
                    "coefficient_model": (
                        offer.coefficient_model.value
                        if offer.coefficient_model is not None
                        else "reference"
                    ),
                    "coefficient_version": offer.coefficient_version,
                    "coefficient_sample_size": offer.coefficient_sample_size,
                    "coefficient_effective_sample_size": str(
                        offer.coefficient_effective_sample_size
                    ),
                    "coefficient_confidence": str(offer.coefficient_confidence),
                    "coefficient_dataset_hash": offer.coefficient_dataset_hash,
                    "normalized_price": str(offer.normalized_price),
                    "match_confidence": str(offer.match_confidence),
                    "tier_confidence": str(offer.tier_confidence),
                    "source_confidence": str(offer.source_confidence),
                    "age_hours": str(offer.age_hours),
                    "source": offer.source,
                    "listing_url": offer.listing_url,
                    "cohort_role": offer.cohort_role.value,
                    "llm_review": (
                        effective_reviews[UUID(offer.observation_id)].as_dict()
                        if UUID(offer.observation_id) in effective_reviews
                        else None
                    ),
                }
                for offer in result.evidence
            ],
            "kemp_reference_offers": [
                {
                    "observation_id": offer.observation_id,
                    "seller_id": offer.seller_id,
                    "seller_name": offer.seller_name,
                    "tier": offer.tier.value,
                    "raw_price": str(offer.raw_price),
                    "normalized_price": str(offer.normalized_price),
                    "listing_url": offer.listing_url,
                    "cohort_role": offer.cohort_role.value,
                    "target_effect": "NOT_IN_TARGET_MEDIAN",
                    "llm_review": (
                        effective_reviews[UUID(offer.observation_id)].as_dict()
                        if UUID(offer.observation_id) in effective_reviews
                        else None
                    ),
                }
                for offer in result.kemp_reference_evidence
            ],
            "tier_coefficients": [
                {
                    "category": coefficient.category,
                    "tier": coefficient.tier.value,
                    "multiplier": str(coefficient.multiplier),
                    "model": coefficient.model.value,
                    "method_version": coefficient.method_version,
                    "coefficient_version": coefficient.coefficient_version,
                    "dataset_hash": coefficient.dataset_hash,
                    "sample_size": coefficient.sample_size,
                    "effective_sample_size": str(coefficient.effective_sample_size),
                    "interval_low": str(coefficient.interval_low)
                    if coefficient.interval_low is not None
                    else None,
                    "interval_high": str(coefficient.interval_high)
                    if coefficient.interval_high is not None
                    else None,
                    "confidence": str(coefficient.confidence),
                    "validated": coefficient.validated,
                    "validation_reasons": list(coefficient.validation_reasons),
                    "excluded_oe_norm": coefficient.excluded_oe_norm,
                    "used_for_price": not tier_agnostic_pricing,
                }
                for coefficient in sorted(
                    coefficients.values(), key=lambda value: value.tier.value
                )
            ],
            "excluded_observations": [
                {
                    "observation_id": excluded.observation_id,
                    "seller_id": excluded.seller_id,
                    "raw_price": str(excluded.raw_price)
                    if excluded.raw_price is not None
                    else None,
                    "tier": excluded.tier.value if excluded.tier else None,
                    "reason": excluded.reason,
                    "stage": excluded.stage,
                    "cohort_role": excluded.cohort_role.value,
                }
                for excluded in result.excluded
            ],
            "priority": {
                "raw_score": str(result.priority_score),
                "score_type": result.priority_score_type.value,
                "review_priority": str(result.review_priority),
                "inputs": dict(result.priority_inputs),
            },
            "policy_version": policy.version,
            "pricing_policy_hash": canonical_sha256(run.policy_config),
            "build_identity": settings.build_identity,
            "parser_version": run.parser_version,
            "classifier_version": run.classifier_version,
            "calibration_dataset_hash": run.calibration_dataset_hash,
            "coefficient_version": applied_coefficient_version,
            "price_tick": str(policy.price_tick),
            "price_tick_version": policy.price_tick_version,
        }
        fingerprint_payload = build_decision_fingerprint_payload(
            context_snapshot=context_snapshot,
            result=result,
            observations=[value[0] for value in latest.values()],
            policy_config=run.policy_config,
            coefficients=coefficients.values(),
            parser_version=run.parser_version,
            classifier_version=run.classifier_version,
            calibration_dataset_hash=run.calibration_dataset_hash,
            coefficient_version=applied_coefficient_version,
            build_identity=settings.build_identity,
            price_tick=policy.price_tick,
            price_tick_version=policy.price_tick_version,
            comparability_reviews=[
                review.as_dict()
                for review in sorted(
                    effective_reviews.values(),
                    key=lambda value: str(value.market_observation_id),
                )
            ],
        )
        decision_fingerprint = canonical_sha256(fingerprint_payload)
        calculation_trace["decision_fingerprint_payload"] = fingerprint_payload
        calculation_trace["decision_fingerprint"] = decision_fingerprint
        recommendation = PricingRecommendation(
            pricing_run_id=run.id,
            pricing_run_item_id=run_item.id,
            catalog_item_id=catalog_item.id,
            catalog_snapshot_id=run.import_batch_id,
            context_snapshot=context_snapshot,
            calculation_trace=calculation_trace,
            action=result.action.value,
            current_price=result.current_price,
            fair_price=result.fair_price,
            recommended_price=result.recommended_price,
            lower_bound=result.lower_bound,
            upper_bound=result.upper_bound,
            confidence=result.confidence,
            confidence_grade=result.confidence_grade,
            weakest_factor=result.weakest_factor,
            factor_scores={
                key: str(value) for key, value in result.factor_scores.items()
            },
            competitor_count=result.competitor_count,
            raw_competitor_count=result.raw_competitor_count,
            unique_seller_count=result.unique_seller_count,
            clean_competitor_count=result.clean_competitor_count,
            target_market_count=result.target_market_count,
            kemp_reference_count=result.kemp_reference_count,
            owned_store_count=result.owned_store_count,
            rejected_count=result.rejected_count,
            effective_competitor_count=result.effective_competitor_count,
            dispersion=result.dispersion,
            outlier_method=result.outlier_method,
            outlier_count=result.outlier_count,
            sensitivity=result.sensitivity,
            action_gates_passed=result.action_gates_passed,
            automatic_eligible=result.automatic_eligible,
            verified_seller_count=result.verified_seller_count,
            comparability_policy_id=result.comparability_policy_id,
            comparability_policy_hash=result.comparability_policy_hash,
            decision_fingerprint=decision_fingerprint,
            hard_gate_trace={
                "hard_gates": dict(result.hard_gate_results),
                "failed_hard_gates": list(result.failed_hard_gates),
                "unknown_hard_fields": list(result.unknown_hard_fields),
            },
            robust_diagnostic=robust_diagnostic,
            cost_floor=result.cost_floor,
            cost_basis_inventory_value=result.cost_basis_inventory_value,
            priority_score=result.priority_score,
            priority_score_type=result.priority_score_type.value,
            review_priority=result.review_priority,
            absolute_recommended_change=result.absolute_recommended_change,
            percentage_recommended_change=result.percentage_recommended_change,
            reason_codes=list(result.reasons),
            evidence_observation_ids=[
                offer.observation_id for offer in result.evidence
            ],
            kemp_reference_observation_ids=[
                offer.observation_id for offer in result.kemp_reference_evidence
            ],
            excluded_observations=[
                {
                    "observation_id": excluded.observation_id,
                    "reason": excluded.reason,
                    "stage": excluded.stage,
                    "cohort_role": excluded.cohort_role.value,
                }
                for excluded in result.excluded
            ],
            policy_version=result.policy_version,
            parser_version=run.parser_version,
            classifier_version=run.classifier_version,
            coefficient_version=applied_coefficient_version,
            calibration_dataset_hash=run.calibration_dataset_hash,
            currency=context.currency,
            price_tick=policy.price_tick,
            price_tick_version=policy.price_tick_version,
        )
        session.add(recommendation)
        run_item.status = (
            "manual_review"
            if result.action
            in {
                RecommendationAction.MANUAL_REVIEW,
                RecommendationAction.INSUFFICIENT_DATA,
            }
            else "calculated"
        )
        run_item.finished_at = now
        run_item.checkpoint = {
            "stage": "calculated",
            "action": result.action.value,
            "confidence": str(result.confidence),
            "at": now.isoformat(),
        }
        await session.commit()
        event_name = {
            RecommendationAction.RAISE: "recommendation_raise",
            RecommendationAction.LOWER: "recommendation_lower",
            RecommendationAction.HOLD: "recommendation_hold",
            RecommendationAction.MANUAL_REVIEW: "recommendation_manual_review",
            RecommendationAction.INSUFFICIENT_DATA: "recommendation_manual_review",
        }[result.action]
        pricing_event(
            event_name,
            pricing_run_id=str(run.id),
            pricing_run_item_id=str(run_item.id),
            action=result.action.value,
            confidence=str(result.confidence),
            competitor_count=result.competitor_count,
            priority_score_type=result.priority_score_type.value,
        )
        pricing_event(
            "matching_candidates_total",
            classification=(
                "automatic_eligible" if result.automatic_eligible else "abstained"
            ),
            reason=(result.reasons[0] if result.reasons else "NONE"),
            value=result.raw_competitor_count,
        )
        pricing_event(
            "matching_automatic_eligible_total",
            policy_version=result.policy_version,
            value=int(result.automatic_eligible),
        )
        for field in result.unknown_hard_fields:
            pricing_event(
                "matching_missing_hard_field_total",
                field=field,
                category="auto_parts",
                value=1,
            )
        if result.action in {
            RecommendationAction.MANUAL_REVIEW,
            RecommendationAction.INSUFFICIENT_DATA,
        }:
            for reason in result.reasons:
                pricing_event(
                    "pricing_abstention_total",
                    reason=reason,
                    policy_version=result.policy_version,
                    value=1,
                )
        if result.cluster_diagnostic and result.cluster_diagnostic.flagged:
            pricing_event(
                "pricing_robust_cluster_flag_total",
                policy_version=result.policy_version,
                value=1,
            )
        if "ROBUST_BASELINE_ABSTENTION_NOT_RELAXABLE" in result.reasons:
            pricing_event(
                "pricing_unsafe_relaxation_blocked_total",
                baseline=policy.robust_baseline_policy_version,
                candidate=result.policy_version,
                value=1,
            )
    await finalize_pricing_run(run_item.pricing_run_id)


def _widened_match_level_ceiling(
    match_level: str | None,
    comparison_evidence: ComparisonEvidence | None,
) -> str | None:
    """Cap the grade at ``ACCEPTABLE_ANALOGUE`` for a related number's market.

    When our own part code has no listing on prom.ua the market is taken by a
    number from its supersession chain.  That is a different sellable part
    until something proves otherwise, so ``EXACT`` is not available here no
    matter what the semantic reviewer said.  The decision is deterministic and
    lives on the persistence/domain side: it reads only the ``retrieval_kind``
    stored with the observation.

    The ceiling only ever lowers a grade.  ``SUSPICIOUS`` and
    ``NOT_APPLICABLE`` pass through untouched — it has no business promoting
    anything.
    """

    if match_level != ComparabilityMatchLevel.EXACT.value:
        return match_level
    retrieval_kind = (
        comparison_evidence.retrieval_kind if comparison_evidence is not None else None
    )
    if not retrieval_kind_is_widened(retrieval_kind):
        return match_level
    return ComparabilityMatchLevel.ACCEPTABLE_ANALOGUE.value


def _semantic_review_required_for_observation(
    observation: MarketObservation,
    *,
    global_required: bool,
    traced_required_observation_ids: frozenset[str] | None = None,
) -> bool:
    """Return the immutable semantic-review authority for one observation.

    Current calculations and calibration pass ``None`` for the traced set:
    every verified cross/analogue is fail-closed even when the global provider
    mode is ``off`` or ``shadow``.  Replay passes the IDs frozen in the trace;
    an empty set deliberately preserves pre-field historical traces.
    """

    if global_required:
        return True
    if traced_required_observation_ids is not None:
        return str(observation.id) in traced_required_observation_ids
    return (
        observation.oe_verification_status == OeVerificationStatus.VERIFIED_CROSS.value
    )


def _domain_offer(
    observation: MarketObservation,
    classification: ObservationTierClassification,
    now: datetime,
    *,
    semantic_review: EffectiveComparabilityReview | None = None,
    semantic_review_required: bool = False,
) -> CompetitorOffer:
    age_seconds = max(0.0, (now - observation.observed_at).total_seconds())
    condition_assessment = classify_condition(
        title=observation.title,
        description=observation.description,
        explicit_condition=observation.condition_raw,
    )
    derived_used = condition_assessment.is_used or observation.condition_state in {
        "USED_OR_REFURBISHED",
        "CONFLICT",
    }
    condition_unknown = condition_assessment.state.value == "UNKNOWN"
    derived_kemp = normalize_brand(observation.brand_raw) == "KEMP"
    comparison_evidence = comparison_evidence_from_dict(observation.comparison_evidence)
    semantic_gate_current = semantic_gate_snapshot_is_current(
        getattr(observation, "candidate_snapshot", None),
        expected_source_listing_id=getattr(observation, "source_listing_id", None),
        expected_raw_capture_id=getattr(observation, "raw_capture_id", None),
        expected_identity_key=getattr(observation, "comparison_identity_key", None),
        require_identity_namespace=(
            getattr(observation, "catalog_item_id", None) is not None
        ),
    )
    if semantic_review_required:
        comparison_evidence = apply_effective_review_to_evidence(
            comparison_evidence,
            semantic_review,
        )
    persisted_admission = bool(
        getattr(observation, "automatic_eligible", False)
        and getattr(observation, "comparability_hard_gate_result", "")
        == HardGateResult.PASS.value
        and observation.oe_verification_status
        in {
            OeVerificationStatus.VERIFIED_EXACT.value,
            OeVerificationStatus.VERIFIED_CROSS.value,
        }
        and getattr(observation, "seller_identity_verified", False) is True
        and getattr(observation, "source_provenance_verified", False) is True
        and persisted_identity_fields_consistent(observation)
        and semantic_gate_current
    )
    cohort_admission = bool(
        not classification.is_owned
        and not classification.is_kemp
        and not classification.is_used
        and not classification.is_dumping
        and str(classification.cohort_role or "").strip()
        == CohortRole.TARGET_MARKET.value
        and not derived_used
        and not derived_kemp
        and not condition_unknown
    )
    return CompetitorOffer(
        observation_id=str(observation.id),
        seller_id=observation.seller_id,
        seller_name=observation.seller_name,
        price=effective_observation_price(observation),
        currency=observation.currency,
        currency_raw=observation.currency_raw,
        currency_inferred=observation.currency_inferred,
        currency_evidence=(
            f"market_observation:{observation.id}:currency_raw"
            if observation.currency_raw
            else None
        ),
        is_available=observation.is_available,
        age_hours=Decimal(str(age_seconds / 3600)),
        match_confidence=observation.match_confidence,
        tier=ProductTier(classification.tier),
        tier_confidence=classification.tier_confidence,
        source_confidence=observation.source_confidence,
        is_used=classification.is_used or derived_used,
        is_kemp=classification.is_kemp or derived_kemp,
        is_owned=classification.is_owned,
        is_dumping=classification.is_dumping,
        severe_conflict=(
            classification.exclusion_reason == "TIER_CONFLICT" or condition_unknown
        ),
        conflict_reason=(
            classification.exclusion_reason
            or ("CONDITION_UNKNOWN" if condition_unknown else None)
        ),
        source=observation.source,
        listing_url=observation.url,
        comparison_evidence=comparison_evidence,
        cohort_role=CohortRole(classification.cohort_role),
        semantic_review_required=semantic_review_required,
        semantic_review_id=(
            str(semantic_review.review_id) if semantic_review is not None else None
        ),
        semantic_review_verdict=(
            semantic_review.verdict.value if semantic_review is not None else None
        ),
        semantic_review_match_level=_widened_match_level_ceiling(
            semantic_review.match_level.value if semantic_review is not None else None,
            comparison_evidence,
        ),
        semantic_review_confidence=(
            semantic_review.confidence if semantic_review is not None else None
        ),
        semantic_gate_current=semantic_gate_current,
        # Older replay/test adapters may expose a lightweight observation
        # without the persisted admission column.  Missing admission is
        # not evidence: fail closed instead of allowing a legacy object to
        # enter a price cohort merely because it lacks the field.
        # The persisted scalar is only one input.  Recheck the immutable
        # identity projection and the current cohort role at the pricing
        # boundary so a stale/hand-built row cannot become a market offer
        # merely by carrying ``automatic_eligible=true``.
        automatic_eligible=persisted_admission and cohort_admission,
    )


async def reset_pricing_item_for_retry(run_item_id: UUID, error: Exception) -> None:
    async with async_session_factory() as session:
        item = await session.get(PricingRunItem, run_item_id)
        if item is None or item.status in {
            "calculated",
            "manual_review",
            "failed",
            "cancelled",
        }:
            return
        item.status = "queued"
        item.error = f"{type(error).__name__}: {error}"[:4000]
        item.checkpoint = {
            "stage": "retry_queued",
            "attempts": item.attempts,
            "at": datetime.now(UTC).isoformat(),
        }
        await session.commit()
        pricing_event(
            "market_collection_retry",
            pricing_run_item_id=str(run_item_id),
            attempt=item.attempts,
            error_type=type(error).__name__,
        )


async def reset_pricing_calculation_for_retry(
    run_item_id: UUID, error: Exception
) -> None:
    async with async_session_factory() as session:
        item = await session.get(PricingRunItem, run_item_id)
        if item is None or item.status in {
            "calculated",
            "manual_review",
            "failed",
            "cancelled",
        }:
            return
        item.status = "classified"
        item.error = f"{type(error).__name__}: {error}"[:4000]
        item.checkpoint = {
            "stage": "calculation_retry_queued",
            "attempts": item.attempts,
            "at": datetime.now(UTC).isoformat(),
        }
        await session.commit()


async def fail_pricing_item(run_item_id: UUID, error: Exception) -> None:
    run_id: UUID | None = None
    async with async_session_factory() as session:
        item = await session.scalar(
            select(PricingRunItem)
            .where(PricingRunItem.id == run_item_id)
            .with_for_update()
        )
        if item is None or item.status in {"calculated", "manual_review", "cancelled"}:
            return
        run_id = item.pricing_run_id
        if item.scrape_target_id is not None and item.status in {
            "queued",
            "collecting",
            "collected",
        }:
            target = await session.scalar(
                select(ScrapeTarget)
                .where(ScrapeTarget.id == item.scrape_target_id)
                .with_for_update()
            )
            siblings = list(
                (
                    await session.scalars(
                        select(PricingRunItem).where(
                            PricingRunItem.scrape_target_id == item.scrape_target_id,
                            PricingRunItem.status.in_(
                                ("queued", "collecting", "collected")
                            ),
                        )
                    )
                ).all()
            )
            now = datetime.now(UTC)
            if target is not None and target.status != "succeeded":
                if target.status != "terminal_failure":
                    target.status = "terminal_failure"
                    _set_terminal_target_contract(
                        target,
                        reason=ScraperErrorCode.RETRY_EXHAUSTED.value,
                        raw_available=target.raw_size_bytes > 0,
                    )
                    target.error_category = ScraperErrorCode.RETRY_EXHAUSTED.value
                    target.error_detail = (f"{type(error).__name__}: {error}")[:4000]
                target.owner_task_id = None
                target.lease_expires_at = None
                target.finished_at = target.finished_at or now
                terminal_reason = (
                    target.error_category or ScraperErrorCode.RETRY_EXHAUSTED.value
                )
                terminal_detail = (
                    target.error_detail or f"{type(error).__name__}: {error}"
                )[:4000]
                for sibling in siblings:
                    sibling.status = "classified"
                    sibling.error = terminal_detail
                    sibling.checkpoint = {
                        "stage": "classified_without_evidence",
                        "reason": terminal_reason,
                        "at": now.isoformat(),
                    }
            else:
                for sibling in siblings:
                    sibling.status = "failed"
                    sibling.error = (
                        f"evidence_persistence: {type(error).__name__}: {error}"
                    )[:4000]
                    sibling.finished_at = now
                    sibling.checkpoint = {
                        "stage": "failed",
                        "reason": ScraperErrorCode.EVIDENCE_PERSISTENCE.value,
                        "at": now.isoformat(),
                    }
            await session.commit()
            pricing_event(
                "pricing_item_failed",
                pricing_run_id=str(run_id),
                pricing_run_item_id=str(run_item_id),
                scrape_target_id=str(item.scrape_target_id),
                error_type=type(error).__name__,
            )
            if run_id is not None:
                await finalize_pricing_run(run_id)
            return
        item.status = "failed"
        item.error = f"{type(error).__name__}: {error}"[:4000]
        item.finished_at = datetime.now(UTC)
        item.checkpoint = {"stage": "failed", "at": item.finished_at.isoformat()}
        await session.commit()
        pricing_event(
            "pricing_item_failed",
            pricing_run_id=str(run_id),
            pricing_run_item_id=str(run_item_id),
            error_type=type(error).__name__,
        )
    if run_id is not None:
        await finalize_pricing_run(run_id)


async def fail_pricing_run_dispatch(run_id: UUID, error: Exception) -> None:
    """Fail a run deterministically after orchestration dispatch is exhausted."""

    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None or run.status in {
            "completed",
            "partial",
            "failed",
            "cancelled",
        }:
            return
        now = datetime.now(UTC)
        detail = f"{type(error).__name__}: {error}"[:4000]
        targets = list(
            (
                await session.scalars(
                    select(ScrapeTarget).where(
                        ScrapeTarget.pricing_run_id == run_id,
                        ScrapeTarget.status.not_in(
                            ("succeeded", "terminal_failure", "cancelled")
                        ),
                    )
                )
            ).all()
        )
        target_ids = [target.id for target in targets]
        for target in targets:
            target.status = "terminal_failure"
            _set_terminal_target_contract(
                target,
                reason=ScraperErrorCode.RETRY_EXHAUSTED.value,
                raw_available=target.raw_size_bytes > 0,
            )
            target.error_category = ScraperErrorCode.RETRY_EXHAUSTED.value
            target.error_detail = detail
            target.owner_task_id = None
            target.lease_expires_at = None
            target.finished_at = now
        if target_ids:
            attempts = list(
                (
                    await session.scalars(
                        select(ScrapeAttempt).where(
                            ScrapeAttempt.scrape_target_id.in_(target_ids),
                            ScrapeAttempt.status == "running",
                        )
                    )
                ).all()
            )
            for attempt in attempts:
                attempt.status = "worker_lost"
                attempt.error_category = "dispatch_exhausted"
                attempt.error_detail = detail
                attempt.finished_at = now
                if attempt.wall_time_ms == 0:
                    attempt.wall_time_ms = max(
                        0,
                        round(
                            (now - _aware_datetime(attempt.started_at)).total_seconds()
                            * 1000
                        ),
                    )
        items = list(
            (
                await session.scalars(
                    select(PricingRunItem).where(
                        PricingRunItem.pricing_run_id == run_id,
                        PricingRunItem.status.not_in(
                            (
                                "calculated",
                                "manual_review",
                                "failed",
                                "cancelled",
                            )
                        ),
                    )
                )
            ).all()
        )
        for item in items:
            item.status = "failed"
            item.error = f"dispatch_exhausted: {detail}"[:4000]
            item.finished_at = now
            item.checkpoint = {
                "stage": "failed",
                "reason": "dispatch_exhausted",
                "at": now.isoformat(),
            }
        run.status = "failed"
        run.failed_items = run.total_items
        run.error = f"Pricing dispatch exhausted: {detail}"[:4000]
        run.finished_at = now
        await session.commit()
        pricing_event(
            "pricing_run_failed",
            pricing_run_id=str(run.id),
            status="failed",
            reason="dispatch_exhausted",
            failed=run.failed_items,
        )


async def finalize_pricing_run(run_id: UUID) -> None:
    async with async_session_factory() as session:
        run = await session.scalar(
            select(PricingRun).where(PricingRun.id == run_id).with_for_update()
        )
        if run is None:
            return
        counts = {
            status: int(count)
            for status, count in (
                await session.execute(
                    select(PricingRunItem.status, func.count(PricingRunItem.id))
                    .where(PricingRunItem.pricing_run_id == run_id)
                    .group_by(PricingRunItem.status)
                )
            ).all()
        }
        calculated = counts.get("calculated", 0)
        manual = counts.get("manual_review", 0)
        failed = counts.get("failed", 0)
        cancelled = counts.get("cancelled", 0)
        terminal = calculated + manual + failed + cancelled
        run.completed_items = calculated + manual
        run.failed_items = failed
        run.manual_review_items = manual
        if terminal >= run.total_items:
            if cancelled == run.total_items:
                run.status = "cancelled"
            elif calculated + manual == 0:
                run.status = "failed"
            elif failed or cancelled:
                run.status = "partial"
            else:
                run.status = "completed"
            run.finished_at = datetime.now(UTC)
            event_name = {
                "completed": "pricing_run_completed",
                "partial": "pricing_run_partial",
                "failed": "pricing_run_failed",
                "cancelled": "pricing_run_cancelled",
            }[run.status]
            pricing_event(
                event_name,
                pricing_run_id=str(run.id),
                status=run.status,
                calculated=calculated,
                manual_review=manual,
                failed=failed,
                cancelled=cancelled,
            )
            # The immutable recommendation remains the audit record; this
            # projection is the small mutable read model used by the daily UI.
            from marko.services.attention import (
                mark_run_attention_failed,
                project_attention_for_run,
            )

            if run.status in {"completed", "partial"}:
                await project_attention_for_run(session, run.id)
            else:
                await mark_run_attention_failed(session, run.id)
        elif run.status not in {
            "failed",
            "cancelled",
            "classifying",
            "calibrating",
            "calculating",
        }:
            run.status = "running"
        await session.commit()


def _source_listing_id(product_id: int | None, url: str | None, price: float) -> str:
    if product_id is not None:
        return str(product_id)
    return hashlib.sha256(f"{url or ''}|{price}".encode()).hexdigest()


def _currency_code(value: str | None) -> str:
    normalized = (value or "").strip().casefold()
    if not normalized:
        return "UNK"
    if normalized in {"uah", "грн", "₴", "гривня", "гривень"}:
        return "UAH"
    return normalized.upper()[:3]


def _source_confidence_bucket(value: Decimal) -> str:
    confidence = Decimal(str(value))
    if confidence <= 0:
        return "zero"
    if confidence < Decimal("0.50"):
        return "below_0_50"
    if confidence < Decimal("0.80"):
        return "0_50_to_0_80"
    if confidence < Decimal("1"):
        return "0_80_to_below_1"
    return "one"


def _availability(explicit: bool | None, presence: str | None) -> bool | None:
    value = " ".join((presence or "").casefold().strip().split())
    inferred: bool | None = None
    if value in {
        "avail",
        "available",
        "in_stock",
        "in stock",
        "в наличии",
        "в наявності",
    }:
        inferred = True
    elif value in {
        "not_avail",
        "not available",
        "unavailable",
        "out_of_stock",
        "out of stock",
        "нет в наличии",
        "немає в наявності",
    }:
        inferred = False
    # Contradictory Apollo fields are parser uncertainty, not a boolean.  A
    # stale ``isAvailable`` must not silently override the card's presence code
    # (or vice versa), because either choice can pollute/exclude a price cohort.
    if explicit is not None and inferred is not None and explicit != inferred:
        return None
    return explicit if explicit is not None else inferred


def _initial_cohort_role(
    classification: TierClassification,
    *,
    is_owned: bool,
    tier_agnostic: bool = False,
) -> CohortRole:
    """Partition one classified offer into its pricing cohort.

    ``tier_agnostic`` reflects the owner's budget-floor decision of 2026-07-30
    (``raise_policy.yaml``): the price is the cheapest comparable offer whatever
    brand level it sits at, so an unreadable brand level is no longer a reason
    to hold an offer out of the cohort.  The classification keeps its
    ``UNKNOWN_TIER`` exclusion reason for diagnostics -- only the cohort role,
    which is a pricing-policy question, follows the policy.

    This is not a general amnesty for excluded offers.  ``UNKNOWN_TIER`` is the
    one exclusion the policy has already discarded; every other reason, and the
    offer-integrity downgrade applied by the caller, still parks the offer.
    """

    if is_owned:
        return CohortRole.OWNED_STORE
    if classification.is_used:
        return CohortRole.USED_REJECTED
    if classification.is_kemp:
        return CohortRole.KEMP_REFERENCE
    if classification.exclusion_reason:
        if tier_agnostic and classification.exclusion_reason == "UNKNOWN_TIER":
            return CohortRole.TARGET_MARKET
        return CohortRole.MANUAL_REVIEW
    return CohortRole.TARGET_MARKET


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _valid_sha256(value: Any) -> bool:
    text = str(value or "").strip().casefold()
    return len(text) == 64 and all(
        character in "0123456789abcdef" for character in text
    )


def _offer_search_identity(
    detail: object,
    *,
    primary: str,
    confirmed_crosses: tuple[ConfirmedCross, ...],
    discovery_queries: tuple[str, ...] = (),
) -> str:
    """The number that actually retrieved this row, not the run's primary.

    A row found by a declared cross must have its identity verified against
    that cross; checking it against the primary OE would either reject a
    genuine widening or credit it with evidence it never had. The widening is
    admitted only when it is one the run froze as a confirmed cross of this
    catalog item, so a payload cannot invent one after the fact.

    A retrieval-only key is the other case, and it is not the same one. It was
    declared, so the acquisition is legitimate and the row is kept — but a
    public MPN asserts no identity, so it never becomes the search identity.
    Such a row is still checked against the primary OE: it earns its evidence
    off the card or it goes to review.
    """

    if not isinstance(detail, Mapping):
        return primary
    raw = str(detail.get("found_by_query") or "").strip()
    if not raw:
        return primary
    widening = normalize_oe(raw)
    if widening is None or widening == primary:
        return primary
    if any(
        cross.search_oe_norm == primary and cross.candidate_oe_norm == widening
        for cross in confirmed_crosses
    ):
        return widening
    if widening in {normalize_oe(value) for value in discovery_queries}:
        return primary
    raise EvidenceAccountingError(
        "ACQUISITION_WIDENING_BINDING_ERROR: a retained offer claims a "
        "number this run declared neither as a confirmed cross nor as a "
        "retrieval-only discovery key"
    )


def _detail_evidence_automatic_safe(
    product: Mapping[str, Any],
    *,
    seller_id: str,
    retained_raw_evidence: tuple[Mapping[str, Any], ...] = (),
) -> bool:
    """Only an exact card capture present in the retained journal is automatic."""

    detail = product.get("detail_evidence")
    if not isinstance(detail, Mapping):
        return False
    detail_hash = str(detail.get("content_sha256") or "").strip().casefold()
    detail_url = str(detail.get("source_url") or "").strip()
    if not (
        detail.get("schema_version") == PROM_PRODUCT_DETAIL_SCHEMA_VERSION
        and detail.get("status") == "SUCCESS"
        and detail.get("selected") is True
        and _valid_sha256(detail_hash)
        and detail_url == str(product.get("url") or "").strip()
        and str(detail.get("product_id") or "").strip()
        == str(product.get("product_id") or product.get("id") or "").strip()
        and str(detail.get("seller_id") or "").strip() == seller_id
    ):
        return False
    conflicts = detail.get("conflicts")
    if isinstance(conflicts, Mapping) and any(
        str(field).strip().casefold() in {"mpn", "oe_raw", "part_numbers"}
        for field in conflicts
    ):
        # Listing/detail disagreement in a candidate-native identity field is
        # a real evidence conflict.  Keep the card visible for review, but do
        # not let the retained listing value make it priceable automatically.
        return False
    return any(
        str(entry.get("request_kind") or "").strip() == "product_page"
        and str(entry.get("prepared_url") or "").strip() == detail_url
        and str(entry.get("raw_content_sha256") or "").strip().casefold() == detail_hash
        for entry in retained_raw_evidence
    )


def _json_safe(value: Any) -> Any:
    """Make observation JSON columns persistable without a custom encoder."""

    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _candidate_review_snapshot(
    product: Mapping[str, Any],
    *,
    raw_capture_id: UUID,
    capture_content_sha256: str,
    raw_offer_index: int,
    raw_offer_sha256: str,
    source_listing_id: str,
) -> dict[str, Any]:
    """Retain normalized candidate fields needed by the semantic reviewer."""

    allowed = {
        "id",
        "name",
        "title",
        "sku",
        "mpn",
        "part_numbers",
        "model_id",
        "category",
        "category_id",
        "category_ids",
        "brand",
        "seller_id",
        "seller_name",
        "image",
        "images",
        "description",
        "oe_raw",
        "fitment",
        "vehicle_generation",
        "year_from",
        "year_to",
        "engine",
        "body_variant",
        "side",
        "position",
        "condition",
        "package_quantity",
        "characteristics",
        "detail_evidence",
        "measure_unit",
        "presence",
        "is_available",
        "url",
        "price",
        "price_original",
        "discounted_price",
        "currency",
    }
    selected = {key: product.get(key) for key in sorted(allowed) if key in product}
    try:
        encoded = json.dumps(
            selected,
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
            default=str,
        )
        decoded = json.loads(encoded)
    except (TypeError, ValueError):
        return {
            "schema_version": "marko-candidate-review-snapshot-v1",
            "snapshot_error": "NON_JSON_VALUE",
        }
    return {
        "schema_version": "marko-candidate-review-snapshot-v1",
        "source_locator": {
            "locator_version": "marko-ai-evidence-source-locator-v1",
            "raw_capture_id": str(raw_capture_id),
            "capture_content_sha256": capture_content_sha256,
            "raw_offer_index": raw_offer_index,
            "raw_offer_sha256": raw_offer_sha256,
            "source_listing_id": source_listing_id,
            "source_pointer": f"/candidate_records/{raw_offer_index}",
        },
        "product": decoded,
    }


def _validated_listing_url(value: Any) -> tuple[str, str | None]:
    raw = str(value or "").strip()
    if not raw:
        return "", "SOURCE_URL_NOT_AVAILABLE"
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "", "INVALID_URL_PROTOCOL"
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return "", "INVALID_URL_PROTOCOL"
    return raw, None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _payload_source_listing_id(
    offer: Mapping[str, Any],
    price: Decimal,
) -> str:
    product_id = offer.get("product_id")
    if product_id is not None:
        return str(product_id)[:255]
    return hashlib.sha256(f"{offer.get('url') or ''}|{price}".encode()).hexdigest()


__all__ = [
    "PermanentCollectionError",
    "PricingItemNotFoundError",
    "calculate_pricing_item",
    "calibrate_run_and_prepare_calculations",
    "claim_collection_finalization",
    "fail_pricing_item",
    "fail_pricing_run_dispatch",
    "finalize_pricing_run",
    "get_pricing_item_run_id",
    "mark_run_calculating",
    "prepare_run_dispatch",
    "process_pricing_item",
    "fail_collection_finalization",
    "reset_pricing_calculation_for_retry",
    "reset_pricing_item_for_retry",
]
