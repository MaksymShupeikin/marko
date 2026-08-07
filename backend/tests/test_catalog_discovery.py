from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from marko.core.config import Settings
from marko.services import catalog_discovery
from marko.services.catalog_discovery import (
    CatalogDiscoveryError,
    _coverage_summary,
    _candidate_article_fields,
    _catalog_identity_query_from_rows,
    _collect_live,
    _effective_discovery_offer,
    _resolve_private_catalog_discovery_query,
    _structured_identity_field,
    _title_carries_query,
    catalog_discovery_query,
    catalog_discovery_search_context,
    catalog_product_key,
    usable_search_requests,
)
from marko.services.market_collection import _market_semantic_candidate_verdict
from marko.services.pricing_runs import (
    customer_identity_available,
    customer_identity_query_from_fields,
)
from marko.services.semantic_candidate_gate import (
    SEMANTIC_PRICING_GATE_VERSION,
    apply_semantic_pricing_gate,
)
from marko.services.scrape_runtime import LogicalRequestTrace
from metis.pricing import (
    CandidateItem,
    CandidateStatus,
    ReferenceItem,
    check_candidate,
    load_candidate_selection_config,
)


_SELECTION_CONFIG = load_candidate_selection_config(
    Path(__file__).resolve().parents[1] / "config" / "comparability.yaml"
)


def _persisted_discovery_offer(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "source_listing_id": "123456789",
        "seller_id": "external",
        "seller_name": "External",
        "title": "Амортизатор 123456789",
        "url": "https://prom.ua/ua/p123456789-item.html",
        "sku": "123456789",
        "brand": "Aftermarket",
        "sale_price": Decimal("500"),
        "reference_price": None,
        "currency": "UAH",
        "measure_unit": "шт.",
        "is_available": True,
        "title_contains_query": True,
        "identity_status": "QUERY_TOKEN_PRESENT",
        "source_confidence": Decimal("1"),
        "reason_codes": ["OK"],
        "selection_status": "PRICING_EVIDENCE",
        "selection_reason": "OK",
        "passed_gates": [],
        "selection_flags": [],
        "selection_details": {},
        "predicted_tier": "aftermarket_a",
        "tier_confidence": Decimal("0.8"),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_historical_pricing_evidence_is_quarantined_at_read_boundary() -> None:
    effective = _effective_discovery_offer(_persisted_discovery_offer())

    assert effective.selection_status == "REFERENCE_ONLY"
    assert effective.selection_reason == "SEMANTIC_GATE_STALE"
    assert "SEMANTIC_GATE_STALE" in effective.reason_codes
    assert effective.selection_details["runtime_admission"]["required_gate_version"] == (
        SEMANTIC_PRICING_GATE_VERSION
    )


def test_discovery_identity_uses_exact_mpn_alongside_sku() -> None:
    product = {
        "sku": "SELLER-SKU-OTHER",
        "mpn": "7E5 827 505 A",
        "oe_raw": None,
    }

    assert _structured_identity_field(product, "7E5827505A") == "MPN"
    assert _candidate_article_fields(product) == (
        ("SKU", "SELLER-SKU-OTHER"),
        ("MPN", "7E5 827 505 A"),
    )


def test_discovery_private_kemp_code_is_never_identity_evidence() -> None:
    product = {
        "sku": "776414",
        "mpn": "776414",
        "oe_raw": "776414",
        "part_numbers": ["776414"],
    }

    assert _structured_identity_field(product, "776414") is None
    assert _title_carries_query("Деталь OE 776414", "776414") is False


def test_current_semantic_pricing_evidence_is_still_discovery_only() -> None:
    effective = _effective_discovery_offer(
        _persisted_discovery_offer(
            selection_details={
                "semantic_gate": {
                    "status": "PRICING_EVIDENCE",
                    "reason": "OK",
                    "gate_version": SEMANTIC_PRICING_GATE_VERSION,
                }
            }
        )
    )

    assert effective.selection_status == "REFERENCE_ONLY"
    assert effective.selection_reason == "DISCOVERY_ONLY_NOT_PRICING_EVIDENCE"
    assert "SEMANTIC_GATE_STALE" not in effective.reason_codes
    assert "DISCOVERY_ONLY_NOT_PRICING_EVIDENCE" in effective.reason_codes
    assert effective.selection_details["runtime_admission"]["discovery_only"] is True


def test_market_semantic_path_preserves_blocked_category_rejection() -> None:
    """A verified OE must not override a non-automotive category hard stop."""

    verdict = _market_semantic_candidate_verdict(
        reference=ReferenceItem(
            oem="7E5827505A",
            title="Замок крышки багажника Volkswagen T5",
            price=Decimal("1000"),
            category="body_lock",
        ),
        product={
            "name": "Замок крышки багажника Volkswagen T5 7E5827505A",
            "seller_id": "external",
            "seller_name": "External",
            "sku": "7E5827505A",
            "brand": "Polcar",
            "condition": "new",
            # This is a real configured Prom blocklist branch (lighting).
            "category_ids": [0, 15, 3710, 999],
        },
        price=Decimal("500"),
        selection_config=_SELECTION_CONFIG,
        owned_sellers=set(),
        confirmed_crosses=(),
        brand_tiers={},
        authoritative_identity=True,
        reference_payload={
            "name": "Замок крышки багажника Volkswagen T5",
            "category": "body_lock",
        },
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "CATEGORY_NOT_AUTOPARTS"
    assert verdict.details["stopped_gate"] == "category_domain"


def test_market_semantic_path_preserves_used_condition_rejection() -> None:
    """A source-asserted OE does not make a used listing price evidence."""

    verdict = _market_semantic_candidate_verdict(
        reference=ReferenceItem(
            oem="7E5827505A",
            title="Замок крышки багажника Volkswagen T5",
            price=Decimal("1000"),
            category="body_lock",
        ),
        product={
            "name": "Замок крышки багажника Volkswagen T5 7E5827505A бу",
            "seller_id": "external",
            "seller_name": "External",
            "sku": "7E5827505A",
            "brand": "Polcar",
            "condition": "used",
            "category_ids": [0, 55, 5502, 341534],
        },
        price=Decimal("500"),
        selection_config=_SELECTION_CONFIG,
        owned_sellers=set(),
        confirmed_crosses=(),
        brand_tiers={},
        authoritative_identity=True,
        reference_payload={
            "name": "Замок крышки багажника Volkswagen T5",
            "category": "body_lock",
        },
    )

    assert verdict.status is CandidateStatus.REJECTED
    assert verdict.reason == "USED"
    assert verdict.details["stopped_gate"] == "condition"


def test_semantic_pricing_gate_demotes_same_number_different_part_type() -> None:
    reference = ReferenceItem(
        oem="7438",
        title="Шкив гидроусилителя рулевого управления Renault Clio",
        price=Decimal("1000"),
        category="steering",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Фильтр масляный Opel Vectra 7438",
        description=None,
        article_field="7438",
        brand="Wix",
        price=Decimal("500"),
        category_path=(0, 55, 5502, 550203),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={
            "title": candidate.title,
            "description": candidate.description,
            "brand": candidate.brand,
            "category": "Автозапчастини",
        },
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_CONFLICT"
    assert "SEMANTIC_HARD_STOP" in gated.flags
    assert gated.details["semantic_gate"]["hard_stop_conflicts"]


def test_semantic_pricing_gate_holds_ambiguous_subtype_pair_for_review() -> None:
    reference = ReferenceItem(
        oem="9017601047",
        title="Кронштейн сдвижной двери Mercedes Sprinter верхний",
        price=Decimal("1000"),
        category="door_hardware",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title=(
            "Ролик двері бічної зсувний правій верхній Mercedes Sprinter "
            "9017601047"
        ),
        description=None,
        article_field="9017601047",
        brand="Aftermarket",
        price=Decimal("500"),
        category_path=(0, 55, 5502, 341534),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_AMBIGUOUS_REVIEW"
    assert "SEMANTIC_AMBIGUOUS_REVIEW" in gated.flags
    assert gated.details["semantic_gate"]["ambiguous_taxonomy_conflicts"]


def test_semantic_pricing_gate_requires_candidate_subtype_evidence() -> None:
    reference = ReferenceItem(
        oem="90336039",
        title="Датчик давления масла Daewoo Lanos 1.5",
        price=Decimal("1000"),
        category="sensors",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Датчик GM 90336039",
        description=None,
        article_field="90336039",
        brand="GM",
        price=Decimal("500"),
        category_path=(0, 55, 5502, 341534),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_SUBTYPE_UNCONFIRMED"
    assert "SEMANTIC_SUBTYPE_UNCONFIRMED" in gated.flags
    assert gated.details["semantic_gate"]["subtype_evidence"] == {
        "required": ["oil_pressure_sensor"],
        "candidate": [],
    }


@pytest.mark.parametrize(
    ("reference_title", "candidate_title", "conflict_dimensions"),
    (
        (
            "Датчик температури VW Golf 4-х контактний",
            "Конектор датчика температури VW Golf",
            {"part_type"},
        ),
        (
            "Блок управления стеклоподъемниками Volkswagen Golf Mk7",
            "Кнопки склопідіймача Volkswagen Golf 7",
            {"part_subtype", "assembly_level"},
        ),
    ),
)
def test_semantic_gate_holds_adjacent_component_with_same_oe(
    reference_title: str,
    candidate_title: str,
    conflict_dimensions: set[str],
) -> None:
    """A copied OE does not override a deterministic component mismatch."""

    reference = ReferenceItem(
        oem="357919501A",
        title=reference_title,
        price=Decimal("1000"),
        category="electrical",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title=candidate_title,
        description=None,
        article_field="357919501A",
        brand="Aftermarket",
        price=Decimal("500"),
        category_path=(0, 55, 5502, 341534),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_CONFLICT"
    assert conflict_dimensions <= {
        row["dimension"]
        for row in gated.details["semantic_gate"]["hard_stop_conflicts"]
    }


def test_semantic_gate_holds_damaged_exact_oe_for_manual_review() -> None:
    reference = ReferenceItem(
        oem="921100001R",
        title="Радіатор кондиціонера Renault Scenic",
        price=Decimal("1000"),
        category="radiator",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Радіатор кондиціонера Renault Scenic 921100001R погнутий",
        description=None,
        article_field="921100001R",
        brand="Aftermarket",
        price=Decimal("500"),
        category_path=(0, 55, 5502, 341534),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_PRICING_EVIDENCE_INCOMPLETE"
    assert gated.details["semantic_gate"]["missing_pricing_dimensions"] == [
        "condition"
    ]


def test_semantic_pricing_gate_holds_explicit_engine_conflict_for_review() -> None:
    reference = ReferenceItem(
        oem="90336039",
        title="Датчик давления масла Daewoo Lanos 1.5",
        price=Decimal("1000"),
        category="sensors",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Датчик давления масла Lanos 2.2 90336039",
        description=None,
        article_field="90336039",
        brand="GM",
        price=Decimal("500"),
        category_path=(0, 55, 5502, 341534),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_FITMENT_CONFLICT_REVIEW"
    assert "SEMANTIC_FITMENT_CONFLICT_REVIEW" in gated.flags
    assert gated.details["semantic_gate"]["fitment_conflicts"]


def test_market_collection_semantic_gate_holds_ambiguous_subtype() -> None:
    verdict = _market_semantic_candidate_verdict(
        reference=ReferenceItem(
            oem="9017601047",
            title="Кронштейн сдвижной двери Mercedes Sprinter верхний",
            price=Decimal("1000"),
            category="door_hardware",
        ),
        product={
            "name": (
                "Ролик двері бічної зсувний правій верхній Mercedes Sprinter "
                "9017601047"
            ),
            "sku": "9017601047",
            "brand": "Aftermarket",
            "seller_id": "external",
            "seller_name": "External",
        },
        price=Decimal("500"),
        selection_config=_SELECTION_CONFIG,
        owned_sellers=set(),
        confirmed_crosses=(),
        brand_tiers={},
        authoritative_identity=False,
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "SEMANTIC_AMBIGUOUS_REVIEW"


def test_market_collection_semantic_gate_holds_fitment_conflict() -> None:
    verdict = _market_semantic_candidate_verdict(
        reference=ReferenceItem(
            oem="90336039",
            title="Датчик давления масла Daewoo Lanos 1.5",
            price=Decimal("1000"),
            category="sensors",
        ),
        product={
            "name": "Датчик давления масла Lanos 2.2 90336039",
            "sku": "90336039",
            "brand": "GM",
            "seller_id": "external",
            "seller_name": "External",
        },
        price=Decimal("500"),
        selection_config=_SELECTION_CONFIG,
        owned_sellers=set(),
        confirmed_crosses=(),
        brand_tiers={},
        authoritative_identity=False,
    )

    assert verdict.status is CandidateStatus.REFERENCE_ONLY
    assert verdict.reason == "SEMANTIC_FITMENT_CONFLICT_REVIEW"


def test_market_collection_semantic_gate_allows_clean_verified_candidate() -> None:
    verdict = _market_semantic_candidate_verdict(
        reference=ReferenceItem(
            oem="7E5827505A",
            title="Замок крышки багажника Volkswagen T5",
            price=Decimal("1000"),
            category="body_lock",
        ),
        product={
            "name": "7E5827505A Замок крышки багажника Фольксваген Т5 T6",
            "sku": "7E5827505A",
            "brand": "Polcar",
            "seller_id": "external",
            "seller_name": "External",
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
        },
        price=Decimal("500"),
        selection_config=_SELECTION_CONFIG,
        owned_sellers=set(),
        confirmed_crosses=(),
        brand_tiers={},
        authoritative_identity=False,
        reference_payload={
            "name": "Замок крышки багажника Volkswagen T5",
            "category": "body_lock",
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
        },
        require_pricing_completeness=True,
    )

    assert verdict.status is CandidateStatus.PRICING_EVIDENCE
    assert verdict.details["semantic_gate"]["reason"] == "OK"


def test_market_pricing_gate_holds_missing_package_and_unit_evidence() -> None:
    """An identity hit without a price basis is visible but not priceable."""

    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    initial = check_candidate(
        reference,
        CandidateItem(
            seller_id="external",
            seller_name="External",
            title="Замок крышки багажника Volkswagen T5 7E5827505A",
            description=None,
            article_field="7E5827505A",
            brand="Polcar",
            price=Decimal("500"),
            category_path=(0, 55, 5502),
        ),
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={
            "title": "Замок крышки багажника Volkswagen T5 7E5827505A",
            "brand": "Polcar",
        },
        authoritative_identity=True,
        reference_payload={
            "name": reference.title,
            "category": reference.category,
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
        },
        require_pricing_completeness=True,
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_PRICING_EVIDENCE_INCOMPLETE"
    assert set(gated.details["semantic_gate"]["missing_pricing_dimensions"]) >= {
        "condition",
        "package_quantity",
        "unit_basis",
    }


def test_market_cross_gate_requires_category_specific_evidence() -> None:
    """A verified cross radiator needs geometry/ports/engine evidence too."""

    reference = ReferenceItem(
        oem="93818439",
        title="Радіатор охолодження двигуна Iveco Daily 2.8 625x440",
        price=Decimal("1000"),
        category="radiator",
    )
    initial = check_candidate(
        reference,
        CandidateItem(
            seller_id="external",
            seller_name="External",
            title="Радіатор охолодження двигуна Iveco Daily 2.8 93818439",
            description=None,
            article_field="93818439",
            brand="Aftermarket",
            price=Decimal("500"),
        ),
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={
            "title": "Радіатор охолодження двигуна Iveco Daily 2.8 93818439 1шт",
            "brand": "Aftermarket",
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
        },
        authoritative_identity=True,
        reference_payload={
            "name": reference.title,
            "category": reference.category,
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
        },
        require_pricing_completeness=True,
        require_analogue_dimensions=True,
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_PRICING_EVIDENCE_INCOMPLETE"
    assert {
        "technical_specs",
        "inlet_outlet",
    }.issubset(gated.details["semantic_gate"]["missing_pricing_dimensions"])


def test_category_required_port_conflict_blocks_exact_oe_pricing() -> None:
    """An exact OE cannot override contradictory reservoir port evidence."""

    reference = ReferenceItem(
        oem="330422371",
        title="Бачок ГУР VW Passat B3/B4",
        price=Decimal("1000"),
        category="steering_reservoir",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Бачок ГУР VW Passat B3/B4 330422371",
        description=None,
        article_field="330422371",
        brand="Aftermarket",
        price=Decimal("500"),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={
            "title": candidate.title,
            "brand": candidate.brand,
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
            "characteristics": {"Количество патрубков": "1"},
        },
        authoritative_identity=True,
        reference_payload={
            "name": reference.title,
            "category": reference.category,
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
            "characteristics": {"Количество патрубков": "2"},
        },
        require_pricing_completeness=True,
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_CATEGORY_CONFLICT"
    assert gated.details["semantic_gate"]["category_specific_conflicts"]
    assert {
        row["dimension"]
        for row in gated.details["semantic_gate"]["category_specific_conflicts"]
    } >= {"ports"}


def test_semantic_pricing_gate_holds_vehicle_model_conflict_for_search() -> None:
    reference = ReferenceItem(
        oem="12345",
        title="Амортизатор задній Toyota Auris",
        price=Decimal("1000"),
        category="suspension",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Амортизатор задній Toyota Prius 12345",
        description=None,
        article_field="12345",
        brand=None,
        price=Decimal("500"),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_FITMENT_CONFLICT_REVIEW"
    assert gated.details["semantic_gate"]["fitment_conflicts"][0]["dimension"] == (
        "vehicle_model"
    )


def test_verified_authoritative_identity_may_cross_vehicle_model() -> None:
    reference = ReferenceItem(
        oem="12345",
        title="Амортизатор задній Toyota Auris",
        price=Decimal("1000"),
        category="suspension",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Амортизатор задній Toyota Prius 12345",
        description=None,
        article_field="12345",
        brand=None,
        price=Decimal("500"),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title},
        authoritative_identity=True,
    )

    assert gated.status is CandidateStatus.PRICING_EVIDENCE
    assert gated.details["semantic_gate"]["fitment_conflicts"] == []
    assert gated.details["semantic_gate"]["fitment_conflicts_bypassed"][0][
        "dimension"
    ] == "vehicle_model"


def test_semantic_pricing_gate_holds_untyped_reference_symmetrically() -> None:
    reference = ReferenceItem(
        oem="7E5827505A",
        title="7E5827505A",
        price=Decimal("1000"),
        category="body_lock",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Замок багажника ляда 7E5827505A VW Transporter T5 T6",
        description=None,
        article_field="7E5827505A",
        brand=None,
        price=Decimal("500"),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_UNCONFIRMED"


def test_semantic_pricing_gate_holds_short_numeric_unknown_part_family() -> None:
    reference = ReferenceItem(
        oem="10164",
        title="Шаровая опора VW T4 нижняя",
        price=Decimal("1000"),
        category="suspension",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="10164",
        description=None,
        article_field="10164",
        brand="Unknown",
        price=Decimal("500"),
        category_path=(0, 55, 5502, 341534),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_UNCONFIRMED"
    assert "SEMANTIC_IDENTITY_UNCONFIRMED" in gated.flags


def test_semantic_pricing_gate_holds_unapproved_category_without_auto_text() -> None:
    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Generic article 7E5827505A",
        description=None,
        article_field="7E5827505A",
        brand="Unknown",
        price=Decimal("500"),
        category_path=(0, 9999, 999901),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "CATEGORY_DOMAIN_UNCONFIRMED"
    assert "CATEGORY_DOMAIN_UNCONFIRMED" in gated.flags


def test_semantic_pricing_gate_does_not_price_generic_exact_article_hit() -> None:
    """An exact article without a typed candidate title is still unverified."""

    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="7E5827505A",
        description=None,
        article_field="7E5827505A",
        brand="Unknown",
        price=Decimal("500"),
        category_path=(0, 55),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_UNCONFIRMED"
    assert "SEMANTIC_IDENTITY_UNCONFIRMED" in gated.flags


def test_authoritative_marketplace_identity_keeps_untyped_listing_review_only() -> (
    None
):
    """Marketplace grouping keeps the card visible, not priceable."""
    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="7E5827505A",
        description=None,
        article_field="SELLER-42",
        brand="Unknown",
        price=Decimal("500"),
        category_path=(0, 55),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "brand": candidate.brand},
        authoritative_identity=True,
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_PRICING_EVIDENCE_INCOMPLETE"
    assert set(gated.details["semantic_gate"]["missing_pricing_dimensions"]) >= {
        "part_subtype",
        "assembly_level",
    }


def test_authoritative_untyped_listing_stays_out_of_persisted_price_cohort() -> None:
    """A marketplace OE grouping is not a substitute for typed sellable facts."""

    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    initial = check_candidate(
        reference,
        CandidateItem(
            seller_id="external",
            seller_name="External",
            title="7E5827505A",
            description=None,
            article_field="SELLER-42",
            brand="Unknown",
            price=Decimal("500"),
            category_path=(0, 55),
        ),
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={
            "title": "7E5827505A",
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
        },
        authoritative_identity=True,
        reference_payload={
            "name": reference.title,
            "category": reference.category,
            "condition": "new",
            "package_quantity": 1,
            "unit_basis": "piece",
        },
        require_pricing_completeness=True,
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_UNCONFIRMED"
    assert "SEMANTIC_IDENTITY_UNCONFIRMED" in gated.flags


def test_ambiguous_sellable_value_blocks_authoritative_pricing_hit() -> None:
    reference = ReferenceItem(
        oem="7E5827505A",
        title="Амортизатор задний Toyota",
        price=Decimal("1000"),
        category="suspension",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Амортизатор задний левый правый Toyota 7E5827505A",
        description=None,
        article_field="7E5827505A",
        brand="Aftermarket",
        price=Decimal("500"),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title},
        authoritative_identity=True,
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "SEMANTIC_AMBIGUOUS_VALUES_REVIEW"
    assert gated.details["semantic_gate"]["ambiguous_pricing_dimensions"] == [
        "side"
    ]


def test_description_only_oe_evidence_is_not_automatic_identity() -> None:
    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Замок крышки багажника Volkswagen T5",
        description="OE: 7E5827505A",
        article_field="SELLER-42",
        brand="Polcar",
        price=Decimal("500"),
        category_path=(0, 55),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "description": candidate.description},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "OE_DESCRIPTION_UNVERIFIED"
    assert "OE_DESCRIPTION_UNVERIFIED" in gated.flags


def test_verified_search_oe_does_not_bypass_description_only_boundary() -> None:
    """Candidate OE proof is not the same as a Prom grouping assertion."""

    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title="Замок крышки багажника Volkswagen T5",
        description="OE: 7E5827505A",
        article_field="SELLER-42",
        brand="Polcar",
        price=Decimal("500"),
        category_path=(0, 55),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title, "description": candidate.description},
        verified_oe_identity=True,
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "OE_DESCRIPTION_UNVERIFIED"
    assert gated.details["semantic_gate"]["identity_authoritative"] is False
    assert gated.details["semantic_gate"]["identity_verified_by_oe"] is True


def test_oem_stuffed_title_requires_review_before_pricing() -> None:
    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title=(
            "7E5827505A 7E5827505B 31827011 16SKV510 "
            "Замок крышки багажника Volkswagen T5"
        ),
        description=None,
        article_field="SELLER-42",
        brand="Polcar",
        price=Decimal("500"),
        category_path=(0, 55),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )
    assert initial.status is CandidateStatus.PRICING_EVIDENCE
    assert "OEM_STUFFED" in initial.flags

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title},
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "OEM_STUFFED_REVIEW"
    assert "OEM_STUFFED_REVIEW" in gated.flags


def test_verified_search_oe_does_not_bypass_oem_stuffing_boundary() -> None:
    """Several OE-like numbers in a search title stay manual-review only."""

    reference = ReferenceItem(
        oem="7E5827505A",
        title="Замок крышки багажника Volkswagen T5",
        price=Decimal("1000"),
        category="body_lock",
    )
    candidate = CandidateItem(
        seller_id="external",
        seller_name="External",
        title=(
            "7E5827505A 7E5827505B 31827011 16SKV510 "
            "Замок крышки багажника Volkswagen T5"
        ),
        description=None,
        article_field="SELLER-42",
        brand="Polcar",
        price=Decimal("500"),
        category_path=(0, 55),
    )
    initial = check_candidate(
        reference,
        candidate,
        _SELECTION_CONFIG,
        tier_agnostic=True,
    )

    gated = apply_semantic_pricing_gate(
        initial,
        reference=reference,
        candidate={"title": candidate.title},
        verified_oe_identity=True,
    )

    assert gated.status is CandidateStatus.REFERENCE_ONLY
    assert gated.reason == "OEM_STUFFED_REVIEW"
    assert gated.details["semantic_gate"]["identity_authoritative"] is False
    assert gated.details["semantic_gate"]["identity_verified_by_oe"] is True


@pytest.mark.parametrize(
    ("title", "query", "expected"),
    [
        ("Деталь 1234567", "123456", False),
        ("Деталь OE 123456", "123456", True),
        ("Деталь #123456", "123456", True),
        ("Кришка 7E5 827 505 A", "7E5827505A", True),
        ("Кришка 7E5827505AB", "7E5827505A", False),
    ],
)
def test_catalog_discovery_identity_flag_uses_exact_title_boundaries(
    title: str,
    query: str,
    expected: bool,
) -> None:
    assert _title_carries_query(title, query) is expected


def test_catalog_discovery_prefers_normalized_oe_over_sku() -> None:
    assert (
        catalog_discovery_query(
            sku="KEMP-LOCAL-ARTICLE",
            oe="7E5 827 505 A",
        )
        == "7E5827505A"
    )


def test_catalog_discovery_falls_back_to_sku_when_wp2_leaves_oe_empty() -> None:
    """After WP-2 an aftermarket position has no ``oe_norm`` at all. The search
    still runs, on the supplier article, and this is the intended branch — not
    a short-circuit nobody noticed."""

    assert catalog_discovery_query(sku="313856", oe=None) == "313856"
    assert catalog_discovery_query(sku="313856", oe="   ") == "313856"


def test_catalog_discovery_prefers_explicit_mpn_over_seller_sku() -> None:
    assert (
        catalog_discovery_query(
            sku="PRIVATE-SELLER-CODE",
            oe=None,
            mpn="TH 652 688 J",
        )
        == "TH652688J"
    )


def test_catalog_discovery_product_key_separates_mpn_variants() -> None:
    first = catalog_product_key(
        sku="PRIVATE-SELLER-CODE",
        oe=None,
        mpn="TH652688J",
        brand="Vernet",
    )
    second = catalog_product_key(
        sku="PRIVATE-SELLER-CODE",
        oe=None,
        mpn="TH652689J",
        brand="Vernet",
    )
    assert first != second


def test_private_catalog_discovery_resolves_to_full_public_mpn() -> None:
    row = SimpleNamespace(
        identity_status="MPN_ONLY",
        oe_norm="776414",
        mpn_norm="115",
        part_numbers_norm=["115070"],
    )

    assert _catalog_identity_query_from_rows([row]) == "115070"


def test_private_catalog_discovery_rejects_conflicting_catalog_rows() -> None:
    rows = [
        SimpleNamespace(
            identity_status="MPN_ONLY",
            oe_norm="776414",
            mpn_norm="115",
            part_numbers_norm=["115070"],
        ),
        SimpleNamespace(
            identity_status="MPN_ONLY",
            oe_norm="776414",
            mpn_norm="115",
            part_numbers_norm=["115071"],
        ),
    ]

    assert _catalog_identity_query_from_rows(rows) is None


@pytest.mark.asyncio
async def test_private_catalog_discovery_never_searches_private_code_without_consensus() -> None:
    class _FakeScalarResult:
        def all(self):
            return [
                SimpleNamespace(
                    identity_status="MPN_ONLY",
                    oe_norm="776414",
                    mpn_norm="115",
                    part_numbers_norm=["115070"],
                )
            ]

    class _FakeSession:
        async def scalars(self, _statement):
            return _FakeScalarResult()

    resolved = await _resolve_private_catalog_discovery_query(
        _FakeSession(),
        workspace_id=uuid4(),
        sku="776414",
        oe=None,
        brand="KEMP",
        requested_query="776414",
    )

    assert resolved == "115070"


@pytest.mark.asyncio
async def test_private_mpn_is_resolved_before_marketplace_search() -> None:
    class _FakeScalarResult:
        def all(self):
            return [
                SimpleNamespace(
                    identity_status="MPN_ONLY",
                    oe_norm="776414",
                    mpn_norm="115070",
                    part_numbers_norm=[],
                )
            ]

    class _FakeSession:
        async def scalars(self, _statement):
            return _FakeScalarResult()

    resolved = await _resolve_private_catalog_discovery_query(
        _FakeSession(),
        workspace_id=uuid4(),
        sku=None,
        oe=None,
        brand="KEMP",
        requested_query="776414",
        mpn="776414",
    )

    assert resolved == "115070"


def test_catalog_discovery_passes_owned_sellers_before_detail_cap(monkeypatch) -> None:
    """Owned storefronts must not consume the bounded enrichment quota."""

    seen: dict[str, object] = {}

    class _Trace:
        def __init__(self, **_kwargs) -> None:
            pass

        def drain_completed_requests(self):
            return (
                SimpleNamespace(
                    raw_body=b"<html />",
                    response_encoding="utf-8",
                ),
            )

        def close(self) -> None:
            pass

    class _TraceContext:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class _Adapter:
        def __init__(self, _config, *, excluded_seller_ids=frozenset()) -> None:
            seen["excluded_seller_ids"] = excluded_seller_ids

        def extract(self, scrape_input):
            seen["search_context"] = scrape_input.search_context
            return SimpleNamespace(
                comparison_payload={"acquisition_outcome": "RESULTS"}
            )

    monkeypatch.setattr(catalog_discovery, "ScrapeExecutionTrace", _Trace)
    monkeypatch.setattr(
        catalog_discovery,
        "scrape_execution",
        lambda _trace: _TraceContext(),
    )
    monkeypatch.setattr(catalog_discovery, "FrozenPromScraperAdapter", _Adapter)
    monkeypatch.setattr(
        catalog_discovery,
        "usable_search_requests",
        lambda requests: tuple(requests),
    )
    monkeypatch.setattr(
        catalog_discovery,
        "parse_search",
        lambda _body, _lang: SimpleNamespace(total=1),
    )

    _collect_live(
        "115070",
        Settings(),
        search_page_limit=1,
        excluded_seller_ids=frozenset({"2847093", "3912822"}),
        search_context=catalog_discovery_search_context(
            title="Амортизатор задній Toyota Camry",
            brand="SACHS",
            category="Амортизатори",
        ),
    )

    assert seen["excluded_seller_ids"] == frozenset({"2847093", "3912822"})
    assert seen["search_context"] == (
        "АМОРТИЗАТОР ЗАДНІЙ TOYOTA CAMRY SACHS АМОРТИЗАТОРИ"
    )


def test_catalog_discovery_search_context_is_bounded_and_optional() -> None:
    assert catalog_discovery_search_context(
        title=None,
        brand=" ",
        category=None,
    ) is None
    context = catalog_discovery_search_context(
        title="x" * 400,
        brand="Brand",
        category="Category",
    )
    assert context is not None
    assert len(context) == 255


def test_catalog_discovery_product_key_is_format_stable() -> None:
    formatted = catalog_product_key(
        sku="7E5 827 505 A",
        oe="7E5 827 505 A",
        brand="Volkswagen",
    )
    compact = catalog_product_key(
        sku="7E5827505A",
        oe="7E5827505A",
        brand="VOLKSWAGEN",
    )

    assert formatted == compact


def _trace(
    sequence_no: int,
    *,
    outcome: str = "success",
    status_code: int | None = 200,
    body: bytes | None = b"<html></html>",
    error_category: str | None = None,
    redirect_location: str | None = None,
) -> LogicalRequestTrace:
    prepared_url = "https://prom.ua/ua/search?search_term=OE" + (
        f"&page={sequence_no}" if sequence_no > 1 else ""
    )
    return LogicalRequestTrace(
        sequence_no=sequence_no,
        request_kind="search_page",
        prepared_url=prepared_url,
        request_key=f"key-{sequence_no}",
        started_at=datetime(2026, 7, 26, tzinfo=UTC),
        started_perf=0.0,
        outcome=outcome,
        response_status_code=status_code,
        response_redirect_location=redirect_location,
        raw_body=body,
        content_sha256=(hashlib.sha256(body).hexdigest() if body is not None else None),
        error_category=error_category,
    )


def _redirect_trace(sequence_no: int) -> LogicalRequestTrace:
    return _trace(
        sequence_no,
        outcome="terminal_failure",
        status_code=301,
        body=b"",
        error_category="upstream_3xx",
        redirect_location="/ua/search?search_term=OE",
    )


def test_trailing_redirect_probe_does_not_invalidate_collected_pages() -> None:
    """8E0121251L reported 67 results but served 66; page 4 answered 301."""

    requests = (_trace(1), _trace(2), _trace(3), _redirect_trace(4))

    usable = usable_search_requests(requests)

    assert [request.sequence_no for request in usable] == [1, 2, 3]


def test_a_run_whose_only_request_redirected_has_no_evidence() -> None:
    with pytest.raises(CatalogDiscoveryError) as error:
        usable_search_requests((_redirect_trace(1),))

    assert error.value.code == "CATALOG_DISCOVERY_HTTP_INCOMPLETE"


@pytest.mark.parametrize(
    ("status_code", "location"),
    [
        (302, "/ua/search?search_term=OE"),
        (301, "/ua/search?search_term=OTHER"),
        (301, "https://example.net/challenge"),
        (301, None),
    ],
)
def test_noncanonical_redirect_is_not_a_pagination_end(
    status_code: int,
    location: str | None,
) -> None:
    redirect = _trace(
        2,
        outcome="terminal_failure",
        status_code=status_code,
        body=b"",
        error_category="upstream_3xx",
        redirect_location=location,
    )

    with pytest.raises(CatalogDiscoveryError) as error:
        usable_search_requests((_trace(1), redirect))

    assert error.value.code == "CATALOG_DISCOVERY_HTTP_INCOMPLETE"


@pytest.mark.parametrize("category", ["upstream_4xx", "upstream_5xx", None])
def test_a_non_redirect_failure_still_fails_the_run(category: str | None) -> None:
    requests = (
        _trace(1),
        _trace(
            2,
            outcome="terminal_failure",
            status_code=500,
            body=None,
            error_category=category,
        ),
    )

    with pytest.raises(CatalogDiscoveryError) as error:
        usable_search_requests(requests)

    assert error.value.code == "CATALOG_DISCOVERY_HTTP_INCOMPLETE"


def test_a_successful_request_without_a_body_is_not_usable() -> None:
    with pytest.raises(CatalogDiscoveryError):
        usable_search_requests((_trace(1, body=None),))


def test_identical_traces_are_not_deduplicated_by_equality() -> None:
    """Two pages can carry byte-identical fields; both must still count."""

    requests = (_trace(1), _trace(1))

    assert len(usable_search_requests(requests)) == 2


def test_catalog_discovery_rejects_product_without_identifier() -> None:
    with pytest.raises(CatalogDiscoveryError) as error:
        catalog_discovery_query(sku=" ", oe=None)

    assert error.value.code == "CATALOG_DISCOVERY_IDENTIFIER_REQUIRED"


@pytest.mark.parametrize(
    (
        "reported_total",
        "retrieved_count",
        "request_count",
        "page_limit",
        "expected",
    ),
    [
        (90, 90, 3, 10, (0, Decimal("1.000000"), "FULL_REPORTED_RESULT_SET")),
        (90, 58, 2, 2, (32, Decimal("0.644444"), "SEARCH_PAGE_HARD_CAP")),
        (90, 58, 2, 10, (32, Decimal("0.644444"), "UPSTREAM_RESULT_GAP")),
        (None, 29, 1, 10, (0, None, "PROM_TOTAL_UNKNOWN")),
        (0, 0, 1, 10, (0, None, "FULL_REPORTED_RESULT_SET")),
    ],
)
def test_catalog_discovery_coverage_summary(
    reported_total: int | None,
    retrieved_count: int,
    request_count: int,
    page_limit: int,
    expected: tuple[int, Decimal | None, str],
) -> None:
    assert (
        _coverage_summary(
            reported_total=reported_total,
            retrieved_count=retrieved_count,
            request_count=request_count,
            search_page_limit=page_limit,
        )
        == expected
    )


@pytest.mark.parametrize("value", [0, 51])
def test_catalog_discovery_page_hard_cap_is_bounded(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(catalog_discovery_max_search_pages=value)


def test_catalog_discovery_page_hard_cap_defaults_to_ten() -> None:
    assert Settings().catalog_discovery_max_search_pages == 10


def _card_trace(
    sequence_no: int,
    *,
    outcome: str = "success",
    status_code: int | None = 200,
    body: bytes | None = b"<html></html>",
    error_category: str | None = None,
) -> LogicalRequestTrace:
    return LogicalRequestTrace(
        sequence_no=sequence_no,
        request_kind="product_page",
        prepared_url=f"https://prom.ua/ua/p{sequence_no}-product.html",
        request_key=f"card-{sequence_no}",
        started_at=datetime(2026, 8, 6, tzinfo=UTC),
        started_perf=0.0,
        outcome=outcome,
        response_status_code=status_code,
        raw_body=body,
        content_sha256=(hashlib.sha256(body).hexdigest() if body is not None else None),
        error_category=error_category,
    )


def test_a_broken_competitor_card_does_not_invalidate_a_discovery_run() -> None:
    """The gateway keeps the listing when a card breaks; so must the run.

    With the detail budget unbounded a run fetches every non-owned row, so a
    single 404 anywhere in that set would otherwise fail every discovery run.
    """

    requests = (
        _trace(1),
        _card_trace(2),
        _card_trace(
            3,
            outcome="terminal_failure",
            status_code=404,
            body=None,
            error_category="upstream_4xx",
        ),
    )

    usable = usable_search_requests(requests)

    assert [request.sequence_no for request in usable] == [1]


def test_search_page_count_excludes_fetched_product_cards() -> None:
    """``request_count`` is exposed as ``search_pages_fetched``.

    Counting detail requests in it inflated the number the SEARCH_PAGE_HARD_CAP
    check reads, and an unbounded detail budget would make it meaningless.
    """

    requests = (_trace(1), _trace(2), _card_trace(3), _card_trace(4))

    assert len(usable_search_requests(requests)) == 2


def test_a_failed_search_page_still_fails_the_run_with_cards_present() -> None:
    requests = (
        _trace(1),
        _card_trace(2),
        _trace(
            3,
            outcome="terminal_failure",
            status_code=500,
            body=None,
            error_category="upstream_5xx",
        ),
    )

    with pytest.raises(CatalogDiscoveryError) as error:
        usable_search_requests(requests)

    assert error.value.code == "CATALOG_DISCOVERY_HTTP_INCOMPLETE"


def test_an_mpn_only_row_is_searchable_but_never_priceable() -> None:
    """The customer's namespace rule, stated as one property (2026-08-06).

    The original vehicle OE is the market identity. A KEMP MPN is a join key
    into the customer's own catalogue: it may find candidates for discovery and
    manual review, but a row without a confirmed public OE must never reach
    pricing or calibration. Both halves are covered separately elsewhere; this
    states the rule itself, because a later "fix" to either half would look
    locally reasonable and silently break the contract.
    """

    row = SimpleNamespace(
        identity_status="MPN_ONLY",
        oe_norm="31211128157",
        mpn_norm="561948-AEZ72",
        part_numbers_norm=["561948-AEZ72"],
        sku="77641360",
    )

    assert customer_identity_available(row) is False
    assert (
        customer_identity_query_from_fields(
            identity_status=row.identity_status,
            oe_norm=row.oe_norm,
            mpn_norm=row.mpn_norm,
            part_numbers_norm=row.part_numbers_norm,
        )
        == "561948-AEZ72"
    )
    assert (
        catalog_discovery_query(sku=row.sku, oe=row.oe_norm, mpn=row.mpn_norm)
        == "31211128157"
    )
