"""Shared builders for the test suite."""
import json

from marko.services.matching import ComparisonParams, PriceComparison, build_comparison
from marko.services.parser_models import Product, SeedInfo


def raw_product(**overrides) -> dict:
    """A raw Apollo product object with sensible defaults, overridable per test."""
    base = {
        "id": 1,
        "name": "Амортизатор задній правий",
        "sku": None,
        "price": "1000",
        "priceCurrency": "грн",
        "manufacturerInfo": {"name": "Bosch"},
        "company": {"id": 10, "name": "Продавець А", "slug": "prodavec-a"},
        "presence": {"isAvailable": True, "presence": "available"},
        "urlText": "amortyzator",
    }
    base.update(overrides)
    return base


def product(**overrides) -> Product:
    return Product.from_raw(raw_product(**overrides), "ua")


def html_with_state(state: dict) -> str:
    return f"<html><script>window.ApolloCacheState = {json.dumps(state)};</script></html>"


def params(query="q", threshold=0.55, max_sellers=10) -> ComparisonParams:
    return ComparisonParams(query=query, threshold=threshold, max_sellers=max_sellers)


def seed_info(**overrides) -> SeedInfo:
    return SeedInfo(product=product(**overrides), seller_count=None, min_price=None, max_price=None)


def comparison_with_prices(prices, seed_price="1000") -> PriceComparison:
    seed = seed_info(id=1, name="Амортизатор задній правий", price=seed_price, company={"id": 1, "name": "A"})
    candidates = [
        product(id=i + 2, name="Амортизатор задній правий", price=str(pr), company={"id": i + 2, "name": f"S{i}"})
        for i, pr in enumerate(prices)
    ]
    return build_comparison(seed, candidates, params())
