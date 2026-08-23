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
    firebase_project_id: str = ""
    competitor_price_cache_ttl_seconds: int = 21_600
    # Кілька сторінок пошуку на термін — джерелу треба більше, ніж один запит.
    competitor_price_source_timeout_seconds: float = 25.0
    # Жодного ключа = відсіювання лишається суто евристичним.
    # Назва моделі і є перемикачем: "claude-*" іде в Anthropic, решта — в
    # OpenAI-сумісний API (сам OpenAI, DeepSeek, будь-що з таким же протоколом).
    competitor_filter_model: str = "claude-haiku-4-5"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""  # напр. https://api.deepseek.com для DeepSeek

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
