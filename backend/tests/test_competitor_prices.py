import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import marko.services.competitor_prices as competitor_prices_module
from factories import product
from marko.services.competitor_prices import (
    CompetitorPriceCache,
    CompetitorPriceReport,
    MarketOffer,
    PartSearchQuery,
    PromPriceSource,
    SourceResult,
    VerifiedPageSnapshot,
    _cache_key,
    _cheapest_by_key,
    _is_own_prom_product,
    _match_score,
    _product_matches,
    _search_terms,
    _query_from_listing,
    _same_marketplace_product,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.ttls[key] = ex


def part_query(listing_id: str = "p1") -> PartSearchQuery:
    return PartSearchQuery(
        listing_id=listing_id,
        oem_numbers=("0451103316",),
        brand="Bosch",
        name="Фільтр масляний Bosch",
        source_url=f"https://prom.ua/ua/p{listing_id.removeprefix('p')}-filtr.html",
    )


def test_product_matches_by_normalized_oem():
    query = PartSearchQuery(
        listing_id="p1",
        oem_numbers=("7700308222",),
        brand="Renault",
        name="Радіатор Renault Kangoo",
        source_url="https://example.test/product",
    )

    assert _match_score(query, "Радіатор охолодження 77 00 308 222 Kangoo") == 0.9
    # Номера немає, але назва та сама — це конкурент, лише з меншою впевненістю.
    assert _match_score(query, "Радіатор охолодження Renault Kangoo") == 0.7
    assert not _product_matches(query, "Фільтр масляний Renault Kangoo")
    # Чужий бренд на тому ж номері — інша деталь.
    assert not _product_matches(query, "Радіатор 7700308222", brand="KEMP")
    assert _product_matches(query, "Радіатор 7700308222", brand="Renault")


def test_name_search_finds_competitors_when_the_number_is_an_own_article():
    """Реальний випадок: по «8200090327KEMP» на Prom лише власні дилери."""
    query = PartSearchQuery(
        listing_id="p1",
        oem_numbers=("8200090327KEMP",),
        brand="KEMP",
        name="Кнопка склопідіймача Renault (Рено) Kango Clio 97-> (6 pin)",
        source_url="https://prom.ua/ua/p1-knopka.html",
    )

    assert "8200090327KEMP" in _search_terms(query)
    # Назва йде окремим запитом і без бренду — інакше знову свої ж товари.
    name_term = _search_terms(query)[-1]
    assert "kemp" not in name_term
    assert "склопідіймача" in name_term

    # ПРОФПАРТС: та сама кнопка, свого артикула KEMP у назві немає.
    assert _match_score(query, "Кнопка склопідіймача Рено Kango Clio 97-> (5 pin)") == 0.7
    # Кнопка багажника — інша деталь, хоч і схожі слова.
    assert not _product_matches(query, "Кнопка багажника Рено, Renault Megane, Clio, Kango")
    # Конкурент продає ту саму кнопку під своєю маркою — бренд не привід
    # викидати збіг за назвою, інакше пошук за назвою нічого не додає.
    assert _match_score(
        query,
        "Кнопка склопідіймача Рено Kango Clio 97-> (5 pin)",
        brand="ERA",
    ) == 0.7


def test_product_matches_rejects_opposite_side_and_short_numbers():
    query = PartSearchQuery(
        listing_id="p1",
        oem_numbers=("1234",),
        brand=None,
        name="Фара передня ліва Renault Kangoo",
        source_url="https://example.test/product",
    )

    # Номер із 4 символів трапляється в чужих назвах — працює збіг за словами.
    assert not _product_matches(query, "Насос паливний 1234567 Ford Transit")
    assert _product_matches(query, "Фара передня ліва Renault Kangoo 00-")
    assert not _product_matches(query, "Фара передня права Renault Kangoo 00-")


def test_short_numeric_oem_needs_a_matching_topic():
    """Справжні випадки з бази: 7 цифр збігаються з чужим внутрішнім артикулом."""
    query = PartSearchQuery(
        listing_id="p1",
        oem_numbers=("1300115",),
        brand=None,
        name="Радіатор Оpel Astra F 1,4-1,6 АКП 525*325",
        source_url="https://prom.ua/ua/p1-radiator.html",
    )

    assert not _product_matches(query, "Пакети для сміття 40шт 60л «МІЦНІ» 1300115")
    assert not _product_matches(query, "Шафа периферійна адресна ВРА-03", "13-00115")
    assert not _product_matches(query, "Ключ Claas роз'єднувач", "1300115.0В")
    # Тема збігається — номер підтверджує, а не вигадує збіг.
    assert _product_matches(query, "Радіатор охолодження Opel Astra F 1991-2002 1300115")


def test_long_or_lettered_oem_matches_without_a_topic_check():
    query = PartSearchQuery(
        listing_id="p1",
        oem_numbers=("93740944",),
        brand=None,
        name="Бігун трамблера Daewoo Matiz",
        source_url="https://prom.ua/ua/p1-bigun.html",
    )

    # 8 цифр — назва може бути хоч транслітом, хоч рекламою.
    assert _product_matches(query, "Бігунок Матіз оригінал", "93740944")
    assert _product_matches(query, "CW 93740944 При замовленні до 17-00 відправимо")


def test_stats_ignore_weak_matches():
    strong = MarketOffer(
        "prom",
        "A",
        Decimal("300"),
        "UAH",
        "https://prom.ua/a",
        confidence=0.9,
        verified=True,
    )
    weak = MarketOffer(
        "prom", "B", Decimal("50"), "UAH", "https://prom.ua/b", confidence=0.65
    )
    source = SourceResult("prom", "Prom.ua", "ok", (strong, weak))

    assert source.min_price == Decimal("300")
    # Неперевірена ціна не стає «ринком» навіть якщо вона єдина.
    assert SourceResult("prom", "Prom.ua", "ok", (weak,)).min_price is None


def test_hard_gates_drop_used_non_fixed_zero_and_unavailable_offers():
    def offer(title: str, price: str = "100", **kwargs) -> MarketOffer:
        return MarketOffer(
            "prom",
            title,
            Decimal(price),
            "UAH",
            f"https://prom.ua/{title}",
            **kwargs,
        )

    valid = offer("Новий бампер VW T4")
    kept, rejected = competitor_prices_module._hard_gate_offers(
        (
            valid,
            offer("Кут бампера VW T4 б/у"),
            offer("Бампер VW T4", seller="Авторозбірка Київ"),
            offer("Бампер — ціна за запитом"),
            offer("Бампер VW T4", "0"),
            offer("Бампер VW T4", availability="Немає в наявності"),
        )
    )

    # Search may lie with zero; it is retained only long enough to reopen the
    # product page and replace it with the fresh authoritative price.
    assert kept == (valid, offer("Бампер VW T4", "0"))
    assert rejected == 4


async def test_prom_source_scans_every_configured_page(monkeypatch):
    requested: list[dict] = []

    class FakeHttpClient:
        def __init__(self, _config) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            pass

        async def get_html(self, _url: str, params: dict | None = None) -> str:
            requested.append(params or {})
            return f"page-{(params or {}).get('page', 1)}"

    def fake_parse_search(html: str, _lang: str):
        number = int(html.removeprefix("page-"))
        # Справжній Product, а не двійник: інакше тест не бачить, які саме
        # поля ціни читає джерело.
        return SimpleNamespace(
            products=[
                product(
                    id=f"90{number}",
                    name=f"Фільтр масляний Bosch 0451103316 №{number}",
                    sku="0451103316",
                    price=str(100 * number),
                    urlText="filtr",
                    company={
                        "id": number,
                        "name": f"seller-{number}",
                        "slug": f"seller-{number}",
                    },
                )
            ]
        )

    monkeypatch.setattr(competitor_prices_module, "AsyncHttpClient", FakeHttpClient)
    monkeypatch.setattr(competitor_prices_module, "parse_search", fake_parse_search)

    result = await PromPriceSource().search(part_query())

    pages = competitor_prices_module._source_config().max_search_pages
    assert {params.get("page") for params in requested} == {
        None,
        *range(2, pages + 1),
    }
    assert {offer.seller for offer in result.offers} == {
        f"seller-{number}" for number in range(1, pages + 1)
    }


async def test_avtopro_keeps_analogues_out_of_the_stats(monkeypatch):
    """Стрічка деталі — це і аналоги: показуємо їх, але ціну задає своя деталь."""
    feed = [
        SimpleNamespace(
            maker=maker, code=code, part_uri=f"/part-{code}/", description="Кнопка",
            city="Київ", availability=None, price=price, currency="UAH",
            warehouse_id=f"wh-{maker}", boosted=False,
        )
        for maker, code, price in (
            ("KEMP", "8200090327", 300.0),
            ("ERA", "AB-777", 180.0),      # аналог іншого виробника
            ("VERNET", "CD-999", 420.0),   # ще один аналог
        )
    ]
    monkeypatch.setattr(
        competitor_prices_module,
        "AvtoproGateway",
        lambda _config: SimpleNamespace(
            offers=lambda *_a, **_kw: SimpleNamespace(
                suggestion=SimpleNamespace(title="Кнопка", part_uri="/part-x/"),
                offers=feed,
            )
        ),
    )

    result = await competitor_prices_module.AvtoproPriceSource().search(
        PartSearchQuery(
            listing_id="p1", oem_numbers=("8200090327",), brand="KEMP",
            name="Кнопка склопідіймача", source_url="https://prom.ua/ua/p1-k.html",
        )
    )

    assert [str(offer.price) for offer in result.offers] == ["180.00", "300.00", "420.00"]
    assert [offer.is_analog for offer in result.offers] == [True, False, True]
    # Навіть точний номер не задає ціну до перевірки сторінки.
    assert result.min_price is None


async def test_google_source_prices_from_snippet_and_page(monkeypatch):
    """Ціна зі сніпета — без GET; без ціни в сніпеті — JSON-LD зі сторінки."""
    serp = {
        "organic": [
            {
                "title": "Фільтр масляний Bosch 0451103316",
                "link": "https://to24.com.ua/buy/bosch-0451103316",
                "snippet": "Купити за 204 грн. Доставка по Україні.",
            },
            {
                "title": "Фільтр масляний 0 451 103 316 Bosch",
                "link": "https://partsplus.com.ua/detail/0451103316/bosch/",
                "snippet": "Оригінальні запчастини у наявності.",
            },
            {   # prom.ua вже покрито власним джерелом
                "title": "Фільтр масляний Bosch 0451103316",
                "link": "https://prom.ua/p123-filtr.html",
                "snippet": "Ціна 150 грн",
            },
            {   # Exist.ua також має окремий видимий source
                "title": "Фільтр масляний Bosch 0451103316",
                "link": "https://exist.ua/uk/bosch-brand/filter-0451103316/",
                "snippet": "Ціна 190 грн",
            },
            {   # зовсім не наша деталь
                "title": "Куртка зимова чоловіча",
                "link": "https://shop.example/kurtka",
                "snippet": "1200 грн",
            },
        ]
    }
    page_html = (
        '<script type="application/ld+json">'
        '{"@type": "Product", "offers": {"@type": "Offer", "price": "193",'
        ' "priceCurrency": "UAH"}}'
        "</script>"
    )
    fetched_pages: list[str] = []

    class FakeResponse:
        def __init__(self, payload=None, text=""):
            self.status_code = 200
            self._payload = payload
            self.text = text

        def json(self):
            return self._payload

        def raise_for_status(self):
            pass

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            pass

        async def post(self, _url, json=None, headers=None):
            return FakeResponse(payload=serp)

        async def get(self, url):
            fetched_pages.append(url)
            return FakeResponse(text=page_html)

    monkeypatch.setattr(
        competitor_prices_module, "httpx", SimpleNamespace(AsyncClient=FakeAsyncClient)
    )
    monkeypatch.setattr(
        competitor_prices_module,
        "get_settings",
        lambda: SimpleNamespace(serper_api_key="test-key"),
    )

    result = await competitor_prices_module.GooglePriceSource().search(part_query())

    assert result.status == "ok"
    assert {(offer.seller, str(offer.price)) for offer in result.offers} == {
        ("to24.com.ua", "204.00"),
        ("partsplus.com.ua", "193.00"),
    }
    # Сторінку качали лише для кандидата без ціни у сніпеті.
    assert fetched_pages == ["https://partsplus.com.ua/detail/0451103316/bosch/"]


async def test_google_source_is_skipped_without_api_key(monkeypatch):
    monkeypatch.setattr(
        competitor_prices_module,
        "get_settings",
        lambda: SimpleNamespace(serper_api_key=""),
    )
    result = await competitor_prices_module.GooglePriceSource().search(part_query())
    assert result.status == "skipped"
    assert result.offers == ()


async def test_exist_source_uses_free_plan_query_and_hard_domain_filter(monkeypatch):
    queries: list[str] = []
    payload = {
        "organic": [
            {
                "title": "Bosch oil filter 0451103316",
                "link": "https://exist.ua/uk/bosch-brand/filter-0451103316/",
                "snippet": "Ціна 200 грн, у наявності",
            },
            {
                "title": "Bosch oil filter 0451103316",
                "link": "https://other.test/filter-0451103316/",
                "snippet": "Ціна 100 грн",
            },
        ]
    }

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return payload

        def raise_for_status(self):
            return None

    class Client:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def post(self, _url, json, headers):
            queries.append(json["q"])
            return Response()

    monkeypatch.setattr(
        competitor_prices_module, "httpx", SimpleNamespace(AsyncClient=Client)
    )
    monkeypatch.setattr(
        competitor_prices_module,
        "get_settings",
        lambda: SimpleNamespace(serper_api_key="test-key"),
    )

    result = await competitor_prices_module.ExistPriceSource().search(part_query())

    assert queries == ["exist.ua Bosch 0451103316"]
    assert result.label == "Exist.ua"
    assert [offer.url for offer in result.offers] == [
        "https://exist.ua/uk/bosch-brand/filter-0451103316/"
    ]


async def test_foreign_offer_is_converted_by_official_nbu_rate(monkeypatch):
    uah = [
        MarketOffer(
            "prom", "A", Decimal("200"), "UAH", "https://prom.ua/a", verified=True
        ),
        MarketOffer(
            "prom", "B", Decimal("240"), "UAH", "https://prom.ua/b", verified=True
        ),
    ]
    usd = MarketOffer("avtopro", "C", Decimal("50"), "USD", "https://avto.pro/c")

    class Rates:
        async def rates_for(self, currencies):
            from marko.services.exchange_rates import NbuRate

            assert currencies == {"USD"}
            return {"USD": NbuRate("USD", Decimal("41.25"), "29.08.2026")}

    monkeypatch.setattr(competitor_prices_module, "_nbu_rates", Rates())
    sources = await competitor_prices_module._normalize_currencies(
        (
            SourceResult("prom", "Prom.ua", "ok", tuple(uah)),
            SourceResult("avtopro", "Avto.pro", "ok", (usd,)),
        ),
        lambda *_: None,
    )

    assert sources[0].min_price == Decimal("200")
    converted = sources[1].offers[0]
    assert converted.price == Decimal("2062.50")
    assert converted.currency == "UAH"
    assert converted.original_price == Decimal("50")
    assert converted.original_currency == "USD"
    assert converted.exchange_rate == Decimal("41.25")
    assert converted.exchange_rate_date == "29.08.2026"


async def test_foreign_offers_fail_closed_without_current_nbu_rate(monkeypatch):
    uah = MarketOffer("prom", "A", Decimal("200"), "UAH", "https://prom.ua/a")
    usd = [
        MarketOffer("avtopro", "B", Decimal("50"), "USD", "https://avto.pro/b"),
        MarketOffer("avtopro", "C", Decimal("60"), "USD", "https://avto.pro/c"),
    ]

    class NoRates:
        async def rates_for(self, currencies):
            return {}

    monkeypatch.setattr(competitor_prices_module, "_nbu_rates", NoRates())
    sources = await competitor_prices_module._normalize_currencies(
        (
            SourceResult("prom", "Prom.ua", "ok", (uah,)),
            SourceResult("avtopro", "Avto.pro", "ok", tuple(usd)),
        ),
        lambda *_: None,
    )

    assert [offer.price for offer in sources[0].offers] == [Decimal("200")]
    assert sources[0].offers[0].original_currency == "UAH"
    assert sources[1].offers == ()
    assert sources[1].status == "empty"


def test_report_stats_use_all_sources_and_cache_flag():
    query = PartSearchQuery(
        listing_id="p1",
        oem_numbers=("A1",),
        brand=None,
        name="Part",
        source_url="https://example.test/product",
    )
    report = CompetitorPriceReport(
        query=query,
        sources=(
            SourceResult(
                source="prom",
                label="Prom.ua",
                status="ok",
                offers=(
                    MarketOffer(
                        "prom",
                        "A",
                        Decimal("100"),
                        "UAH",
                        "https://prom.ua/a",
                        verified=True,
                    ),
                    MarketOffer(
                        "prom",
                        "B",
                        Decimal("300"),
                        "UAH",
                        "https://prom.ua/b",
                        verified=True,
                    ),
                ),
            ),
            SourceResult(source="avtopro", label="Avto.pro", status="empty"),
        ),
        observed_at=datetime.fromtimestamp(0, UTC),
    )

    payload = report.as_json()

    assert payload["stats"]["offers_total"] == 2
    assert payload["stats"]["eligible_offers_total"] == 2
    assert payload["stats"]["sources_total"] == 2
    assert payload["stats"]["min_price"] == "100"
    assert payload["stats"]["median_price"] == "200.00"
    assert payload["stats"]["max_price"] == "300"
    assert payload["stats"]["recommended_price_from"] == "93"
    assert payload["stats"]["recommended_price"] == "94"
    assert payload["stats"]["recommended_price_to"] == "95"
    assert payload["stats"]["pricing_status"] == "reliable"


def test_recommendation_contract_for_3200_uah():
    offers = tuple(
        MarketOffer(
            "prom", str(price), Decimal(price), "UAH", f"https://prom.ua/{price}",
            verified=True,
        )
        for price in ("3200", "3400")
    )
    report = CompetitorPriceReport(
        query=part_query(),
        sources=(SourceResult("prom", "Prom.ua", "ok", offers),),
        observed_at=datetime.fromtimestamp(0, UTC),
    )

    stats = report.as_json()["stats"]
    assert stats["recommended_price_from"] == "2976"
    assert stats["recommended_price"] == "3008"
    assert stats["recommended_price_to"] == "3040"
    assert stats["recommended_discount_percent"] == 6
    assert stats["slider_discount_min_percent"] == 1
    assert stats["slider_discount_max_percent"] == 30


def test_report_refuses_recommendation_from_one_verified_price():
    report = CompetitorPriceReport(
        query=part_query(),
        sources=(
            SourceResult(
                "prom",
                "Prom.ua",
                "ok",
                (
                    MarketOffer(
                        "prom",
                        "A",
                        Decimal("2082"),
                        "UAH",
                        "https://prom.ua/a",
                        verified=True,
                    ),
                ),
            ),
        ),
        observed_at=datetime.fromtimestamp(0, UTC),
    )

    stats = report.as_json()["stats"]
    assert stats["eligible_offers_total"] == 1
    assert stats["min_price"] == "2082"
    assert stats["recommended_price"] is None


def test_cheapest_by_key_keeps_lowest_offer_per_seller():
    offers = [
        MarketOffer("prom", "A", Decimal("300"), "UAH", "https://prom.ua/a", seller="seller"),
        MarketOffer("prom", "B", Decimal("200"), "UAH", "https://prom.ua/b", seller="seller"),
        MarketOffer("prom", "C", Decimal("250"), "UAH", "https://prom.ua/c", seller="other"),
    ]

    unique = _cheapest_by_key(offers, key=lambda offer: offer.seller or offer.url)

    assert [(offer.title, offer.price) for offer in unique] == [
        ("B", Decimal("200")),
        ("C", Decimal("250")),
    ]


def test_own_prom_store_offer_is_excluded_by_seller_id():
    query = PartSearchQuery(
        listing_id="p1",
        oem_numbers=("0451103316",),
        brand="Bosch",
        name="Фільтр масляний Bosch",
        source_url="https://prom.ua/ua/p123-filtr.html",
        owner_seller_ids=("2847093", "2231191"),
        owner_seller_slugs=("kemp", "motor-avto"),
    )

    assert _is_own_prom_product(
        query,
        SimpleNamespace(
            seller_id=2847093,
            seller_slug="kemp",
            url="https://prom.ua/ua/p999-inshyi-filtr.html",
        ),
    )
    assert not _is_own_prom_product(
        query,
        SimpleNamespace(
            seller_id=111,
            seller_slug="competitor",
            url="https://prom.ua/ua/p999-inshyi-filtr.html",
        ),
    )

    assert _is_own_prom_product(
        query,
        SimpleNamespace(
            seller_id=2231191,
            seller_slug="motor-avto",
            url="https://prom.ua/ua/p888-inshyi-filtr.html",
        ),
    )


def test_own_prom_product_is_excluded_when_url_language_or_host_differs():
    assert _same_marketplace_product(
        "https://kemp-cs2847093.prom.ua/p123-filtr.html?source=export",
        "https://www.prom.ua/ua/p123-filtr.html",
    )


def test_query_contains_all_owned_prom_stores():
    listing = SimpleNamespace(
        id="listing-1",
        sku="0451103316",
        brand="Bosch",
        name="Фільтр масляний Bosch",
        url="https://prom.ua/ua/p123-filtr.html",
        raw_data={"seller_id": 2847093, "seller_slug": "kemp"},
    )
    owned_stores = [
        SimpleNamespace(
            marketplace="prom",
            external_id="2231191",
            name="motor-avto",
        ),
        SimpleNamespace(
            marketplace="prom",
            external_id="2847093",
            name="kemp",
        ),
        SimpleNamespace(
            marketplace="olx",
            external_id="olx-shop",
            name="olx-shop",
        ),
    ]

    query = _query_from_listing(listing, owned_stores)

    assert query.owner_seller_ids == ("2231191", "2847093")
    assert query.owner_seller_slugs == ("kemp", "motor-avto")


def test_manual_search_query_excludes_owned_prom_stores():
    owned_stores = [
        SimpleNamespace(marketplace="prom", external_id="2847093", name="kemp"),
        SimpleNamespace(marketplace="olx", external_id="olx-shop", name="olx-shop"),
    ]

    query = competitor_prices_module.manual_search_query(
        "0451103316", "Bosch", owned_stores=owned_stores
    )

    assert query.owner_seller_ids == ("2847093",)
    assert query.owner_seller_slugs == ("kemp",)
    own_product = SimpleNamespace(
        seller_id=2847093, seller_slug="kemp", url="https://prom.ua/ua/p1-a.html"
    )
    assert _is_own_prom_product(query, own_product)


async def test_redis_cache_keeps_multiple_products_independently():
    redis = FakeRedis()
    cache = CompetitorPriceCache("redis://unused/2", client=redis)
    first_key = _cache_key(part_query("p1"))
    second_key = _cache_key(part_query("p2"))

    await cache.set(first_key, {"query": {"listing_id": "p1"}}, 3600)
    await cache.set(second_key, {"query": {"listing_id": "p2"}}, 7200)

    assert first_key != second_key
    assert (await cache.get(first_key))["query"]["listing_id"] == "p1"
    assert (await cache.get(second_key))["query"]["listing_id"] == "p2"
    assert (await cache.get(first_key))["cached"] is True
    assert redis.ttls == {first_key: 3600, second_key: 7200}


async def test_redis_cache_treats_invalid_payload_as_miss():
    redis = FakeRedis()
    redis.values["broken"] = "not-json"
    cache = CompetitorPriceCache("redis://unused/2", client=redis)

    assert await cache.get("broken") is None


async def test_price_service_caches_each_product_and_refreshes(monkeypatch):
    redis = FakeRedis()
    cache = CompetitorPriceCache("redis://unused/2", client=redis)
    collect_calls: list[str] = []

    async def fake_get_listing(_session, _workspace_id, listing_id):
        return SimpleNamespace(
            id=listing_id,
            sku="0451103316",
            brand="Bosch",
            name=f"Фільтр {listing_id}",
            url=f"https://prom.ua/ua/p{str(listing_id).removeprefix('p')}-filtr.html",
            raw_data={"oem_numbers": ["0451103316"]},
        )

    async def fake_exclusions(_session, _workspace_id):
        return ()

    async def fake_collect(query, _on_event=None):
        collect_calls.append(query.listing_id)
        return CompetitorPriceReport(
            query=query,
            sources=(SourceResult("prom", "Prom.ua", "empty"),),
            observed_at=datetime.fromtimestamp(len(collect_calls), UTC),
        )

    monkeypatch.setattr(competitor_prices_module, "_cache", cache)
    monkeypatch.setattr(
        competitor_prices_module,
        "get_workspace_listing",
        fake_get_listing,
    )
    monkeypatch.setattr(
        competitor_prices_module,
        "load_prom_seller_exclusions",
        fake_exclusions,
    )
    monkeypatch.setattr(competitor_prices_module, "_collect", fake_collect)

    first = await competitor_prices_module.competitor_prices_for_listing(
        object(), "workspace", "p1"
    )
    cached_first = await competitor_prices_module.competitor_prices_for_listing(
        object(), "workspace", "p1"
    )
    second = await competitor_prices_module.competitor_prices_for_listing(
        object(), "workspace", "p2"
    )
    refreshed_first = await competitor_prices_module.competitor_prices_for_listing(
        object(), "workspace", "p1", refresh=True
    )

    assert first["cached"] is False
    assert cached_first["cached"] is True
    assert second["query"]["listing_id"] == "p2"
    assert refreshed_first["cached"] is False
    assert collect_calls == ["p1", "p2", "p1"]
    assert len(redis.values) == 2


async def test_queued_identical_report_reuses_fresh_cache(monkeypatch):
    """Другий такий самий запит, що чекав на слот, бере готовий звіт із кешу."""
    redis = FakeRedis()
    cache = CompetitorPriceCache("redis://unused/2", client=redis)
    collect_calls: list[str] = []

    async def slow_collect(query, _on_event=None):
        collect_calls.append(query.listing_id)
        await asyncio.sleep(0.01)
        return CompetitorPriceReport(
            query=query,
            sources=(SourceResult("prom", "Prom.ua", "empty"),),
            observed_at=datetime.fromtimestamp(1, UTC),
        )

    monkeypatch.setattr(competitor_prices_module, "_cache", cache)
    monkeypatch.setattr(competitor_prices_module, "_collect", slow_collect)
    monkeypatch.setattr(
        competitor_prices_module, "_collect_slots", asyncio.Semaphore(1)
    )

    query = part_query("p1")
    first, second = await asyncio.gather(
        competitor_prices_module.competitor_prices_for_query(query),
        competitor_prices_module.competitor_prices_for_query(query),
    )

    assert collect_calls == ["p1"]
    assert {first["cached"], second["cached"]} == {False, True}

async def test_llm_filter_drops_foreign_offers_and_regrades_the_rest(monkeypatch):
    """Вердикт моделі вирішує долю пропозиції; джерело без збігів стає порожнім."""
    def offer(title: str, price: str) -> MarketOffer:
        return MarketOffer(
            source="prom", title=title, price=Decimal(price), currency="UAH",
            url=f"https://prom.ua/{price}", seller=title, confidence=0.55,
        )

    prom = SourceResult("prom", "Prom.ua", "ok", (
        offer("Фільтр масляний Bosch 0451103316", "300"),
        offer("Фільтр масляний Mann аналог", "280"),
        offer("Пакети для сміття 1300115", "40"),
    ))
    avtopro = SourceResult("avtopro", "Avto.pro", "ok", (offer("Шафа ВРА-03", "900"),))
    monkeypatch.setattr(competitor_prices_module.llm_filter, "is_enabled", lambda: True)

    verdict_by_title = {
        "Фільтр масляний Bosch 0451103316": "same",
        "Фільтр масляний Mann аналог": "analog",
        "Пакети для сміття 1300115": "no",
        "Шафа ВРА-03": "no",
    }

    async def fake_classify(*, titles, **_kwargs):
        return {index: verdict_by_title[title] for index, title in enumerate(titles)}

    monkeypatch.setattr(competitor_prices_module.llm_filter, "classify", fake_classify)

    stages: list[tuple[str, str]] = []
    def emit(stage, message):
        stages.append((stage, message))

    refined_prom = await competitor_prices_module._refine_source(
        part_query(), prom, emit
    )
    refined_avtopro = await competitor_prices_module._refine_source(
        part_query(), avtopro, emit
    )

    assert [o.title for o in refined_prom.offers] == [
        "Фільтр масляний Bosch 0451103316",
        "Фільтр масляний Mann аналог",
    ]
    assert [o.is_analog for o in refined_prom.offers] == [False, True]
    assert refined_prom.offers[0].confidence == 0.95
    assert refined_avtopro.offers == () and refined_avtopro.status == "empty"
    assert [stage for stage, _ in stages] == ["filter"] * 4


async def test_llm_filter_keeps_everything_when_the_model_is_off(monkeypatch):
    source = SourceResult("prom", "Prom.ua", "ok", (
        MarketOffer(source="prom", title="Фільтр", price=Decimal("10"),
                    currency="UAH", url="https://prom.ua/1"),
    ))
    monkeypatch.setattr(competitor_prices_module.llm_filter, "is_enabled", lambda: False)

    assert await competitor_prices_module._refine_source(
        part_query(), source, lambda *_: None
    ) == source


async def test_llm_filter_failure_is_fail_closed(monkeypatch):
    source = SourceResult(
        "prom",
        "Prom.ua",
        "ok",
        (
            MarketOffer(
                source="prom",
                title="Фільтр",
                price=Decimal("100"),
                currency="UAH",
                url="https://prom.ua/1",
            ),
        ),
    )
    monkeypatch.setattr(competitor_prices_module.llm_filter, "is_enabled", lambda: True)

    async def failed_classify(**_kwargs):
        return {}

    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "classify", failed_classify
    )
    result = await competitor_prices_module._refine_source(
        part_query(), source, lambda *_: None
    )

    assert result.offers == ()
    assert result.status == "empty"


async def test_second_pass_refreshes_and_verifies_exact_and_analog(monkeypatch):
    accepted = MarketOffer(
        "prom",
        "Фільтр Bosch",
        Decimal("300"),
        "UAH",
        "https://prom.ua/accepted",
        confidence=0.95,
    )
    rejected = MarketOffer(
        "google",
        "Фільтр Bosch",
        Decimal("310"),
        "UAH",
        "https://shop.test/rejected",
        confidence=0.95,
    )
    analog = MarketOffer(
        "prom",
        "Фільтр Mann",
        Decimal("250"),
        "UAH",
        "https://prom.ua/analog",
        confidence=0.6,
        is_analog=True,
    )
    sources = (
        SourceResult("prom", "Prom.ua", "ok", (accepted, analog)),
        SourceResult("google", "Google", "ok", (rejected,)),
    )
    monkeypatch.setattr(competitor_prices_module.llm_filter, "is_enabled", lambda: True)

    checked_at = datetime.fromtimestamp(10, UTC)

    def snapshot(offer, price):
        return VerifiedPageSnapshot(
            url=offer.url,
            title=offer.title,
            code=None,
            brand=None,
            price=Decimal(price),
            currency="UAH",
            availability="InStock",
            condition="NewCondition",
            verified_at=checked_at,
            evidence_text="new fixed price in stock",
        )

    async def snapshots(_query, offers):
        assert offers == [accepted, analog, rejected]
        return [snapshot(accepted, "305"), snapshot(analog, "255"), snapshot(rejected, "315")]

    async def verify(**_kwargs):
        return {0: True, 1: True, 2: False}

    monkeypatch.setattr(competitor_prices_module, "_fetch_verified_snapshots", snapshots)
    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_pricing_offers", verify
    )

    result = await competitor_prices_module._verify_pricing_offers(
        part_query(), sources, lambda *_: None
    )
    offers = [offer for source in result for offer in source.offers]

    assert [offer.url for offer in offers] == [accepted.url, analog.url]
    assert offers[0].verified is True and offers[0].price == Decimal("305")
    assert offers[0].condition == "new"
    assert offers[1].is_analog is True and offers[1].verified is True
    assert offers[1].price == Decimal("255")
    assert offers[1].confidence == 0.99


async def test_search_zero_or_absurd_price_is_replaced_by_page_price(monkeypatch):
    offers = [
        MarketOffer("google", "Part", Decimal("0"), "UAH", "https://shop.test/zero"),
        MarketOffer(
            "google", "Part", Decimal("3000000"), "UAH", "https://shop.test/absurd"
        ),
    ]
    checked_at = datetime.fromtimestamp(10, UTC)

    async def snapshots(_query, candidates):
        return [
            VerifiedPageSnapshot(
                url=offer.url,
                title="Фільтр масляний Bosch 0451103316",
                code="0451103316",
                brand="Bosch",
                price=Decimal("200"),
                currency="UAH",
                availability="InStock",
                condition="NewCondition",
                verified_at=checked_at,
                evidence_text="new fixed price 200 in stock",
            )
            for offer in candidates
        ]

    async def accept_all(**kwargs):
        return {index: True for index in range(len(kwargs["candidates"]))}

    monkeypatch.setattr(competitor_prices_module.llm_filter, "is_enabled", lambda: True)
    monkeypatch.setattr(competitor_prices_module, "_fetch_verified_snapshots", snapshots)
    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_pricing_offers", accept_all
    )

    result = await competitor_prices_module._verify_pricing_offers(
        part_query(),
        (SourceResult("google", "Google", "ok", tuple(offers)),),
        lambda *_: None,
    )

    assert [offer.price for offer in result[0].offers] == [
        Decimal("200"),
        Decimal("200"),
    ]
    assert all(offer.price_changed_on_page for offer in result[0].offers)
    assert all(offer.original_price == Decimal("200") for offer in result[0].offers)


def test_exist_primary_product_price_ignores_related_analog_cards():
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"Product","name":"Bosch oil filter","sku":"0451103316",
       "brand":{"@type":"Brand","name":"Bosch"},
       "offers":{"@type":"Offer","price":"200","priceCurrency":"UAH",
                 "availability":"https://schema.org/InStock"}},
      {"@type":"Product","name":"Cheap related analogue","sku":"OTHER-1",
       "offers":{"@type":"Offer","price":"50","priceCurrency":"UAH"}}
    ]}
    </script>
    """
    offer = MarketOffer(
        "exist", "Bosch filter", Decimal("0"), "UAH", "https://exist.ua/product"
    )

    snapshot = competitor_prices_module._snapshot_from_html(part_query(), offer, html)

    assert snapshot is not None
    assert snapshot.price == Decimal("200")
    assert snapshot.code == "0451103316"


def test_ambiguous_structured_prices_are_rejected():
    html = """
    <script type="application/ld+json">
    [{"@type":"Offer","price":"200","priceCurrency":"UAH"},
     {"@type":"Offer","price":"350","priceCurrency":"UAH"}]
    </script>
    """
    offer = MarketOffer(
        "google", "Part", Decimal("200"), "UAH", "https://shop.test/product"
    )

    assert competitor_prices_module._snapshot_from_html(part_query(), offer, html) is None


async def test_persistent_low_verified_price_is_rechecked_and_removed(monkeypatch):
    offers = tuple(
        MarketOffer(
            "prom",
            str(price),
            Decimal(price),
            "UAH",
            f"https://prom.ua/{price}",
            verified=True,
        )
        for price in ("400", "1000", "1100")
    )
    async def unchanged(_query, suspicious):
        assert [offer.price for offer in suspicious] == [Decimal("400")]
        return suspicious

    monkeypatch.setattr(
        competitor_prices_module, "_refresh_anomalous_prices", unchanged
    )
    result, status = await competitor_prices_module._apply_anomaly_gates(
        part_query(),
        (SourceResult("prom", "Prom.ua", "ok", offers),),
        lambda *_: None,
    )

    assert status == "reliable"
    assert [offer.price for offer in result[0].offers] == [
        Decimal("1000"),
        Decimal("1100"),
    ]


async def test_persistent_absurd_high_price_is_rechecked_and_removed(monkeypatch):
    offers = tuple(
        MarketOffer(
            "prom", str(price), Decimal(price), "UAH", f"https://prom.ua/{price}",
            verified=True,
        )
        for price in ("1000", "1100", "3000000")
    )

    async def unchanged(_query, suspicious):
        assert [offer.price for offer in suspicious] == [Decimal("3000000")]
        return suspicious

    monkeypatch.setattr(
        competitor_prices_module, "_refresh_anomalous_prices", unchanged
    )
    result, status = await competitor_prices_module._apply_anomaly_gates(
        part_query(),
        (SourceResult("prom", "Prom.ua", "ok", offers),),
        lambda *_: None,
    )

    assert status == "reliable"
    assert [offer.price for offer in result[0].offers] == [
        Decimal("1000"),
        Decimal("1100"),
    ]


async def test_two_prices_over_2x_become_conflict_after_recheck(monkeypatch):
    offers = tuple(
        MarketOffer(
            "prom", str(price), Decimal(price), "UAH", f"https://prom.ua/{price}",
            verified=True,
        )
        for price in ("1000", "2500")
    )

    async def unchanged(_query, candidates):
        return candidates

    monkeypatch.setattr(
        competitor_prices_module, "_refresh_anomalous_prices", unchanged
    )
    result, status = await competitor_prices_module._apply_anomaly_gates(
        part_query(),
        (SourceResult("prom", "Prom.ua", "ok", offers),),
        lambda *_: None,
    )

    assert status == "conflict"
    assert not any(offer.verified for offer in result[0].offers)
    report = CompetitorPriceReport(
        query=part_query(), sources=result, observed_at=datetime.now(UTC),
        pricing_status=status,
    )
    assert report.as_json()["stats"]["recommended_price"] is None


async def test_verified_analogues_form_a_reliable_market(monkeypatch):
    """Regression: 11 useful Sierra offers must not yield 'one price only'."""
    offers = tuple(
        MarketOffer(
            "avtopro", f"Analog {index}", Decimal(price), "UAH",
            f"https://avto.pro/{index}", confidence=0.99, is_analog=True,
            verified=True, source_offer_id=f"wh-{index}",
        )
        for index, price in enumerate(("750", "805", "862.12", "897.79", "907.50"))
    )

    sources, status = await competitor_prices_module._apply_anomaly_gates(
        part_query(),
        (SourceResult("avtopro", "Avto.pro", "ok", offers),),
        lambda *_: None,
    )
    report = CompetitorPriceReport(
        query=part_query(), sources=sources, observed_at=datetime.now(UTC),
        pricing_status=status,
    )

    stats = report.as_json()["stats"]
    assert status == "reliable"
    assert stats["eligible_offers_total"] == 5
    assert stats["recommended_price"] == "705"


async def test_classify_treats_missing_verdicts_as_no(monkeypatch):
    """Кандидат без вердикту раніше проходив у видачу без перевірки."""
    from marko.services import llm_filter

    monkeypatch.setattr(llm_filter, "is_enabled", lambda: True)

    async def fake_ask(_prompt: str) -> str:
        return '{"verdicts": [{"index": 0, "verdict": "same"}]}'

    monkeypatch.setattr(llm_filter, "_ask_openai", fake_ask)
    verdicts = await llm_filter.classify(
        name="Фільтр", brand=None, oem_numbers=(), titles=["Фільтр", "Тапочки", "Сумка"]
    )
    assert verdicts == {0: "same", 1: "no", 2: "no"}

    async def empty_ask(_prompt: str) -> str:
        return '{"verdicts": []}'

    monkeypatch.setattr(llm_filter, "_ask_openai", empty_ask)
    # Жодного вердикту — це збій моделі, а не «все чуже»: фільтр вимикається.
    assert await llm_filter.classify(
        name="Фільтр", brand=None, oem_numbers=(), titles=["Фільтр"]
    ) == {}


def test_openai_api_key_enables_llm_filter(monkeypatch):
    """Наявність openai_api_key вмикає LLM-фільтр."""
    from marko.core.config import get_settings
    from marko.services import llm_filter

    def settings(model: str = "gpt-5-nano", key: str = ""):
        get_settings.cache_clear()
        monkeypatch.setenv("OPENAI_API_KEY", key)
        monkeypatch.setenv("COMPETITOR_FILTER_MODEL", model)
        return get_settings()

    settings(key="sk-test")
    assert llm_filter.is_enabled()

    settings(key="")
    assert not llm_filter.is_enabled()
    get_settings.cache_clear()


async def test_one_broken_page_does_not_kill_the_whole_prom_source(monkeypatch):
    """Сторінок тепер десяток: збій однієї не має лишати звіт без Prom."""
    class FakeHttpClient:
        def __init__(self, _config) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            pass

        async def get_html(self, _url: str, params: dict | None = None) -> str:
            page = (params or {}).get("page", 1)
            if page == 2:
                raise RuntimeError("мережа впала")
            return f"page-{page}"

    def fake_parse_search(html: str, _lang: str):
        number = int(html.removeprefix("page-"))
        return SimpleNamespace(products=[
            product(
                id=f"90{number}", name="Фільтр масляний Bosch 0451103316",
                sku="0451103316", price=str(100 * number), urlText="filtr",
                company={"id": number, "name": f"seller-{number}", "slug": f"s-{number}"},
            )
        ])

    monkeypatch.setattr(competitor_prices_module, "AsyncHttpClient", FakeHttpClient)
    monkeypatch.setattr(competitor_prices_module, "parse_search", fake_parse_search)

    result = await PromPriceSource().search(part_query())

    pages = competitor_prices_module._source_config().max_search_pages
    assert result.status == "ok"
    assert len(result.offers) == pages - 1  # усі, крім зламаної сторінки
    assert "seller-2" not in {offer.seller for offer in result.offers}
