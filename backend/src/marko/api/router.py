"""Top-level API router."""
from __future__ import annotations

from fastapi import APIRouter

from .routers.v1.auth import router as auth_router
from .routers.v1.avtopro import router as avtopro_router
from .routers.v1.health import router as health_router
from .routers.v1.jobs import router as jobs_router
from .routers.v1.products import router as products_router
from .routers.v1.stores import router as stores_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(stores_router, prefix="/stores", tags=["stores"])
api_router.include_router(products_router, prefix="/products", tags=["products"])
api_router.include_router(jobs_router, prefix="/jobs", tags=["jobs"])
api_router.include_router(avtopro_router, prefix="/competitors", tags=["competitors"])
