
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application settings
    app_name: str = "Enterprise Knowledge Retrieval & RAG Assistant"
    app_environment: Literal[
        "development", "testing", "production"
    ] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # OpenAI configuration
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"

    # Redis and Celery configuration
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Document upload configuration
    max_upload_size_mb: int = Field(default=25, ge=1)
    storage_root: Path = Path("storage")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
