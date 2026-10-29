
from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralized application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Enterprise Knowledge Retrieval & RAG Assistant"
    app_environment: Literal["development", "testing", "production"] = ("development")
    debug: bool = False
    api_prefix: str = "/api/v1"

    # Keep secrets out of source code and prevent accidental display.
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-4o-mini"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""
    return Settings()
