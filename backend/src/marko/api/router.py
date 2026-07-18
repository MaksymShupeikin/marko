"""Top-level API router."""
from __future__ import annotations

from fastapi import APIRouter

from .routers.v1.auth import router as auth_router
from .routers.v1.catalog import router as catalog_router
from .routers.v1.health import router as health_router
from .routers.v1.jobs import router as jobs_router
from .routers.v1.operations import router as operations_router
from .routers.v1.pricing import router as pricing_router
from .routers.v1.stores import router as stores_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
api_router.include_router(stores_router, prefix="/stores", tags=["stores"])
api_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
api_router.include_router(
    operations_router,
    prefix="/operations",
    tags=["operations"],
)
api_router.include_router(pricing_router, prefix="/pricing", tags=["pricing"])
