"""Ручний пошук цін конкурентів за OEM-номером і брендом.

Той самий конвеєр, що й у картці товару (`products/{id}/competitor-prices`):
Prom.ua разом з Avto.pro, відсіювання моделлю, ті самі поля у відповіді.
Різниця лише в тому, звідки взявся запит — з форми, а не з каталогу.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, get_session
from marko.api.schemas.competitor_prices import CompetitorPriceReportResponse
from marko.api.sse import competitor_price_stream
from marko.services.billing import consume_check
from marko.services.competitor_prices import (
    competitor_prices_for_query,
    manual_search_query,
)
from marko.services.seller_exclusions import load_prom_seller_exclusions

router = APIRouter()

OemQuery = Annotated[str, Query(min_length=2, max_length=64)]
BrandQuery = Annotated[str | None, Query(max_length=64)]
# Назва товару підказує марку, коли номер належить кільком одразу.
NameQuery = Annotated[str | None, Query(max_length=512)]


@router.get("/search", response_model=CompetitorPriceReportResponse)
async def search_competitors(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    oem: OemQuery,
    brand: BrandQuery = None,
    name: NameQuery = None,
    refresh: bool = False,
) -> CompetitorPriceReportResponse:
    await consume_check(session, current.workspace_id)
    exclusions = await load_prom_seller_exclusions(session, current.workspace_id)
    payload = await competitor_prices_for_query(
        manual_search_query(oem, brand, name, seller_exclusions=exclusions),
        refresh=refresh,
    )
    if not payload["stats"]["offers_total"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="За цим запитом пропозицій не знайдено",
        )
    return CompetitorPriceReportResponse.model_validate(payload)


@router.get("/search/stream")
async def search_competitors_stream(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    oem: OemQuery,
    brand: BrandQuery = None,
    name: NameQuery = None,
    refresh: bool = False,
) -> StreamingResponse:
    """Те саме, але з підписами стадій, поки джерела ще збираються."""
    # Пейвол — до старту потоку: у генераторі сесії вже немає (див. sse.py).
    await consume_check(session, current.workspace_id)
    exclusions = await load_prom_seller_exclusions(session, current.workspace_id)
    return competitor_price_stream(
        manual_search_query(oem, brand, name, seller_exclusions=exclusions),
        refresh=refresh,
    )
