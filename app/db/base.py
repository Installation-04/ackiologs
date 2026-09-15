from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_async_engine(settings.database_url, connect_args=_connect_args, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


def is_sqlite() -> bool:
    return engine.dialect.name == "sqlite"


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
