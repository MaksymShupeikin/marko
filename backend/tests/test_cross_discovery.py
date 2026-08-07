from marko.services.cross_discovery import evaluate_cross_discovery_product
from marko.services.parser_models import Product


def _product(**overrides) -> Product:
    raw = {
        "id": 1,
        "name": "Радіатор новий",
        "sku": "1K0-121-251",
        "price": "1000",
        "priceCurrency": "UAH",
        "presence": {"isAvailable": True, "presence": "avail"},
        "company": {"id": 20, "name": "Independent", "slug": "independent"},
        "manufacturerInfo": {"name": "KEMP"},
        "urlText": "radiator",
    }
    raw.update(overrides)
    return Product.from_raw(raw)


def test_independent_kemp_exact_cross_is_retained() -> None:
    result = evaluate_cross_discovery_product(
        _product(), cross_oe="1K0121251", owned_seller_ids={"10"}
    )

    assert result["exact"] is True
    assert result["independent_kemp"] is True
    assert result["discovery_candidate"] is True
    assert result["pricing_eligible"] is False


def test_owned_seller_is_excluded_even_when_exact() -> None:
    result = evaluate_cross_discovery_product(
        _product(company={"id": 10, "name": "Yuri", "slug": "yuri"}),
        cross_oe="1K0121251",
        owned_seller_ids={"10"},
    )

    assert result["owned"] is True
    assert result["discovery_candidate"] is False
    assert "OWNED_SELLER" in result["reason_codes"]


def test_title_only_cross_is_not_counted_as_exact() -> None:
    result = evaluate_cross_discovery_product(
        _product(sku="OTHER-1", name="Радіатор 1K0121251"),
        cross_oe="1K0121251",
        owned_seller_ids={"10"},
    )

    assert result["exact"] is False
    assert result["discovery_candidate"] is False
    assert "NOT_EXACT_CROSS_SKU_OR_OE" in result["reason_codes"]


def test_candidate_mpn_is_a_native_cross_identifier() -> None:
    result = evaluate_cross_discovery_product(
        _product(sku="SELLER-SKU", identifiers={"mpn": "1K0 121 251"}),
        cross_oe="1K0121251",
        owned_seller_ids={"10"},
    )

    assert result["exact"] is True
    assert result["discovery_candidate"] is True


def test_private_kemp_code_is_not_a_cross_identifier() -> None:
    result = evaluate_cross_discovery_product(
        _product(sku="776414", identifiers={"mpn": "776414"}),
        cross_oe="776414",
        owned_seller_ids={"10"},
    )

    assert result["exact"] is False
    assert "NOT_EXACT_CROSS_SKU_OR_OE" in result["reason_codes"]


def test_private_kemp_code_is_not_a_cross_target() -> None:
    result = evaluate_cross_discovery_product(
        _product(sku="PUBLIC-123", identifiers={"mpn": "PUBLIC-123"}),
        cross_oe="776414",
        owned_seller_ids={"10"},
    )

    assert result["exact"] is False
    assert "NOT_EXACT_CROSS_SKU_OR_OE" in result["reason_codes"]


def test_normalized_search_snapshot_round_trips_without_losing_evidence() -> None:
    original = _product()

    restored = Product.from_normalized_snapshot(original.as_dict())
    result = evaluate_cross_discovery_product(
        restored, cross_oe="1K0121251", owned_seller_ids={"10"}
    )

    assert restored.seller_id == 20
    assert restored.is_available is True
    assert result["discovery_candidate"] is True
    assert result["pricing_eligible"] is False


def test_legacy_normalized_snapshot_defaults_new_fields_without_losing_evidence() -> None:
    snapshot = _product().as_dict()
    snapshot.pop("characteristics")

    restored = Product.from_normalized_snapshot(snapshot)
    result = evaluate_cross_discovery_product(
        restored, cross_oe="1K0121251", owned_seller_ids={"10"}
    )

    assert restored.characteristics is None
    assert restored.seller_id == 20
    assert restored.is_available is True
    assert result["discovery_candidate"] is True


def test_normalized_snapshot_rejects_unknown_schema_fields() -> None:
    snapshot = _product().as_dict()
    snapshot["unexpected_future_field"] = "unsafe"

    try:
        Product.from_normalized_snapshot(snapshot)
    except ValueError as exc:
        assert "unexpected_future_field" in str(exc)
    else:
        raise AssertionError("unknown normalized snapshot field was silently ignored")
