from marko.parsers.prom.gateway import PromGateway
from marko.services.parser_models import ListingPage

from factories import product


def test_catalog_boundary_does_not_collapse_distinct_products_without_ids(
    monkeypatch,
) -> None:
    products = [
        product(id=None, name="Missing ID A"),
        product(id=None, name="Missing ID B"),
    ]

    def fake_pages(self, client, seller, *, strict=False):
        del self, client, seller, strict
        yield ListingPage(products=products, total=2, lang="ua")

    monkeypatch.setattr(PromGateway, "_iter_pages", fake_pages)

    extracted = list(
        PromGateway().scrape(
            "https://prom.ua/ua/c2847093-kemp.html",
            strict=True,
        )
    )

    assert extracted == products
