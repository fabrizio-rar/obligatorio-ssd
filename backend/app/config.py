"""Application settings, read from environment variables (see .env.example)."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # DB
    database_url: str
    test_database_url: str | None = None

    # Ingest
    dataset_path: Path = Path("data/raw/MercaNova_dataset_obligatorio_2.xlsx")
    ingest_report_path: Path = Path("reports/ingest_report.json")

    # LLM: optional so the app starts without it (only the chat is disabled)
    openai_api_key: SecretStr | None = None
    llm_model: str = "gpt-6-luna"

    @property
    def chat_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
