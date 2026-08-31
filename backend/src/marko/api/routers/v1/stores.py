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

from marko.api.dependencies import CurrentUser, WorkspaceManager, get_session
from marko.api.schemas.stores import (
    ProductPageResponse,
    ProductResponse,
    StoreCreateRequest,
    StoreFileImportResponse,
    StoreResponse,
    StoreSyncResponse,
)
from marko.core.config import get_settings
from marko.parsers.prom_export import ExportFormatError
from marko.services.catalog_import import import_export_file
from marko.services.rate_limit import enforce_workspace_limit
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
    current: WorkspaceManager,
) -> StoreSyncResponse:
    await enforce_workspace_limit(
        current.workspace_id,
        policy="store-create",
        limit=6,
        window_seconds=600,
    )
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


_UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    content = bytearray()
    try:
        while True:
            remaining = max_bytes - len(content)
            chunk = await file.read(min(_UPLOAD_CHUNK_BYTES, remaining + 1))
            if not chunk:
                return bytes(content)
            content.extend(chunk)
            if len(content) > max_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    detail=f"Файл більший за {max_bytes // (1024 * 1024)} МБ",
                )
    finally:
        await file.close()


@router.post("/import-file", response_model=StoreFileImportResponse)
async def import_catalog_file(
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceManager,
    file: Annotated[UploadFile, File()],
) -> StoreFileImportResponse:
    await enforce_workspace_limit(
        current.workspace_id,
        policy="catalog-upload",
        limit=3,
        window_seconds=600,
    )
    if not (file.filename or "").casefold().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Підтримуються лише файли .xlsx",
        )
    content = await _read_upload_limited(file, get_settings().upload_max_bytes)
    try:
        result = await import_export_file(
            session,
            workspace_id=current.workspace_id,
            content=content,
        )
    except (ExportFormatError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
        ) from exc
    return StoreResponse(**store.__dict__)


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_store(
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceManager,
) -> Response:
    await enforce_workspace_limit(
        current.workspace_id,
        policy="store-mutation",
        limit=20,
        window_seconds=600,
    )
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
    current: WorkspaceManager,
) -> StoreSyncResponse:
    await enforce_workspace_limit(
        current.workspace_id,
        policy="store-sync",
        limit=12,
        window_seconds=600,
    )
    try:
        sync_run = await queue_store_sync(
            session,
            store_id=store_id,
            workspace_id=current.workspace_id,
            celery_app=celery_app,
        )
    except StoreNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
        ) from exc
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
        ) from exc
    return ProductPageResponse(
        items=[ProductResponse.model_validate(item) for item in page.items],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
    )
