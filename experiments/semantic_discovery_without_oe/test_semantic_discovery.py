from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from marko.services.parser_models import Product

from semantic_discovery import (
    CatalogSeed,
    DEFAULT_OWNED_SELLER_IDS,
    DeterministicDisposition,
    LunaSemanticOutput,
    assess_candidate,
    bound_luna_output_schema,
    build_evidence_catalog,
    build_luna_snapshot,
    build_query_plan,
    build_seed_profile,
    non_monetary_product,
    redact_monetary_material,
    semantic_model_candidate_record,
    semantic_model_seed_record,
    strict_luna_output_schema,
    snapshot_scalar_paths,
    validate_luna_evidence_against_snapshot,
)


def _seed(
    title: str = "Амортизатор задний Ford (Форд) Sierra 1.6-2.0 82-93 масло",
    *,
    mpn: str = "",
    internal_code: str = "776424",
    candidates: tuple[str, ...] = ("106828",),
) -> CatalogSeed:
    return CatalogSeed(
        row_id="1153724243",
        title=title,
        source_title_uk="",
        category="3,1 Амортизаторы",
        brand="KEMP",
        mpn=mpn,
        internal_code=internal_code,
        source_catalog_code="776465",
        unconfirmed_candidates=candidates,
        no_oe_reason="номер не подтверждён как OE",
        product_url="https://kemp.example/p1153724243.html",
        description="Задний масляный амортизатор для Ford Sierra.",
        characteristics=(),
        image_urls=("https://images.prom.ua/seed.jpg",),
    )


def _candidate(name: str, *, seller_id: int = 999) -> dict:
    product = Product.from_raw(
        {
            "id": 42,
            "name": name,
            "price": "1234.50",
            "priceCurrency": "UAH",
            "urlText": "candidate-card",
            "company": {"id": seller_id, "name": "Independent", "slug": "shop"},
            "imageAlt": "https://images.prom.ua/candidate.jpg",
            "presence": {"presence": "avail", "isAvailable": True},
            "description": "Цена 1 234 грн. Амортизатор для Ford Sierra.",
        }
    )
    return non_monetary_product(product)


def test_query_plan_strips_every_unconfirmed_identifier_but_keeps_specs() -> None:
    seed = _seed(
        title=(
            "KEMP Амортизатор задний Ford Sierra 1.6-2.0 82-93 "
            "106828 776424 776465 MPN-555 масло"
        ),
        mpn="MPN-555",
    )
    profile = build_seed_profile(seed)

    plan = build_query_plan(seed, profile)
    joined = " ".join(item["query"] for item in plan["queries"])

    assert "106828" not in joined
    assert "776424" not in joined
    assert "776465" not in joined
    assert "MPN-555" not in joined
    assert "82-93" in joined
    assert "1.6-2.0" in joined
    assert "задний" in joined.casefold()
    assert plan["identifiers_used_for_retrieval"] == []


def test_structured_candidate_and_description_do_not_leak_price() -> None:
    candidate = _candidate("Амортизатор задний Ford Sierra")
    rendered = json.dumps(candidate, ensure_ascii=False).casefold()

    assert "\"price\"" not in rendered
    assert "pricecurrency" not in rendered
    assert "1234.50" not in rendered
    assert "1 234 грн" not in rendered
    assert "<price_redacted>" in rendered


def test_monetary_redactor_drops_price_labelled_characteristic() -> None:
    clean = redact_monetary_material(
        {
            "characteristics": [
                {"name": "Ціна", "value": "1250"},
                {"name": "Тип", "value": "Масляний"},
            ],
            "description": "Акційна ціна: 1250, доставка завтра",
        }
    )

    rendered = json.dumps(clean, ensure_ascii=False).casefold()
    assert "1250" not in rendered
    assert "ціна: 1250" not in rendered
    assert "ціна\", \"value" not in rendered
    assert "масляний" in rendered
    assert "<price_redacted>" in rendered


@pytest.mark.parametrize(
    ("ours", "candidate", "dimension"),
    (
        (
            "Амортизатор задний Ford Sierra 82-93",
            "Амортизатор передний Ford Sierra 82-93",
            "position",
        ),
        (
            "Суппорт задний левый Audi A4 без скобы",
            "Суппорт задний правый Audi A4 без скобы",
            "side",
        ),
        (
            "Суппорт задний VW Passat без скобы",
            "Суппорт задний VW Passat с скобой",
            "included_components",
        ),
        (
            "Амортизатор задний Ford Sierra",
            "Амортизатор задний Renault Master",
            "vehicle_make",
        ),
        (
            "Амортизатор задний Ford Sierra 82-93 масло",
            "Амортизатор задний Ford Sierra 82-93 газ",
            "damping_medium",
        ),
    ),
)
def test_explicit_no_oe_conflicts_are_deterministic_rejections(
    ours: str,
    candidate: str,
    dimension: str,
) -> None:
    seed = _seed(title=ours, internal_code="", candidates=())

    assessment = assess_candidate(seed, {"name": candidate, "seller_id": 999})

    assert assessment.disposition is DeterministicDisposition.SEMANTIC_NOT_MATCH
    assert dimension in {item["dimension"] for item in assessment.hard_conflicts}
    assert assessment.retrieval_score == 0


def test_positive_similarity_only_enters_luna_review() -> None:
    seed = _seed()
    assessment = assess_candidate(
        seed,
        _candidate("Амортизатор FORD Sierra 87-93 задний масло"),
    )

    assert assessment.disposition is DeterministicDisposition.SEMANTIC_NEEDS_LUNA
    assert assessment.retrieval_score > 0
    output = assessment.as_dict()
    assert output["retrieval_score_is_identity_confidence"] is False
    assert output["automatic_eligible"] is False
    assert output["pricing_eligible_by_construction"] is False


def test_missing_candidate_part_type_stays_reviewable_unknown() -> None:
    assessment = assess_candidate(
        _seed(),
        {"name": "Ford Sierra 82-93 задняя деталь", "seller_id": 999},
    )

    assert assessment.disposition is DeterministicDisposition.SEMANTIC_NEEDS_LUNA
    assert "CANDIDATE_PART_TYPE_UNKNOWN" in assessment.reason_codes


def test_owned_kemp_seller_is_never_a_market_candidate() -> None:
    seller = int(next(iter(DEFAULT_OWNED_SELLER_IDS)))
    assessment = assess_candidate(
        _seed(),
        {"name": "Амортизатор задний Ford Sierra", "seller_id": seller},
    )

    assert assessment.disposition is DeterministicDisposition.OWNED_SELLER_EXCLUDED


def test_luna_snapshot_is_structurally_non_admitting() -> None:
    seed = _seed()
    candidate = _candidate("Амортизатор задний Ford Sierra 82-93")
    candidate["mpn"] = "20765R"
    candidate["part_numbers"] = ["20765R"]
    candidate["description"] += " Код запчастини 20765R."
    candidate["characteristics"] = [
        {"name": "Код запчастини", "value": "20765R"},
        {"name": "Тип", "value": "Масляний"},
    ]
    assessment = assess_candidate(seed, candidate)

    snapshot = build_luna_snapshot(seed, candidate, assessment)

    assert snapshot["constraints"]["confirmed_oe_available"] is False
    assert snapshot["constraints"]["model_may_infer_oe"] is False
    assert snapshot["constraints"]["automatic_eligible"] is False
    assert snapshot["constraints"]["pricing_eligible_by_construction"] is False
    assert "unconfirmed_candidates" not in json.dumps(snapshot)
    assert "internal_code" not in json.dumps(snapshot)
    rendered = json.dumps(snapshot, ensure_ascii=False)
    assert "106828" not in rendered
    assert "776465" not in rendered
    assert "20765R" not in rendered


def test_model_records_redact_identifiers_but_keep_semantic_facts() -> None:
    seed_record = semantic_model_seed_record(_seed())
    candidate_record = semantic_model_candidate_record(
        {
            "name": "Амортизатор 20765R Ford Sierra",
            "mpn": "20765R",
            "part_numbers": ["20765R"],
            "description": "Задний масляный амортизатор, код 20765R",
            "characteristics": [
                {"name": "Код запчастини", "value": "20765R"},
                {"name": "Тип", "value": "Масляний"},
            ],
        }
    )

    assert "106828" not in json.dumps(seed_record, ensure_ascii=False)
    assert "776465" not in json.dumps(seed_record, ensure_ascii=False)
    rendered = json.dumps(candidate_record, ensure_ascii=False)
    assert "20765R" not in rendered
    assert "Масляний" in rendered
    assert "Задний" in rendered


def _valid_luna_match(evidence_id: str = "E_aaaaaaaaaaaaaaaa") -> dict:
    return {
        "schema_version": "luna-semantic-discovery-output-v2",
        "verdict": "MATCH",
        "match_class": "SAME_SELLABLE_DESCRIPTION",
        "semantic_match_score": 92,
        "decision_confidence": 88,
        "image_assessment": "NON_DIAGNOSTIC",
        "rationale": "The explicit part type and installation facts match.",
        "reason_codes": ["PART_TYPE_AND_POSITION_MATCH"],
        "dimension_findings": [
            {
                "dimension": "part_type",
                "outcome": "MATCH",
                "explanation": "Both cards explicitly describe a shock absorber.",
                "evidence": [{"evidence_id": evidence_id}],
            }
        ],
        "unresolved_critical_facts": [],
        "oe_numbers_inferred": [],
        "identity_proven": False,
        "automatic_eligible": False,
        "pricing_eligible": False,
    }


def test_luna_schema_accepts_only_non_admitting_match() -> None:
    output = LunaSemanticOutput.model_validate(_valid_luna_match())

    assert output.verdict.value == "MATCH"
    assert output.identity_proven is False
    assert output.oe_numbers_inferred == []


def test_luna_schema_rejects_oe_invention_and_automatic_admission() -> None:
    unsafe = _valid_luna_match()
    unsafe["oe_numbers_inferred"] = ["123456"]
    unsafe["automatic_eligible"] = True

    with pytest.raises(ValidationError):
        LunaSemanticOutput.model_validate(unsafe)


def test_luna_match_requires_explicit_part_type_match() -> None:
    unsafe = _valid_luna_match()
    unsafe["dimension_findings"][0]["outcome"] = "UNKNOWN"

    with pytest.raises(ValidationError, match="part_type MATCH"):
        LunaSemanticOutput.model_validate(unsafe)


def test_diagnostic_image_assessment_requires_bound_image_evidence() -> None:
    snapshot = {
        "our_product": {"name": "Shock absorber"},
        "candidate": {"name": "Candidate"},
        "deterministic_gate": {"status": "review"},
        "image_evidence_manifest": [{"content_sha256": "abc"}],
    }
    snapshot["evidence_catalog"] = build_evidence_catalog(snapshot)
    our_id = next(
        item["evidence_id"]
        for item in snapshot["evidence_catalog"]
        if item["field_path"] == "$.our_product.name"
    )
    unsafe = _valid_luna_match(our_id)
    unsafe["image_assessment"] = "SUPPORTS"
    output = LunaSemanticOutput.model_validate(unsafe)

    with pytest.raises(ValueError, match="image SHA"):
        validate_luna_evidence_against_snapshot(output, snapshot)


def test_post_validation_rejects_unknown_or_stale_evidence_id() -> None:
    snapshot = {
        "our_product": {"name": "Shock absorber"},
        "candidate": {},
        "deterministic_gate": {},
        "image_evidence_manifest": [],
    }
    snapshot["evidence_catalog"] = build_evidence_catalog(snapshot)
    known_id = snapshot["evidence_catalog"][0]["evidence_id"]
    output = LunaSemanticOutput.model_validate(
        _valid_luna_match("E_ffffffffffffffff")
    )

    with pytest.raises(ValueError, match="Unknown evidence ID"):
        validate_luna_evidence_against_snapshot(output, snapshot)

    output = LunaSemanticOutput.model_validate(_valid_luna_match(known_id))
    snapshot["our_product"]["name"] = "Changed after catalog binding"
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_luna_evidence_against_snapshot(output, snapshot)


def test_output_schema_is_strict_and_requires_safety_flags() -> None:
    schema = strict_luna_output_schema()

    assert schema["additionalProperties"] is False
    assert "identity_proven" in schema["required"]
    assert "automatic_eligible" in schema["required"]
    assert "pricing_eligible" in schema["required"]


def test_snapshot_bound_schema_only_allows_server_authored_evidence_ids() -> None:
    snapshot = {
        "our_product": {"name": "Shock absorber"},
        "candidate": {"name": "Candidate", "fitment": None},
        "deterministic_gate": {
            "semantic_feature_matrix": {
                "comparisons": {"technical_specs": {"state": "UNKNOWN"}}
            }
        },
        "image_evidence_manifest": [{"content_sha256": "abc"}],
    }
    snapshot["evidence_catalog"] = build_evidence_catalog(snapshot)

    paths = snapshot_scalar_paths(snapshot)
    schema = bound_luna_output_schema(snapshot)
    allowed = schema["$defs"]["LunaEvidenceReference"]["properties"][
        "evidence_id"
    ]["enum"]

    assert "$.candidate.fitment" in paths
    assert allowed == [item["evidence_id"] for item in snapshot["evidence_catalog"]]
    assert "E_ffffffffffffffff" not in allowed
