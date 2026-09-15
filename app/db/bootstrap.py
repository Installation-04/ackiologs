import logging

from sqlalchemy import text

from app.db.base import Base, engine, is_postgres

logger = logging.getLogger(__name__)


async def init_db() -> None:
    """Create all tables, and — on Postgres — enable TimescaleDB and convert tag_values
    into a hypertable. Safe to call on every startup (all operations are idempotent)."""

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        if is_postgres():
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS timescaledb"))
            try:
                await conn.execute(
                    text(
                        "SELECT create_hypertable('tag_values', 'ts', "
                        "if_not_exists => TRUE, migrate_data => TRUE)"
                    )
                )
            except Exception:  # extension unavailable in this Postgres — fall back to a plain table
                logger.warning("TimescaleDB hypertable creation failed; continuing with a plain Postgres table.")

            if get_retention_days() > 0:
                try:
                    await conn.execute(
                        text(
                            "SELECT add_retention_policy('tag_values', "
                            f"INTERVAL '{get_retention_days()} days', if_not_exists => TRUE)"
                        )
                    )
                except Exception:
                    logger.warning("Could not set TimescaleDB retention policy.")


def get_retention_days() -> int:
    from app.config import get_settings

    return get_settings().retention_days
