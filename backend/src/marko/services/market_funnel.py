"""Read-only five-stage OE/OEM market funnel and blinded review batching.

The funnel reports what persisted execution evidence proves.  It does not run
collection, change a recommendation, or turn a retrieval-only identifier into
pricing identity.  Owned storefront observations are counted as diagnostics
and excluded from the external-candidate stage.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from marko.services.public_search_keys import (
    PublicSearchKey,
    build_public_search_keys,
)


MARKET_FUNNEL_REPORT_VERSION = "oe-market-funnel-v1"
PRICE_BEARING_ACTIONS = frozenset({"RAISE", "HOLD", "LOWER"})
VERIFIED_OE_STATUSES = frozenset({"VERIFIED_EXACT", "VERIFIED_CROSS"})
_REVIEW_MONETARY_KEYS = frozenset(
    {
        "price",
        "priceoriginal",
        "discountedprice",
        "currency",
        "pricecurrency",
        "priceusd",
        "cost",
        "цена",
        "ціна",
        "оптоваціна",
        "оптоваяцена",
    }
)
_REVIEW_MONETARY_LABEL_KEYS = frozenset({"name", "label", "caption", "title"})
_REVIEW_PRICE_TEXT = re.compile(
    r"(?<!\w)(?:(?:price|цена|ціна|вартість|стоимость)\s*"
    r"(?:[:=–—-]\s*)?(?:від|от|from)?\s*[$€₴]?\s*\d[\d\s.,]*|"
    r"[$€₴]\s*\d[\d\s.,]*|\d[\d\s.,]*\s*"
    r"(?:грн|₴|uah|usd|eur|\$|€))(?!\w)",
    re.IGNORECASE,
)

_BASE_ITEMS_SQL = text(
    """
    SELECT
      pri.id::text AS pricing_run_item_id,
      ci.id::text AS catalog_item_id,
      ci.source_row,
      COALESCE(
        pri.start_snapshot,
        json_build_object(
          'identity_status', ci.identity_status,
          'oe_norm', ci.oe_norm,
          'mpn_norm', ci.mpn_norm,
          'part_numbers_norm', ci.part_numbers_norm,
          'confirmed_identity_links', '[]'::json,
          'sku', ci.sku,
          'name', ci.name,
          'brand', ci.brand,
          'category', ci.category,
          'product_url', ci.product_url,
          'description', ci.description,
          'applicability_brands', ci.applicability_brands,
          'applicability_models', ci.applicability_models,
          'characteristics_raw', ci.characteristics_raw
        )
      ) AS start_snapshot,
      COALESCE(pri.status, 'not_in_run_scope') AS run_item_status,
      pri.error AS run_item_error,
      COALESCE(st.status, 'not_in_run_scope') AS scrape_target_status,
      CASE
        WHEN st.id IS NOT NULL THEN st.reason_codes
        WHEN ci.is_available IS FALSE THEN '["SCOPE_ITEM_UNAVAILABLE"]'::json
        ELSE '["NOT_IN_PRICING_RUN_SCOPE"]'::json
      END AS scrape_target_reason_codes
    FROM pricing_runs AS pr
    JOIN catalog_items AS ci
      ON ci.import_batch_id = pr.import_batch_id
     AND ci.workspace_id = pr.workspace_id
    LEFT JOIN pricing_run_items AS pri
      ON pri.pricing_run_id = pr.id
     AND pri.catalog_item_id = ci.id
    LEFT JOIN scrape_targets AS st ON st.id = pri.scrape_target_id
    WHERE pr.id = :run_id
      AND pr.workspace_id = :workspace_id
      AND ci.identity_status = 'OE_CONFIRMED'
    ORDER BY ci.source_row, ci.id
    """
)

_OBSERVATIONS_SQL = text(
    """
    WITH current_tier AS (
      SELECT DISTINCT ON (market_observation_id)
        market_observation_id,
        is_owned,
        cohort_role,
        reason_codes
      FROM observation_tier_classifications
      ORDER BY market_observation_id, classified_at DESC, id DESC
    ),
    current_review AS (
      SELECT DISTINCT ON (market_observation_id)
        market_observation_id,
        identity_verdict,
        pricing_admission,
        status,
        error_code
      FROM candidate_comparability_reviews
      ORDER BY market_observation_id, reviewed_at DESC, id DESC
    )
    SELECT
      mo.pricing_run_item_id::text AS pricing_run_item_id,
      mo.id::text AS observation_id,
      mo.via_oe_number,
      current_tier.is_owned AS is_owned,
      COALESCE(current_tier.cohort_role, 'MANUAL_REVIEW') AS cohort_role,
      mo.oe_verification_status,
      mo.comparability_hard_gate_result,
      mo.automatic_eligible,
      mo.calibration_exclusion_codes,
      COALESCE(current_tier.reason_codes, '[]'::json) AS tier_reason_codes,
      mo.source_listing_id,
      mo.seller_id,
      mo.seller_name,
      mo.title,
      mo.description,
      mo.url,
      mo.brand_raw,
      mo.is_available,
      mo.condition_state,
      mo.candidate_snapshot,
      current_review.identity_verdict AS model_identity_verdict,
      current_review.pricing_admission AS model_pricing_admission,
      current_review.status AS model_review_status,
      current_review.error_code AS model_review_error_code
    FROM market_observations AS mo
    JOIN pricing_run_items AS pri ON pri.id = mo.pricing_run_item_id
    LEFT JOIN current_tier ON current_tier.market_observation_id = mo.id
    LEFT JOIN current_review ON current_review.market_observation_id = mo.id
    WHERE pri.pricing_run_id = :run_id
    ORDER BY mo.pricing_run_item_id, mo.observed_at, mo.id
    """
)

_RECOMMENDATIONS_SQL = text(
    """
    SELECT
      pricing_run_item_id::text AS pricing_run_item_id,
      action,
      action_gates_passed,
      recommended_price,
      reason_codes,
      evidence_observation_ids
    FROM pricing_recommendations
    WHERE pricing_run_id = :run_id
    ORDER BY pricing_run_item_id, computed_at, id
    """
)


class MarketFunnelError(RuntimeError):
    pass


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(item) for item in value if str(item or "").strip())


def _mapping_sequence(value: object) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _review_key(value: object) -> str:
    return re.sub(r"[^a-zа-яїієґ0-9]+", "", str(value or "").casefold())


def _redact_review_monetary_material(value: Any) -> Any:
    if isinstance(value, Mapping):
        if any(
            _review_key(key) in _REVIEW_MONETARY_LABEL_KEYS
            and _review_key(item) in _REVIEW_MONETARY_KEYS
            for key, item in value.items()
        ):
            return None
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _review_key(key) in _REVIEW_MONETARY_KEYS:
                continue
            redacted = _redact_review_monetary_material(item)
            if redacted is not None:
                result[str(key)] = redacted
        return result
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        result = []
        for item in value:
            redacted = _redact_review_monetary_material(item)
            if redacted is not None:
                result.append(redacted)
        return result
    if isinstance(value, str):
        return _REVIEW_PRICE_TEXT.sub("<PRICE_REDACTED>", value)
    return value


def _redacted_review_text(value: object) -> str:
    redacted = _redact_review_monetary_material(str(value or ""))
    return str(redacted or "")


def _redacted_review_field(field: str, value: object) -> str:
    if field in {
        "our_applicability",
        "our_characteristics",
        "offer_fitment",
        "offer_characteristics",
    }:
        try:
            parsed = json.loads(str(value or ""))
        except json.JSONDecodeError:
            return _redacted_review_text(value)
        return json.dumps(
            _redact_review_monetary_material(parsed),
            ensure_ascii=False,
            sort_keys=True,
        )
    return _redacted_review_text(value)


def public_keys_from_start_snapshot(
    snapshot: Mapping[str, object] | None,
) -> tuple[PublicSearchKey, ...]:
    """Rebuild the exact ordered safe-key contract from frozen run input."""

    if not isinstance(snapshot, Mapping):
        return ()
    return build_public_search_keys(
        identity_status=str(snapshot.get("identity_status") or ""),
        oe_norm=str(snapshot.get("oe_norm") or ""),
        mpn_norm=str(snapshot.get("mpn_norm") or ""),
        part_numbers_norm=_string_sequence(snapshot.get("part_numbers_norm")),
        confirmed_identity_links=_mapping_sequence(
            snapshot.get("confirmed_identity_links")
        ),
    )


@dataclass(frozen=True, slots=True)
class MarketObservationInput:
    observation_id: str
    via_oe_number: str
    is_owned: bool | None
    cohort_role: str
    oe_verification_status: str
    comparability_hard_gate_result: str
    automatic_eligible: bool
    reason_codes: tuple[str, ...]
    source_listing_id: str = ""
    seller_id: str = ""
    seller_name: str = ""
    title: str = ""
    description: str = ""
    url: str = ""
    brand: str = ""
    is_available: bool | None = None
    condition_state: str = "UNKNOWN"
    candidate_snapshot: Mapping[str, Any] | None = None
    model_identity_verdict: str = "MANUAL_REVIEW"
    model_pricing_admission: str = "MANUAL_REVIEW"
    model_review_status: str = "NOT_REVIEWED"
    model_review_error_code: str = ""


@dataclass(frozen=True, slots=True)
class RecommendationInput:
    action: str
    action_gates_passed: bool
    recommended_price: str | None
    reason_codes: tuple[str, ...]
    evidence_observation_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FunnelItemInput:
    catalog_item_id: str
    source_row: int
    start_snapshot: Mapping[str, object]
    scrape_target_status: str
    scrape_target_reason_codes: tuple[str, ...]
    run_item_status: str
    run_item_error: str | None
    observations: tuple[MarketObservationInput, ...]
    recommendations: tuple[RecommendationInput, ...]


@dataclass(frozen=True, slots=True)
class FunnelItemRow:
    catalog_item_id: str
    source_row: int
    public_keys: tuple[dict[str, Any], ...]
    pricing_primary_key_count: int
    retrieval_only_key_count: int
    external_candidate_count: int
    owned_echo_count: int
    ownership_unclassified_count: int
    retrieval_only_candidate_count: int
    surviving_candidate_count: int
    automatic_candidate_count: int
    unsafe_price_recommendation_count: int
    has_price_recommendation: bool
    recommendation_actions: tuple[str, ...]
    drop_stage: str | None
    reason_codes: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class MarketFunnelReport:
    report_version: str
    generated_at: str
    population: int
    positions_with_public_key: int
    positions_with_pricing_primary_key: int
    positions_with_external_candidate: int
    positions_with_candidate_surviving_comparison: int
    positions_with_automatic_candidate: int
    positions_with_price_recommendation: int
    positions_with_retrieval_only_candidate: int
    owned_echo_observations: int
    ownership_unclassified_observations: int
    unsafe_price_recommendations: int
    drop_stage_histogram: Mapping[str, int]
    drop_reason_histogram: Mapping[str, int]
    stage_counts_are_monotonic: bool
    rows: tuple[FunnelItemRow, ...]

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rows"] = [row.as_dict() for row in self.rows]
        payload["price_showing_ready"] = False
        payload["human_accuracy_measured_by_this_report"] = False
        payload["boundaries"] = {
            "owned_storefronts_count_as_market": False,
            "ownership_requires_persisted_classification": True,
            "retrieval_only_key_authorizes_pricing": False,
            "recommendation_evidence_requires_automatic_candidate": True,
            "price_recommendation_actions": sorted(PRICE_BEARING_ACTIONS),
            "live_collection_performed": False,
        }
        return payload


def _unique_reason_codes(values: Sequence[object]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        rendered = str(value or "").strip()
        if rendered and rendered not in result:
            result.append(rendered)
    return tuple(result)


def _funnel_row(item: FunnelItemInput) -> FunnelItemRow:
    keys = public_keys_from_start_snapshot(item.start_snapshot)
    primary_numbers = {key.number for key in keys if key.pricing_primary}
    retrieval_numbers = {key.number for key in keys if not key.pricing_primary}
    external = tuple(
        observation
        for observation in item.observations
        if observation.is_owned is False
    )
    owned = tuple(
        observation for observation in item.observations if observation.is_owned is True
    )
    ownership_unclassified = tuple(
        observation for observation in item.observations if observation.is_owned is None
    )
    surviving = tuple(
        observation
        for observation in external
        if observation.cohort_role == "TARGET_MARKET"
        and observation.oe_verification_status in VERIFIED_OE_STATUSES
        and observation.comparability_hard_gate_result == "PASS"
    )
    automatic = tuple(
        observation
        for observation in surviving
        if observation.automatic_eligible
        and observation.via_oe_number in primary_numbers
    )
    retrieval_only = tuple(
        observation
        for observation in external
        if observation.via_oe_number in retrieval_numbers
        and observation.via_oe_number not in primary_numbers
    )
    raw_price_recommendations = tuple(
        recommendation
        for recommendation in item.recommendations
        if recommendation.action in PRICE_BEARING_ACTIONS
        and recommendation.action_gates_passed
        and recommendation.recommended_price is not None
    )
    automatic_observation_ids = {
        observation.observation_id for observation in automatic
    }
    price_recommendations = tuple(
        recommendation
        for recommendation in raw_price_recommendations
        if recommendation.evidence_observation_ids
        and set(recommendation.evidence_observation_ids).issubset(
            automatic_observation_ids
        )
    )
    unsafe_price_recommendation_count = len(raw_price_recommendations) - len(
        price_recommendations
    )

    if not keys:
        drop_stage = "PUBLIC_KEY"
        reasons = (*item.scrape_target_reason_codes, "NO_SAFE_PUBLIC_KEY")
    elif not external:
        drop_stage = "MARKET_CANDIDATE"
        reasons = (
            *item.scrape_target_reason_codes,
            *(("OWNERSHIP_UNCLASSIFIED",) if ownership_unclassified else ()),
            "NO_EXTERNAL_MARKET_CANDIDATE",
        )
    elif not surviving:
        drop_stage = "COMPARISON"
        reasons = tuple(
            reason
            for observation in external
            for reason in (
                f"COHORT_{observation.cohort_role}",
                f"OE_{observation.oe_verification_status}",
                f"COMPARABILITY_{observation.comparability_hard_gate_result}",
                *observation.reason_codes,
            )
        )
    elif not price_recommendations:
        drop_stage = "PRICE_RECOMMENDATION"
        reasons = (
            *(
                reason
                for recommendation in item.recommendations
                for reason in (
                    f"ACTION_{recommendation.action}",
                    *recommendation.reason_codes,
                )
            ),
            *(
                ("RECOMMENDATION_EVIDENCE_NOT_AUTOMATICALLY_ELIGIBLE",)
                if unsafe_price_recommendation_count
                else ()
            ),
        ) or (item.run_item_error or f"RUN_ITEM_{item.run_item_status}",)
    else:
        drop_stage = None
        reasons = ()

    return FunnelItemRow(
        catalog_item_id=item.catalog_item_id,
        source_row=item.source_row,
        public_keys=tuple(key.as_dict() for key in keys),
        pricing_primary_key_count=sum(key.pricing_primary for key in keys),
        retrieval_only_key_count=sum(not key.pricing_primary for key in keys),
        external_candidate_count=len(external),
        owned_echo_count=len(owned),
        ownership_unclassified_count=len(ownership_unclassified),
        retrieval_only_candidate_count=len(retrieval_only),
        surviving_candidate_count=len(surviving),
        automatic_candidate_count=len(automatic),
        unsafe_price_recommendation_count=unsafe_price_recommendation_count,
        has_price_recommendation=bool(price_recommendations),
        recommendation_actions=tuple(
            recommendation.action for recommendation in item.recommendations
        ),
        drop_stage=drop_stage,
        reason_codes=_unique_reason_codes(reasons),
    )


def build_market_funnel_report(
    items: Sequence[FunnelItemInput],
) -> MarketFunnelReport:
    rows = tuple(_funnel_row(item) for item in items)
    stage_counts = (
        len(rows),
        sum(bool(row.public_keys) for row in rows),
        sum(row.external_candidate_count > 0 for row in rows),
        sum(row.surviving_candidate_count > 0 for row in rows),
        sum(row.has_price_recommendation for row in rows),
    )
    return MarketFunnelReport(
        report_version=MARKET_FUNNEL_REPORT_VERSION,
        generated_at=datetime.now(UTC).isoformat(),
        population=stage_counts[0],
        positions_with_public_key=stage_counts[1],
        positions_with_pricing_primary_key=sum(
            row.pricing_primary_key_count > 0 for row in rows
        ),
        positions_with_external_candidate=stage_counts[2],
        positions_with_candidate_surviving_comparison=stage_counts[3],
        positions_with_automatic_candidate=sum(
            row.automatic_candidate_count > 0 for row in rows
        ),
        positions_with_price_recommendation=stage_counts[4],
        positions_with_retrieval_only_candidate=sum(
            row.retrieval_only_candidate_count > 0 for row in rows
        ),
        owned_echo_observations=sum(row.owned_echo_count for row in rows),
        ownership_unclassified_observations=sum(
            row.ownership_unclassified_count for row in rows
        ),
        unsafe_price_recommendations=sum(
            row.unsafe_price_recommendation_count for row in rows
        ),
        drop_stage_histogram=dict(
            sorted(Counter(row.drop_stage or "COMPLETED" for row in rows).items())
        ),
        drop_reason_histogram=dict(
            sorted(
                Counter(reason for row in rows for reason in row.reason_codes).items()
            )
        ),
        stage_counts_are_monotonic=all(
            left >= right for left, right in zip(stage_counts, stage_counts[1:])
        ),
        rows=rows,
    )


def _json_list(value: object) -> tuple[str, ...]:
    return _string_sequence(value)


async def load_market_funnel_inputs(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    run_id: UUID,
) -> tuple[FunnelItemInput, ...]:
    """Load one persisted pricing run without mutating or collecting anything."""

    base_rows = list(
        (
            await session.execute(
                _BASE_ITEMS_SQL,
                {"workspace_id": workspace_id, "run_id": run_id},
            )
        ).mappings()
    )
    if not base_rows:
        raise MarketFunnelError(
            "pricing run is missing, belongs to another workspace, or contains "
            "no OE_CONFIRMED catalog rows"
        )
    observation_rows = list(
        (await session.execute(_OBSERVATIONS_SQL, {"run_id": run_id})).mappings()
    )
    recommendation_rows = list(
        (await session.execute(_RECOMMENDATIONS_SQL, {"run_id": run_id})).mappings()
    )
    observations: dict[str, list[MarketObservationInput]] = defaultdict(list)
    for row in observation_rows:
        reasons = _unique_reason_codes(
            (
                *_json_list(row["calibration_exclusion_codes"]),
                *_json_list(row["tier_reason_codes"]),
            )
        )
        observations[str(row["pricing_run_item_id"])].append(
            MarketObservationInput(
                observation_id=str(row["observation_id"]),
                via_oe_number=str(row["via_oe_number"] or ""),
                is_owned=(
                    row["is_owned"] if isinstance(row["is_owned"], bool) else None
                ),
                cohort_role=str(row["cohort_role"] or "MANUAL_REVIEW"),
                oe_verification_status=str(row["oe_verification_status"] or "UNKNOWN"),
                comparability_hard_gate_result=str(
                    row["comparability_hard_gate_result"] or "MANUAL_REVIEW"
                ),
                automatic_eligible=bool(row["automatic_eligible"]),
                reason_codes=reasons,
                source_listing_id=str(row["source_listing_id"] or ""),
                seller_id=str(row["seller_id"] or ""),
                seller_name=str(row["seller_name"] or ""),
                title=str(row["title"] or ""),
                description=str(row["description"] or ""),
                url=str(row["url"] or ""),
                brand=str(row["brand_raw"] or ""),
                is_available=row["is_available"],
                condition_state=str(row["condition_state"] or "UNKNOWN"),
                candidate_snapshot=(
                    row["candidate_snapshot"]
                    if isinstance(row["candidate_snapshot"], Mapping)
                    else None
                ),
                model_identity_verdict=str(
                    row["model_identity_verdict"] or "MANUAL_REVIEW"
                ),
                model_pricing_admission=str(
                    row["model_pricing_admission"] or "MANUAL_REVIEW"
                ),
                model_review_status=str(row["model_review_status"] or "NOT_REVIEWED"),
                model_review_error_code=str(row["model_review_error_code"] or ""),
            )
        )
    recommendations: dict[str, list[RecommendationInput]] = defaultdict(list)
    for row in recommendation_rows:
        recommendations[str(row["pricing_run_item_id"])].append(
            RecommendationInput(
                action=str(row["action"] or ""),
                action_gates_passed=bool(row["action_gates_passed"]),
                recommended_price=(
                    str(row["recommended_price"])
                    if row["recommended_price"] is not None
                    else None
                ),
                reason_codes=_json_list(row["reason_codes"]),
                evidence_observation_ids=_json_list(row["evidence_observation_ids"]),
            )
        )
    inputs: list[FunnelItemInput] = []
    for row in base_rows:
        run_item_id = (
            str(row["pricing_run_item_id"])
            if row["pricing_run_item_id"] is not None
            else f"catalog:{row['catalog_item_id']}"
        )
        snapshot = row["start_snapshot"]
        inputs.append(
            FunnelItemInput(
                catalog_item_id=str(row["catalog_item_id"]),
                source_row=int(row["source_row"]),
                start_snapshot=snapshot if isinstance(snapshot, Mapping) else {},
                scrape_target_status=str(row["scrape_target_status"] or "missing"),
                scrape_target_reason_codes=_json_list(
                    row["scrape_target_reason_codes"]
                ),
                run_item_status=str(row["run_item_status"] or ""),
                run_item_error=(
                    str(row["run_item_error"]) if row["run_item_error"] else None
                ),
                observations=tuple(observations.get(run_item_id, ())),
                recommendations=tuple(recommendations.get(run_item_id, ())),
            )
        )
    return tuple(inputs)


def market_review_source_rows(
    items: Sequence[FunnelItemInput],
) -> tuple[dict[str, str], ...]:
    """Project persisted evidence to the prediction- and price-blind CSV schema."""

    rows: list[dict[str, str]] = []
    for item in items:
        seed = item.start_snapshot
        for observation in item.observations:
            if observation.is_owned is not False:
                continue
            candidate = observation.candidate_snapshot or {}
            rows.append(
                {
                    "pair_id": observation.observation_id,
                    "our_oe": str(seed.get("oe_norm") or ""),
                    "our_mpn": str(seed.get("mpn_norm") or ""),
                    "our_sku": str(seed.get("sku") or ""),
                    "our_title": _redacted_review_text(seed.get("name")),
                    "our_brand": str(seed.get("brand") or ""),
                    "our_category": str(seed.get("category") or ""),
                    "our_part_numbers": json.dumps(
                        list(_string_sequence(seed.get("part_numbers_norm"))),
                        ensure_ascii=False,
                    ),
                    "our_applicability": json.dumps(
                        {
                            "brands": seed.get("applicability_brands") or [],
                            "models": seed.get("applicability_models") or [],
                        },
                        ensure_ascii=False,
                    ),
                    "our_characteristics": json.dumps(
                        _redact_review_monetary_material(
                            seed.get("characteristics_raw") or {}
                        ),
                        ensure_ascii=False,
                    ),
                    "our_product_url": str(seed.get("product_url") or ""),
                    "our_description": _redacted_review_text(seed.get("description")),
                    "offer_id": observation.source_listing_id,
                    "offer_title": _redacted_review_text(observation.title),
                    "offer_sku": str(candidate.get("sku") or ""),
                    "offer_brand": observation.brand,
                    "offer_url": observation.url,
                    "offer_seller_name": observation.seller_name,
                    "offer_image_url": str(candidate.get("image") or ""),
                    "offer_category": str(candidate.get("category") or ""),
                    "offer_category_path": str(candidate.get("category_path") or ""),
                    "offer_measure_unit": str(candidate.get("measure_unit") or ""),
                    "offer_availability": str(observation.is_available),
                    "offer_condition": observation.condition_state,
                    "offer_oe_raw": "",
                    "offer_fitment": json.dumps(
                        _redact_review_monetary_material(
                            candidate.get("fitment") or {}
                        ),
                        ensure_ascii=False,
                    ),
                    "offer_description": _redacted_review_text(observation.description),
                    "offer_characteristics": json.dumps(
                        _redact_review_monetary_material(
                            candidate.get("characteristics") or []
                        ),
                        ensure_ascii=False,
                    ),
                }
            )
    return tuple(rows)


def market_review_prediction_payload(
    items: Sequence[FunnelItemInput],
) -> dict[str, Any]:
    """Export persisted model decisions separately from the blinded human file."""

    pairs: list[dict[str, Any]] = []
    owned = 0
    ownership_unclassified = 0
    for item in items:
        for observation in item.observations:
            if observation.is_owned is True:
                owned += 1
                continue
            if observation.is_owned is None:
                ownership_unclassified += 1
                continue
            identity = observation.model_identity_verdict.strip().upper()
            if identity not in {"MATCH", "NOT_MATCH", "MANUAL_REVIEW"}:
                identity = "MANUAL_REVIEW"
            admission = observation.model_pricing_admission.strip().upper()
            if admission not in {"ADMITTED", "EXCLUDED", "MANUAL_REVIEW"}:
                admission = "MANUAL_REVIEW"
            pairs.append(
                {
                    "pair_id": observation.observation_id,
                    "identity_verdict": identity,
                    "pricing_admission": admission,
                    "review_status": observation.model_review_status,
                    "review_error_code": observation.model_review_error_code or None,
                }
            )
    return {
        "schema_version": "market-review-predictions-v1",
        "pairs": pairs,
        "operational_metrics": {
            "candidate_terminal_results": len(pairs),
            "valid_terminal_results": sum(
                row["review_status"] in {"COMPLETED", "HARD_STOP", "CACHED"}
                for row in pairs
            ),
            "provider_requests": sum(
                row["review_status"] == "COMPLETED" for row in pairs
            ),
            "owned_store_candidates": owned,
            "owned_store_excluded": owned,
            "ownership_unclassified_candidates": ownership_unclassified,
            "ownership_unclassified_excluded": ownership_unclassified,
        },
        "contains_human_truth": False,
        "model_is_ground_truth": False,
    }


def score_reviewed_market_pairs(
    reviewed_payload: Mapping[str, object],
    prediction_payload: Mapping[str, object],
    *,
    canary_key: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Compare persisted model decisions with blinded human labels.

    Canary rows are verified independently and are excluded from model scoring:
    they were injected by the batch builder and therefore have no persisted
    market-observation prediction.
    """

    tasks = reviewed_payload.get("tasks")
    raw_predictions = prediction_payload.get("pairs")
    if not isinstance(tasks, list) or not isinstance(raw_predictions, list):
        raise MarketFunnelError("reviewed set or prediction payload has invalid schema")
    predictions = {
        str(row.get("pair_id") or ""): row
        for row in raw_predictions
        if isinstance(row, Mapping) and str(row.get("pair_id") or "")
    }
    canary_ranks = {
        str(row.get("opaque_source_rank") or "")
        for row in (
            canary_key.get("canaries", []) if isinstance(canary_key, Mapping) else []
        )
        if isinstance(row, Mapping) and str(row.get("opaque_source_rank") or "")
    }
    labelled = human_matches = human_not_matches = 0
    false_accepts = false_not_matches = abstentions = automatic_matches = 0
    unsafe_pricing = 0
    missing: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    scored_task_count = 0
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        refs = task.get("source_refs")
        pair_id = ""
        if isinstance(refs, list):
            for ref in refs:
                if not isinstance(ref, Mapping):
                    continue
                candidate = str(ref.get("source_rank") or "")
                if candidate in canary_ranks:
                    pair_id = candidate
                    break
                if candidate in predictions:
                    pair_id = candidate
                    break
        if pair_id in canary_ranks:
            continue
        scored_task_count += 1
        labels = task.get("labels")
        truth = (
            str(labels.get("identity_truth") or "").strip().upper()
            if isinstance(labels, Mapping)
            else ""
        )
        pricing_truth = (
            str(labels.get("pricing_admission_truth") or "").strip().upper()
            if isinstance(labels, Mapping)
            else ""
        )
        prediction = predictions.get(pair_id)
        if (
            prediction is None
            or truth not in {"MATCH", "NOT_MATCH"}
            or pricing_truth not in {"ADMITTED", "EXCLUDED"}
        ):
            missing.append(
                {
                    "review_id": task.get("review_id"),
                    "pair_id": pair_id or None,
                    "reason": "MISSING_PREDICTION_OR_FINAL_HUMAN_LABEL",
                }
            )
            continue
        review_status = str(prediction.get("review_status") or "").strip().upper()
        if review_status and review_status not in {"COMPLETED", "HARD_STOP", "CACHED"}:
            missing.append(
                {
                    "review_id": task.get("review_id"),
                    "pair_id": pair_id,
                    "reason": "MODEL_REVIEW_NOT_TERMINAL",
                    "model_review_status": review_status,
                }
            )
            continue
        identity = str(prediction.get("identity_verdict") or "").strip().upper()
        admission = str(prediction.get("pricing_admission") or "").strip().upper()
        if identity not in {"MATCH", "NOT_MATCH", "MANUAL_REVIEW"}:
            identity = "MANUAL_REVIEW"
        if admission not in {"ADMITTED", "EXCLUDED", "MANUAL_REVIEW"}:
            admission = "MANUAL_REVIEW"
        labelled += 1
        human_matches += int(truth == "MATCH")
        human_not_matches += int(truth == "NOT_MATCH")
        automatic_matches += int(identity == "MATCH" and truth == "MATCH")
        false_accepts += int(identity == "MATCH" and truth == "NOT_MATCH")
        false_not_matches += int(identity == "NOT_MATCH" and truth == "MATCH")
        abstentions += int(identity == "MANUAL_REVIEW")
        unsafe_pricing += int(
            admission == "ADMITTED"
            and (truth != "MATCH" or pricing_truth != "ADMITTED")
        )
        rows.append(
            {
                "review_id": task.get("review_id"),
                "pair_id": pair_id,
                "identity_truth": truth,
                "identity_prediction": identity,
                "pricing_truth": pricing_truth,
                "pricing_prediction": admission,
            }
        )
    complete = labelled == scored_task_count and not missing and labelled > 0
    class_coverage_complete = human_matches > 0 and human_not_matches > 0
    review_batch_size_valid = 150 <= len(tasks) <= 300
    return {
        "score_version": "market-human-model-score-v1",
        "labelled_pairs": labelled,
        "review_tasks_total": len(tasks),
        "canary_pairs_excluded_from_model_score": len(tasks) - scored_task_count,
        "model_pairs_expected": scored_task_count,
        "human_matches": human_matches,
        "human_not_matches": human_not_matches,
        "human_class_coverage_complete": class_coverage_complete,
        "review_batch_size_valid": review_batch_size_valid,
        "model_false_accept_count": false_accepts,
        "model_false_accept_rate": (
            str(
                (Decimal(false_accepts) / Decimal(human_not_matches)).quantize(
                    Decimal("0.000001")
                )
            )
            if human_not_matches
            else None
        ),
        "model_false_not_match_count": false_not_matches,
        "model_match_recall": (
            str(
                (Decimal(automatic_matches) / Decimal(human_matches)).quantize(
                    Decimal("0.000001")
                )
            )
            if human_matches
            else None
        ),
        "model_abstention_count": abstentions,
        "model_abstention_rate": (
            str(
                (Decimal(abstentions) / Decimal(labelled)).quantize(Decimal("0.000001"))
            )
            if labelled
            else None
        ),
        "unsafe_pricing_admission_count": unsafe_pricing,
        "complete_pair_accounting": complete,
        "missing": missing,
        "rows": rows,
        "model_is_ground_truth": False,
        "human_labels_are_ground_truth": True,
        "price_showing_ready": False,
        "operator_decision_required": (
            complete and class_coverage_complete and review_batch_size_valid
        ),
        "critical_false_accept_gate_passed": false_accepts == 0,
    }


MARKET_REVIEW_SOURCE_FIELDS = (
    "pair_id",
    "our_oe",
    "our_mpn",
    "our_sku",
    "our_title",
    "our_brand",
    "our_category",
    "our_part_numbers",
    "our_applicability",
    "our_characteristics",
    "our_product_url",
    "our_image_urls",
    "our_description",
    "offer_id",
    "offer_title",
    "offer_sku",
    "offer_brand",
    "offer_url",
    "offer_seller_name",
    "offer_image_url",
    "offer_category",
    "offer_category_path",
    "offer_measure_unit",
    "offer_availability",
    "offer_condition",
    "offer_package_quantity",
    "offer_oe_raw",
    "offer_fitment",
    "offer_engine",
    "offer_year_from",
    "offer_year_to",
    "offer_body_variant",
    "offer_side",
    "offer_position",
    "offer_description",
    "offer_characteristics",
)


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _blinded_row(row: Mapping[str, object], *, pair_id: str) -> dict[str, str]:
    return {
        field: (
            pair_id
            if field == "pair_id"
            else _redacted_review_field(field, row.get(field))
        )
        for field in MARKET_REVIEW_SOURCE_FIELDS
    }


@dataclass(frozen=True, slots=True)
class BlindedReviewBatch:
    rows: tuple[dict[str, str], ...]
    canary_count: int
    canary_key: Mapping[str, Any]


def build_blinded_review_batch(
    market_rows: Sequence[Mapping[str, object]],
    canary_rows: Sequence[Mapping[str, object]],
    *,
    batch_size: int,
    selection_seed: str,
) -> BlindedReviewBatch:
    """Reserve known-answer canaries while removing every answer from evidence."""

    if batch_size <= 0:
        raise MarketFunnelError("review batch size must be positive")
    if not selection_seed.strip():
        raise MarketFunnelError("review selection seed must be non-empty")
    if not canary_rows:
        raise MarketFunnelError(
            "review batch requires at least one known-answer canary"
        )
    if len(canary_rows) > batch_size:
        raise MarketFunnelError("canary count exceeds review batch size")
    selected_market = sorted(
        market_rows,
        key=lambda row: hashlib.sha256(
            f"{selection_seed}\0{_canonical_sha256(row)}".encode("utf-8")
        ).hexdigest(),
    )[: batch_size - len(canary_rows)]
    output: list[dict[str, str]] = []
    for row in selected_market:
        opaque = str(row.get("pair_id") or "").strip() or _canonical_sha256(row)[:24]
        output.append(_blinded_row(row, pair_id=opaque))

    key_rows: list[dict[str, str]] = []
    for row in canary_rows:
        identity = str(row.get("expected_identity_truth") or "").strip().upper()
        admission = (
            str(row.get("expected_pricing_admission_truth") or "").strip().upper()
        )
        if identity not in {"MATCH", "NOT_MATCH"}:
            raise MarketFunnelError("canary identity truth must be MATCH or NOT_MATCH")
        if admission not in {"ADMITTED", "EXCLUDED"}:
            raise MarketFunnelError("canary pricing truth must be ADMITTED or EXCLUDED")
        canary_id = str(row.get("canary_id") or "").strip()
        if not canary_id:
            raise MarketFunnelError("every canary requires canary_id")
        opaque = hashlib.sha256(
            f"{selection_seed}\0canary\0{canary_id}\0{_canonical_sha256(row)}".encode(
                "utf-8"
            )
        ).hexdigest()[:24]
        output.append(_blinded_row(row, pair_id=opaque))
        key_rows.append(
            {
                "canary_id": canary_id,
                "opaque_source_rank": opaque,
                "expected_identity_truth": identity,
                "expected_pricing_admission_truth": admission,
            }
        )
    ordered = tuple(
        sorted(
            output,
            key=lambda row: hashlib.sha256(
                f"{selection_seed}\0final\0{row['pair_id']}".encode("utf-8")
            ).hexdigest(),
        )
    )
    return BlindedReviewBatch(
        rows=ordered,
        canary_count=len(key_rows),
        canary_key={
            "schema_version": "market-review-canary-key-v1",
            "selection_seed_sha256": hashlib.sha256(
                selection_seed.encode("utf-8")
            ).hexdigest(),
            "canaries": key_rows,
        },
    )


def verify_canary_labels(
    reviewed_payload: Mapping[str, object],
    canary_key: Mapping[str, object],
) -> dict[str, Any]:
    tasks = reviewed_payload.get("tasks")
    key_rows = canary_key.get("canaries")
    if not isinstance(tasks, list) or not isinstance(key_rows, list):
        raise MarketFunnelError("reviewed payload or canary key has invalid schema")
    task_by_rank: dict[str, Mapping[str, object]] = {}
    for task in tasks:
        if not isinstance(task, Mapping):
            continue
        refs = task.get("source_refs")
        if not isinstance(refs, list):
            continue
        for ref in refs:
            if isinstance(ref, Mapping):
                rank = str(ref.get("source_rank") or "")
                if rank:
                    task_by_rank[rank] = task
    mismatches: list[dict[str, Any]] = []
    correct = 0
    for key_row in key_rows:
        if not isinstance(key_row, Mapping):
            continue
        rank = str(key_row.get("opaque_source_rank") or "")
        task = task_by_rank.get(rank)
        labels = task.get("labels") if isinstance(task, Mapping) else None
        identity = (
            str(labels.get("identity_truth") or "").strip().upper()
            if isinstance(labels, Mapping)
            else ""
        )
        admission = (
            str(labels.get("pricing_admission_truth") or "").strip().upper()
            if isinstance(labels, Mapping)
            else ""
        )
        expected_identity = str(key_row.get("expected_identity_truth") or "").upper()
        expected_admission = str(
            key_row.get("expected_pricing_admission_truth") or ""
        ).upper()
        if identity == expected_identity and admission == expected_admission:
            correct += 1
        else:
            mismatches.append(
                {
                    "review_id": task.get("review_id") if task else None,
                    "opaque_source_rank": rank,
                    "expected_identity_truth": expected_identity,
                    "actual_identity_truth": identity,
                    "expected_pricing_admission_truth": expected_admission,
                    "actual_pricing_admission_truth": admission,
                }
            )
    expected = len(key_rows)
    return {
        "verification_version": "market-review-canary-verification-v1",
        "status": "PASS" if expected > 0 and correct == expected else "FAIL",
        "canaries_expected": expected,
        "canaries_correct": correct,
        "mismatches": mismatches,
        "review_batch_accepted": expected > 0 and correct == expected,
    }


__all__ = [
    "BlindedReviewBatch",
    "FunnelItemInput",
    "FunnelItemRow",
    "MARKET_FUNNEL_REPORT_VERSION",
    "MARKET_REVIEW_SOURCE_FIELDS",
    "MarketFunnelError",
    "MarketFunnelReport",
    "MarketObservationInput",
    "RecommendationInput",
    "build_blinded_review_batch",
    "build_market_funnel_report",
    "load_market_funnel_inputs",
    "market_review_source_rows",
    "market_review_prediction_payload",
    "public_keys_from_start_snapshot",
    "score_reviewed_market_pairs",
    "verify_canary_labels",
]
