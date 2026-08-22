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
    assert '"Skip":24' in page.continuation_token


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
    # Без назви лишається стара поведінка — перша підказка сайту.
    assert pick_suggestion(suggestions, "KEMP") is suggestions[0]
    # Назва без марки нічого не ламає.
    assert pick_suggestion(suggestions, None, "Кільця поршнів STD") is suggestions[0]
