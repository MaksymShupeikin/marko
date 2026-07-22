from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

import pytest

from metis.fitment import (
    Availability,
    CommercialContext,
    CompatibilityStatus,
    Condition,
    EvidenceClaim,
    EvidencePolarity,
    FitmentFeature,
    PartIdentity,
    PriceComparabilityStatus,
    SellerRelation,
    SourceTier,
    StatementStatus,
    assess_compatibility,
    assess_price_comparability,
    normalize_price_unit,
)
from metis.pricing.types import ProductTier


FIXTURE_PATH = Path(__file__).parent / "fixtures/fitment_evaluation_dataset_v1.json"
DATASET: dict[str, Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
NOW = datetime(2026, 7, 21, tzinfo=UTC)
IDENTITY_FEATURES = {
    FitmentFeature.ARTICLE_IDENTITY,
    FitmentFeature.OE_EXACT,
    FitmentFeature.OE_SUPERSESSION,
    FitmentFeature.CROSS_CONFIRMED,
}


def _identity(values: dict[str, Any], overrides: dict[str, Any] | None = None):
    merged = {**values, **(overrides or {})}
    merged["oe_numbers"] = tuple(merged.get("oe_numbers", ()))
    return PartIdentity(**merged)


def _claim(
    feature: FitmentFeature,
    *,
    value: str = "1",
    source_id: str = "official",
    source_tier: SourceTier = SourceTier.A,
    correlation_group: str | None = None,
    reliability: str = "0.95",
    extraction_confidence: str = "0.95",
) -> EvidenceClaim:
    numeric = Decimal(value)
    return EvidenceClaim(
        evidence_id=f"{source_id}:{feature.value}:{value}",
        feature=feature,
        value=numeric,
        source_id=source_id,
        source_type="evaluation_fixture",
        source_tier=source_tier,
        source_reliability=Decimal(reliability),
        extraction_confidence=Decimal(extraction_confidence),
        independence_factor=Decimal("1"),
        freshness_factor=Decimal("1"),
        correlation_group=correlation_group or source_id,
        polarity=(
            EvidencePolarity.SUPPORTS
            if numeric > 0
            else EvidencePolarity.CONTRADICTS
            if numeric < 0
            else EvidencePolarity.UNKNOWN
        ),
        statement_status=StatementStatus.FACT,
        claim_value={"synthetic": True},
        retrieved_at=NOW,
        source_url=f"https://{source_id}.example/fixture",
        source_document_sha256=(source_id.encode().hex() + "0" * 64)[:64],
    )


def _claims(case: dict[str, Any]) -> list[EvidenceClaim]:
    negative = {FitmentFeature(value) for value in case.get("negative_features", [])}
    profile = case["identity_profile"]
    source_tier = SourceTier.D if profile == "photo_only" else SourceTier.A
    source_kwargs = (
        {"reliability": "0.50", "extraction_confidence": "0.80"}
        if profile == "photo_only"
        else {}
    )
    allowed_photo_features = {
        FitmentFeature.PART_CATEGORY,
        FitmentFeature.AXLE,
        FitmentFeature.SIDE,
        FitmentFeature.VEHICLE_MAKE_MODEL,
        FitmentFeature.GENERATION,
    }
    claims = [
        _claim(
            feature,
            value="-1" if feature in negative else "1",
            source_id="photo-discovery" if profile == "photo_only" else "official",
            source_tier=source_tier,
            **source_kwargs,
        )
        for feature in FitmentFeature
        if feature not in IDENTITY_FEATURES
        and (profile != "photo_only" or feature in allowed_photo_features)
        and (
            profile != "official_exact_missing_side"
            or feature != FitmentFeature.SIDE
        )
    ]

    candidate_article = case.get("candidate_overrides", {}).get(
        "manufacturer_article",
        DATASET["base_target"].get("manufacturer_article"),
    )
    if (
        profile
        in {
            "official_exact",
            "official_cross",
            "official_supersession",
            "official_prom_conflict",
            "official_exact_missing_side",
        }
        and candidate_article
        == DATASET["base_target"].get("manufacturer_article")
    ):
        claims.append(_claim(FitmentFeature.ARTICLE_IDENTITY))

    if profile in {"official_exact", "official_exact_missing_side"}:
        claims.append(_claim(FitmentFeature.OE_EXACT))
    elif profile == "official_cross":
        claims.append(_claim(FitmentFeature.CROSS_CONFIRMED))
    elif profile == "official_supersession":
        claims.append(_claim(FitmentFeature.OE_SUPERSESSION))
    elif profile == "negative_exact":
        claims.append(_claim(FitmentFeature.OE_EXACT, value="-1"))
    elif profile == "official_prom_conflict":
        claims.extend(
            [
                _claim(FitmentFeature.OE_EXACT),
                _claim(
                    FitmentFeature.OE_EXACT,
                    value="-1",
                    source_id="prom-listing",
                    source_tier=SourceTier.D,
                    reliability="0.50",
                    extraction_confidence="0.80",
                ),
            ]
        )
    elif profile == "correlated_tier_b_cross":
        claims.extend(
            [
                _claim(
                    FitmentFeature.CROSS_CONFIRMED,
                    source_id=f"catalog-mirror-{index}",
                    source_tier=SourceTier.B,
                    correlation_group="shared-upstream",
                    reliability="0.80",
                    extraction_confidence="0.90",
                )
                for index in range(2)
            ]
        )
    elif profile == "contradictory_exact":
        claims.extend(
            [
                _claim(FitmentFeature.OE_EXACT, source_id="catalog-positive"),
                _claim(
                    FitmentFeature.OE_EXACT,
                    value="-1",
                    source_id="catalog-negative",
                ),
            ]
        )
    elif profile not in {"missing_identity", "photo_only"}:
        raise AssertionError(f"unknown identity profile: {profile}")
    return claims


def _commercial(overrides: dict[str, Any] | None = None) -> CommercialContext:
    values: dict[str, Any] = {
        "condition": Condition.NEW,
        "package_quantity": Decimal("1"),
        "unit_basis": "piece",
        "currency": "UAH",
        "tier": ProductTier.AFTERMARKET_B,
        "availability": Availability.IN_STOCK,
        "seller_relation": SellerRelation.INDEPENDENT,
        "stable_seller_id_verified": True,
        "seller_group_id": "independent-seller",
        "product_identity_key": "brand:article",
    }
    values.update(overrides or {})
    if values["package_quantity"] is not None:
        values["package_quantity"] = Decimal(str(values["package_quantity"]))
    values["condition"] = Condition(values["condition"])
    values["availability"] = Availability(values["availability"])
    values["seller_relation"] = SellerRelation(values["seller_relation"])
    tier = values["tier"]
    values["tier"] = tier if isinstance(tier, ProductTier) else ProductTier[tier]
    return CommercialContext(**values)


def _normalized_unit_context(context: CommercialContext) -> CommercialContext:
    normalized = normalize_price_unit(
        Decimal("100"),
        quantity_in_offer=context.package_quantity,
        unit_basis=context.unit_basis,
    )
    if normalized.normalized_price_per_piece is None:
        return context
    return replace(context, package_quantity=Decimal("1"), unit_basis="piece")


def test_dataset_declares_complete_non_representative_contract() -> None:
    cases = DATASET["cases"]
    case_types = {case["case_type"] for case in cases}

    assert DATASET["schema_version"] == "metis-fitment-evaluation-v1"
    assert DATASET["data_class"] == "synthetic_adversarial"
    assert DATASET["representative"] is False
    assert len(cases) >= 35
    assert len({case["id"] for case in cases}) == len(cases)
    assert case_types == set(DATASET["required_case_types"])


@pytest.mark.parametrize("case", DATASET["cases"], ids=lambda item: item["id"])
def test_adversarial_fitment_case(case: dict[str, Any]) -> None:
    target = _identity(DATASET["base_target"], case.get("target_overrides"))
    candidate = _identity(DATASET["base_target"], case.get("candidate_overrides"))
    fitment = assess_compatibility(target, candidate, _claims(case))
    target_commercial = _commercial()
    candidate_commercial = _commercial(case.get("candidate_commercial_overrides"))
    if case.get("normalize_units"):
        target_commercial = _normalized_unit_context(target_commercial)
        candidate_commercial = _normalized_unit_context(candidate_commercial)
    price = assess_price_comparability(
        fitment,
        target_commercial,
        candidate_commercial,
        source_quality=Decimal("0.90"),
        freshness_factor=Decimal("0.95"),
    )

    assert fitment.status == CompatibilityStatus(case["expected_physical_status"])
    assert price.status == PriceComparabilityStatus(case["expected_price_status"])
    reason_codes = {
        *fitment.hard_rejections,
        *fitment.reason_codes,
        *price.reason_codes,
    }
    assert case["expected_reason"] in reason_codes
