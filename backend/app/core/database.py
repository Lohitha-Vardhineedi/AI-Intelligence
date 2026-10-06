"""Database engines and sessions.

The API uses an async engine; Celery workers and the local job thread use a sync one.
Both are built from the same DATABASE_URL, so it only needs the database, not a driver:
"postgresql://..." or "sqlite:///...".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import BACKEND_DIR, get_settings

_DRIVERS = {
    "postgresql": ("postgresql+psycopg", "postgresql+psycopg"),  # (sync, async)
    "sqlite": ("sqlite", "sqlite+aiosqlite"),
}


def database_url(raw: str, *, use_async: bool) -> URL:
    url = make_url(raw)
    backend = url.get_backend_name()
    if backend not in _DRIVERS:
        raise ValueError(f"Unsupported database: {backend}. Use PostgreSQL or SQLite.")
    url = url.set(drivername=_DRIVERS[backend][1 if use_async else 0])
    if backend == "sqlite" and url.database and url.database != ":memory:":
        path = Path(url.database)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        path.parent.mkdir(parents=True, exist_ok=True)
        url = url.set(database=str(path))
    return url


def _configure_sqlite(engine: Engine) -> None:
    """WAL lets the API read while a job is writing; foreign keys are off by default."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


def make_async_engine(raw_url: str) -> AsyncEngine:
    url = database_url(raw_url, use_async=True)
    engine = create_async_engine(url, pool_pre_ping=url.get_backend_name() != "sqlite")
    if url.get_backend_name() == "sqlite":
        _configure_sqlite(engine.sync_engine)
    return engine


def make_sync_engine(raw_url: str) -> Engine:
    url = database_url(raw_url, use_async=False)
    engine = create_engine(url, pool_pre_ping=url.get_backend_name() != "sqlite")
    if url.get_backend_name() == "sqlite":
        _configure_sqlite(engine)
    return engine


@lru_cache
def async_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = make_async_engine(get_settings().database_url)
    return async_sessionmaker(engine, expire_on_commit=False)


@lru_cache
def sync_session_factory() -> sessionmaker[Session]:
    return sessionmaker(make_sync_engine(get_settings().database_url), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    async with async_session_factory()() as session:
        yield session
