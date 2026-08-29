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


class CompetitorPriceReportResponse(BaseModel):
    query: CompetitorPriceQueryResponse
    cached: bool
    observed_at: datetime
    stats: CompetitorPriceStatsResponse
    sources: list[SourcePriceResponse]
