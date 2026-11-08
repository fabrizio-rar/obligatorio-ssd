"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DB
    database_url: str
    test_database_url: str | None = None

    # Ingest
    dataset_path: Path = Path("data/raw/MercaNova_dataset_obligatorio_2.xlsx")
    ingest_report_path: Path = Path("reports/ingest_report.json")

    # Auth (docs/PLAN.md §7.2, §12)
    auth_token_ttl_hours: int = Field(default=72, gt=0)
    seed_demo_user: bool = True

    # OpenAI: optional so the app starts without it (chat and semantic search are disabled)
    openai_api_key: SecretStr | None = None
    llm_provider: Literal["openai"] = "openai"  # the only adapter implemented
    llm_model: str = "gpt-6-luna"
    llm_reasoning_effort: Literal["none", "low", "medium", "high"] = "low"
    llm_timeout_seconds: float = 60
    llm_max_retries: int = 2  # retries on 429 / 5xx / timeout (with backoff, by the SDK)

    # Agent loop limits (docs/PLAN.md §10.7.3)
    agent_max_steps: int = Field(default=6, ge=1)
    agent_history_messages: int = Field(default=10, ge=0)
    agent_turn_timeout_seconds: float = Field(default=90, gt=0)
    agent_max_tokens_per_turn: int = Field(default=12000, gt=0)

    # Embeddings (docs/PLAN.md §9.3)
    embedding_provider: Literal["openai", "fake"] = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = Field(default=100, ge=1, le=2048)
    embedding_usd_per_1m_tokens: float = 0.02

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.get_secret_value())

    @property
    def chat_enabled(self) -> bool:
        return self.openai_configured


@lru_cache
def get_settings() -> Settings:
    return Settings()
