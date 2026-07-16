"""Environment-based application configuration."""
from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Marko API"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://marko@localhost:5432/marko"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    cors_origins: str = "http://localhost:8080,http://localhost:3000"
    firebase_project_id: str = ""
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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
