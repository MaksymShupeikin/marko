from marko.services.matching import (
    _MAX_QUERY_TOKENS,
    Match,
    _price_value,
    _token_similarity,
    brands_compatible,
    build_comparison,
    build_search_query,
    laterality_conflict,
    match_offer,
    normalize_tokens,
)

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
    seed = product(id=1, sku="S1")
    cand = product(id=2, name="геть інша назва", sku="S1")
    assert match_offer(seed, cand, 0.55).kind == "sku"


def test_match_offer_exact_model_ignores_brand_as_identity_gate():
    seed = product(id=1, **{"model": {"id": "M1"}}, manufacturerInfo={"name": "Bosch"})
    cand = product(id=2, **{"model": {"id": "M1"}}, manufacturerInfo={"name": "Sachs"})
    assert match_offer(seed, cand, 0.01) == Match("model", 1.0)


def test_match_offer_exact_sku_does_not_bypass_laterality_conflict():
    seed = product(id=1, sku="S1", name="Фара ліва")
    cand = product(id=2, sku="S1", name="Фара права")
    assert match_offer(seed, cand, 0.01) is None


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


# _price_value


def test_price_value_from_price():
    assert _price_value(product(price="1234.5")) == 1234.5


def test_price_value_falls_back_to_price_original():
    assert _price_value(product(price=None, priceOriginal="50")) == 50.0


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
    assert [o.price for o in comparison.offers] == [700.0]


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
    assert [o.price for o in comparison.offers] == [500.0, 700.0]


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
    assert (comp.min_price, comp.median_price, comp.max_price) == (300.0, 500.0, 700.0)


def test_comparison_spread_pct():
    comp = comparison_with_prices([100, 150])
    assert comp.spread_pct == 50.0


def test_comparison_savings_vs_seed():
    comp = comparison_with_prices([600], seed_price="1000")
    assert comp.savings_vs_seed == 400.0


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
