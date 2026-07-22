from decimal import Decimal
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from marko.infrastructure.db.models import MarketObservation, OfferProcessingOutcome
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.market_collection import _persist_payload_observations
from marko.services.offer_processing import (
    AcceptedCandidate,
    OfferAccounting,
    OfferOutcomeCode,
    RejectedOffer,
    process_offer_candidate,
    resolve_offer_price_boundary,
)
from marko.services.pricing_runs import policy_to_dict
from marko.services.scraper_contract import PROM_ADAPTER_VERSION
from metis.pricing import PricingPolicy, ProductTier


def _offer(**overrides):
    value = {
        "product_id": 42,
        "price": "100.00",
        "currency": "UAH",
        "seller_id": "seller-1",
        "name": "Part",
        "is_available": True,
        "url": "https://prom.ua/ua/p42-part.html",
    }
    value.update(overrides)
    return value


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (None, OfferOutcomeCode.REJECTED_NOT_MAPPING),
        ({"product_id": 1}, OfferOutcomeCode.REJECTED_INVALID_PRICE),
        (_offer(price="NaN"), OfferOutcomeCode.REJECTED_INVALID_PRICE),
        (_offer(price="Infinity"), OfferOutcomeCode.REJECTED_INVALID_PRICE),
        (_offer(price="-1"), OfferOutcomeCode.REJECTED_INVALID_PRICE),
        (
            {"price": "10", "currency": "UAH"},
            OfferOutcomeCode.REJECTED_MISSING_LISTING_IDENTITY,
        ),
        (
            {
                "raw_offer_index": 8,
                "product": _offer(),
            },
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
        ),
        (
            {
                "raw_offer_index": 0,
                "retrieval_score": "NaN",
                "product": _offer(),
            },
            OfferOutcomeCode.REJECTED_INVALID_MATCH_SCORE,
        ),
        (
            {
                "raw_offer_index": 0,
                "product": _offer(),
                "upstream_comparison_evidence": [],
            },
            OfferOutcomeCode.REJECTED_SCHEMA_MISMATCH,
        ),
    ],
)
def test_every_invalid_candidate_has_one_typed_terminal_result(raw, code) -> None:
    result = process_offer_candidate(raw, fallback_index=0)

    assert isinstance(result, RejectedOffer)
    assert result.outcome_code == code
    assert result.raw_offer_index == 0


def test_valid_query_candidate_does_not_invent_retrieval_score() -> None:
    result = process_offer_candidate(
        {
            "raw_offer_index": 0,
            "retrieval_kind": "search_query",
            "retrieval_score": None,
            "product": _offer(),
            "upstream_comparison_evidence": None,
        },
        fallback_index=0,
    )

    assert isinstance(result, AcceptedCandidate)
    assert result.retrieval_score is None
    assert result.price == Decimal("100.00")


@pytest.mark.parametrize(
    ("payload", "sale", "reference"),
    [
        (
            {"price": "412", "discounted_price": "330"},
            Decimal("330.00"),
            Decimal("412.00"),
        ),
        (
            {"sale_price": "330", "reference_price": "412", "price": "412"},
            Decimal("330.00"),
            Decimal("412.00"),
        ),
        ({"price": "330", "price_original": "412"}, Decimal("330.00"), Decimal("412.00")),
        ({"price": "330", "reference_price": "300"}, Decimal("330.00"), None),
    ],
)
def test_price_boundary_never_uses_crossed_out_price_as_sale(
    payload, sale, reference
) -> None:
    assert resolve_offer_price_boundary(payload) == (sale, reference)


def test_offer_accounting_enforces_conservation_law() -> None:
    OfferAccounting(4, 1, 2, 1).validate()

    with pytest.raises(ValueError, match=r"R != O \+ J \+ F"):
        OfferAccounting(4, 1, 1, 1).validate()


@pytest.mark.asyncio
async def test_materialization_persists_one_terminal_outcome_per_raw_element(
    monkeypatch,
) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.added: list[object] = []

        def add(self, value: object) -> None:
            self.added.append(value)

        async def flush(self) -> None:
            for value in self.added:
                if isinstance(value, MarketObservation) and value.id is None:
                    value.id = uuid4()

    raw_evidence = [
        {
            "logical_request_id": str(uuid4()),
            "raw_content_sha256": "a" * 64,
        }
    ]
    session = FakeSession()
    from marko.services import market_collection

    original_extract = market_collection.extract_oe_evidence

    def fail_one_extractor(raw_offer, raw_capture_manifest):
        if raw_offer.get("name") == "EXTRACTOR-BOOM":
            raise RuntimeError("intentional extractor variation")
        return original_extract(raw_offer, raw_capture_manifest)

    monkeypatch.setattr(
        market_collection,
        "extract_oe_evidence",
        fail_one_extractor,
    )
    accounting = await _persist_payload_observations(
        session,
        run=SimpleNamespace(
            id=uuid4(),
            parser_version=PROM_ADAPTER_VERSION,
            policy_config=policy_to_dict(PricingPolicy()),
        ),
        run_item=SimpleNamespace(id=uuid4()),
        catalog_item=SimpleNamespace(
            id=uuid4(), category="brakes", oe_norm="1K0121251"
        ),
        capture=SimpleNamespace(
            id=uuid4(),
            parser_version=PROM_ADAPTER_VERSION,
            payload={
                "raw_evidence": raw_evidence,
                "raw_manifest_sha256": canonical_sha256(raw_evidence),
            },
        ),
        offers=[
            {
                "raw_offer_index": 0,
                "retrieval_kind": "search_query",
                "retrieval_score": None,
                "product": {
                    **_offer(oe_raw="1K0 121 251", condition="NEW"),
                    "position": "front",
                    "package_quantity": 1,
                },
                "upstream_comparison_evidence": None,
            },
            {"raw_offer_index": 1, "product": _offer(price="NaN")},
            None,
            {
                "raw_offer_index": 3,
                "retrieval_kind": "search_query",
                "retrieval_score": None,
                "product": _offer(
                    product_id=43,
                    name="EXTRACTOR-BOOM",
                    url="https://prom.ua/ua/p43-part.html",
                ),
                "upstream_comparison_evidence": None,
            },
            {
                "raw_offer_index": 4,
                "retrieval_kind": "search_query",
                "retrieval_score": None,
                "product": _offer(),
                "upstream_comparison_evidence": None,
            },
            {
                "raw_offer_index": 5,
                "retrieval_kind": "search_query",
                "retrieval_score": None,
                "product": _offer(
                    product_id=44,
                    seller_id=None,
                    url="https://prom.ua/ua/p44-part.html",
                    oe_raw="1K0 121 251",
                ),
                "upstream_comparison_evidence": None,
            },
            {
                "raw_offer_index": 6,
                "retrieval_kind": "search_query",
                "retrieval_score": None,
                "product": _offer(
                    product_id=45,
                    url="javascript:alert(1)",
                    oe_raw="1K0 121 251",
                ),
                "upstream_comparison_evidence": None,
            },
        ],
        owned_sellers=set(),
        brand_tiers={"KEMP": ProductTier.KEMP},
        brand_confidence={},
        observed_at=datetime(2026, 7, 19, tzinfo=UTC),
        source_type="persisted_replay",
    )

    assert accounting.as_dict() == {
        "retrieved": 7,
        "observations_persisted": 3,
        "rejected": 3,
        "internal_failures": 1,
    }
    outcomes = [
        value for value in session.added if isinstance(value, OfferProcessingOutcome)
    ]
    assert len(outcomes) == 7
    assert {value.raw_offer_index for value in outcomes} == set(range(7))
    accepted = [
        value
        for value in outcomes
        if value.outcome_code == OfferOutcomeCode.OBSERVATION_PERSISTED.value
    ]
    assert len(accepted) == 3
    assert all(value.market_observation_id is not None for value in accepted)
    observations = [
        value for value in session.added if isinstance(value, MarketObservation)
    ]
    missing_seller = next(
        value for value in observations if value.source_listing_id == "44"
    )
    invalid_url = next(
        value for value in observations if value.source_listing_id == "45"
    )
    assert missing_seller.seller_id == ""
    assert missing_seller.automatic_eligible is False
    assert missing_seller.source_confidence < 1
    assert invalid_url.url == ""
    assert invalid_url.url_absence_reason == "INVALID_URL_PROTOCOL"
    assert invalid_url.automatic_eligible is False
    assert invalid_url.source_confidence < 1
    assert any(
        value.outcome_code == OfferOutcomeCode.FAILED_INTERNAL_PROCESSING.value
        for value in outcomes
    )
