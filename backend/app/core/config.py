"""Settings from environment variables and `.env`. This is the only module that reads
the environment; everything else is handed a `Settings` object."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
PROJECT_DIR = BACKEND_DIR.parent

SmsProviderName = Literal["console", "twilio", "msg91", "aws_sns"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Later files win: backend/.env overrides the project-level .env.
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    timezone: str = "Asia/Kolkata"

    # PostgreSQL in production, e.g. postgresql://user:password@localhost:5432/ai_video.
    # The SQLite default needs no setup.
    database_url: str = "sqlite:///storage/app.db"
    # With Redis set, uploaded videos are processed by a Celery worker. Without it, the
    # API processes them on a background thread (one at a time).
    redis_url: str = ""
    storage_dir: str = "storage"  # uploaded videos and analysis results
    # On hosts whose disk is wiped on restart, delete records of videos whose files are gone.
    forget_missing_videos: bool = False
    scene_config_path: str = "config/scene.yaml"
    max_upload_mb: int = Field(default=1024, ge=1)
    cors_origins: str = "http://localhost:3000"  # comma-separated

    ai_model_path: str = "models/yolo11n.pt"
    ai_device: str = "auto"  # auto | cpu | cuda | cuda:0 | mps
    ai_confidence_threshold: float = Field(default=0.4, ge=0.05, le=0.99)
    ai_iou_threshold: float = Field(default=0.5, ge=0.05, le=0.95)
    ai_image_size: int = Field(default=640, ge=160, le=1920)
    # ByteTrack uses weak detections to keep existing tracks alive (never to start new
    # ones), so the detector itself runs at this lower threshold.
    ai_tracker_low_threshold: float = Field(default=0.1, ge=0.01, le=0.9)
    # CPU threads for inference and video encoding. 0 = the libraries' default (all
    # cores). Set 1 on servers with a fraction of a CPU, where more threads only add overhead.
    ai_cpu_threads: int = Field(default=0, ge=0, le=64)
    # Overrides detection.inference_fps in the scene config, e.g. to analyse fewer frames
    # per second on a small server.
    ai_inference_fps: float | None = Field(default=None, gt=0, le=60)

    sms_provider: SmsProviderName = "console"
    sms_recipients: str = ""  # comma-separated
    sms_default_country_code: str = "91"
    sms_max_per_hour: int = Field(default=10, ge=1)
    # Twilio
    sms_account_sid: str = ""
    sms_auth_token: SecretStr = SecretStr("")
    sms_from_number: str = ""  # Twilio number, or a Messaging Service SID (MG...)
    # MSG91 (Flow API, DLT template based)
    sms_api_key: SecretStr = SecretStr("")
    sms_template_id: str = ""
    # AWS SNS (credentials via the standard AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)
    aws_region: str = "ap-south-1"
    sms_sender_id: str = ""
    sms_dlt_entity_id: str = ""
    sms_dlt_template_id: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def recipients(self) -> list[str]:
        return [n.strip() for n in self.sms_recipients.split(",") if n.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def resolve_path(self, value: str | Path) -> Path:
        """Resolve a path from settings relative to the backend directory."""
        path = Path(value)
        return path if path.is_absolute() else BACKEND_DIR / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
