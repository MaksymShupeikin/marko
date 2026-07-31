"""Top-level API router."""

from __future__ import annotations

from fastapi import APIRouter

from .schemas.errors import error_responses
from .routers.v1.auth import router as auth_router
from .routers.v1.catalog import router as catalog_router
from .routers.v1.health import router as health_router
from .routers.v1.fitment import router as fitment_router
from .routers.v1.jobs import router as jobs_router
from .routers.v1.operations import router as operations_router
from .routers.v1.pricing import router as pricing_router
from .routers.v1.stores import router as stores_router

api_router = APIRouter()
api_router.include_router(
    health_router,
    prefix="/health",
    tags=["health"],
    responses=error_responses(500, 503),
)
api_router.include_router(
    auth_router,
    prefix="/auth",
    tags=["auth"],
    responses=error_responses(401, 409, 422, 500, 503),
)
api_router.include_router(
    catalog_router,
    prefix="/catalog",
    tags=["catalog"],
    responses=error_responses(401, 403, 404, 409, 415, 422, 500, 503),
)
api_router.include_router(
    stores_router,
    prefix="/stores",
    tags=["stores"],
    responses=error_responses(401, 403, 404, 409, 422, 500, 503),
)
api_router.include_router(
    jobs_router,
    prefix="/jobs",
    tags=["jobs"],
    responses=error_responses(401, 403, 404, 409, 422, 500, 503),
)
api_router.include_router(
    operations_router,
    prefix="/operations",
    tags=["operations"],
    responses=error_responses(401, 403, 404, 409, 422, 500, 503),
)
api_router.include_router(
    pricing_router,
    prefix="/pricing",
    tags=["pricing"],
    responses=error_responses(401, 403, 404, 409, 422, 500, 503),
)


def include_fitment_router(router: APIRouter) -> None:
    """Publish the fitment surface, which this delivery deliberately withholds.

    Kept out of the module-level router so the phase boundary is a deployment
    decision read from settings at application build time, rather than something
    fixed at import time and therefore untestable in both states.
    """

    router.include_router(
        fitment_router,
        prefix="/fitment",
        tags=["fitment"],
        responses=error_responses(401, 403, 404, 409, 422, 500, 503),
    )
