"""Parsing checks for the avto.pro feed and search responses."""
from marko.parsers.avtopro import parse_feed, parse_search_suggestions, pick_suggestion

# Trimmed from a real part page (attribute layout preserved).
_ROW = """
<tr data-seller-is-safe-deal="True" data-wholesale="0"
    data-wh-id="LS489A;645;0000;347922" data-is-boost-position="1"
    data-interactive-feed-item-element="true" data-feedItemClickKey="x">
<td class="ap-feed__table__expand"></td>
<td data-type="maker"><span> Purflux </span></td>
<td data-type="code"><a class="text" title="LS489A" data-link="true"
    href="/part-LS489A-PURFLUX-978/">LS489A</a></td>
<td></td>
<td title="Фильтр масляный"><span class="ap-feed__table__descr">Фильтр масляный</span></td>
<td data-type="delivery" data-city="Кременчуг"
    data-tooltip-content="Товар в наличии и готов к отправке из г. Кременчуг">
    <span>В наличии,</span></td>
<td data-type="price" data-value="256.00"><span><span title="256.00">
    256<small>,00</small><b data-type="currency">грн</b></span></span></td>
</tr>
"""

_ROW_NO_PRICE = _ROW.replace('data-value="256.00"', 'data-value="0"')

_SHOW_MORE = (
    '<button data-token="{&quot;Descriptor&quot;:{&quot;Code&quot;:'
    '&quot;0451103316&quot;},&quot;Skip&quot;:24,&quot;Group&quot;:0}">'
)

_SEARCH_PAYLOAD = {
    "Suggestions": [
        {
            "Title": "LADA W9142",
            "Uri": "/api/v1/search/result-redirect?uri=%2Fzapchasti-W9142%2F",
            "FoundPart": {"Part": {"Brand": {"Name": "LADA", "Path": "LADA"}}},
        },
        {
            "Title": "Mann-Filter W 9142",
            "Uri": "/api/v1/search/result-redirect?sInd=3&uri=%2Fpart-W9142-MANN-1%2F",
            "FoundPart": {
                "Part": {
                    "Brand": {"Name": "Mann-Filter", "Path": "MANN", "IsOriginal": False}
                }
            },
        },
    ]
}


def test_parse_feed_row_and_token():
    page = parse_feed('<article class="ap-feed">' + _ROW + _ROW_NO_PRICE + _SHOW_MORE)
    assert len(page.offers) == 1  # priceless row dropped
    offer = page.offers[0]
    assert offer.maker == "Purflux"
    assert offer.code == "LS489A"
    assert offer.part_uri == "/part-LS489A-PURFLUX-978/"
    assert offer.description == "Фильтр масляный"
    assert offer.city == "Кременчуг"
    assert "в наличии" in offer.availability.lower()
    assert offer.price == 256.00
    assert offer.currency == "UAH"
    assert offer.warehouse_id == "LS489A;645;0000;347922"
    assert offer.boosted is True
    assert offer.used is False
    assert '"Skip":24' in page.continuation_token


def test_used_rows_are_recognised_without_the_word_in_the_description():
    """Справжній випадок: із пʼяти вживаних лише одна писала «б/у» словами.

    Решта йшли як звичайні, і найдешевша з них ставала мінімумом ринку —
    заказчик клікав рекомендацію й потрапляв на вживану ступицю. Рядок
    несе машинний прапорець data-bu, на нього й спираємось.
    """
    used_flag = _ROW.replace(
        'data-wholesale="0"', 'data-wholesale="0" data-bu="1"'
    )
    dismantling = _ROW.replace(
        'data-wholesale="0"', 'data-wholesale="0" data-is-cardismantling="True"'
    )
    badge = _ROW.replace(
        '<span class="ap-feed__table__descr">Фильтр масляный</span>',
        '<span data-tooltip-content="Запчасти, которые были в употреблении">'
        "Б/У</span><span>Фильтр масляный</span>",
    )

    for markup, label in (
        (used_flag, "data-bu"),
        (dismantling, "розборка"),
        (badge, "бейдж"),
    ):
        page = parse_feed('<article class="ap-feed">' + markup)
        assert page.offers[0].used is True, label
        # Опис так і лишився без слова «б/у» — текстом це не спіймати.
        assert "б/у" not in (page.offers[0].description or "").lower()


def test_parse_search_skips_non_part_uris_and_picks_brand():
    suggestions = parse_search_suggestions(_SEARCH_PAYLOAD)
    assert [s.brand for s in suggestions] == ["Mann-Filter"]
    assert suggestions[0].part_uri == "/part-W9142-MANN-1/"
    assert pick_suggestion(suggestions, "MANN").brand == "Mann-Filter"
    assert pick_suggestion(suggestions, None) is suggestions[0]
    assert pick_suggestion([], None) is None


def test_pick_suggestion_falls_back_to_make_from_product_name():
    payload = {
        "Suggestions": [
            {
                "Title": "China 7700308222",
                "Uri": "/api/v1/search/result-redirect?uri=%2Fpart-7700308222-CHINA-1%2F",
                "FoundPart": {"Part": {"Brand": {"Name": "China", "Path": "CHINA"}}},
            },
            {
                "Title": "Renault/Dacia (RVI) 77 00 308 222",
                "Uri": "/api/v1/search/result-redirect?uri=%2Fpart-7700308222-RENAULT-2%2F",
                "FoundPart": {
                    "Part": {"Brand": {"Name": "Renault/Dacia (RVI)", "Path": "RENAULT"}}
                },
            },
        ]
    }
    suggestions = parse_search_suggestions(payload)
    name = "Радіатор Renault Kangoo 00- 1.2-1.6 16V 480*415"
    assert pick_suggestion(suggestions, "KEMP", name).brand == "Renault/Dacia (RVI)"
    # Ні бренд, ні назва не збіглися — краще нічого, ніж чужа марка з топ-1.
    assert pick_suggestion(suggestions, "KEMP") is None
    assert pick_suggestion(suggestions, None, "Кільця поршнів STD") is None


def test_broken_continuation_keeps_the_first_page(monkeypatch):
    """401 і антибот на продовженні стрічки — звична річ, сторінка 1 має вціліти."""
    from marko.parsers.avtopro import AvtoproGateway
    from marko.parsers.prom.exceptions import RequestFailed

    part_page = f"<div class='ap-feed'>{_ROW}</div>{_SHOW_MORE}"

    class FakeClient:
        def __init__(self, _config) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc) -> None:
            pass

        def put_json(self, _url, _payload):
            return {
                "Suggestions": [
                    {
                        "Title": "Purflux LS489A",
                        "Uri": "/r?uri=%2Fpart-LS489A-PURFLUX-978%2F",
                        "FoundPart": {"Part": {"Brand": {"Name": "Purflux"}}},
                    }
                ]
            }

        def get_html(self, url: str) -> str:
            if "Continuation" in url:
                raise RequestFailed("HTTP 401 для avto.pro")
            return part_page

    import marko.parsers.avtopro.gateway as gateway_module

    monkeypatch.setattr(gateway_module, "HttpClient", FakeClient)

    result = AvtoproGateway().offers("LS489A", brand="Purflux")

    assert result is not None
    assert [offer.code for offer in result.offers] == ["LS489A"]
    assert result.pages_fetched == 1
