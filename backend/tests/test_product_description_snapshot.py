import pytest

from marko.services.prom_product_urls import validate_product_url


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
    assert validate_product_url(url) == expected


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
        validate_product_url(url)
