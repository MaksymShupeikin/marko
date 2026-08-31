"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from marko.core.config import get_settings, validate_production_settings

from .router import api_router
from .security import SecurityHeadersMiddleware


def create_app() -> FastAPI:
    settings = get_settings()
    validate_production_settings(settings)
    docs_enabled = settings.api_docs_enabled and not settings.is_production
    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    if settings.is_production:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=settings.trusted_host_list,
        )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Accept", "Authorization", "Content-Type"],
    )
    # Added last so even CORS/Host rejections receive the hardening headers.
    application.add_middleware(SecurityHeadersMiddleware, settings=settings)
    application.include_router(api_router, prefix=settings.api_prefix)

    @application.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        payload = {"service": settings.app_name}
        if docs_enabled:
            payload["docs"] = "/docs"
        return payload

    return application


app = create_app()
