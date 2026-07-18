"""Authenticated catalog import and snapshot endpoints."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, WorkspaceAdmin, get_session
from marko.api.schemas.catalog import (
    CatalogImportPageResponse,
    CatalogImportResponse,
    CatalogItemPageResponse,
    CatalogItemResponse,
)
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found")
    return CatalogImportResponse.model_validate(batch)


@router.get("/items", response_model=CatalogItemPageResponse)
async def get_catalog_items(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    batch_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=250)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogItemPageResponse:
    if batch_id is not None and await get_import_batch(
        session, workspace_id=current.workspace_id, batch_id=batch_id
    ) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Import not found")
    items, total = await list_catalog_items(
        session,
        workspace_id=current.workspace_id,
        batch_id=batch_id,
        limit=limit,
        offset=offset,
    )
    return CatalogItemPageResponse(
        items=[CatalogItemResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
