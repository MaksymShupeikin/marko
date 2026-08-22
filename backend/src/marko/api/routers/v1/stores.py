"""Store registration, synchronization, and catalog endpoints."""
from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, get_session
from marko.api.schemas.stores import (
    ProductPageResponse,
    ProductResponse,
    StoreCreateRequest,
    StoreFileImportResponse,
    StoreResponse,
    StoreSyncResponse,
)
from marko.parsers.prom_export import ExportFormatError
from marko.services.catalog_import import import_export_file
from marko.services.stores import (
    StoreNotFoundError,
    TaskDispatchError,
    delete_store,
    get_store,
    list_store_products,
    list_stores,
    queue_store_sync,
    register_store,
)
from marko.worker.celery_app import celery_app

router = APIRouter()


@router.post("", response_model=StoreSyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_store(
    payload: StoreCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> StoreSyncResponse:
    try:
        store_id, sync_run = await register_store(
            session,
            url=payload.url,
            workspace_id=current.workspace_id,
            celery_app=celery_app,
        )
    except TaskDispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return StoreSyncResponse(
        store_id=store_id,
        sync_run_id=sync_run.id,
        status=sync_run.status.value,
    )


_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


@router.post("/import-file", response_model=StoreFileImportResponse)
async def import_catalog_file(
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> StoreFileImportResponse:
    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Файл більший за 25 МБ",
        )
    try:
        result = await import_export_file(
            session,
            workspace_id=current.workspace_id,
            content=content,
        )
    except (ExportFormatError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return StoreFileImportResponse(
        store_id=result.store_id,
        store_name=result.store_name,
        imported=result.imported,
        skipped=result.skipped,
    )


@router.get("", response_model=list[StoreResponse])
async def get_stores(
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> list[StoreResponse]:
    stores = await list_stores(session, current.workspace_id)
    return [StoreResponse(**store.__dict__) for store in stores]


@router.get("/{store_id}", response_model=StoreResponse)
async def get_store_details(
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> StoreResponse:
    try:
        store = await get_store(
            session,
            store_id=store_id,
            workspace_id=current.workspace_id,
        )
    except StoreNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found") from exc
    return StoreResponse(**store.__dict__)


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_store(
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> Response:
    try:
        await delete_store(
            session,
            store_id=store_id,
            workspace_id=current.workspace_id,
        )
    except StoreNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Store not found",
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{store_id}/sync",
    response_model=StoreSyncResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_store(
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
) -> StoreSyncResponse:
    try:
        sync_run = await queue_store_sync(
            session,
            store_id=store_id,
            workspace_id=current.workspace_id,
            celery_app=celery_app,
        )
    except StoreNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found") from exc
    except TaskDispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return StoreSyncResponse(
        store_id=store_id,
        sync_run_id=sync_run.id,
        status=sync_run.status.value,
    )


@router.get("/{store_id}/products", response_model=ProductPageResponse)
async def get_products(
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProductPageResponse:
    try:
        page = await list_store_products(
            session,
            store_id=store_id,
            workspace_id=current.workspace_id,
            limit=limit,
            offset=offset,
        )
    except StoreNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Store not found") from exc
    return ProductPageResponse(
        items=[ProductResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
