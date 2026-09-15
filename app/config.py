import logging
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.paths import default_config_dir, default_data_dir


def _default_database_url() -> str:
    # Zero-config default: a local SQLite file next to the app (repo root when running
    # from source; next to the executable for the packaged Linux/Windows builds).
    # Point at Postgres/TimescaleDB for production, e.g.
    # postgresql+asyncpg://historian:historian@localhost:5432/ackiologs
    db_path = default_data_dir() / "ackiologs.db"
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


def _default_secret_key() -> str:
    # No hardcoded fallback here on purpose: a shared literal default would let anyone
    # who read the source forge admin JWTs against any deployment that forgot to set
    # ACKIOLOGS_SECRET_KEY. Instead, generate a random key on first run and persist it
    # next to the data directory, so it's stable across restarts but unique per install.
    # Set ACKIOLOGS_SECRET_KEY explicitly for a multi-instance/HA deployment so every
    # instance shares one key.
    secret_file = default_data_dir() / ".secret_key"
    try:
        if secret_file.exists():
            key = secret_file.read_text().strip()
            if key:
                return key
        default_data_dir().mkdir(parents=True, exist_ok=True)
        key = secrets.token_hex(32)
        secret_file.write_text(key)
        try:
            secret_file.chmod(0o600)
        except OSError:
            pass
        return key
    except OSError:
        logging.getLogger("ackiologs").warning(
            "Could not read or persist a JWT signing key at %s — using a fresh one for "
            "this process only, which will invalidate sessions on every restart. Set "
            "ACKIOLOGS_SECRET_KEY explicitly to fix this.",
            secret_file,
        )
        return secrets.token_hex(32)


class Settings(BaseSettings):
    """Central runtime configuration, overridable via environment variables or .env."""

    # env_ignore_empty: an empty-but-set env var (e.g. docker-compose's `${ACKIOLOGS_SECRET_KEY:-}`
    # substitution when the operator hasn't set one) falls through to the default_factory
    # below instead of locking in an empty string as the JWT signing key.
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="ACKIOLOGS_", extra="ignore", env_ignore_empty=True
    )

    app_name: str = "Ackiologs Historian"

    database_url: str = Field(default_factory=_default_database_url)

    # Where tag and connection definitions live.
    tags_config_path: Path = Field(default_factory=lambda: default_config_dir() / "tags.yaml")
    connections_config_path: Path = Field(default_factory=lambda: default_config_dir() / "connections.yaml")

    # Ingestion pipeline tuning.
    ingest_queue_maxsize: int = 50_000
    ingest_batch_size: int = 500
    ingest_flush_interval_seconds: float = 1.0

    # Deadband/store rules default (percent of engineering range) when a tag doesn't override it.
    default_deadband_percent: float = 0.0

    # Auth
    secret_key: str = Field(default_factory=_default_secret_key)
    access_token_expire_minutes: int = 480
    auth_enabled: bool = True

    # Retention (days). 0 disables automatic pruning.
    retention_days: int = 0

    cors_allow_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
