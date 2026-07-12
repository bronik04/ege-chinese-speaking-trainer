from trainer.infrastructure.storage.factory import storage_from_env
from trainer.infrastructure.storage.local import LocalAudioStorage
from trainer.infrastructure.storage.protocols import AudioStorage
from trainer.infrastructure.storage.s3 import S3AudioStorage

__all__ = ["AudioStorage", "LocalAudioStorage", "S3AudioStorage", "storage_from_env"]
