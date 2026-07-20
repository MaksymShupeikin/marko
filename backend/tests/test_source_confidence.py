from decimal import Decimal

import pytest

from marko.api.schemas.pricing import CompetitorOfferInput
from marko.services.offer_processing import assess_source_confidence
from metis.pricing import CompetitorOffer


def _assessment(**overrides):
    values = {
        "raw_capture_verified": True,
        "parser_contract_verified": True,
        "listing_identity_quality": Decimal("1"),
        "seller_identity_quality": Decimal("1"),
        "price_currency_quality": Decimal("1"),
        "availability_quality": Decimal("1"),
        "url_quality": Decimal("1"),
        "structured_completeness": Decimal("1"),
    }
    values.update(overrides)
    return assess_source_confidence(**values)


def test_source_confidence_defaults_fail_closed() -> None:
    assert CompetitorOffer.__dataclass_fields__["source_confidence"].default == Decimal(
        "0"
    )
    assert CompetitorOfferInput.model_fields["source_confidence"].default == Decimal(
        "0"
    )


def test_complete_verified_source_can_receive_one() -> None:
    result = _assessment()

    assert result.value == Decimal("1.0000")
    assert result.reason_codes == ()
    assert result.method_version == "source-confidence-v1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("listing_identity_quality", Decimal("0.75")),
        ("seller_identity_quality", Decimal("0.35")),
        ("price_currency_quality", Decimal("0.60")),
        ("availability_quality", Decimal("0.60")),
        ("url_quality", Decimal("0.40")),
        ("structured_completeness", Decimal("0.80")),
    ],
)
def test_any_incomplete_factor_prevents_confidence_one(field, value) -> None:
    result = _assessment(**{field: value})

    assert Decimal("0") < result.value < Decimal("1")
    factor_key = field.removesuffix("_quality")
    assert result.factors[factor_key] == format(value, "f")


@pytest.mark.parametrize(
    "gate",
    ["raw_capture_verified", "parser_contract_verified"],
)
def test_unverified_foundational_provenance_forces_zero(gate: str) -> None:
    result = _assessment(**{gate: False})

    assert result.value == 0
    assert result.reason_codes


def test_out_of_range_factor_is_rejected() -> None:
    with pytest.raises(ValueError):
        _assessment(structured_completeness=Decimal("1.01"))
