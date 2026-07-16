"""Public pricing-domain API."""

from .calibration import (
    calibration_dataset_hash,
    fit_shrinkage_coefficients,
    fit_simple_coefficients,
)
from .engine import recommend_price
from .tiering import DEFAULT_BRAND_TIERS, classify_tier, normalize_brand
from .types import (
    CalibrationPair,
    CoefficientModel,
    CompetitorOffer,
    ConfidenceAggregation,
    ExcludedOffer,
    NormalizedOffer,
    PricingPolicy,
    PricingResult,
    PriorityScoreType,
    ProductPricingContext,
    ProductTier,
    RecommendationAction,
    StockStatus,
    TierClassification,
    TierCoefficient,
)

__all__ = [
    "CalibrationPair",
    "CoefficientModel",
    "CompetitorOffer",
    "ConfidenceAggregation",
    "DEFAULT_BRAND_TIERS",
    "ExcludedOffer",
    "NormalizedOffer",
    "PricingPolicy",
    "PricingResult",
    "PriorityScoreType",
    "ProductPricingContext",
    "ProductTier",
    "RecommendationAction",
    "StockStatus",
    "TierClassification",
    "TierCoefficient",
    "calibration_dataset_hash",
    "classify_tier",
    "fit_shrinkage_coefficients",
    "fit_simple_coefficients",
    "normalize_brand",
    "recommend_price",
]
