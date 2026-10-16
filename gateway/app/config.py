from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ollama_url: str = "http://ollama:11434"
    # Comma-separated SHA-256 hex digests of allowed API keys (never store raw keys).
    api_key_hashes: str = ""
    # Requests per minute per API key (token bucket), plus burst capacity.
    rate_limit_rpm: int = Field(default=60, ge=1)
    rate_limit_burst: int = Field(default=10, ge=1)
    # Optional allow-list of model names; empty = all models served by Ollama.
    allowed_models: str = ""
    max_body_bytes: int = 1_000_000
    upstream_timeout: float = 300.0

    @property
    def key_hashes(self) -> frozenset[str]:
        return frozenset(h.strip().lower() for h in self.api_key_hashes.split(",") if h.strip())

    @property
    def models(self) -> frozenset[str]:
        return frozenset(m.strip() for m in self.allowed_models.split(",") if m.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
