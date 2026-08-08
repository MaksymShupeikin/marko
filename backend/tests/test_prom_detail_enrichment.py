from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from types import SimpleNamespace

from marko.parsers.prom.client import HttpDocument
from marko.parsers.prom.config import ScrapeConfig
from marko.parsers.prom.gateway import (
    PROM_PRODUCT_DETAIL_SCHEMA_VERSION,
    PromGateway,
)
from marko.services.decision_fingerprint import canonical_sha256
from marko.services.market_collection import (
    _detail_evidence_automatic_safe,
    _verified_capture_raw_evidence,
)
from marko.services.parser_models import Product


def _raw_product(
    product_id: int,
    seller_id: int,
    *,
    sku: str,
    name: str = "Термостат 1086282",
    price: str = "1000",
    attributes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": product_id,
        "name": name,
        "sku": sku,
        "price": price,
        "priceCurrency": "UAH",
        "urlText": f"part-{product_id}",
        "company": {"id": seller_id, "name": f"Seller {seller_id}"},
        "presence": {"presence": "available", "isAvailable": True},
        "attributes": attributes,
    }


def _product(
    product_id: int,
    seller_id: int,
    *,
    sku: str,
    name: str = "Термостат 1086282",
    price: str = "1000",
) -> Product:
    return Product.from_raw(
        _raw_product(
            product_id,
            seller_id,
            sku=sku,
            name=name,
            price=price,
        )
    )


def _product_card_html(raw: dict[str, object]) -> str:
    state = {
        "_FAST_CACHE": {
            "ProductCardPageQuery:test": {
                "result": {
                    "product": raw,
                    "motorsProductPage": {
                        "normalizedPartCode": "1086282",
                        "partGroupId": 77,
                        "compatibleOENumbers": [
                            {"oeNumberNormalized": "1086282"},
                            {"oeNumberNormalized": "89FF8575AA"},
                        ],
                        "compatibleVehicles": [
                            {
                                "manufacturer": {"name": "Ford"},
                                "model": {
                                    "name": "Focus",
                                    "dateFrom": "1998",
                                    "dateTo": "2004",
                                },
                                "name": "1.8 TDDI",
                                "fuelType": "diesel",
                            }
                        ],
                    },
                }
            }
        }
    }
    return f"<script>window.ApolloCacheState = {json.dumps(state)};</script>"


class _DocumentClient:
    def __init__(self, document: HttpDocument) -> None:
        self.document = document
        self.urls: list[str] = []

    def get_document(self, url: str) -> HttpDocument:
        self.urls.append(url)
        return self.document


def test_detail_enrichment_binds_exact_bytes_and_never_overwrites_price() -> None:
    listing = _product(101, 501, sku="1086282", price="1000")
    detail_raw = _raw_product(
        101,
        501,
        sku="FORD-1086282",
        price="1",
        attributes=[
            {
                "id": 1,
                "name": "Стан",
                "values": [{"value": "Новий"}],
            },
            {
                "id": 2,
                "name": "Кількість в упаковці",
                "values": [{"value": "1 шт."}],
            },
                {
                    "id": 3,
                    "name": "Оригінальні номери",
                "values": [{"value": "1086282"}],
            },
        ],
    )
    detail_raw["identifiers"] = {"mpn": "TH652688J"}
    detail_raw["descriptionPlain"] = "Термостат Ford 1.8 diesel, новий."
    html = _product_card_html(detail_raw)
    digest = hashlib.sha256(html.encode()).hexdigest()
    client = _DocumentClient(
        HttpDocument(
            text=html,
            content_sha256=digest,
            request_url=listing.url or "",
            status_code=200,
        )
    )

    enriched = PromGateway()._fetch_candidate_detail(client, listing, lang="ua")

    assert enriched.price == "1000"
    assert enriched.sku == "1086282"
    assert enriched.mpn == "TH652688J"
    assert enriched.condition == "Новий"
    assert enriched.package_quantity == 1
    assert enriched.description == "Термостат Ford 1.8 diesel, новий."
    assert enriched.detail_evidence is not None
    assert enriched.detail_evidence["status"] == "SUCCESS_WITH_CONFLICTS"
    assert enriched.detail_evidence["content_sha256"] == digest
    assert enriched.detail_evidence["schema_version"] == (
        PROM_PRODUCT_DETAIL_SCHEMA_VERSION
    )
    assert enriched.detail_evidence["conflicts"]["sku"] == {
        "listing": "1086282",
        "detail": "FORD-1086282",
    }
    assert enriched.detail_evidence["field_sources"]["mpn"] == (
        "$.result.product.identifiers.mpn"
    )
    assert enriched.detail_evidence["field_sources"]["condition"] == (
        "$.result.product.attributes[*].values[*].value"
    )
    assert enriched.detail_evidence["motors"]["compatible_oe_numbers"] == [
        "1086282",
        "89FF8575AA",
    ]
    assert enriched.detail_evidence["motors"]["compatible_vehicles"][0][
        "manufacturer"
    ] == "Ford"
    owner_evidence = enriched.detail_evidence["owner_oe_evidence"][0]
    assert owner_evidence["publisher"] == "kemp_owned_store"
    assert owner_evidence["source_version"] == PROM_PRODUCT_DETAIL_SCHEMA_VERSION
    assert owner_evidence["captured_at"]
    assert owner_evidence["card_title"] == enriched.name
    assert "characteristics" in owner_evidence["card_spec"]


def test_detail_identity_mismatch_is_explicit_and_merges_nothing() -> None:
    listing = _product(101, 501, sku="1086282")
    html = _product_card_html(
        _raw_product(
            999,
            501,
            sku="1086282",
            attributes=[
                {"name": "Стан", "values": [{"value": "Новий"}]}
            ],
        )
    )
    client = _DocumentClient(
        HttpDocument(
            text=html,
            content_sha256=hashlib.sha256(html.encode()).hexdigest(),
            request_url=listing.url or "",
            status_code=200,
        )
    )

    enriched = PromGateway()._fetch_candidate_detail(client, listing, lang="ua")

    assert enriched.condition is None
    assert enriched.detail_evidence is not None
    assert enriched.detail_evidence["status"] == "FAILED"
    assert enriched.detail_evidence["error_code"] == "PRODUCT_IDENTITY_MISMATCH"


def test_missing_product_card_record_is_not_an_empty_market() -> None:
    listing = _product(101, 501, sku="1086282")
    html = '<script>window.ApolloCacheState = {"_FAST_CACHE": {}};</script>'
    client = _DocumentClient(
        HttpDocument(
            text=html,
            content_sha256=hashlib.sha256(html.encode()).hexdigest(),
            request_url=listing.url or "",
            status_code=200,
        )
    )

    enriched = PromGateway()._fetch_candidate_detail(client, listing, lang="ua")

    assert enriched.id == listing.id
    assert enriched.detail_evidence is not None
    assert enriched.detail_evidence["status"] == "FAILED"
    assert enriched.detail_evidence["error_code"] == "PARSER_SCHEMA_CHANGED"


def test_search_detail_shortlist_is_bounded_unique_and_excludes_owned(
    monkeypatch,
) -> None:
    products = [
        _product(1, 900, sku="1086282"),
        _product(2, 901, sku="OTHER", name="Ford 1086282 thermostat"),
        _product(3, 901, sku="1086282"),
        _product(4, 902, sku="NOPE", name="unrelated"),
    ]
    gateway = PromGateway(ScrapeConfig(max_detail_cards=2))
    fetched: list[int] = []

    def _fake_fetch(_client, product: Product, *, lang: str) -> Product:
        assert lang == "ua"
        fetched.append(product.id or 0)
        return replace(
            product,
            detail_evidence={"status": "SUCCESS", "selected": True},
        )

    monkeypatch.setattr(gateway, "_fetch_candidate_detail", _fake_fetch)
    enriched = gateway._enrich_search_shortlist(
        object(),
        products,
        query="1086282",
        lang="ua",
        excluded_seller_ids=frozenset({"900"}),
    )

    # Product 3 outranks product 2 for seller 901; seller 902 consumes the
    # second and final external-seller detail slot.
    assert fetched == [3, 4]
    assert enriched[0].detail_evidence == {
        "schema_version": PROM_PRODUCT_DETAIL_SCHEMA_VERSION,
        "status": "NOT_SELECTED",
        "selected": False,
        "source_url": products[0].url,
        "content_sha256": None,
        "product_id": 1,
        "seller_id": "900",
        "error_code": "OWNED_SELLER",
        "conflicts": {},
        "field_sources": {},
    }
    assert enriched[1].detail_evidence is not None
    assert enriched[1].detail_evidence["status"] == "NOT_SELECTED"
    assert enriched[1].detail_evidence["error_code"] == "DETAIL_BUDGET"
    assert enriched[2].detail_evidence == {"status": "SUCCESS", "selected": True}
    assert enriched[3].detail_evidence == {"status": "SUCCESS", "selected": True}


def test_automatic_detail_gate_requires_exact_conflict_free_binding() -> None:
    product = {
        "id": 42,
        "seller_id": "501",
        "url": "https://prom.ua/ua/p42-part.html",
        "detail_evidence": {
            "schema_version": PROM_PRODUCT_DETAIL_SCHEMA_VERSION,
            "status": "SUCCESS",
            "selected": True,
            "content_sha256": "a" * 64,
            "source_url": "https://prom.ua/ua/p42-part.html",
            "product_id": 42,
            "seller_id": "501",
        },
    }
    retained_raw_evidence = (
        {
            "request_kind": "product_page",
            "prepared_url": "https://prom.ua/ua/p42-part.html",
            "raw_content_sha256": "a" * 64,
        },
    )

    assert (
        _detail_evidence_automatic_safe(
            product,
            seller_id="501",
            retained_raw_evidence=retained_raw_evidence,
        )
        is True
    )
    identity_conflict = {
        **product,
        "detail_evidence": {
            **product["detail_evidence"],
            "conflicts": {
                "mpn": {"listing": "A", "detail": "B"},
            },
        },
    }
    assert (
        _detail_evidence_automatic_safe(
            identity_conflict,
            seller_id="501",
            retained_raw_evidence=retained_raw_evidence,
        )
        is False
    )
    for field, bad_value in (
        ("schema_version", "prom-product-detail-evidence-v0"),
        ("status", "SUCCESS_WITH_CONFLICTS"),
        ("selected", False),
        ("content_sha256", "not-a-hash"),
        ("source_url", "https://prom.ua/ua/p43-other.html"),
        ("product_id", 43),
        ("seller_id", "502"),
    ):
        changed = {
            **product,
            "detail_evidence": {
                **product["detail_evidence"],
                field: bad_value,
            },
        }
        assert (
            _detail_evidence_automatic_safe(
                changed,
                seller_id="501",
                retained_raw_evidence=retained_raw_evidence,
            )
            is False
        )

    assert _detail_evidence_automatic_safe(product, seller_id="501") is False
    for trace_override in (
        {"request_kind": "search_page"},
        {"prepared_url": "https://prom.ua/ua/p43-other.html"},
        {"raw_content_sha256": "b" * 64},
    ):
        mismatched_trace = ({**retained_raw_evidence[0], **trace_override},)
        assert (
            _detail_evidence_automatic_safe(
                product,
                seller_id="501",
                retained_raw_evidence=mismatched_trace,
            )
            is False
        )


def test_detail_trace_manifest_must_retain_its_canonical_hash() -> None:
    evidence = [
        {
            "request_kind": "product_page",
            "prepared_url": "https://prom.ua/ua/p42-part.html",
            "raw_content_sha256": "a" * 64,
        }
    ]
    capture = SimpleNamespace(
        payload={
            "raw_evidence": evidence,
            "raw_manifest_sha256": canonical_sha256(evidence),
        }
    )

    assert _verified_capture_raw_evidence(capture) == tuple(evidence)
    capture.payload["raw_manifest_sha256"] = "b" * 64
    assert _verified_capture_raw_evidence(capture) == ()


def test_an_unbounded_detail_budget_fetches_every_external_row(monkeypatch) -> None:
    """The owner's decision on 2026-08-06: parse as many cards as possible.

    The pre-fetch ranking in ``_detail_priority`` is a guess made from title
    and SKU text. Capping the budget made that guess final; without a cap the
    deterministic and semantic gates choose among every row instead.
    """

    products = [
        _product(1, 900, sku="1086282"),
        _product(2, 901, sku="OTHER", name="Ford 1086282 thermostat"),
        _product(3, 901, sku="1086282"),
        _product(4, 902, sku="NOPE", name="unrelated"),
    ]
    gateway = PromGateway(ScrapeConfig(max_detail_cards=0))
    fetched: list[int] = []

    def _fake_fetch(_client, item: Product, *, lang: str) -> Product:
        fetched.append(item.id or 0)
        return replace(item, detail_evidence={"status": "SUCCESS", "selected": True})

    monkeypatch.setattr(gateway, "_fetch_candidate_detail", _fake_fetch)
    enriched = gateway._enrich_search_shortlist(
        object(),
        products,
        query="1086282",
        lang="ua",
        excluded_seller_ids=frozenset({"900"}),
    )

    # Owned seller 900 is still excluded, and a seller listing the part twice
    # now contributes both rows rather than only its best-ranked one.
    assert sorted(fetched) == [2, 3, 4]
    assert enriched[0].detail_evidence["error_code"] == "OWNED_SELLER"


def test_the_detail_budget_is_not_the_comparison_seller_cap() -> None:
    """Two questions, two knobs: what to fetch, and what may set a price."""

    config = ScrapeConfig(max_sellers=10, max_detail_cards=30)

    assert config.max_sellers == 10
    assert config.max_detail_cards == 30
