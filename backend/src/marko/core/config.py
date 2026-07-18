"""Environment-based application configuration."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Marko API"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://marko@localhost:5432/marko"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    api_docs_enabled: bool | None = None
    allowed_hosts: str = "localhost,127.0.0.1,test,testserver"
    cors_origins: str = "http://localhost:8080,http://localhost:3000"
    cors_allow_credentials: bool = False
    cors_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    cors_headers: str = "Authorization,Content-Type,Accept,Origin,X-Request-ID"
    firebase_project_id: str = ""
    prom_marketplace_source_access_verdict: Literal[
        "PERMITTED_OFFICIAL",
        "PERMITTED_LIMITED",
        "NOT_PERMITTED",
        "UNKNOWN",
    ] = "NOT_PERMITTED"
    prom_marketplace_source_access_reference: str = ""
    pricing_collection_min_interval_seconds: float = 2.0
    pricing_circuit_failure_threshold: int = 5
    pricing_circuit_open_seconds: int = 300
    pricing_dispatch_batch_size: int = 100
    pricing_collection_worker_count: int = 1
    pricing_collection_max_task_executions: int = 4
    pricing_collection_item_deadline_seconds: int = 1800
    pricing_collection_lease_seconds: int = 900
    pricing_collection_task_soft_time_limit_seconds: int = 840
    pricing_collection_task_time_limit_seconds: int = 900
    pricing_scraper_http_timeout_seconds: float = 30.0
    pricing_scraper_http_max_attempts: int = 4
    pricing_scraper_request_delay_seconds: float = 1.0
    pricing_scraper_request_jitter_seconds: float = 0.5
    pricing_scraper_max_search_pages: int = 3
    pricing_scraper_max_sellers: int = 10
    pricing_v3_robust_dispersion_enabled: bool = False
    store_sync_worker_count: int = 2
    store_sync_max_task_executions: int = 3
    store_sync_item_deadline_seconds: int = 3600
    store_sync_lease_seconds: int = 300
    store_sync_task_soft_time_limit_seconds: int = 1740
    store_sync_task_time_limit_seconds: int = 1800
    store_sync_retry_base_delay_seconds: int = 30
    store_sync_scraper_http_timeout_seconds: float = 30.0
    store_sync_scraper_http_max_attempts: int = 4
    store_sync_scraper_max_pages: int = 0
    scrape_raw_evidence_replay_enabled: bool = True
    scrape_evidence_gc_batch_size: int = 1000
    scrape_evidence_gc_interval_seconds: int = 3600
    scrape_outbox_reconcile_batch_size: int = 100
    scrape_outbox_reconcile_interval_seconds: int = 15

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_security_boundary(self) -> Settings:
        environment = self.environment.strip().casefold()
        if not environment:
            raise ValueError("ENVIRONMENT must not be empty")
        if self.cors_allow_credentials and "*" in self.cors_origin_list:
            raise ValueError("Wildcard CORS origins cannot be used with credentials")
        if self.prom_marketplace_source_access_verdict.startswith("PERMITTED_"):
            if not self.prom_marketplace_source_access_reference.strip():
                raise ValueError(
                    "A permitted Prom marketplace source requires an auditable "
                    "PROM_MARKETPLACE_SOURCE_ACCESS_REFERENCE"
                )
        if environment == "production":
            if self.debug:
                raise ValueError("DEBUG must be false in production")
            if not self.allowed_host_list or "*" in self.allowed_host_list:
                raise ValueError(
                    "Production ALLOWED_HOSTS must be explicit and non-empty"
                )
            if "*" in self.cors_origin_list:
                raise ValueError("Production CORS_ORIGINS must not contain a wildcard")
            if not self.firebase_project_id.strip():
                raise ValueError("FIREBASE_PROJECT_ID must be configured in production")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.strip().casefold() == "production"

    @property
    def effective_api_docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return not self.is_production

    @property
    def allowed_host_list(self) -> list[str]:
        return [host.strip() for host in self.allowed_hosts.split(",") if host.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def cors_method_list(self) -> list[str]:
        return [
            method.strip() for method in self.cors_methods.split(",") if method.strip()
        ]

    @property
    def cors_header_list(self) -> list[str]:
        return [
            header.strip() for header in self.cors_headers.split(",") if header.strip()
        ]

    @property
    def firebase_auth_issuer(self) -> str:
        return f"https://securetoken.google.com/{self.firebase_project_id}"

    @property
    def firebase_jwks_url(self) -> str:
        return (
            "https://www.googleapis.com/service_accounts/v1/jwk/"
            "securetoken@system.gserviceaccount.com"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
