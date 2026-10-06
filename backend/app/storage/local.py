"""File storage on the local disk. Files are addressed by keys such as
"videos/<id>/original.mp4", so an S3 or Azure implementation can replace this class."""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path
from typing import BinaryIO

from app.core.config import get_settings


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Storage key escapes the storage root: {key}")
        return path

    def key(self, path: Path | str) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()

    def save(self, key: str, source: BinaryIO) -> int:
        """Copies `source` to `key` and returns the number of bytes written."""
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            shutil.copyfileobj(source, fh, length=1 << 20)
        return path.stat().st_size

    def delete(self, key: str) -> None:
        """Deletes a file, or a folder and everything in it."""
        path = self.path(key)
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)


@lru_cache
def get_storage() -> LocalStorage:
    settings = get_settings()
    return LocalStorage(settings.resolve_path(settings.storage_dir))
