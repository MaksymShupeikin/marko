#!/usr/bin/env python3
"""Reproducible, offline probes for the 2026-08-30 price audit.

These probes intentionally describe current behaviour. They do not encode a
desired product contract and they never call external services.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from marko.parsers.prom_export import parse_price  # noqa: E402
from marko.services import competitor_prices as cp  # noqa: E402
from marko.services import offer_gates  # noqa: E402
from marko.services.matching import (  # noqa: E402
    laterality_conflict,
    normalize_tokens,
    token_similarity,
)

logging.disable(logging.CRITICAL)


@dataclass(frozen=True)
class Probe:
    check: str
    mechanism_confirmed: bool
    evidence: dict[str, Any]
    note: str


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    return value


def _query(
    *,
    name: str = "Амортизатор передній Ford Focus",
    numbers: tuple[str, ...] = ("5202CY",),
) -> cp.PartSearchQuery:
    return cp.PartSearchQuery(
        listing_id="audit",
        oem_numbers=numbers,
        brand="KEMP",
        name=name,
        source_url="https://owned.example/item",
    )


def price_format_probe() -> Probe:
    samples = ["1,234.56", "1.234", "1 234,56", "-15%"]
    actual = {sample: parse_price(sample) for sample in samples}
    return Probe(
        "A1",
        actual["1,234.56"] == Decimal("1.23"),
        {"parse_price": actual},
        "US thousands+decimal notation is truncated to 1.23; frequency is not proven.",
    )


def structured_currency_probe() -> Probe:
    missing_currency = cp._structured_price(
        '<script type="application/ld+json">'
        '{"@type":"Offer","price":"50"}'
        "</script>"
    )
    usd_microdata = cp._structured_price(
        '<meta itemprop="priceCurrency" content="USD">'
        '<meta itemprop="price" content="50">'
    )
    return Probe(
        "A2",
        bool(
            missing_currency
            and missing_currency[1] == "UAH"
            and usd_microdata
            and usd_microdata[1] == "UAH"
        ),
        {
            "json_ld_without_currency": missing_currency,
            "microdata_with_usd_currency": usd_microdata,
        },
        "Missing/adjacent structured currency becomes UAH; live frequency is unknown.",
    )


def wrong_json_ld_node_probe() -> Probe:
    html = (
        '<script type="application/ld+json">'
        '[{"@type":"Offer","price":"70","priceCurrency":"UAH"},'
        '{"@type":"Product","image":"https://cdn.shop.ua/right.jpg",'
        '"offers":{"@type":"Offer","price":"2500","priceCurrency":"UAH"}}]'
        "</script>"
    )
    actual = cp._structured_price(html)
    return Probe(
        "A3",
        actual == (Decimal("70.00"), "UAH", "https://cdn.shop.ua/right.jpg"),
        {"structured_price": actual},
        "The first recursive Offer wins and may be paired with another node's image.",
    )


def category_url_probe() -> Probe:
    item = {
        "link": "https://shop.com.ua/catalog/search?q=5202CY",
        "title": "Амортизатор передній Ford Focus 5202CY",
        "snippet": "Інші товари категорії",
    }
    picked = cp.GooglePriceSource()._candidates(_query(), [[item]])
    return Probe(
        "A4",
        len(picked) == 1,
        {"accepted_urls": [entry[0]["link"] for entry in picked]},
        "No product-URL gate rejects search/catalog pages; frequency is cache/live dependent.",
    )


def snippet_price_probe() -> Probe:
    samples = {
        "covered_installment": "від 365 ₴ x 6 ; від 365 ₴",
        "multiplier_before_price": "6 платежів по 365 грн",
        "from_price": "ціна від 999 грн",
        "delivery_price": "доставка від 70 грн",
        "old_then_sale": "999 грн 799 грн",
    }
    actual = {name: cp._price_from_text(text) for name, text in samples.items()}
    return Probe(
        "A5",
        actual == {
            "covered_installment": None,
            "multiplier_before_price": Decimal("365.00"),
            "from_price": Decimal("999.00"),
            "delivery_price": Decimal("70.00"),
            "old_then_sale": Decimal("999.00"),
        },
        {"price_from_text": actual},
        "Several syntactic classes still produce a non-product or wrong anchor price.",
    )


def prom_currency_probe() -> Probe:
    uah = cp.MarketOffer("prom", "UAH", Decimal("500"), "UAH", "https://p/uah")
    raw = cp.MarketOffer("prom", "raw", Decimal("450"), "грн", "https://p/raw")
    cleaned = cp._single_currency(
        (cp.SourceResult("prom", "Prom.ua", "ok", (uah, raw)),)
    )
    return Probe(
        "A6",
        [offer.title for offer in cleaned[0].offers] == ["UAH"],
        {
            "norm_currency_grn": cp._norm_currency("грн"),
            "norm_currency_uah_dot": cp._norm_currency("UAH."),
            "offers_after_single_currency_without_prom_normalization": [
                offer.title for offer in cleaned[0].offers
            ],
        },
        "Prom offers bypass _norm_currency; uncommon raw labels can be discarded.",
    )


def unit_and_availability_probe() -> Probe:
    return Probe(
        "A7/A8",
        not offer_gates.is_junk(
            "Амортизатор, ціна за пару", "Немає в наявності"
        ),
        {
            "measure_unit_used_by_market_offer": False,
            "out_of_stock_is_junk": offer_gates.is_junk(
                "Амортизатор, ціна за пару", "Немає в наявності"
            ),
        },
        "Unit semantics are not carried into MarketOffer; out-of-stock is deliberately retained.",
    )


def word_oem_probe() -> Probe:
    generic = _query(
        name="Сайлентблок передній Ford Focus", numbers=("САЙЛЕНТБЛОК",)
    )
    model_word = _query(name="Амортизатор Ford Sierra", numbers=("FORDSIERRA",))
    actual_catalog_style = _query(
        name="Прокладка впускного колектора Peugeot 206",
        numbers=("PEUGEOT206",),
    )
    evidence = {
        "generic_part_word": cp._match_score(
            generic, "Сайлентблок балки Renault Laguna"
        ),
        "model_word_in_accessory": cp._match_score(
            model_word, "Чохли салону FORD SIERRA комплект"
        ),
        "actual_peugeot206_style_in_accessory": cp._match_score(
            actual_catalog_style, "Чохли салону PEUGEOT 206 комплект"
        ),
    }
    return Probe(
        "B1",
        all(score == cp._OEM_HIT_SCORE for score in evidence.values()),
        evidence,
        "Word/model-like values can create an unconditional 0.9 substring hit.",
    )


def numeric_identifier_probe() -> Probe:
    phone = _query(name="Радіатор Ford", numbers=("380012345678",))
    ean = _query(name="Радіатор Ford", numbers=("5901234123457",))
    evidence = {
        "phone_in_title": cp._match_score(phone, "Телефон +380012345678, магазин"),
        "ean_in_title": cp._match_score(ean, "Штрихкод 5901234123457, аксесуар"),
    }
    return Probe(
        "B2",
        all(score == cp._OEM_HIT_SCORE for score in evidence.values()),
        evidence,
        "All-digit identifiers >=8 bypass topic overlap, including phones/EANs.",
    )


def set_pair_probe() -> Probe:
    query = _query()
    candidate = "Амортизатор передній Ford Focus комплект 2 шт"
    score = cp._match_score(query, candidate)
    return Probe(
        "B3",
        score >= cp._MIN_STATS_CONFIDENCE and not offer_gates.is_junk(candidate),
        {"match_score": score, "deterministic_junk_gate": offer_gates.is_junk(candidate)},
        "A set can enter statistics before the nondeterministic first LLM pass.",
    )


def laterality_probe() -> Probe:
    false_conflict = laterality_conflict(
        normalize_tokens("Редуктор задній"), normalize_tokens("Коробка передач")
    )
    missing_pair = laterality_conflict(
        normalize_tokens("ШРУС внутрішній"), normalize_tokens("ШРУС зовнішній")
    )
    return Probe(
        "B4",
        false_conflict and not missing_pair,
        {"korobka_peredach_false_conflict": false_conflict, "inner_outer_conflict": missing_pair},
        "Prefix matching treats 'передач' as front; inner/outer is not modelled.",
    )


def bilingual_probe() -> Probe:
    samples = {
        "hub": token_similarity(
            set(normalize_tokens("маточина передня")),
            set(normalize_tokens("ступица передняя")),
        ),
        "cover": token_similarity(
            set(normalize_tokens("кришка клапанів")),
            set(normalize_tokens("крышка клапанов")),
        ),
    }
    return Probe(
        "B5",
        all(score < cp._MIN_NAME_SIMILARITY for score in samples.values()),
        samples,
        "Exact token matching has no Ukrainian/Russian synonym or stemming bridge.",
    )


def used_and_call_marker_probe() -> Probe:
    used_samples = ["Двигун зі шроту", "Деталь з пробігом", "Деталь с пробегом"]
    evidence = {
        "used_markers": {text: offer_gates.is_used(text) for text in used_samples},
        "real_price_call_to_action_is_junk": offer_gates.is_junk(
            "Фільтр 500 грн, у наявності, дзвоніть!"
        ),
    }
    return Probe(
        "B7",
        not any(evidence["used_markers"].values())
        and evidence["real_price_call_to_action_is_junk"],
        evidence,
        "Three used-part phrases are missed; a call-to-action with a real price is dropped.",
    )


def thin_market_and_stats_fallback_probe() -> Probe:
    offers = [
        cp.MarketOffer("x", "strong-500", Decimal("500"), "UAH", "https://x/1", confidence=0.9),
        cp.MarketOffer("x", "strong-520", Decimal("520"), "UAH", "https://x/2", confidence=0.9),
        cp.MarketOffer("x", "weak-50", Decimal("50"), "UAH", "https://x/3", confidence=0.5),
        cp.MarketOffer("x", "weak-100", Decimal("100"), "UAH", "https://x/4", confidence=0.5),
        cp.MarketOffer("x", "weak-120", Decimal("120"), "UAH", "https://x/5", confidence=0.5),
    ]
    source = cp.SourceResult("x", "X", "ok", tuple(offers))
    prices = cp._stats_prices(offers)
    _, anchor = cp._indexed_anchor((source,))
    return Probe(
        "B8/C2",
        min(prices) == Decimal("50") and anchor is None,
        {
            "stats_prices": prices,
            "recommended_price": cp._recommended_price(prices),
            "verification_photo_anchor": anchor,
        },
        "Two strong + three demoted offers re-enable the weak minimum; two strong alone disable verification/photo.",
    )


def exist_and_cross_source_probe() -> Probe:
    same_prom = cp.MarketOffer(
        "prom", "Фільтр X", Decimal("500"), "UAH", "https://prom.ua/x", seller="Shop X"
    )
    same_google = cp.MarketOffer(
        "google", "Фільтр X", Decimal("500"), "UAH", "https://shop-x.ua/x", seller="shop-x.ua"
    )
    report = cp.CompetitorPriceReport(
        query=_query(),
        sources=(
            cp.SourceResult("prom", "Prom", "ok", (same_prom,)),
            cp.SourceResult("google", "Google", "ok", (same_google,)),
        ),
        observed_at=cp.datetime.fromtimestamp(0, cp.UTC),
    )
    return Probe(
        "C3/C4",
        cp._covered_elsewhere("exist.ua") and len(report.offers) == 2,
        {
            "exist_covered_elsewhere": cp._covered_elsewhere("exist.ua"),
            "exist_terms": cp.ExistPriceSource()._terms(_query()),
            "cross_source_duplicate_count": len(report.offers),
        },
        "General Google excludes Exist; no report-level cross-source deduplication exists.",
    )


def cheapest_before_classification_probe() -> Probe:
    wrong = cp.MarketOffer(
        "prom", "Кріплення", Decimal("50"), "UAH", "https://p/wrong", seller="same"
    )
    right = cp.MarketOffer(
        "prom", "Амортизатор", Decimal("500"), "UAH", "https://p/right", seller="same"
    )
    selected = cp._cheapest_by_key([wrong, right], key=lambda offer: offer.seller)
    return Probe(
        "C5",
        [offer.title for offer in selected] == ["Кріплення"],
        {"selected_before_llm": [offer.title for offer in selected]},
        "Seller dedup can discard the correct higher-priced item before the LLM sees it.",
    )


async def source_timeout_probe() -> Probe:
    class PartialSource:
        source = "partial"
        label = "Partial"

        def __init__(self) -> None:
            self.collected = 0

        async def search(self, _query: cp.PartSearchQuery) -> cp.SourceResult:
            self.collected = 1
            await asyncio.sleep(0.05)
            offer = cp.MarketOffer(
                "partial", "A", Decimal("500"), "UAH", "https://partial/a"
            )
            return cp.SourceResult("partial", "Partial", "ok", (offer,))

    source = PartialSource()
    result = await cp._run_source(source, _query(), 0.001, lambda *_: None)
    return Probe(
        "C7",
        source.collected == 1 and result.status == "error" and not result.offers,
        {
            "source_had_partial_internal_state": source.collected,
            "returned_status": result.status,
            "returned_offers": len(result.offers),
        },
        "The whole-source timeout returns an empty error result even after internal collection began.",
    )


async def main() -> None:
    probes = [
        price_format_probe(),
        structured_currency_probe(),
        wrong_json_ld_node_probe(),
        category_url_probe(),
        snippet_price_probe(),
        prom_currency_probe(),
        unit_and_availability_probe(),
        word_oem_probe(),
        numeric_identifier_probe(),
        set_pair_probe(),
        laterality_probe(),
        bilingual_probe(),
        used_and_call_marker_probe(),
        thin_market_and_stats_fallback_probe(),
        exist_and_cross_source_probe(),
        cheapest_before_classification_probe(),
        await source_timeout_probe(),
    ]
    payload = {
        "scope": "offline current-behaviour probes; no external calls",
        "all_mechanisms_confirmed": all(probe.mechanism_confirmed for probe in probes),
        "probes": [asdict(probe) for probe in probes],
    }
    print(json.dumps(_json_value(payload), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
