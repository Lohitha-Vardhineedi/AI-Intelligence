from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.api.deps import Db, Storage
from app.core.errors import NotFoundError
from app.schemas.common import PagedResponse, Pagination
from app.schemas.video import EventOut
from app.services import videos as service

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def list_events(
    db: Db,
    job_id: str | None = None,
    video_id: str | None = None,
    event_type: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> PagedResponse[EventOut]:
    events, total = await service.list_events(
        db, job_id=job_id, video_id=video_id, event_type=event_type,
        page=page, page_size=page_size,
    )
    return PagedResponse(
        data=[EventOut.model_validate(e) for e in events],
        pagination=Pagination.of(page, page_size, total),
    )


@router.get("/{event_id}/snapshot", response_class=FileResponse)
async def event_snapshot(event_id: str, db: Db, storage: Storage) -> FileResponse:
    event = await service.get_event(db, event_id)
    if event.snapshot_key is None:
        raise NotFoundError("Snapshot")
    return FileResponse(storage.path(event.snapshot_key), media_type="image/jpeg")
