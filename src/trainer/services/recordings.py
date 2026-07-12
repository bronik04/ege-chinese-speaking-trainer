from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from trainer.infrastructure.storage import storage_from_env


def write_recording(root: Path, key: str, source: Path, content_type: str) -> None:
    storage_from_env(root).put(key, source, content_type)


def read_recording(root: Path, key: str) -> bytes:
    return storage_from_env(root).read(key)


def delete_recordings(root: Path, keys) -> None:
    try:
        storage = storage_from_env(root)
    except Exception:
        return
    for key in keys:
        with suppress(Exception):
            storage.delete(key)
