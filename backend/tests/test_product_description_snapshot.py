from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "capture_prom_product_descriptions.py"
)
SPEC = importlib.util.spec_from_file_location(
    "capture_prom_product_descriptions", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://prom.ua/ua/p2710874304-radiator.html", 2710874304),
        ("https://www.prom.ua/p42-product.html", 42),
    ],
)
def test_validate_product_url_accepts_canonical_https_prom_urls(
    url: str, expected: int
) -> None:
    assert MODULE.validate_product_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://prom.ua/ua/p42-product.html",
        "https://evil.example/ua/p42-product.html",
        "https://prom.ua.evil.example/ua/p42-product.html",
        "https://user:pass@prom.ua/ua/p42-product.html",
        "https://prom.ua:444/ua/p42-product.html",
        "https://prom.ua/ua/search?search_term=42",
        "https://prom.ua/ua/p42-product.html?tracking=1",
    ],
)
def test_validate_product_url_rejects_unsafe_or_non_product_urls(url: str) -> None:
    with pytest.raises(ValueError):
        MODULE.validate_product_url(url)
