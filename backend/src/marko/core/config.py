"""Environment-based application configuration."""

from __future__ import annotations

from decimal import Decimal
from functools import cached_property, lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from marko.core.cost_encryption import CostKeyring, parse_cost_keyring


class Settings(BaseSettings):
    app_name: str = "Marko API"
    build_identity: str = "NOT_AVAILABLE"
    environment: str = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    database_url: str = "postgresql+asyncpg://marko@localhost:5432/marko"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    celery_visibility_timeout_seconds: int = Field(default=3600, gt=0)
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
    cost_privacy_mode: Literal[
        "UNDECIDED",
        "LOCAL_DEVICE_ONLY",
        "SERVER_SIDE_ENCRYPTED",
    ] = "UNDECIDED"
    cost_encryption_active_key_id: str = ""
    cost_encryption_keys_json: SecretStr = SecretStr("")
    pricing_collection_min_interval_seconds: float = 2.0
    pricing_circuit_failure_threshold: int = 5
    pricing_circuit_open_seconds: int = 300
    pricing_dispatch_batch_size: int = 100
    pricing_oe_reenrichment_batch_size: int = Field(default=100, ge=1, le=1000)
    pricing_parser_schema_changed_alert_count: int = Field(default=0, ge=0)
    pricing_parser_schema_changed_critical_rate: Decimal = Field(
        default=Decimal("0.01"), ge=0, le=1
    )
    pricing_offer_internal_failure_alert_count: int = Field(default=0, ge=0)
    pricing_evidence_accounting_error_critical_count: int = Field(default=0, ge=0)
    pricing_verified_oe_drop_warning_delta: Decimal = Field(
        default=Decimal("0.20"), ge=0, le=1
    )
    pricing_source_confidence_p50_drop_warning_delta: Decimal = Field(
        default=Decimal("0.15"), ge=0, le=1
    )
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
    pricing_brand_tiers_path: str = ""
    pricing_crosses_path: str = "config/crosses.yaml"
    pricing_v3_robust_dispersion_enabled: bool = False
    pricing_v3_activation_artifact: str = ""
    pricing_v3_activation_sha256: str = ""
    pricing_comparability_v1_automatic_enabled: bool = False
    pricing_comparability_activation_artifact: str = ""
    pricing_comparability_activation_sha256: str = ""
    e2e_auth_bypass: bool = False
    e2e_auth_token: str = ""
    e2e_task_hold_seconds: float = 0.0
    public_api_base_url: str = ""
    firebase_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_messaging_sender_id: str = ""
    firebase_web_app_id: str = ""
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
    store_url_resolver_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    store_url_resolver_max_redirects: int = Field(default=3, ge=0, le=10)
    store_url_resolver_max_response_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=64 * 1024,
        le=10 * 1024 * 1024,
    )
    scrape_raw_evidence_replay_enabled: bool = True
    scrape_evidence_gc_batch_size: int = 1000
    scrape_evidence_gc_interval_seconds: int = 3600
    scrape_outbox_reconcile_batch_size: int = 100
    scrape_outbox_reconcile_interval_seconds: int = 15
    scheduler_singleton_lock_key: str = "marko:scheduler:singleton:v1"
    scheduler_singleton_ttl_seconds: int = Field(default=90, ge=30, le=600)
    scheduler_singleton_refresh_seconds: int = Field(default=20, ge=1, le=120)
    scheduler_singleton_reacquire_initial_seconds: float = Field(
        default=1.0, ge=0.1, le=60
    )
    scheduler_singleton_reacquire_max_seconds: float = Field(
        default=30.0, ge=0.1, le=300
    )
    scheduler_health_state_path: str = "/tmp/marko-scheduler-health.json"

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
        if self.e2e_auth_bypass:
            if environment != "e2e":
                raise ValueError("E2E_AUTH_BYPASS is allowed only in ENVIRONMENT=e2e")
            if len(self.e2e_auth_token) < 32:
                raise ValueError(
                    "E2E_AUTH_TOKEN must contain at least 32 characters when bypass is enabled"
                )
        elif self.e2e_auth_token:
            raise ValueError("E2E_AUTH_TOKEN requires E2E_AUTH_BYPASS=true")
        if self.e2e_task_hold_seconds < 0:
            raise ValueError("E2E_TASK_HOLD_SECONDS must not be negative")
        if self.e2e_task_hold_seconds and environment != "e2e":
            raise ValueError("E2E_TASK_HOLD_SECONDS is allowed only in ENVIRONMENT=e2e")
        if self.scheduler_singleton_refresh_seconds * 2 >= (
            self.scheduler_singleton_ttl_seconds
        ):
            raise ValueError(
                "SCHEDULER_SINGLETON_REFRESH_SECONDS must be less than half "
                "SCHEDULER_SINGLETON_TTL_SECONDS"
            )
        if (
            self.scheduler_singleton_reacquire_max_seconds
            < self.scheduler_singleton_reacquire_initial_seconds
        ):
            raise ValueError(
                "SCHEDULER_SINGLETON_REACQUIRE_MAX_SECONDS must not be less than "
                "SCHEDULER_SINGLETON_REACQUIRE_INITIAL_SECONDS"
            )
        if not Path(self.scheduler_health_state_path).is_absolute():
            raise ValueError("SCHEDULER_HEALTH_STATE_PATH must be absolute")
        if self.cost_privacy_mode == "SERVER_SIDE_ENCRYPTED":
            parse_cost_keyring(
                active_key_id=self.cost_encryption_active_key_id,
                keys_json=self.cost_encryption_keys_json.get_secret_value(),
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
            if self.pricing_v3_robust_dispersion_enabled and not all(
                (
                    self.pricing_v3_activation_artifact.strip(),
                    self.pricing_v3_activation_sha256.strip(),
                )
            ):
                raise ValueError(
                    "Robust v3 production activation requires an artifact and SHA-256"
                )
            if self.pricing_comparability_v1_automatic_enabled and not all(
                (
                    self.pricing_comparability_activation_artifact.strip(),
                    self.pricing_comparability_activation_sha256.strip(),
                )
            ):
                raise ValueError(
                    "Comparability automatic activation requires an artifact and SHA-256"
                )
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.strip().casefold() == "production"

    @property
    def effective_api_docs_enabled(self) -> bool:
        if self.api_docs_enabled is not None:
            return self.api_docs_enabled
        return not self.is_production

    @cached_property
    def cost_keyring(self) -> CostKeyring:
        if self.cost_privacy_mode != "SERVER_SIDE_ENCRYPTED":
            raise ValueError("Server-side cost encryption is not enabled")
        return parse_cost_keyring(
            active_key_id=self.cost_encryption_active_key_id,
            keys_json=self.cost_encryption_keys_json.get_secret_value(),
        )

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
