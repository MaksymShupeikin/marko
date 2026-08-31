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
    competitor_price_cache_url: str = "redis://localhost:6379/2"
    cors_origins: str = "http://localhost:8080,http://localhost:3000"
    # На інстанс: pool_size + max_overflow одночасних з'єднань. Сумарно по всіх
    # інстансах має лишатися нижче max_connections Postgres (типово 100).
    db_pool_size: int = 10
    db_max_overflow: int = 10
    # Скільки звітів конкурентів збирається одночасно (на процес): захищає
    # і власний event loop, і джерела від шквалу скрейпів.
    competitor_report_concurrency: int = 8
    firebase_project_id: str = ""
    competitor_price_cache_ttl_seconds: int = 21_600
    # Кілька сторінок пошуку на термін — джерелу треба більше, ніж один запит.
    competitor_price_source_timeout_seconds: float = 25.0
    # OpenAI API / GPT модель для фільтрації пропозицій конкурентів
    competitor_filter_model: str = "gpt-5-nano"
    # Порожньо = джерело Google (Serper.dev) вимкнене.
    serper_api_key: str = ""
    openai_api_key: str = ""
    # Пейвол: безкоштовні перевірки цін на воркспейс, далі — запит доступу.
    free_check_limit: int = 30
    openai_base_url: str = ""  # напр. https://api.deepseek.com для DeepSeek або проксі
    # Production hardening. API docs remain available in development, but are
    # fail-closed in production even if this flag is accidentally left true.
    api_docs_enabled: bool = True
    trusted_hosts: str = "api.markoprice.com,localhost,127.0.0.1,api,testserver"
    hsts_max_age_seconds: int = 31_536_000
    rate_limits_enabled: bool = True
    upload_max_bytes: int = 25 * 1024 * 1024
    upload_max_uncompressed_bytes: int = 200 * 1024 * 1024
    upload_max_rows: int = 100_000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    @property
    def trusted_host_list(self) -> list[str]:
        return [host.strip() for host in self.trusted_hosts.split(",") if host.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.strip().casefold() == "production"

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


def validate_production_settings(settings: Settings) -> None:
    if not settings.is_production:
        return
    errors: list[str] = []
    if settings.debug:
        errors.append("DEBUG must be false")
    if not settings.firebase_project_id.strip():
        errors.append("FIREBASE_PROJECT_ID must be configured")
    if not settings.rate_limits_enabled:
        errors.append("RATE_LIMITS_ENABLED must be true")
    if settings.hsts_max_age_seconds < 31_536_000:
        errors.append("HSTS_MAX_AGE_SECONDS must be at least 31536000")
    if not settings.cors_origin_list or any(
        not origin.startswith("https://") or "*" in origin
        for origin in settings.cors_origin_list
    ):
        errors.append("CORS_ORIGINS must contain explicit HTTPS origins")
    if not settings.trusted_host_list or any(
        "*" in host for host in settings.trusted_host_list
    ):
        errors.append("TRUSTED_HOSTS must not contain wildcards")
    if "://marko:marko@" in settings.database_url:
        errors.append("the default database password is forbidden")
    if errors:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(errors))
