"""Shared FastAPI dependencies. Tests override these to swap the database, storage and
job dispatcher."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.services.videos import JobDispatcher
from app.storage.local import LocalStorage, get_storage
from app.workers.dispatch import dispatch_video_job


def get_dispatcher() -> JobDispatcher:
    return dispatch_video_job


Db = Annotated[AsyncSession, Depends(get_db)]
Storage = Annotated[LocalStorage, Depends(get_storage)]
AppSettings = Annotated[Settings, Depends(get_settings)]
Dispatcher = Annotated[JobDispatcher, Depends(get_dispatcher)]
