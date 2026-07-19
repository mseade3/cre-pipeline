from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="CRE_", extra="ignore")

    database_url: str = "sqlite:///data/cre_pipeline.db"
    scoring_config: Path = Path("config/scoring.yaml")
    log_level: str = "INFO"
    operator_name: str = ""


def get_settings() -> Settings:
    return Settings()
