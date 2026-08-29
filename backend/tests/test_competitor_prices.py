import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import marko.services.competitor_prices as competitor_prices_module
from factories import product
from marko.services.competitor_prices import (
    CompetitorPriceCache,
    CompetitorPriceReport,
    GLOBAL_OWN_PROM_SELLERS,
    MarketOffer,
    PartSearchQuery,
    PromPriceSource,
    SourceResult,
    _cache_key,
    _cheapest_by_key,
    _is_own_prom_product,
    _market_brand,
    _match_score,
    _product_matches,
    _prom_seller_id_from_url,
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


async def test_avtopro_counts_interchangeable_analogues_in_the_stats(monkeypatch):
    """Стрічка деталі — це і аналоги: вони теж формують ринкову ціну.

    Рішення замовника: аналог — це та сама деталь на ту саму машину від іншого
    виробника, і вона конкурує з нашою. Деталь на іншу машину сюди не доходить.
    Ризик відомий: дешевий аналог тягне рекомендацію вниз — саме тому кожен
    оффер у статистиці проходить другий прохід моделі.
    """
    feed = [
        SimpleNamespace(
            maker=maker, code=code, part_uri=f"/part-{code}/", description="Кнопка",
            city="Київ", availability=None, price=price, currency="UAH",
            warehouse_id=f"wh-{maker}", boosted=False, used=False,
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
    # Позначка «аналог» лишається для ока, але ціну він задає нарівні з точним.
    assert result.min_price == Decimal("180.00")


async def test_google_source_prices_from_snippet_and_page(monkeypatch):
    """Сторінка (JSON-LD) — головне джерело ціни; сніпет — лише резерв.

    Сніпетна регулярка ловила «доставка 0 грн» і склеєні цифри, тому GET
    робиться для кожного кандидата в межах ліміту, а сніпет рятує тільки
    тих, чия сторінка не віддала ціну.
    """
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
            {   # закордонний магазин: не ринок замовника, хоч деталь і та
                "title": "Bosch 0451103316 Oil Filter",
                "link": "https://eeuroparts.com/parts/0451103316",
                "snippet": "$4.99 In Stock",
            },
            {   # зовсім не наша деталь
                "title": "Куртка зимова чоловіча",
                "link": "https://shop.example.com.ua/kurtka",
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
            # Сторінка to24 «лежить» — для неї ціна прийде зі сніпета.
            if "to24" in url:
                response = FakeResponse(text="")
                response.status_code = 500
                return response
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
    # Сторінки качали для обох кандидатів: сторінка важливіша за сніпет.
    assert fetched_pages == [
        "https://to24.com.ua/buy/bosch-0451103316",
        "https://partsplus.com.ua/detail/0451103316/bosch/",
    ]


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


async def test_foreign_offers_convert_to_uah_by_nbu_rate(monkeypatch):
    """50 USD за курсом 41.5 — це 2075 грн у виданні й статистиці."""
    uah = MarketOffer("prom", "A", Decimal("2200"), "UAH", "https://prom.ua/a")
    usd = MarketOffer("google", "B", Decimal("50"), "USD", "https://shop.example/b")

    async def fake_rates():
        return {"USD": Decimal("41.5"), "EUR": Decimal("45.0")}

    monkeypatch.setattr(
        competitor_prices_module.exchange_rates, "uah_rates", fake_rates
    )

    sources = await competitor_prices_module._to_uah(
        (
            SourceResult("prom", "Prom.ua", "ok", (uah,)),
            SourceResult("google", "Google", "ok", (usd,)),
        )
    )

    converted = sources[1].offers[0]
    assert converted.price == Decimal("2075.00")
    assert converted.currency == "UAH"
    # Гривневі пропозиції не чіпаємо.
    assert sources[0].offers == (uah,)


async def test_unavailable_rates_keep_old_drop_behavior(monkeypatch):
    """НБУ лежить → конвертації немає, долари зніме _single_currency."""
    uah = MarketOffer("prom", "A", Decimal("200"), "UAH", "https://prom.ua/a")
    usd = MarketOffer("google", "B", Decimal("50"), "USD", "https://shop.example/b")

    async def no_rates():
        return {}

    monkeypatch.setattr(competitor_prices_module.exchange_rates, "uah_rates", no_rates)

    sources = await competitor_prices_module._to_uah(
        (SourceResult("google", "Google", "ok", (uah, usd)),)
    )
    assert sources[0].offers == (uah, usd)

    cleaned = competitor_prices_module._single_currency(sources)
    assert cleaned[0].offers == (uah,)


def test_zero_prices_are_dropped_always():
    """«Доставка 0 грн» зі сніпета не має ставати ціною товару."""
    offers = (
        MarketOffer("google", "A", Decimal("0"), "UAH", "https://shop.example/a"),
        MarketOffer("google", "B", Decimal("204"), "UAH", "https://shop.example/b"),
    )

    sources = competitor_prices_module._drop_implausible(
        (SourceResult("google", "Google", "ok", offers),)
    )

    assert [str(offer.price) for offer in sources[0].offers] == ["204"]


def test_million_outlier_is_dropped_against_median():
    """Склеєні цифри («3 000 000 грн») відсікаються медіаною впевнених."""
    prices = ["190", "200", "210", "3000000"]
    offers = tuple(
        MarketOffer("google", f"O{i}", Decimal(p), "UAH", f"https://s.example/{i}")
        for i, p in enumerate(prices)
    )

    sources = competitor_prices_module._drop_implausible(
        (SourceResult("google", "Google", "ok", offers),)
    )

    assert [str(offer.price) for offer in sources[0].offers] == ["190", "200", "210"]


def test_small_reports_keep_honest_spread():
    """Три пропозиції — не статистика: розкид не рубаємо, щоб не втратити ринок."""
    offers = tuple(
        MarketOffer("google", f"O{i}", Decimal(p), "UAH", f"https://s.example/{i}")
        for i, p in enumerate(["100", "200", "5000"])
    )

    sources = competitor_prices_module._drop_implausible(
        (SourceResult("google", "Google", "ok", offers),)
    )

    assert len(sources[0].offers) == 3


def test_recommended_price_is_never_zero():
    """Копійчана ціна після −6% і округлення не має давати 0 грн."""
    assert competitor_prices_module._recommended_price([Decimal("0.30")]) == Decimal(
        "1"
    )
    assert competitor_prices_module._recommended_price([Decimal("200")]) == Decimal(
        "188"
    )


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
    # Рекомендація — конкретна сума: на 6% нижче мінімуму конкурентів.
    assert payload["stats"]["recommended_price"] == "94"
    # Відсоток їде поруч, щоб підпис у картці не розходився з формулою.
    assert payload["stats"]["recommended_discount_percent"] == 6


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


def _kemp_listing(**over):
    """Картка під власною маркою: саме такі 86% каталогу замовника."""
    base = dict(
        id="listing-kemp",
        sku="312783",
        brand="KEMP",
        name="Амортизатор задний Audi (Ауді) A4 (В6) 00-04",
        url="https://prom.ua/ua/p2749852485-amortizator.html",
        raw_data={"oem_numbers": ["8E0513033", "312783"]},
    )
    return SimpleNamespace(**{**base, **over})


def test_own_house_brand_is_not_treated_as_a_manufacturer():
    """KEMP — марка магазину; справжня марка каталогу лишається як була."""
    assert _market_brand("KEMP") is None
    # Регістр і пробіли не мають рятувати власну марку від скасування.
    assert _market_brand(" kemp ") is None
    assert _market_brand("Bosch") == "Bosch"

    # У самому запиті марка лишається: avto.pro шукає деталь у каталозі за
    # виробником, і там KEMP — справжній ключ, без нього джерело порожнє.
    assert _query_from_listing(_kemp_listing()).brand == "KEMP"


def test_number_match_survives_a_foreign_brand_under_own_house_brand():
    """Головна причина порожніх звітів: збіг за номером анулювався брендом."""
    query = _query_from_listing(_kemp_listing())

    # Конкурент продає ту саму деталь під своєю маркою — це і є ринок.
    assert _match_score(query, "Амортизатор задній 8E0513033", brand="VAG") == 0.9
    assert _match_score(query, "Амортизатор задній 8E0513033", brand="Sachs") == 0.9


def test_real_brand_still_rejects_the_same_number_under_another_make():
    """Для справжньої марки звірка бренду лишається: контракт не зламано."""
    query = _query_from_listing(
        _kemp_listing(brand="Bosch", raw_data={"oem_numbers": ["0451103316"]})
    )

    assert _match_score(query, "Фільтр 0451103316", brand="Bosch") == 0.9
    assert _match_score(query, "Фільтр 0451103316", brand="Mann") == 0.0


def test_google_skips_own_sites_but_keeps_dealers():
    """kemp.ua — сайт замовника; дилер із товаром KEMP лишається конкурентом."""
    query = _query_from_listing(_kemp_listing())
    batch = [
        {"link": "https://kemp.ua/amortyzator-8E0513033", "title": "Амортизатор задний Audi A4 (В6) 00-04"},
        {"link": "https://shop.kemp.ua/p/8E0513033", "title": "Амортизатор задний Audi A4 (В6) 00-04"},
        {"link": "https://autoshop.com.ua/8E0513033", "title": "Амортизатор задний Audi A4 (В6) 00-04 KEMP"},
    ]

    picked = competitor_prices_module.GooglePriceSource()._candidates(query, [batch])

    assert [domain for _item, domain, _score in picked] == ["autoshop.com.ua"]


def test_query_contains_global_and_workspace_prom_exclusions():
    listing = SimpleNamespace(
        id="listing-1",
        sku="0451103316",
        brand="Bosch",
        name="Фільтр масляний Bosch",
        url="https://prom.ua/ua/p123-filtr.html",
        raw_data={"seller_id": 2847093, "seller_slug": "kemp"},
    )
    seller_exclusions = [
        SimpleNamespace(
            marketplace="prom",
            external_id="2231191",
            slug="motor-avto",
        ),
        SimpleNamespace(
            marketplace="prom",
            external_id="2847093",
            slug="kemp",
        ),
        SimpleNamespace(
            marketplace="olx",
            external_id="olx-shop",
            slug="olx-shop",
        ),
    ]

    query = _query_from_listing(listing, seller_exclusions)

    assert query.owner_seller_ids == (
        "2231191",
        "2847093",
        "3325174",
        "3912822",
        "4015921",
    )
    assert query.owner_seller_slugs == (
        "avtobust",
        "kemp",
        "motor-avto",
        "parts-avto",
        "profparts",
    )


def test_manual_search_query_excludes_owned_prom_stores():
    seller_exclusions = [
        SimpleNamespace(marketplace="prom", external_id="9876543", slug="my-shop"),
        SimpleNamespace(marketplace="olx", external_id="olx-shop", slug="olx-shop"),
    ]

    query = competitor_prices_module.manual_search_query(
        "0451103316", "Bosch", seller_exclusions=seller_exclusions
    )

    assert query.owner_seller_ids == (
        "2847093",
        "3325174",
        "3912822",
        "4015921",
        "9876543",
    )
    assert query.owner_seller_slugs == (
        "avtobust",
        "kemp",
        "my-shop",
        "parts-avto",
        "profparts",
    )
    own_product = SimpleNamespace(
        seller_id=9876543,
        seller_slug="my-shop",
        url="https://prom.ua/ua/p1-a.html",
    )
    assert _is_own_prom_product(query, own_product)


def test_all_global_own_prom_sellers_are_filtered_before_offer_creation():
    query = competitor_prices_module.manual_search_query("0451103316", "Bosch")
    products = [
        product(
            id=index,
            name="Фільтр масляний Bosch 0451103316",
            sku="0451103316",
            urlText=f"filtr-{index}",
            company={"id": int(seller_id), "name": slug, "slug": slug},
        )
        for index, (seller_id, slug) in enumerate(GLOBAL_OWN_PROM_SELLERS, start=1)
    ]
    products.append(
        product(
            id=99,
            name="Фільтр масляний Bosch 0451103316",
            sku="0451103316",
            urlText="competitor-filter",
            company={"id": 999, "name": "Market Seller", "slug": "market-seller"},
        )
    )

    offers = list(PromPriceSource()._offers_from(query, products, "0451103316"))

    assert [offer.seller for offer in offers] == ["Market Seller"]


def test_own_prom_seller_id_falls_back_to_store_subdomain():
    query = competitor_prices_module.manual_search_query("0451103316", "Bosch")
    own_url = "https://kemp-cs2847093.prom.ua/ua/p999-filtr.html"

    assert _prom_seller_id_from_url(own_url) == "2847093"
    assert _is_own_prom_product(
        query,
        SimpleNamespace(
            seller_id=None,
            seller_slug=None,
            url=own_url,
        ),
    )


def test_cache_key_is_v10_and_changes_with_workspace_exclusions():
    base = competitor_prices_module.manual_search_query("0451103316", "Bosch")
    workspace = competitor_prices_module.manual_search_query(
        "0451103316",
        "Bosch",
        seller_exclusions=[
            SimpleNamespace(
                marketplace="prom",
                external_id="9876543",
                slug="my-shop",
            )
        ],
    )

    assert _cache_key(base).startswith("competitor-prices:v10:")
    assert _cache_key(base) != _cache_key(workspace)


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

    async def fake_seller_exclusions(_session, _workspace_id):
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
        "list_competitor_seller_exclusions",
        fake_seller_exclusions,
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

    async def fake_ask(_prompt: str, _system: str = "") -> str:
        return '{"verdicts": [{"index": 0, "verdict": "same"}]}'

    monkeypatch.setattr(llm_filter, "_ask_openai", fake_ask)
    verdicts = await llm_filter.classify(
        name="Фільтр", brand=None, oem_numbers=(), titles=["Фільтр", "Тапочки", "Сумка"]
    )
    assert verdicts == {0: "same", 1: "no", 2: "no"}

    async def empty_ask(_prompt: str, _system: str = "") -> str:
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


def _verify_offer(title: str, price: str, confidence: float = 0.9) -> MarketOffer:
    return MarketOffer(
        source="prom",
        title=title,
        price=Decimal(price),
        currency="UAH",
        url=f"https://prom.ua/{price}",
        seller="shop",
        availability="в наявності",
        confidence=confidence,
    )


def _enable_verification(monkeypatch, *, enabled: bool = True) -> None:
    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "is_enabled", lambda: enabled
    )
    monkeypatch.setattr(
        competitor_prices_module,
        "get_settings",
        lambda: SimpleNamespace(competitor_verify_enabled=True),
    )


async def test_suspicious_cheap_offer_is_reverified_and_dropped(monkeypatch):
    """Ціна вп'ятеро нижча за медіану — модель дивиться на неї з усіма даними."""
    _enable_verification(monkeypatch)
    sources = (
        SourceResult(
            "prom",
            "Prom.ua",
            "ok",
            (
                _verify_offer("Кріплення фільтра", "40"),
                _verify_offer("Фільтр масляний Bosch", "200"),
                _verify_offer("Фільтр масляний Bosch B", "210"),
                _verify_offer("Фільтр масляний Bosch C", "220"),
            ),
        ),
    )
    seen: dict = {}

    async def fake_verify(*, offers, market_summary, **kwargs):
        seen["offers"] = offers
        seen["summary"] = market_summary
        seen.update(kwargs)
        return {index: ("drop" if "Кріплення" in o.title else "ok")
                for index, o in enumerate(offers)}

    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_offers", fake_verify
    )

    checked = await competitor_prices_module._verify_offers(
        part_query(), sources, lambda *_: None
    )

    assert [o.title for o in checked[0].offers] == [
        "Фільтр масляний Bosch",
        "Фільтр масляний Bosch B",
        "Фільтр масляний Bosch C",
    ]
    # Модель бачить ціну, продавця й наявність — не лише назву.
    assert seen["offers"][0].price.startswith("40")
    assert seen["offers"][0].seller == "shop"
    assert seen["offers"][0].availability == "в наявності"
    assert "медіана" in seen["summary"].lower()


async def test_every_offer_in_the_stats_is_verified(monkeypatch):
    """Перевіряємо все, що формує звіт, а не лише дивні ціни."""
    _enable_verification(monkeypatch)
    prices = ["500", "520", "540", "560", "580"]
    sources = (
        SourceResult(
            "prom", "Prom.ua", "ok",
            tuple(_verify_offer(f"Фільтр {p}", p) for p in prices),
        ),
    )
    sent: list[str] = []

    async def fake_verify(*, offers, **_kwargs):
        sent.extend(o.title for o in offers)
        return {index: "ok" for index in range(len(offers))}

    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_offers", fake_verify
    )

    await competitor_prices_module._verify_offers(
        part_query(), sources, lambda *_: None
    )

    assert len(sent) == 5
    # Найдешевші першими: саме вони задають рекомендацію.
    assert sent[0] == "Фільтр 500"


async def test_unverified_offer_stays_visible_but_out_of_stats(monkeypatch):
    """«unsure» не видаляє пропозицію, але й не пускає її в рекомендацію."""
    _enable_verification(monkeypatch)
    sources = (
        SourceResult(
            "prom", "Prom.ua", "ok",
            (
                _verify_offer("Фільтр дешевий", "50"),
                _verify_offer("Фільтр A", "500"),
                _verify_offer("Фільтр B", "520"),
                _verify_offer("Фільтр C", "540"),
            ),
        ),
    )

    async def fake_verify(*, offers, **_kwargs):
        return {index: ("unsure" if "дешевий" in o.title else "ok")
                for index, o in enumerate(offers)}

    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_offers", fake_verify
    )

    checked = await competitor_prices_module._verify_offers(
        part_query(), sources, lambda *_: None
    )

    cheap = next(o for o in checked[0].offers if "дешевий" in o.title)
    assert cheap.confidence == 0.5
    # У статистику пішли лише впевнені — 50 грн рекомендації не задає.
    assert min(checked[0].prices) == Decimal("500")


async def test_model_silence_keeps_ordinary_prices_in_the_stats(monkeypatch):
    """Модель мовчить — це не привід вирізати чесний ринок.

    Реальний випадок: із 29 пропозицій модель підтвердила дві, решту
    позначила «не знаю» — і рекомендація вийшла втричі вища за ринок.
    Тепер «не знаю» понижує лише підозріло дешеві.
    """
    _enable_verification(monkeypatch)
    sources = (
        SourceResult(
            "prom", "Prom.ua", "ok",
            tuple(
                _verify_offer(f"Фільтр {p}", p)
                for p in ("100", "500", "520", "540")
            ),
        ),
    )

    async def fake_verify(**_kwargs):
        return {}

    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_offers", fake_verify
    )

    checked = await competitor_prices_module._verify_offers(
        part_query(), sources, lambda *_: None
    )
    kept = {o.price: o.confidence for o in checked[0].offers}

    assert len(checked[0].offers) == 4
    # Звичайні ціни лишаються в статистиці...
    assert kept[Decimal("500")] > 0.5
    assert kept[Decimal("540")] > 0.5
    # ...а вп'ятеро дешевша за медіану — під підозрою, і поза нею.
    assert kept[Decimal("100")] == 0.5


async def test_verification_is_skipped_without_the_model(monkeypatch):
    _enable_verification(monkeypatch, enabled=False)
    called = False

    async def fake_verify(**_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_offers", fake_verify
    )
    sources = (
        SourceResult(
            "prom", "Prom.ua", "ok",
            tuple(_verify_offer(f"Фільтр {p}", p) for p in ("500", "520", "540")),
        ),
    )

    assert await competitor_prices_module._verify_offers(
        part_query(), sources, lambda *_: None
    ) is sources
    assert not called


async def test_thin_report_skips_verification(monkeypatch):
    """Дві ціни — не статистика: якоря немає, перевіряти нічого."""
    _enable_verification(monkeypatch)
    called = False

    async def fake_verify(**_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_offers", fake_verify
    )
    sources = (
        SourceResult(
            "prom", "Prom.ua", "ok",
            (_verify_offer("Фільтр A", "500"), _verify_offer("Фільтр B", "520")),
        ),
    )

    await competitor_prices_module._verify_offers(
        part_query(), sources, lambda *_: None
    )
    assert not called


async def test_verification_is_capped(monkeypatch):
    _enable_verification(monkeypatch)
    sources = (
        SourceResult(
            "prom", "Prom.ua", "ok",
            tuple(_verify_offer(f"Фільтр {i}", str(500 + i)) for i in range(50)),
        ),
    )
    sent: list[str] = []

    async def fake_verify(*, offers, **_kwargs):
        sent.extend(o.title for o in offers)
        return {index: "ok" for index in range(len(offers))}

    monkeypatch.setattr(
        competitor_prices_module.llm_filter, "verify_offers", fake_verify
    )

    await competitor_prices_module._verify_offers(
        part_query(), sources, lambda *_: None
    )

    assert len(sent) == competitor_prices_module._VERIFY_MAX_OFFERS
    assert sent[0] == "Фільтр 0"  # найдешевший перший


# Добір каталожного номера зі сторінки товару


def _page_listing():
    """Картка, додана посиланням: тільки внутрішній артикул, номера немає."""
    return SimpleNamespace(
        id="listing-1",
        sku="312783 KEMP",
        brand="KEMP",
        name="Амортизатор задний Audi (Ауді) A4 (В6) 00-04",
        url="https://prom.ua/ua/p2749852485-amortizator.html",
        raw_data={"seller_id": 2847093, "seller_slug": "kemp"},
    )


def _patch_listing_lookup(monkeypatch, view):
    async def fake_listing(_session, _workspace_id, _listing_id):
        return view

    async def fake_exclusions(_session, _workspace_id):
        return []

    monkeypatch.setattr(competitor_prices_module, "get_workspace_listing", fake_listing)
    monkeypatch.setattr(
        competitor_prices_module.stores_repo,
        "list_competitor_seller_exclusions",
        fake_exclusions,
    )


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


async def test_missing_number_is_read_from_the_product_page(monkeypatch):
    """За «312783 KEMP» ринку немає; номер зі сторінки його знаходить."""
    saved: dict = {}
    _patch_listing_lookup(monkeypatch, _page_listing())

    class FakeClient:
        def __init__(self, _config) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc) -> None:
            return None

        async def get_html(self, url: str) -> str:
            saved["url"] = url
            return "<html/>"

    async def fake_store(_session, listing_id, numbers):
        saved["stored"] = (listing_id, numbers)

    monkeypatch.setattr(competitor_prices_module, "AsyncHttpClient", FakeClient)
    monkeypatch.setattr(
        competitor_prices_module,
        "parse_product_page",
        lambda _html: SimpleNamespace(
            product=SimpleNamespace(oem_numbers=("8E0513033",))
        ),
    )
    monkeypatch.setattr(competitor_prices_module, "set_listing_oem_numbers", fake_store)

    session = _FakeSession()
    query = await competitor_prices_module.listing_search_query(
        session, "workspace-1", "listing-1"
    )

    assert query.oem_numbers[0] == "8E0513033"
    # Артикул лишається кандидатом для звірки, просто вже не першим.
    assert "312783KEMP" in query.oem_numbers
    assert saved["stored"] == ("listing-1", ["8E0513033"])
    assert saved["url"] == "https://prom.ua/ua/p2749852485-amortizator.html"
    assert session.commits == 1


async def test_unreachable_product_page_does_not_break_the_report(monkeypatch):
    """Антибот на сторінці — не привід лишити замовника без звіту."""
    _patch_listing_lookup(monkeypatch, _page_listing())

    class BrokenClient:
        def __init__(self, _config) -> None:
            pass

        async def __aenter__(self):
            raise RuntimeError("403 Forbidden")

        async def __aexit__(self, *_exc) -> None:
            return None

    monkeypatch.setattr(competitor_prices_module, "AsyncHttpClient", BrokenClient)

    session = _FakeSession()
    query = await competitor_prices_module.listing_search_query(
        session, "workspace-1", "listing-1"
    )

    assert query.oem_numbers == ("312783KEMP",)
    assert session.commits == 0


async def test_existing_numbers_skip_the_extra_page_request(monkeypatch):
    """Картка з номерами вже не платить зайвим запитом за кожен звіт."""
    view = _page_listing()
    view.raw_data = {**view.raw_data, "oem_numbers": ["8E0513033"]}
    _patch_listing_lookup(monkeypatch, view)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("сторінку не мали чіпати")

    monkeypatch.setattr(competitor_prices_module, "AsyncHttpClient", forbidden)

    query = await competitor_prices_module.listing_search_query(
        _FakeSession(), "workspace-1", "listing-1"
    )

    assert query.oem_numbers == ("8E0513033", "312783KEMP")
