from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.api.deps import get_dispatcher
from app.core.database import database_url, get_db, make_sync_engine
from app.main import app
from app.models import Base
from app.storage.local import LocalStorage, get_storage


@pytest.fixture
def db_url(tmp_path: Path) -> str:
    url = f"sqlite:///{tmp_path / 'test.db'}"
    Base.metadata.create_all(make_sync_engine(url))
    return url


@pytest.fixture
def sync_sessions(db_url: str) -> sessionmaker[Session]:
    return sessionmaker(make_sync_engine(db_url), expire_on_commit=False)


@pytest.fixture
def storage(tmp_path: Path) -> LocalStorage:
    return LocalStorage(tmp_path / "storage")


@pytest.fixture
def dispatched() -> list[str]:
    return []


@pytest.fixture
def client(db_url: str, storage: LocalStorage, dispatched: list[str]) -> Iterator[TestClient]:
    # NullPool: TestClient may use a new event loop per request, so connections can't be reused.
    engine = create_async_engine(database_url(db_url, use_async=True), poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def test_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_dispatcher] = lambda: dispatched.append
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def sample_video(tmp_path: Path) -> Path:
    """Two seconds of 64x48 video at 10 fps."""
    path = tmp_path / "clip.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 48))
    for i in range(20):
        writer.write(np.full((48, 64, 3), i * 10, dtype=np.uint8))
    writer.release()
    return path
