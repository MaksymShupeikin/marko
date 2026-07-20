"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from marko.core.config import get_settings
from marko.services.source_access import SourceAccessBlocked
from marko.services.cost_privacy import privacy_safe_validation_errors

from .router import api_router


def create_app() -> FastAPI:
    settings = get_settings()
    docs_enabled = settings.effective_api_docs_enabled
    application = FastAPI(
        title=settings.app_name,
        debug=settings.debug,
        version="0.1.0",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.allowed_host_list,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_method_list,
        allow_headers=settings.cors_header_list,
    )
    application.include_router(api_router, prefix=settings.api_prefix)
    if settings.environment.strip().casefold() == "e2e" and settings.e2e_auth_bypass:
        from .routers.e2e import router as e2e_router

        application.include_router(
            e2e_router,
            prefix=f"{settings.api_prefix}/e2e",
            tags=["e2e"],
        )

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=()",
        )
        if settings.is_production and request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response

    @application.exception_handler(SourceAccessBlocked)
    async def source_access_blocked_handler(
        _request: Request,
        exc: SourceAccessBlocked,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={
                "detail": {
                    "code": exc.code,
                    "message": str(exc),
                    "verdict": exc.verdict,
                    "reference": exc.reference,
                }
            },
        )

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": privacy_safe_validation_errors(exc.errors())},
        )

    @application.get("/", include_in_schema=False)
    async def root() -> dict[str, str | bool | None]:
        return {
            "service": settings.app_name,
            "docs_enabled": docs_enabled,
            "docs": "/docs" if docs_enabled else None,
        }

    return application


app = create_app()
