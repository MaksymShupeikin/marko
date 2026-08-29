"""Response schemas for aggregated competitor marketplace prices."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class CompetitorPriceQueryResponse(BaseModel):
    listing_id: str
    oem_numbers: list[str] | tuple[str, ...]
    brand: str | None
    name: str
    source_url: str


class MarketOfferResponse(BaseModel):
    source: str
    title: str
    price: str
    currency: str
    url: str
    seller: str | None = None
    city: str | None = None
    availability: str | None = None
    condition: str | None = None
    image_url: str | None = None
    confidence: float = 1.0
    is_analog: bool = False
    verified: bool = False
    original_price: str | None = None
    original_currency: str | None = None
    exchange_rate: str | None = None
    exchange_rate_date: str | None = None
    verified_at: datetime | None = None
    price_changed_on_page: bool = False


class SourcePriceResponse(BaseModel):
    source: str
    label: str
    status: str
    error: str | None = None
    offers_total: int
    min_price: str | None = None
    median_price: str | None = None
    max_price: str | None = None
    offers: list[MarketOfferResponse] = Field(default_factory=list)


class CompetitorPriceStatsResponse(BaseModel):
    offers_total: int
    eligible_offers_total: int = 0
    sources_total: int
    min_price: str | None = None
    median_price: str | None = None
    max_price: str | None = None
    recommended_price: str | None = None
    recommended_price_from: str | None = None
    recommended_price_to: str | None = None
    recommended_discount_percent: int = 6
    recommended_discount_min_percent: int = 5
    recommended_discount_max_percent: int = 7
    slider_discount_min_percent: int = 1
    slider_discount_max_percent: int = 30
    pricing_status: str = "insufficient"


class CompetitorPriceReportResponse(BaseModel):
    query: CompetitorPriceQueryResponse
    cached: bool
    observed_at: datetime
    stats: CompetitorPriceStatsResponse
    sources: list[SourcePriceResponse]
