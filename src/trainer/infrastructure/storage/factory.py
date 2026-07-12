from __future__ import annotations

import os
from pathlib import Path

from trainer.infrastructure.storage.local import LocalAudioStorage
from trainer.infrastructure.storage.protocols import AudioStorage
from trainer.infrastructure.storage.s3 import S3AudioStorage


def storage_from_env(local_root: Path) -> AudioStorage:
    backend = os.environ.get("TRAINER_AUDIO_STORAGE", "local").strip().lower()
    if backend == "local":
        return LocalAudioStorage(local_root)
    if backend != "s3":
        raise RuntimeError("TRAINER_AUDIO_STORAGE must be 'local' or 's3'")
    bucket = os.environ.get("TRAINER_S3_BUCKET", "").strip()
    if not bucket:
        raise RuntimeError("TRAINER_S3_BUCKET is required for S3 audio storage")
    return S3AudioStorage(
        bucket=bucket,
        endpoint_url=os.environ.get("TRAINER_S3_ENDPOINT_URL"),
        region=os.environ.get("AWS_DEFAULT_REGION", "auto"),
    )
