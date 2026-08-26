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
        "prom", "A", Decimal("300"), "UAH", "https://prom.ua/a", confidence=0.9
    )
    weak = MarketOffer(
        "prom", "B", Decimal("50"), "UAH", "https://prom.ua/b", confidence=0.65
    )
    source = SourceResult("prom", "Prom.ua", "ok", (strong, weak))

    assert source.min_price == Decimal("300")
    # Немає жодного впевненого збігу — рахуємо за тим, що є.
    assert SourceResult("prom", "Prom.ua", "ok", (weak,)).min_price == Decimal("50")


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
    # Дешевший аналог не має вдавати, що наша деталь коштує 180.
    assert result.min_price == Decimal("300.00")


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


def test_minority_currency_offers_are_dropped():
    uah = [
        MarketOffer("prom", "A", Decimal("200"), "UAH", "https://prom.ua/a"),
        MarketOffer("prom", "B", Decimal("240"), "UAH", "https://prom.ua/b"),
    ]
    usd = MarketOffer("avtopro", "C", Decimal("50"), "USD", "https://avto.pro/c")

    sources = competitor_prices_module._single_currency(
        (
            SourceResult("prom", "Prom.ua", "ok", tuple(uah)),
            SourceResult("avtopro", "Avto.pro", "ok", (usd,)),
        )
    )

    # 50 USD не є мінімумом проти 200 грн — без курсу порівнювати нічим.
    assert sources[0].min_price == Decimal("200")
    assert sources[1].offers == ()
    assert sources[1].status == "empty"


def test_uah_offers_win_even_as_minority():
    """Каталог гривневий: доларова більшість не має перемикати звіт у USD."""
    uah = MarketOffer("prom", "A", Decimal("200"), "UAH", "https://prom.ua/a")
    usd = [
        MarketOffer("avtopro", "B", Decimal("50"), "USD", "https://avto.pro/b"),
        MarketOffer("avtopro", "C", Decimal("60"), "USD", "https://avto.pro/c"),
    ]

    sources = competitor_prices_module._single_currency(
        (
            SourceResult("prom", "Prom.ua", "ok", (uah,)),
            SourceResult("avtopro", "Avto.pro", "ok", tuple(usd)),
        )
    )

    assert sources[0].offers == (uah,)
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
                    MarketOffer("prom", "A", Decimal("100"), "UAH", "https://prom.ua/a"),
                    MarketOffer("prom", "B", Decimal("300"), "UAH", "https://prom.ua/b"),
                ),
            ),
            SourceResult(source="avtopro", label="Avto.pro", status="empty"),
        ),
        observed_at=datetime.fromtimestamp(0, UTC),
    )

    payload = report.as_json()

    assert payload["stats"]["offers_total"] == 2
    assert payload["stats"]["sources_total"] == 2
    assert payload["stats"]["min_price"] == "100"
    assert payload["stats"]["median_price"] == "200.00"
    assert payload["stats"]["max_price"] == "300"
    # Рекомендація — конкретна сума: на 1% нижче мінімуму конкурентів.
    assert payload["stats"]["recommended_price"] == "99"


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

    async def fake_owned_stores(_session, _workspace_id, _kind):
        return []

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
        competitor_prices_module.stores_repo,
        "list_workspace_stores_by_kind",
        fake_owned_stores,
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
    emit = lambda stage, message: stages.append((stage, message))
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
