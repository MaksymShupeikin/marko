"""Authenticated catalog import and snapshot endpoints."""

from __future__ import annotations

import asyncio
import logging
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
    CatalogDiscoveryRequest,
    CatalogIdentifierEnrichmentResponse,
    CatalogImportPageResponse,
    CatalogImportPreviewResponse,
    CatalogImportResponse,
    CatalogItemPageResponse,
    CatalogItemResponse,
    CatalogKempLinkRebuildRequest,
    CatalogKempLinkReportResponse,
    CatalogMatchRunResponse,
    CatalogMatchStartRequest,
    CatalogOeEnrichmentRequest,
    CatalogOeEnrichmentResponse,
    CatalogTerminalManifestResponse,
    OwnedCatalogPageResponse,
    OwnedCatalogProductResponse,
    OwnedCatalogStoreOptionResponse,
)
from marko.core.config import get_settings
from marko.parsers.prom.exceptions import ParseError, RequestFailed
from marko.services.catalog_competitors import (
    list_catalog_competitors,
    list_catalog_recommendation_summaries,
)
from marko.services.recommendation_export import _export_identity_fields
from marko.services.catalog_discovery import (
    CatalogDiscoveryError,
    collect_catalog_discovery,
    latest_catalog_discovery,
)
from marko.services.catalog_match import (
    CatalogMatchError,
    catalog_match_spend,
    start_catalog_match,
)
from marko.infrastructure.db.models import CatalogMatchRun
from marko.services.catalog_costs import cost_configuration_map
from marko.services.catalog_internal_code_join import (
    catalog_internal_code_join_report,
    rebuild_catalog_internal_code_links,
)
from marko.services.catalog_data_evidence import catalog_data_evidence
from marko.services.attention import (
    mark_source_monitoring_failed,
    start_import_monitoring_run,
)
from marko.services.cost_privacy import privacy_safe_mapping
from marko.services.owned_catalog import (
    enrich_listing_identifiers,
    enrich_listing_oe,
    get_owned_catalog_product,
    list_owned_catalog,
)
from marko.services.source_access import SourceAccessBlocked
from marko.services.unified_product_catalog import (
    get_unified_product,
    list_unified_products,
)
from marko.services.xlsx_catalog import (
    MAX_XLSX_BYTES,
    CatalogImportError,
    build_catalog_terminal_manifest,
    get_import_batch,
    import_catalog_xlsx,
    list_catalog_items,
    list_import_batches,
    parse_mapping_json,
    preview_catalog_xlsx,
)
from marko.services.unified_catalog import SOURCE_XLSX, xlsx_source_id
from marko.worker.celery_app import celery_app

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/competitors", response_model=CatalogCompetitorComparisonResponse)
async def get_catalog_product_competitors(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    product_id: Annotated[UUID | None, Query()] = None,
    sku: Annotated[str | None, Query(max_length=255)] = None,
    oe: Annotated[str | None, Query(max_length=255)] = None,
    mpn: Annotated[str | None, Query(max_length=255)] = None,
    brand: Annotated[str | None, Query(max_length=255)] = None,
) -> CatalogCompetitorComparisonResponse:
    comparison = await list_catalog_competitors(
        session,
        workspace_id=current.workspace_id,
        product_id=product_id,
        sku=sku,
        oe=oe,
        mpn=mpn,
        brand=brand,
    )
    return CatalogCompetitorComparisonResponse.model_validate(comparison)


@router.post(
    "/competitors/discover",
    response_model=CatalogCompetitorComparisonResponse,
    status_code=status.HTTP_201_CREATED,
)
async def discover_catalog_product_competitors(
    payload: CatalogDiscoveryRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogCompetitorComparisonResponse:
    try:
        await collect_catalog_discovery(
            session,
            workspace_id=current.workspace_id,
            sku=payload.sku,
            oe=payload.oe,
            mpn=payload.mpn,
            brand=payload.brand,
            title=payload.title,
            current_price=payload.current_price,
            currency=payload.currency,
            category=payload.category,
        )
    except SourceAccessBlocked as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CatalogDiscoveryError as exc:
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.code
            in {
                "CATALOG_DISCOVERY_IDENTIFIER_REQUIRED",
                "CATALOG_DISCOVERY_IDENTITY_UNRESOLVED",
                "CATALOG_DISCOVERY_IDENTITY_AMBIGUOUS",
            }
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    comparison = await list_catalog_competitors(
        session,
        workspace_id=current.workspace_id,
        product_id=None,
        sku=payload.sku,
        oe=payload.oe,
        mpn=payload.mpn,
        brand=payload.brand,
    )
    return CatalogCompetitorComparisonResponse.model_validate(comparison)


@router.post(
    "/competitors/match",
    response_model=CatalogMatchRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_catalog_product_match(
    payload: CatalogMatchStartRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogMatchRunResponse:
    """Judge the offers this card's last collection saved, off the request thread.

    Returns immediately with a run id. The review itself is minutes of paid
    work -- forty-two distinct products on the card that prompted this feature
    -- and an HTTP request is the wrong place to wait for it.
    """

    settings = get_settings()
    if not settings.catalog_match_enabled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CATALOG_MATCH_DISABLED",
                "message": "Сопоставление моделью выключено в этой среде.",
            },
        )
    snapshot = await latest_catalog_discovery(
        session,
        workspace_id=current.workspace_id,
        sku=payload.sku,
        oe=payload.oe,
        mpn=payload.mpn,
        brand=payload.brand,
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "CATALOG_MATCH_NOTHING_COLLECTED",
                "message": "Сначала соберите объявления с Prom.ua.",
            },
        )
    try:
        run = await start_catalog_match(
            session,
            workspace_id=current.workspace_id,
            discovery_run_id=snapshot.run_id,
            product_snapshot={
                "sku": payload.sku,
                "mpn_norm": payload.mpn,
                "brand": payload.brand,
                "name": payload.title,
                "category": payload.category,
                "characteristics_raw": (
                    {"Стан": payload.condition} if payload.condition else {}
                ),
            },
        )
    except CatalogMatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    celery_app.send_task(
        "marko.worker.process_catalog_match_run", args=[str(run.id)]
    )
    return CatalogMatchRunResponse.model_validate(run)


@router.get(
    "/competitors/match/{match_run_id}",
    response_model=CatalogMatchRunResponse,
)
async def get_catalog_product_match(
    match_run_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogMatchRunResponse:
    run = await session.get(CatalogMatchRun, match_run_id)
    if run is None or run.workspace_id != current.workspace_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Match run not found"
        )
    response = CatalogMatchRunResponse.model_validate(run)
    # Что стоило это нажатие — рядом с самим нажатием, а не в таблице, которую
    # никто не складывает.
    return response.model_copy(
        update={
            "spent_usd": await catalog_match_spend(session, match_run_id=run.id),
        }
    )


@router.post("/products/oe", response_model=CatalogOeEnrichmentResponse)
async def enrich_catalog_product_oe(
    payload: CatalogOeEnrichmentRequest,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogOeEnrichmentResponse:
    try:
        oe = await enrich_listing_oe(
            session,
            workspace_id=current.workspace_id,
            store_id=payload.store_id,
            external_id=payload.external_id,
        )
    except SourceAccessBlocked as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (RequestFailed, ParseError):
        oe = None
    return CatalogOeEnrichmentResponse(oe=oe)


@router.post(
    "/products/identifiers",
    response_model=CatalogIdentifierEnrichmentResponse,
)
async def enrich_catalog_product_identifiers(
    payload: CatalogOeEnrichmentRequest,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogIdentifierEnrichmentResponse:
    try:
        identifiers = await enrich_listing_identifiers(
            session,
            workspace_id=current.workspace_id,
            store_id=payload.store_id,
            external_id=payload.external_id,
        )
    except SourceAccessBlocked as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (RequestFailed, ParseError):
        # Do not convert a failed detail fetch into an invented identifier.
        # The caller may keep using its already persisted fallback fields.
        return CatalogIdentifierEnrichmentResponse(
            oe=None,
            mpn=None,
            status="FETCH_FAILED",
        )
    if identifiers is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog listing not found",
        )
    return CatalogIdentifierEnrichmentResponse(
        oe=identifiers.oe,
        mpn=identifiers.mpn,
        status=identifiers.status,
    )


@router.get("/products", response_model=OwnedCatalogPageResponse)
async def get_owned_catalog_products(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(max_length=255)] = None,
    store_id: Annotated[list[UUID] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OwnedCatalogPageResponse:
    page = await list_owned_catalog(
        session,
        workspace_id=current.workspace_id,
        query=q,
        store_ids=frozenset(store_id) if store_id else None,
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


@router.get("/unified-products", response_model=OwnedCatalogPageResponse)
async def get_unified_catalog_products(
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str | None, Query(max_length=255)] = None,
    store_id: Annotated[list[UUID] | None, Query()] = None,
    kemp_status: Annotated[str | None, Query(max_length=48)] = None,
    no_oem: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 48,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OwnedCatalogPageResponse:
    page = await list_unified_products(
        session,
        workspace_id=current.workspace_id,
        query=q,
        store_ids=frozenset(store_id) if store_id else None,
        limit=limit,
        offset=offset,
        kemp_status=kemp_status,
        no_oem=no_oem,
    )
    return OwnedCatalogPageResponse.model_validate(page)


@router.get(
    "/unified-products/{product_id}",
    response_model=OwnedCatalogProductResponse,
)
async def get_unified_catalog_product(
    product_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OwnedCatalogProductResponse:
    product = await get_unified_product(
        session,
        workspace_id=current.workspace_id,
        product_id=product_id,
    )
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog product not found",
        )
    return OwnedCatalogProductResponse.model_validate(product)


@router.get("/products/{product_id}", response_model=OwnedCatalogProductResponse)
async def get_owned_catalog_product_details(
    product_id: str,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OwnedCatalogProductResponse:
    product = await get_owned_catalog_product(
        session,
        workspace_id=current.workspace_id,
        product_id=product_id,
    )
    if product is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Catalog product not found",
        )
    response = OwnedCatalogProductResponse.model_validate(product)
    recommendations = await list_catalog_recommendation_summaries(
        session,
        workspace_id=current.workspace_id,
        products=(product,),
    )
    recommendation = recommendations.get(product.id)
    if recommendation is None:
        return response
    return response.model_copy(
        update={
            "recommended_price": recommendation.recommended_price,
            "recommendation_currency": recommendation.currency,
            "recommendation_action": recommendation.action,
            "recommendation_computed_at": recommendation.computed_at,
        }
    )


@router.post(
    "/imports/preview",
    response_model=CatalogImportPreviewResponse,
)
async def preview_catalog_import(
    _current: WorkspaceAdmin,
    file: Annotated[UploadFile, File(description="Prom.ua XLSX export")],
) -> CatalogImportPreviewResponse:
    filename = file.filename or "catalog.xlsx"
    if not filename.casefold().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "CATALOG_IMPORT_XLSX_REQUIRED",
                "message": "Only .xlsx files are supported",
            },
        )
    content = await file.read(MAX_XLSX_BYTES + 1)
    await file.close()
    try:
        preview = await asyncio.to_thread(
            preview_catalog_xlsx,
            content,
            filename=filename,
        )
    except CatalogImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "CATALOG_IMPORT_PREVIEW_INVALID", "message": str(exc)},
        ) from exc
    return CatalogImportPreviewResponse.model_validate(
        {
            **preview.__dict__,
            "sheets": [sheet.__dict__ for sheet in preview.sheets],
        }
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
    sheet_name: Annotated[str, Form(min_length=1)],
    mapping: Annotated[str | None, Form()] = None,
) -> CatalogImportResponse:
    filename = file.filename or "catalog.xlsx"
    if not filename.casefold().endswith(".xlsx"):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "CATALOG_IMPORT_XLSX_REQUIRED",
                "message": "Only .xlsx files are supported",
            },
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
        try:
            await start_import_monitoring_run(
                session,
                batch=batch,
                celery_app=celery_app,
            )
        except Exception:
            # The imported catalog is useful even when live Prom collection is
            # unavailable. Products remain visible in the attention queue and
            # monitoring can be retried without asking for the file again.
            failed_batch_id = batch.id
            failed_workspace_id = batch.workspace_id
            failed_filename = batch.filename
            log.exception(
                "Automatic attention pricing could not be started for import %s",
                failed_batch_id,
            )
            try:
                await mark_source_monitoring_failed(
                    session,
                    workspace_id=failed_workspace_id,
                    source_kind=SOURCE_XLSX,
                    source_id=xlsx_source_id(
                        workspace_id=failed_workspace_id,
                        filename=failed_filename,
                    ),
                )
                await session.commit()
            except Exception:
                log.exception(
                    "Failed to move import %s from processing to review",
                    failed_batch_id,
                )
    except CatalogImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "CATALOG_IMPORT_INVALID", "message": str(exc)},
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


@router.get(
    "/imports/{batch_id}/kemp-links",
    response_model=CatalogKempLinkReportResponse,
)
async def get_catalog_import_kemp_links(
    batch_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogKempLinkReportResponse:
    if (
        await get_import_batch(
            session, workspace_id=current.workspace_id, batch_id=batch_id
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Import not found")
    report = await catalog_internal_code_join_report(
        session, workspace_id=current.workspace_id, import_batch_id=batch_id
    )
    return CatalogKempLinkReportResponse.model_validate(report.as_dict())


@router.post(
    "/imports/{batch_id}/kemp-links/preview",
    response_model=CatalogKempLinkReportResponse,
)
async def preview_catalog_import_kemp_links(
    batch_id: UUID,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogKempLinkReportResponse:
    return await get_catalog_import_kemp_links(batch_id, current, session)


@router.post(
    "/imports/{batch_id}/kemp-links/rebuild",
    response_model=CatalogKempLinkReportResponse,
)
async def rebuild_catalog_import_kemp_links(
    batch_id: UUID,
    payload: CatalogKempLinkRebuildRequest,
    current: WorkspaceAdmin,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CatalogKempLinkReportResponse:
    if (
        await get_import_batch(
            session, workspace_id=current.workspace_id, batch_id=batch_id
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Import not found")
    report = await rebuild_catalog_internal_code_links(
        session,
        workspace_id=current.workspace_id,
        import_batch_id=batch_id,
        max_items=payload.max_items,
    )
    return CatalogKempLinkReportResponse.model_validate(report.as_dict())


@router.get(
    "/imports/{batch_id}/terminal-manifest",
    response_model=CatalogTerminalManifestResponse,
)
async def get_catalog_import_terminal_manifest(
    batch_id: UUID,
    current: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_session)],
    run_id: Annotated[UUID | None, Query()] = None,
) -> CatalogTerminalManifestResponse:
    manifest = await build_catalog_terminal_manifest(
        session,
        workspace_id=current.workspace_id,
        batch_id=batch_id,
        run_id=run_id,
    )
    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import not found",
        )
    return CatalogTerminalManifestResponse.model_validate(manifest)


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


# Поля ответа, которые собираются здесь, а не читаются со строки каталога.
# Всё остальное берётся через getattr, поэтому любое поле схемы, которого нет
# у модели, роняет эндпоинт на первой же позиции.
DERIVED_CATALOG_ITEM_FIELDS = frozenset(
    {
        "cost_configured",
        "cost_privacy_mode",
        "raw_row",
        "oe_norm",
        "mpn_norm",
        "search_identity",
        "identity_status",
        "catalog_data_evidence",
    }
)


def _catalog_item_response(
    item: Any, *, cost_configured: bool = False
) -> CatalogItemResponse:
    identity = _export_identity_fields(item)
    public_fields = {
        field: getattr(item, field)
        for field in CatalogItemResponse.model_fields
        if field not in DERIVED_CATALOG_ITEM_FIELDS
    }
    return CatalogItemResponse(
        **public_fields,
        oe_norm=identity["oe"],
        mpn_norm=identity["mpn"],
        search_identity=identity["search_identity"] or None,
        identity_status=identity["identity_status"],
        catalog_data_evidence=catalog_data_evidence(item).as_dict(),
        cost_configured=cost_configured,
        cost_privacy_mode=get_settings().cost_privacy_mode,
        raw_row=privacy_safe_mapping(item.raw_row),
    )
