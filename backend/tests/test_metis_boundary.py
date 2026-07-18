"""Application-to-kernel ownership contract."""

from metis.pricing import (
    PricingPolicy as MetisPricingPolicy,
    RobustScaleMethod as MetisRobustScaleMethod,
    qn_scale as metis_qn_scale,
    recommend_price as metis_recommend_price,
)
from marko.pricing import (
    PricingPolicy as CompatibilityPricingPolicy,
    RobustScaleMethod as CompatibilityRobustScaleMethod,
    qn_scale as compatibility_qn_scale,
    recommend_price as compatibility_recommend_price,
)


def test_marko_compatibility_path_resolves_to_metis_kernel() -> None:
    assert CompatibilityPricingPolicy is MetisPricingPolicy
    assert compatibility_recommend_price is metis_recommend_price
    assert CompatibilityRobustScaleMethod is MetisRobustScaleMethod
    assert compatibility_qn_scale is metis_qn_scale
