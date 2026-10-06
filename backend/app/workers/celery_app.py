"""Celery app. Start a worker from the backend folder with:

    celery -A app.workers.celery_app worker --pool=solo --loglevel=info

--pool=solo is needed on Windows, and it also suits this workload: one video at a time
gets the whole CPU or GPU.
"""

from __future__ import annotations

from typing import Any

from celery import Celery, signals

from app.core.config import get_settings
from app.core.logging import configure_logging

_settings = get_settings()

celery_app = Celery(
    "ai_video",
    broker=_settings.redis_url or None,
    include=["app.workers.tasks.video_processing"],
)
celery_app.conf.update(
    task_acks_late=True,  # a job is redelivered if the worker dies part-way
    worker_prefetch_multiplier=1,  # don't reserve jobs another worker could start
    broker_connection_retry_on_startup=True,
)


@signals.setup_logging.connect
def _setup_logging(**_: Any) -> None:
    configure_logging(_settings.log_level, _settings.log_format)
