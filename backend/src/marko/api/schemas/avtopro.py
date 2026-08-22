"""Response schemas for avto.pro competitor price search."""
from __future__ import annotations

from pydantic import BaseModel


class CompetitorOfferResponse(BaseModel):
    maker: str | None
    code: str | None
    description: str | None
    city: str | None
    availability: str | None
    price: float
    currency: str
    boosted: bool


class CompetitorSearchResponse(BaseModel):
    query: str
    title: str
    brand: str | None
    is_original: bool
    part_url: str
    offers_total: int
    min_price: float | None
    median_price: float | None
    max_price: float | None
    offers: list[CompetitorOfferResponse]
