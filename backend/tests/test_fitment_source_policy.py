from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from marko.infrastructure.db.models import FitmentSource
from marko.infrastructure.db.models import (
    FitmentAnalysis,
    FitmentCandidateAssessment,
    FitmentEvidenceClaim,
)
from marko.services.fitment_intelligence import (
    AnalysisSpec,
    CandidateAnalysisSpec,
    FitmentIntelligenceError,
    FitmentSourceBlocked,
    SubmittedEvidence,
    _analysis_spec_from_payload,
    _authorize_submitted_evidence_batch,
    _json_safe,
    _resolve_cross_reference_evidence,
    _validate_analysis_scope,
    register_fitment_source,
    register_source_document,
)
from metis.fitment import (
    Availability,
    CommercialContext,
    Condition,
    EvidenceClaim,
    EvidencePolarity,
    FitmentFeature,
    PartIdentity,
    SellerRelation,
    SourceTier,
    StatementStatus,
)
from metis.pricing.types import ProductTier


NOW = datetime(2026, 7, 21, tzinfo=UTC)


def _claim(*, source_type: str, tier: SourceTier, reliability: str) -> EvidenceClaim:
    return EvidenceClaim(
        evidence_id=f"evidence-{source_type}",
        feature=FitmentFeature.OE_EXACT,
        value=Decimal("1"),
        source_id="untrusted-input",
        source_type=source_type,
        source_tier=tier,
        source_reliability=Decimal(reliability),
        extraction_confidence=Decimal("1"),
        independence_factor=Decimal("1"),
        freshness_factor=Decimal("1"),
        correlation_group="untrusted-input",
        polarity=EvidencePolarity.SUPPORTS,
        statement_status=StatementStatus.FACT,
        claim_value={"oe": "48530-89025"},
        retrieved_at=NOW,
    )


def _source_kwargs() -> dict:
    return {
        "workspace_id": uuid4(),
        "actor_user_id": uuid4(),
        "source_key": "kyb-official",
        "source_type": "official_manufacturer_catalog",
        "source_tier": SourceTier.A,
        "base_reliability": Decimal("0.95"),
        "domain": "catalog.kyb.example",
        "access_method": "licensed_api",
        "access_status": "PERMITTED",
        "access_reference": "contract:KYB-2026-01",
        "robots_checked": True,
        "terms_checked": True,
        "rate_limit": "10/min",
        "cache_policy": "fact_level_only",
        "policy_version": "v1",
        "reviewed_at": NOW,
    }


@pytest.mark.asyncio
async def test_fitment_scope_cannot_replace_confirmed_oe_with_supplier_article() -> None:
    workspace_id = uuid4()
    catalog_item_id = uuid4()
    observation_id = uuid4()
    catalog_item = type(
        "CatalogItemFixture",
        (),
        {
            "workspace_id": workspace_id,
            "identity_status": "OE_CONFIRMED",
            "oe_norm": "330422371",
        },
    )()

    class _Rows:
        def all(self):
            return [observation_id]

    class _Session:
        async def get(self, _model, _identifier):
            return catalog_item

        async def scalars(self, _statement):
            return _Rows()

    candidate = CandidateAnalysisSpec(
        market_observation_id=observation_id,
        identity=PartIdentity(manufacturer_article="1145200500"),
        commercial_context=CommercialContext(),
    )
    spec = AnalysisSpec(
        target_identity=PartIdentity(
            manufacturer_article="1145200500",
            oe_numbers=("1145200500",),
        ),
        target_commercial_context=CommercialContext(),
        candidates=(candidate,),
        source_policy_snapshot={},
    )

    with pytest.raises(
        FitmentIntelligenceError,
        match="confirmed original OE",
    ):
        await _validate_analysis_scope(
            _Session(),  # type: ignore[arg-type]
            workspace_id=workspace_id,
            catalog_item_id=catalog_item_id,
            pricing_run_id=None,
            spec=spec,
            authorize_evidence=False,
        )

    spec = AnalysisSpec(
        target_identity=PartIdentity(
            manufacturer_article="1145200500",
            oe_numbers=("330 422 371",),
        ),
        target_commercial_context=CommercialContext(),
        candidates=(candidate,),
        source_policy_snapshot={},
    )
    await _validate_analysis_scope(
        _Session(),  # type: ignore[arg-type]
        workspace_id=workspace_id,
        catalog_item_id=catalog_item_id,
        pricing_run_id=None,
        spec=spec,
        authorize_evidence=False,
    )


@pytest.mark.asyncio
async def test_source_tier_cannot_claim_out_of_band_reliability() -> None:
    values = _source_kwargs()
    values["base_reliability"] = Decimal("0.90")

    with pytest.raises(FitmentIntelligenceError, match="tier A reliability"):
        await register_fitment_source(None, **values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_approved_source_requires_auditable_policy_review() -> None:
    values = _source_kwargs()
    values["access_reference"] = ""

    with pytest.raises(FitmentIntelligenceError, match="access reference"):
        await register_fitment_source(None, **values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unregistered_marketplace_claim_is_forced_to_tier_d() -> None:
    submission = SubmittedEvidence(
        _claim(source_type="prom_public", tier=SourceTier.A, reliability="1")
    )

    authorized = await _authorize_submitted_evidence_batch(
        None,  # type: ignore[arg-type]
        workspace_id=uuid4(),
        submissions=(submission,),
    )

    claim = authorized[id(submission)]
    assert claim.source_tier == SourceTier.D
    assert claim.source_reliability == Decimal("0.55")
    assert claim.statement_status == StatementStatus.INFERENCE


@pytest.mark.asyncio
async def test_unregistered_external_catalog_claim_is_blocked() -> None:
    submission = SubmittedEvidence(
        _claim(
            source_type="official_manufacturer_catalog",
            tier=SourceTier.A,
            reliability="1",
        )
    )

    with pytest.raises(FitmentSourceBlocked, match="registered source document"):
        await _authorize_submitted_evidence_batch(
            None,  # type: ignore[arg-type]
            workspace_id=uuid4(),
            submissions=(submission,),
        )


class _GetOnlySession:
    def __init__(self, source: FitmentSource) -> None:
        self.source = source

    async def get(self, _model, _identifier):
        return self.source


@pytest.mark.asyncio
async def test_source_document_cannot_escape_registered_domain() -> None:
    workspace_id = uuid4()
    source = FitmentSource(
        id=uuid4(),
        workspace_id=workspace_id,
        source_key="kyb-official",
        source_type="official_manufacturer_catalog",
        source_tier="A",
        base_reliability=Decimal("0.95"),
        domain="catalog.kyb.example",
        access_method="licensed_api",
        access_status="PERMITTED",
        access_reference="contract:KYB-2026-01",
        robots_checked=True,
        terms_checked=True,
        rate_limit="10/min",
        cache_policy="fact_level_only",
        policy_version="v1",
        reviewed_at=NOW,
    )

    with pytest.raises(FitmentSourceBlocked, match="outside"):
        await register_source_document(
            _GetOnlySession(source),  # type: ignore[arg-type]
            workspace_id=workspace_id,
            actor_user_id=uuid4(),
            source_id=source.id,
            source_url="https://attacker.example/catalog/item",
            retrieval_query="article=341267",
            content_sha256="a" * 64,
            content_locator=None,
            response_metadata={},
            retrieved_at=NOW,
            expires_at=None,
        )


class _RowsResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def all(self) -> list[tuple]:
        return self._rows


class _CrossEvidenceSession:
    def __init__(self, rows: list[tuple], *, review_count: int) -> None:
        self.rows = rows
        self.review_count = review_count

    async def execute(self, _statement):
        return _RowsResult(self.rows)

    async def scalar(self, _statement):
        return self.review_count


def _cross_row(*, tier: str, group: str = "official") -> tuple:
    assessment = FitmentCandidateAssessment(
        id=uuid4(),
        candidate_identity={"manufacturer_article": "341267"},
    )
    analysis = FitmentAnalysis(
        target_identity={"oe_numbers": ["48530-89025"]},
    )
    claim = FitmentEvidenceClaim(
        id=uuid4(),
        assessment_id=assessment.id,
        feature=FitmentFeature.CROSS_CONFIRMED.value,
        evidence_value=Decimal("1"),
        source_tier=tier,
        correlation_group=group,
    )
    return claim, assessment, analysis


@pytest.mark.asyncio
async def test_human_cross_requires_matching_persisted_review() -> None:
    row = _cross_row(tier="D")
    session = _CrossEvidenceSession([row], review_count=0)

    with pytest.raises(FitmentIntelligenceError, match="persisted human review"):
        await _resolve_cross_reference_evidence(
            session,  # type: ignore[arg-type]
            workspace_id=uuid4(),
            article="341267",
            oe="4853089025",
            relation_status="human_confirmed",
            evidence_claim_ids=[row[0].id],
        )


@pytest.mark.asyncio
async def test_cross_source_and_human_counts_are_computed_from_evidence() -> None:
    first = _cross_row(tier="B", group="partsouq")
    second = _cross_row(tier="B", group="seven-zap")
    # One review is enough for human confirmation; two upstream groups are
    # counted from persisted claims and never accepted from the request body.
    session = _CrossEvidenceSession([first, second], review_count=1)

    evidence_ids, source_count, human_count = await _resolve_cross_reference_evidence(
        session,  # type: ignore[arg-type]
        workspace_id=uuid4(),
        article="341267",
        oe="4853089025",
        relation_status="human_confirmed",
        evidence_claim_ids=[first[0].id, second[0].id],
    )

    assert evidence_ids == sorted([str(first[0].id), str(second[0].id)])
    assert source_count == 2
    assert human_count == 1


@pytest.mark.asyncio
async def test_source_confirmed_cross_requires_authoritative_identity_evidence() -> (
    None
):
    row = _cross_row(tier="D", group="prom")
    session = _CrossEvidenceSession([row], review_count=0)

    with pytest.raises(
        FitmentIntelligenceError,
        match="strong persisted source evidence|Tier A or two",
    ):
        await _resolve_cross_reference_evidence(
            session,  # type: ignore[arg-type]
            workspace_id=uuid4(),
            article="341267",
            oe="4853089025",
            relation_status="source_confirmed",
            evidence_claim_ids=[row[0].id],
        )


def test_queued_analysis_payload_round_trips_without_losing_typed_evidence() -> None:
    document_id = uuid4()
    original = AnalysisSpec(
        target_identity=PartIdentity(
            category="shock_absorber",
            axle="rear",
            side="right",
            manufacturer_article="KEMP-1",
            oe_numbers=("001-48530",),
            side_specific=True,
        ),
        target_commercial_context=CommercialContext(
            condition=Condition.NEW,
            package_quantity=Decimal("1"),
            unit_basis="piece",
            currency="UAH",
            tier=ProductTier.KEMP,
            availability=Availability.IN_STOCK,
            seller_relation=SellerRelation.OWN,
            stable_seller_id_verified=True,
        ),
        candidates=(
            CandidateAnalysisSpec(
                market_observation_id=uuid4(),
                identity=PartIdentity(
                    category="shock_absorber",
                    manufacturer_article="341267",
                    oe_numbers=("001-48530",),
                ),
                commercial_context=CommercialContext(
                    condition=Condition.NEW,
                    package_quantity=Decimal("1"),
                    unit_basis="piece",
                    currency="UAH",
                    tier=ProductTier.AFTERMARKET_B,
                    availability=Availability.IN_STOCK,
                    seller_relation=SellerRelation.INDEPENDENT,
                    stable_seller_id_verified=True,
                ),
                evidence=(
                    SubmittedEvidence(
                        claim=_claim(
                            source_type="official_manufacturer_catalog",
                            tier=SourceTier.A,
                            reliability="0.95",
                        ),
                        source_document_id=document_id,
                    ),
                ),
            ),
        ),
        source_policy_snapshot={"request": "pilot"},
    )

    restored = _analysis_spec_from_payload(_json_safe(original))

    assert restored == original
    assert restored.target_identity.oe_numbers == ("001-48530",)
    assert restored.candidates[0].evidence[0].source_document_id == document_id
