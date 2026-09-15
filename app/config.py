from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central runtime configuration, overridable via environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ACKIOLOGS_", extra="ignore")

    app_name: str = "Ackiologs Historian"

    # Zero-config default: a local SQLite file. Point at Postgres/TimescaleDB for production, e.g.
    # postgresql+asyncpg://historian:historian@localhost:5432/ackiologs
    database_url: str = "sqlite+aiosqlite:///./data/ackiologs.db"

    # Where tag and connection definitions live.
    tags_config_path: Path = Path("config/tags.yaml")
    connections_config_path: Path = Path("config/connections.yaml")

    # Ingestion pipeline tuning.
    ingest_queue_maxsize: int = 50_000
    ingest_batch_size: int = 500
    ingest_flush_interval_seconds: float = 1.0

    # Deadband/store rules default (percent of engineering range) when a tag doesn't override it.
    default_deadband_percent: float = 0.0

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 480
    auth_enabled: bool = True

    # Retention (days). 0 disables automatic pruning.
    retention_days: int = 0

    cors_allow_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
