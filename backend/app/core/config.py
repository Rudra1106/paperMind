"""
app/core/config.py

Centralises all environment-variable reads in one place.
Every other module imports from here — nothing reaches for os.environ directly.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── OpenRouter ────────────────────────────────────────────────────────────
    openrouter_api_key: str = Field(..., description="OpenRouter API key")

    # ── Cognee Cloud ──────────────────────────────────────────────────────────
    # cognee.serve() natively reads COGNEE_SERVICE_URL and COGNEE_API_KEY.
    # Set both to route all Cognee calls to your cloud tenant.
    # Leave COGNEE_SERVICE_URL blank to use local SQLite+LanceDB mode.
    cognee_api_key: str = Field(default="", description="Cognee Cloud X-Api-Key")
    cognee_service_url: str = Field(
        default="",
        description="Cognee Cloud API Base URL (e.g. https://tenant-xxx.aws.cognee.ai)",
    )

    # ── LLM settings forwarded to Cognee's internal pipeline ──────────────────
    llm_api_key: str = Field(default="", description="LLM provider API key for Cognee")
    llm_provider: str = Field(default="openai", description="LLM provider identifier")
    llm_model: str = Field(default="deepseek/deepseek-chat:free", description="Default LLM model slug")
    llm_endpoint: str = Field(default="https://openrouter.ai/api/v1", description="LLM API base URL")

    # ── Embedding settings for Cognee ─────────────────────────────────────────
    embedding_api_key: str = Field(default="", description="Embedding provider API key")
    embedding_provider: str = Field(default="openai", description="Embedding provider")
    embedding_model: str = Field(default="text-embedding-3-small", description="Embedding model")
    embedding_endpoint: str = Field(default="https://openrouter.ai/api/v1", description="Embedding endpoint")

    # ── Application ───────────────────────────────────────────────────────────
    allowed_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        description="Comma-separated CORS origins",
    )

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def cognee_cloud_enabled(self) -> bool:
        """True when both a service URL and API key are set — both are required for Cloud."""
        return bool(self.cognee_service_url and self.cognee_api_key)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton settings object."""
    return Settings()
