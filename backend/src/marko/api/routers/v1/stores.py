"""Store registration, synchronization, and catalog endpoints."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from marko.api.dependencies import CurrentUser, WorkspaceAdmin, get_session
from marko.api.schemas.stores import (
    ProductPageResponse,
    ProductResponse,
    StoreCreateRequest,
    StoreResponse,
    StoreSyncResponse,
)
from marko.services.stores import (
    StoreNotFoundError,
    TaskDispatchError,
    delete_owned_store,
    get_store,
    list_store_products,
    list_stores,
    queue_store_sync,
    register_store,
)
from marko.services.seller_url_resolver import (
    PromSellerUrlError,
    PromSellerUrlUnavailable,
)
from marko.worker.celery_app import celery_app

router = APIRouter()


@router.post("", response_model=StoreSyncResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_store(
    payload: StoreCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceAdmin,
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
    except PromSellerUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "PROM_SELLER_URL_UNRESOLVED", "message": str(exc)},
        ) from exc
    except PromSellerUrlUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "PROM_SELLER_URL_UNAVAILABLE", "message": str(exc)},
        ) from exc
    return StoreSyncResponse(
        store_id=store_id,
        sync_run_id=sync_run.id,
        status=sync_run.status.value,
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
async def delete_store(
    store_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    current: WorkspaceAdmin,
) -> Response:
    try:
        await delete_owned_store(
            session,
            store_id=store_id,
            workspace_id=current.workspace_id,
        )
    except StoreNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Store not found"
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
    current: WorkspaceAdmin,
) -> StoreSyncResponse:
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
