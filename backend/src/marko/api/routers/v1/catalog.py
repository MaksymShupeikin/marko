"""Authenticated catalog import and snapshot endpoints."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, WorkspaceAdmin, get_session
from marko.api.schemas.catalog import (
    CatalogCompetitorComparisonResponse,
    CatalogImportPageResponse,
    CatalogImportResponse,
    CatalogItemPageResponse,
    CatalogItemResponse,
    OwnedCatalogPageResponse,
    OwnedCatalogProductResponse,
    OwnedCatalogStoreOptionResponse,
)
from marko.core.config import get_settings
from marko.services.catalog_competitors import (
    list_catalog_competitors,
    list_catalog_recommendation_summaries,
)
from marko.services.catalog_costs import cost_configuration_map
from marko.services.cost_privacy import privacy_safe_mapping
from marko.services.owned_catalog import list_owned_catalog
from marko.services.xlsx_catalog import (
    MAX_XLSX_BYTES,
    CatalogImportError,
    get_import_batch,
    import_catalog_xlsx,
    list_catalog_items,
    list_import_batches,
    parse_mapping_json,
)

router = APIRouter()


@router.get("/competitors", response_model=CatalogCompetitorComparisonResponse)
async def get_catalog_product_competitors(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    sku: Annotated[str | None, Query(max_length=255)] = None,
    oe: Annotated[str | None, Query(max_length=255)] = None,
    brand: Annotated[str | None, Query(max_length=255)] = None,
) -> CatalogCompetitorComparisonResponse:
    comparison = await list_catalog_competitors(
        session,
        workspace_id=current.workspace_id,
        sku=sku,
        oe=oe,
        brand=brand,
    )
    return CatalogCompetitorComparisonResponse.model_validate(comparison)


@router.get("/products", response_model=OwnedCatalogPageResponse)
async def get_owned_catalog_products(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(max_length=255)] = None,
    store_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OwnedCatalogPageResponse:
    page = await list_owned_catalog(
        session,
        workspace_id=current.workspace_id,
        query=q,
        store_id=store_id,
        limit=limit,
        offset=offset,
    )
    recommendations = await list_catalog_recommendation_summaries(
        session,
        workspace_id=current.workspace_id,
        products=page.items,
    )
    item_responses = []
    for item in page.items:
        response = OwnedCatalogProductResponse.model_validate(item)
        recommendation = recommendations.get(item.id)
        if recommendation is not None:
            response = response.model_copy(
                update={
                    "recommended_price": recommendation.recommended_price,
                    "recommendation_currency": recommendation.currency,
                    "recommendation_action": recommendation.action,
                    "recommendation_computed_at": recommendation.computed_at,
                }
            )
        item_responses.append(response)
    return OwnedCatalogPageResponse(
        items=item_responses,
        total=page.total,
        catalog_total=page.catalog_total,
        listing_total=page.listing_total,
        duplicates_removed=page.duplicates_removed,
        store_total=page.store_total,
        stores=[
            OwnedCatalogStoreOptionResponse.model_validate(store)
            for store in page.stores
        ],
        limit=page.limit,
        offset=page.offset,
    )


@router.post(
    "/imports",
    response_model=CatalogImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_catalog(
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
    file: Annotated[UploadFile, File(description="Prom.ua XLSX export")],
    mapping: Annotated[str | None, Form()] = None,
    sheet_name: Annotated[str | None, Form()] = None,
) -> CatalogImportResponse:
    filename = file.filename or "catalog.xlsx"
    if not filename.casefold().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only .xlsx files are supported",
        )
    content = await file.read(MAX_XLSX_BYTES + 1)
    await file.close()
    try:
        explicit_mapping = parse_mapping_json(mapping)
        batch = await import_catalog_xlsx(
            session,
            workspace_id=current.workspace_id,
            filename=filename,
            content=content,
            explicit_mapping=explicit_mapping,
            sheet_name=sheet_name,
            user_id=current.user.id,
        )
    except CatalogImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return CatalogImportResponse.model_validate(batch)


@router.get("/imports", response_model=CatalogImportPageResponse)
async def get_catalog_imports(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogImportPageResponse:
    items, total = await list_import_batches(
        session,
        workspace_id=current.workspace_id,
        limit=limit,
        offset=offset,
    )
    return CatalogImportPageResponse(
        items=[CatalogImportResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/imports/{batch_id}", response_model=CatalogImportResponse)
async def get_catalog_import(
    batch_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogImportResponse:
    batch = await get_import_batch(
        session, workspace_id=current.workspace_id, batch_id=batch_id
    )
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Import not found"
        )
    return CatalogImportResponse.model_validate(batch)


@router.get("/items", response_model=CatalogItemPageResponse)
async def get_catalog_items(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    batch_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogItemPageResponse:
    if (
        batch_id is not None
        and await get_import_batch(
            session, workspace_id=current.workspace_id, batch_id=batch_id
        )
        is None
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Import not found"
        )
    items, total = await list_catalog_items(
        session,
        workspace_id=current.workspace_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )
    cost_state = await cost_configuration_map(
        session,
        workspace_id=current.workspace_id,
        catalog_item_ids=(item.id for item in items),
    )
    return CatalogItemPageResponse(
        items=[
            _catalog_item_response(
                item,
                cost_configured=cost_state.get(item.id, False),
            )
            for item in items
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


def _catalog_item_response(
    item: Any, *, cost_configured: bool = False
) -> CatalogItemResponse:
    public_fields = {
        field: getattr(item, field)
        for field in CatalogItemResponse.model_fields
        if field not in {"cost_configured", "cost_privacy_mode", "raw_row"}
    }
    return CatalogItemResponse(
        **public_fields,
        cost_configured=cost_configured,
        cost_privacy_mode=get_settings().cost_privacy_mode,
        raw_row=privacy_safe_mapping(item.raw_row),
    )
