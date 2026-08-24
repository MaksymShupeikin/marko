import json

from marko.services.parser_models import Product


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

