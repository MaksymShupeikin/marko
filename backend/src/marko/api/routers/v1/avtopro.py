"""Live competitor price lookup on avto.pro by OEM number."""
from __future__ import annotations

from dataclasses import replace
from statistics import median
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from marko.api.dependencies import CurrentUser
from marko.api.schemas.avtopro import CompetitorOfferResponse, CompetitorSearchResponse
from marko.parsers.avtopro import AvtoproGateway, default_config
from marko.parsers.avtopro.gateway import BASE_URL
from marko.parsers.prom.exceptions import ParseError, RequestFailed

router = APIRouter()


# Sync `def` on purpose: FastAPI runs it in a threadpool, so the scraping
# requests do not block the event loop. Two feed pages keep the call within
# the client's request timeout.
@router.get("/avtopro", response_model=CompetitorSearchResponse)
def search_competitors(
    _current: CurrentUser,
    oem: Annotated[str, Query(min_length=2, max_length=64)],
    brand: Annotated[str | None, Query(max_length=64)] = None,
    # Назва товару підказує марку, коли номер належить кільком одразу.
    name: Annotated[str | None, Query(max_length=512)] = None,
) -> CompetitorSearchResponse:
    gateway = AvtoproGateway(replace(default_config(), max_search_pages=2))
    try:
        result = gateway.offers(oem, brand=brand, name=name)
    except (ParseError, RequestFailed) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"avto.pro недоступен: {exc}",
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="По этому OEM номеру ничего не найдено",
        )
    offers = sorted(result.offers, key=lambda offer: offer.price)
    prices = [offer.price for offer in offers]
    return CompetitorSearchResponse(
        query=oem,
        title=result.suggestion.title,
        brand=result.suggestion.brand,
        is_original=result.suggestion.is_original,
        part_url=BASE_URL + result.suggestion.part_uri,
        offers_total=len(offers),
        min_price=min(prices) if prices else None,
        median_price=round(median(prices), 2) if prices else None,
        max_price=max(prices) if prices else None,
        offers=[
            CompetitorOfferResponse(
                maker=offer.maker,
                code=offer.code,
                description=offer.description,
                city=offer.city,
                availability=offer.availability,
                price=offer.price,
                currency=offer.currency,
                boosted=offer.boosted,
            )
            for offer in offers
        ],
    )
