from dataclasses import replace
from decimal import Decimal

from marko.services.matching import (
    _MAX_QUERY_TOKENS,
    Match,
    Offer,
    PriceComparison,
    _price_value,
    _token_similarity,
    brands_compatible,
    build_product_comparison_evidence,
    build_comparison,
    build_search_query,
    laterality_conflict,
    match_offer,
    normalize_tokens,
)
from marko.parsers.prom.gateway import _detail_identity_conflicts_with_comparison
from marko.services.parser_models import Product
from metis.pricing import EvidenceState

from factories import comparison_with_prices, params, product, seed_info


# normalize_tokens


def test_normalize_tokens_none_returns_empty():
    assert normalize_tokens(None) == []


def test_normalize_tokens_drops_stopwords_and_single_chars():
    assert normalize_tokens("Фара для BMW і X") == ["фара", "bmw"]


def test_normalize_tokens_lowercases():
    assert normalize_tokens("Bosch ФАРА") == ["bosch", "фара"]


# _token_similarity


def test_token_similarity_identical_is_one():
    assert _token_similarity({"a", "b"}, {"a", "b"}) == 1.0


def test_token_similarity_disjoint_is_zero():
    assert _token_similarity({"a"}, {"b"}) == 0.0


def test_token_similarity_empty_is_zero():
    assert _token_similarity(set(), {"a"}) == 0.0


def test_token_similarity_blends_jaccard_and_containment():
    assert _token_similarity({"a", "b"}, {"a", "b", "c", "d"}) == 0.75


# laterality_conflict


def test_laterality_conflict_left_vs_right():
    assert laterality_conflict(["лівий"], ["правий"]) is True


def test_laterality_conflict_front_vs_rear():
    assert laterality_conflict(["передній"], ["задній"]) is True


def test_laterality_conflict_same_side_is_false():
    assert laterality_conflict(["лівий"], ["лівий"]) is False


def test_laterality_conflict_unspecified_is_false():
    assert laterality_conflict(["фара"], ["правий"]) is False


def test_build_comparison_drops_explicitly_wrong_part_family():
    """Vehicle/side overlap must not expose a tail lamp as a shock absorber."""

    seed = seed_info(
        id=1,
        name="Амортизатор задній правий Toyota Camry V40",
        company={"id": 1, "name": "KEMP"},
    )
    wrong_family = product(
        id=2,
        name="Ліхтар задній правий Toyota Camry V40",
        price="2446",
        company={"id": 2, "name": "Wrong family"},
    )
    comparison = build_comparison(seed, [wrong_family], params())

    assert comparison.offers == []


def test_build_comparison_drops_explicit_semantic_variant_conflict():
    """A rigid brake line is not a flexible brake hose competitor."""

    seed = seed_info(
        id=1,
        name="Шланг тормозной передний VW Transporter T4",
        company={"id": 1, "name": "KEMP"},
    )
    wrong_variant = product(
        id=2,
        name="Трубка тормозная передняя VW Transporter T4",
        price="700",
        company={"id": 2, "name": "Wrong variant"},
    )

    assert build_comparison(seed, [wrong_variant], params()).offers == []


def test_build_comparison_drops_structured_condition_conflict():
    """A structured used flag must not be hidden by an identical title."""

    seed = seed_info(
        id=1,
        name="Амортизатор задній правий Toyota Camry V40",
        comparisonEvidence={"condition": "новий"},
        company={"id": 1, "name": "KEMP"},
    )
    used = product(
        id=2,
        name="Амортизатор задній правий Toyota Camry V40",
        comparisonEvidence={"condition": "б/у"},
        price="900",
        company={"id": 2, "name": "Used seller"},
    )

    assert build_comparison(seed, [used], params()).offers == []


# brands_compatible


def test_brands_compatible_equal():
    assert brands_compatible("Bosch", "bosch") is True


def test_brands_compatible_missing_one_side():
    assert brands_compatible("Bosch", None) is False


def test_brands_compatible_different_brands():
    assert brands_compatible("Bosch", "Sachs") is False


# match_offer


def test_match_offer_model_id_exact():
    seed = product(id=1, **{"model": {"id": "M1"}})
    cand = product(id=2, name="геть інша назва", **{"model": {"id": "M1"}})
    assert match_offer(seed, cand, 0.55) == Match("model", 1.0)


def test_match_offer_sku_exact():
    seed = product(id=1, sku="S123")
    cand = product(id=2, name="геть інша назва", sku="S123")
    assert match_offer(seed, cand, 0.55).kind == "sku"


def test_match_offer_mpn_exact_when_seller_sku_is_different():
    seed = product(id=1, sku="KEMP-SKU", identifiers={"mpn": "MA-00290"})
    cand = product(
        id=2,
        name="інша назва продавця",
        sku="SELLER-PRIVATE-SKU",
        identifiers={"mpn": "MA00290"},
    )

    assert match_offer(seed, cand, 0.99).kind == "mpn"


def test_search_number_matches_structured_mpn():
    seed = product(id=1, name="Искомая деталь")
    cand = product(
        id=2,
        name="Другая деталь",
        sku="SELLER-SKU",
        identifiers={"mpn": "D6X-004-TT"},
    )

    assert match_offer(seed, cand, 0.99, search_number="D6X004TT") == Match(
        "number", 1.0
    )


def test_search_number_matches_labelled_part_number_from_prom_attribute():
    seed = replace(product(id=1, name="Радіатор"), part_numbers=("230588",))
    cand = replace(
        product(id=2, name="Радіатор охолодження"),
        part_numbers=("230588", "230 589"),
    )

    assert match_offer(seed, cand, 0.99, search_number="230588") == Match(
        "number", 1.0
    )


def test_labelled_part_number_does_not_override_conflicting_native_mpn():
    seed = replace(product(id=1, name="Замок"), part_numbers=("7E5827505A",))
    cand = replace(
        product(id=2, name="Замок 7E5827505A"),
        mpn="7E5827505B",
        part_numbers=("7E5827505A",),
    )

    assert match_offer(seed, cand, 0.99, search_number="7E5827505A") is None


def test_search_number_rejects_conflicting_labelled_part_number():
    seed = product(id=1, name="Радіатор")
    cand = replace(
        product(id=2, name="Радіатор 77646966"),
        part_numbers=("77646679",),
    )

    assert match_offer(seed, cand, 0.99, search_number="77646966") is None


def test_search_number_matches_structured_oe_when_mpn_query_is_used():
    """A detail parser may expose a public MPN under its OE field."""

    seed = Product(
        id=None,
        name="Амортизатор Mercedes W124",
        sku=None,
        mpn="D6X004TT",
        price="1000",
        price_original=None,
        discounted_price=None,
        has_discount=None,
        currency="UAH",
        price_usd=None,
        presence=None,
        is_available=True,
        measure_unit=None,
        category_id=None,
        category_ids=None,
        category=None,
        brand=None,
        model_id=None,
        seller_id=None,
        seller_name=None,
        seller_slug=None,
        opinions_count=None,
        opinions_rating=None,
        image=None,
        url_text=None,
        oe_raw=None,
        fitment=None,
        vehicle_generation=None,
        year_from=None,
        year_to=None,
        engine=None,
        body_variant=None,
        side=None,
        position=None,
        condition=None,
        package_quantity=None,
        characteristics=None,
        description=None,
    )
    candidate = replace(
        seed,
        name="Амортизатор Mercedes W124 D6X004TT",
        mpn=None,
        oe_raw="D6X-004-TT",
    )

    assert match_offer(seed, candidate, 0.99, search_number="D6X004TT") == Match(
        "number", 1.0
    )


def test_private_kemp_code_is_not_a_public_identity_match():
    seed = product(id=1, name="Термостат Ford Focus", mpn="776414")
    candidate = product(
        id=2,
        name="Совсем другая деталь",
        oe="776 414",
        mpn=None,
    )

    assert match_offer(seed, candidate, 0.99, search_number="776414") is None


def test_search_number_accepts_exact_oe_alongside_different_native_mpn():
    """One exact native namespace is enough; another may be a cross code."""

    seed = product(id=1, name="Радиатор", identifiers={"mpn": "93818439"})
    candidate = replace(
        seed,
        id=2,
        name="Радиатор Iveco 93818439",
        mpn="AFTERMARKET-93818439",
        oe_raw="93818439",
    )

    assert match_offer(seed, candidate, 0.99, search_number="93818439") == Match(
        "number", 1.0
    )


def test_search_number_rejects_title_or_sku_when_native_codes_conflict():
    seed = product(id=1, name="Радиатор", identifiers={"mpn": "93818439"})
    candidate = replace(
        seed,
        id=2,
        name="Радиатор 93818439",
        sku="93818439",
        mpn="OTHER-MPN",
        oe_raw=None,
    )

    assert match_offer(seed, candidate, 0.99, search_number="93818439") is None


def test_detail_identity_accepts_exact_oe_with_alternate_mpn():
    seed = seed_info(id=1, name="Радиатор", identifiers={"mpn": "93818439"})
    candidate = product(
        id=2,
        name="Радиатор Iveco 93818439",
        identifiers={"mpn": "AFTERMARKET-93818439"},
        comparisonEvidence={"oeRaw": "93818439"},
    )
    enriched = replace(
        candidate,
        detail_evidence={"status": "SUCCESS"},
    )
    offer = Offer(
        product=candidate,
        match=Match("number", 1.0),
        price=Decimal("100"),
        comparison_evidence=build_product_comparison_evidence(
            seed.product,
            candidate,
            retrieval_kind="number",
        ),
    )
    comparison = PriceComparison(
        seed=seed,
        query="93818439",
        offers=[offer],
        candidates_scanned=1,
    )

    assert not _detail_identity_conflicts_with_comparison(
        comparison, offer, enriched
    )


def test_build_search_query_prefers_mpn_when_oe_missing():
    candidate = product(
        id=1,
        name="Очень общий заголовок детали",
        identifiers={"mpn": "TH652688J"},
    )

    assert build_search_query(candidate) == "TH652688J"


def test_build_search_query_prefers_explicit_original_oe_over_private_code_and_mpn():
    """Public Prom discovery must use the vehicle OE, not KEMP's shelf code."""

    candidate = product(
        id=1,
        name="Термостат Ford Focus",
        oe="776414",
        identifiers={"mpn": "KEMP-THERMOSTAT"},
        attributes=[
            {"name": "OE", "values": [{"value": "1086282"}]},
            {"name": "Код запчастини", "values": [{"value": "776414"}]},
        ],
    )

    assert build_search_query(candidate) == "1086282"


def test_build_search_query_does_not_promote_generic_article_over_public_mpn():
    """A supplier article label is not an original-OE assertion."""

    candidate = product(
        id=1,
        name="Термостат Ford Focus",
        identifiers={"mpn": "TH652688J"},
        attributes=[
            {"name": "Код запчастини", "values": [{"value": "SUP-776414"}]},
        ],
    )

    assert build_search_query(candidate) == "TH652688J"


def test_match_offer_exact_model_ignores_brand_as_identity_gate():
    seed = product(id=1, **{"model": {"id": "M1"}}, manufacturerInfo={"name": "Bosch"})
    cand = product(id=2, **{"model": {"id": "M1"}}, manufacturerInfo={"name": "Sachs"})
    assert match_offer(seed, cand, 0.01) == Match("model", 1.0)


def test_match_offer_exact_sku_does_not_bypass_laterality_conflict():
    seed = product(id=1, sku="S1", name="Фара ліва")
    cand = product(id=2, sku="S1", name="Фара права")
    assert match_offer(seed, cand, 0.01) is None


def test_match_offer_does_not_treat_seller_sku_as_identity():
    seed = product(
        id=1,
        sku="77641041",
        name="Амортизатор передній Ford Mondeo",
    )
    cand = product(
        id=2,
        sku="77641041",
        name="Датчик тиску палива BMW",
    )

    assert match_offer(seed, cand, 0.99) is None


def test_search_number_does_not_match_a_private_candidate_sku_only():
    seed = product(id=1, name="Амортизатор передній Ford Mondeo")
    cand = product(
        id=2,
        sku="77641041",
        name="Датчик тиску палива BMW",
    )

    assert match_offer(seed, cand, 0.99, search_number="77641041") is None


def test_private_search_number_cannot_fall_back_to_fuzzy_name_match():
    seed = product(
        id=1,
        name="Амортизатор задній Ford Escort",
        sku="77642123",
    )
    cand = product(
        id=2,
        name="Амортизатор задній Ford Escort",
        sku="77642123",
    )

    assert match_offer(seed, cand, 0.01, search_number="77642123") is None


def test_match_offer_fuzzy_above_threshold():
    seed = product(id=1, name="Амортизатор задній правий")
    cand = product(id=2, name="Амортизатор задній правий")
    assert match_offer(seed, cand, 0.55).kind == "fuzzy"


def test_match_offer_below_threshold_returns_none():
    seed = product(id=1, name="Амортизатор задній")
    cand = product(id=2, name="Фара передня ліва")
    assert match_offer(seed, cand, 0.55) is None


def test_match_offer_rejects_laterality_conflict():
    seed = product(id=1, name="Амортизатор лівий")
    cand = product(id=2, name="Амортизатор правий")
    assert match_offer(seed, cand, 0.10) is None


def test_match_offer_allows_brand_mismatch_to_reach_comparability():
    seed = product(
        id=1, name="Амортизатор задній правий", manufacturerInfo={"name": "Bosch"}
    )
    cand = product(
        id=2, name="Амортизатор задній правий", manufacturerInfo={"name": "Sachs"}
    )
    assert match_offer(seed, cand, 0.55).kind == "fuzzy"


def test_search_number_does_not_match_inside_a_longer_title_identifier():
    seed = product(id=1, name="Искомая деталь")
    cand = product(id=2, name="Другая деталь 1234567")

    assert match_offer(seed, cand, 0.99, search_number="123456") is None


def test_search_number_does_not_fall_back_to_fuzzy_name_match():
    seed = product(
        id=1,
        name="Амортизатор задній правий Toyota Camry",
        identifiers={"mpn": "ABC123"},
    )
    candidate = product(
        id=2,
        name="Амортизатор задній правий Toyota Camry",
        identifiers={"mpn": "OTHER456"},
    )

    assert match_offer(seed, candidate, 0.0, search_number="ABC123") is None


def test_search_number_short_numeric_title_requires_an_identifier_label():
    seed = product(id=1, name="Искомая деталь")
    unlabelled = product(id=2, name="Другая деталь 123456")
    labelled = product(id=3, name="Другая деталь OE 123456")
    hash_labelled = product(id=4, name="Другая деталь #123456")

    assert match_offer(seed, unlabelled, 0.99, search_number="123456") is None
    assert match_offer(seed, labelled, 0.99, search_number="123456") == Match(
        "number", 1.0
    )
    assert match_offer(seed, hash_labelled, 0.99, search_number="123456") == Match(
        "number", 1.0
    )


def test_search_number_accepts_grouped_oem_token_but_not_sku_suffix():
    seed = product(id=1, name="Искомая деталь")
    grouped = product(id=2, name="Деталь OE 1K0 121 251")
    suffix = product(id=3, name="Другая деталь", sku="1K0121251A")
    exact = product(id=4, name="Другая деталь", sku="1K0-121-251")

    assert match_offer(seed, grouped, 0.99, search_number="1K0121251") == Match(
        "number", 1.0
    )
    assert match_offer(seed, suffix, 0.99, search_number="1K0121251") is None
    assert match_offer(seed, exact, 0.99, search_number="1K0121251") == Match(
        "number", 1.0
    )


def test_comparison_evidence_normalizes_multilingual_structured_variants() -> None:
    seed = product(
        comparisonEvidence={
            "side": "лівий",
            "position": "передня вісь",
            "bodyVariant": "універсал",
            "condition": "новий",
        }
    )
    candidate = product(
        id=2,
        comparisonEvidence={
            "side": "LEFT",
            "position": "front_axle",
            "bodyVariant": "station-wagon",
            "condition": "NEW",
        },
    )

    evidence = build_product_comparison_evidence(
        seed,
        candidate,
        retrieval_kind="model",
    )

    for dimension in ("side", "position", "body_variant", "condition"):
        assert evidence.dimensions[dimension].state is EvidenceState.MATCH


def test_detail_identity_conflict_forces_manual_comparison_evidence() -> None:
    seed = product(id=1, oe="7E5827505A")
    candidate = replace(
        product(id=2, oe="7E5827505A"),
        detail_evidence={
            "conflicts": {
                "mpn": {"listing": "7E5827505A", "detail": "7E5827505B"},
            }
        },
    )

    evidence = build_product_comparison_evidence(
        seed,
        candidate,
        retrieval_kind="number",
    )

    assert evidence.hard_gate_result.name == "MANUAL_REVIEW"
    assert "DETAIL_IDENTITY_CONFLICT" in evidence.reason_codes


def test_comparison_evidence_only_conflicts_on_recognized_exclusive_values() -> None:
    seed = product(
        comparisonEvidence={
            "side": "лівий",
            "position": "передній",
            "bodyVariant": "седан",
            "condition": "новий",
        }
    )
    candidate = product(
        id=2,
        comparisonEvidence={
            "side": "правий",
            "position": "задній",
            "bodyVariant": "хетчбек",
            "condition": "б/у",
        },
    )

    evidence = build_product_comparison_evidence(
        seed,
        candidate,
        retrieval_kind="model",
    )

    for dimension in ("side", "position", "body_variant", "condition"):
        assert evidence.dimensions[dimension].state is EvidenceState.CONFLICT


def test_opaque_fitment_wording_drift_is_unknown_not_false_conflict() -> None:
    seed = product(
        comparisonEvidence={
            "fitment": "Toyota Camry V40 2006-2011",
            "vehicleGeneration": "XV40",
            "engine": "2.4 бензин",
        }
    )
    candidate = product(
        id=2,
        comparisonEvidence={
            "fitment": "Camry 40 (2006–11)",
            "vehicleGeneration": "Camry 40",
            "engine": "2.4i",
        },
    )

    evidence = build_product_comparison_evidence(
        seed,
        candidate,
        retrieval_kind="model",
    )

    for dimension in ("fitment", "vehicle_generation", "engine"):
        assert evidence.dimensions[dimension].state is EvidenceState.UNKNOWN


# _price_value


def test_price_value_from_price():
    assert _price_value(product(price="1234.5")) == Decimal("1234.5")


def test_price_value_prefers_active_discount_over_crossed_out_price():
    assert _price_value(
        product(price="412", discountedPrice="330", priceOriginal="412")
    ) == Decimal("330")


def test_price_value_rejects_discount_field_above_current_price():
    assert _price_value(
        product(price="330", discountedPrice="412", priceOriginal="412")
    ) == Decimal("330")


def test_price_value_uses_original_when_current_price_is_missing():
    assert _price_value(
        product(price=None, discountedPrice="412", priceOriginal="330")
    ) == Decimal("330")


def test_comparison_serializes_sale_and_reference_prices_separately():
    seed = seed_info(id=1, name="Радіатор VW Touareg", company={"id": 1})
    candidate = product(
        id=2,
        name="Радіатор VW Touareg",
        price="412",
        discountedPrice="330",
        priceOriginal="412",
        company={"id": 2, "name": "Seller"},
    )

    comparison = build_comparison(seed, [candidate], params())

    offer = comparison.as_dict()["offers"][0]
    assert offer["price"] == "330"
    assert offer["sale_price"] == "330"
    assert offer["reference_price"] == "412"
    assert offer["discounted_price"] == "330"


def test_raw_comparison_never_claims_persisted_automatic_admission():
    """The in-memory matcher cannot prove the persisted pricing gates."""

    seed = seed_info(id=1, name="Радіатор VW Touareg", company={"id": 1})
    candidate = product(
        id=2,
        name="Радіатор VW Touareg",
        price="330",
        company={"id": 2, "name": "Seller"},
        comparisonEvidence={
            "oeRaw": "",
            "fitment": "VW Touareg",
            "condition": "new",
            "packageQuantity": 1,
        },
    )

    offer = build_comparison(seed, [candidate], params()).as_dict()["offers"][0]

    assert offer["automatic_eligible"] is False
    assert offer["comparability_hard_gate_pass"] is False
    assert offer["automatic_eligibility_reason"] == (
        "PERSISTED_ADMISSION_NOT_EVALUATED"
    )


def test_price_value_falls_back_to_price_original():
    assert _price_value(product(price=None, priceOriginal="50")) == Decimal("50")


def test_price_value_preserves_decimal_digits_beyond_binary_float_precision():
    raw = "1234.567890123456789"

    assert _price_value(product(price=raw)) == Decimal(raw)
    assert str(_price_value(product(price=raw))) == raw


def test_price_value_none_when_missing():
    assert _price_value(product(price=None, priceOriginal=None)) is None


def test_price_value_garbage_returns_none():
    assert _price_value(product(price="—")) is None


# build_comparison


def test_build_comparison_keeps_cheapest_per_seller():
    seed = seed_info(
        id=1, name="Амортизатор задній правий", company={"id": 1, "name": "A"}
    )
    dear = product(
        id=2,
        name="Амортизатор задній правий",
        price="900",
        company={"id": 5, "name": "B"},
    )
    cheap = product(
        id=3,
        name="Амортизатор задній правий",
        price="700",
        company={"id": 5, "name": "B"},
    )
    comparison = build_comparison(seed, [dear, cheap], params())
    assert [o.price for o in comparison.offers] == [Decimal("700")]


def test_build_comparison_skips_seed_own_seller():
    seed = seed_info(
        id=1, name="Амортизатор задній правий", company={"id": 5, "name": "B"}
    )
    same_seller = product(
        id=2,
        name="Амортизатор задній правий",
        price="700",
        company={"id": 5, "name": "B"},
    )
    assert build_comparison(seed, [same_seller], params()).offers == []


def test_build_comparison_sorts_and_caps_max_sellers():
    seed = seed_info(
        id=1, name="Амортизатор задній правий", company={"id": 1, "name": "A"}
    )
    candidates = [
        product(
            id=i,
            name="Амортизатор задній правий",
            price=str(price),
            company={"id": i, "name": f"S{i}"},
        )
        for i, price in [(2, 900), (3, 500), (4, 700)]
    ]
    comparison = build_comparison(seed, candidates, params(max_sellers=2))
    assert [o.price for o in comparison.offers] == [
        Decimal("500"),
        Decimal("700"),
    ]


def test_build_comparison_counts_all_scanned():
    seed = seed_info(id=1, company={"id": 1, "name": "A"})
    candidates = [
        product(
            id=2, name="нічого спільного", price="1", company={"id": 2, "name": "S"}
        )
    ]
    assert build_comparison(seed, candidates, params()).candidates_scanned == 1


# PriceComparison properties


def test_comparison_stats_min_median_max():
    comp = comparison_with_prices([300, 500, 700])
    assert (comp.min_price, comp.median_price, comp.max_price) == (
        Decimal("300"),
        Decimal("500"),
        Decimal("700"),
    )


def test_comparison_spread_pct():
    comp = comparison_with_prices([100, 150])
    assert comp.spread_pct == 50.0


def test_comparison_savings_vs_seed():
    comp = comparison_with_prices([600], seed_price="1000")
    assert comp.savings_vs_seed == Decimal("400")


def test_comparison_money_serializes_as_decimal_strings():
    comp = comparison_with_prices(
        ["0.100000000000000001", "0.300000000000000003"],
        seed_price="0.500000000000000005",
    )

    payload = comp.as_dict()

    assert payload["stats"]["min_price"] == "0.100000000000000001"
    assert payload["stats"]["median_price"] == "0.200000000000000002"
    assert payload["stats"]["savings_vs_seed"] == "0.400000000000000004"
    assert payload["offers"][0]["price"] == "0.100000000000000001"


def test_comparison_empty_stats_are_none():
    comp = comparison_with_prices([])
    assert (comp.min_price, comp.median_price, comp.spread_pct, comp.cheapest) == (
        None,
        None,
        None,
        None,
    )


# build_search_query


def test_build_query_truncates_tokens_and_prepends_brand():
    p = product(
        name="один два три чотири п'ять шість сім вісім дев'ять",
        manufacturerInfo={"name": "Bosch"},
    )
    query = build_search_query(p)
    assert query.startswith("Bosch ") and len(query.split()) == _MAX_QUERY_TOKENS + 1


def test_build_query_never_uses_private_kemp_code_as_public_identity():
    p = product(
        oe="77642440",
        identifiers={"mpn": "TH652688J"},
        name="Термостат Ford Focus",
    )

    assert build_search_query(p) == "TH652688J"


def test_build_query_falls_back_to_title_when_only_private_kemp_code_exists():
    p = product(oe="77642440", name="Термостат Ford Focus")

    assert build_search_query(p) != "77642440"


def test_build_query_never_uses_seller_sku_as_public_identity():
    p = product(
        id=1153724202,
        sku="1153724202",
        name="Радіатор Iveco 625*440",
    )

    query = build_search_query(p)

    assert query != "1153724202"
    assert "радіатор" in query.casefold()
