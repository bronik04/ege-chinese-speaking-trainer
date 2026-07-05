from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol


class AudioStorage(Protocol):
    def put(self, key: str, source: Path, content_type: str) -> None: ...
    def download(self, key: str, target: Path) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalAudioStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if self.root not in target.parents:
            raise ValueError("Invalid storage key")
        return target

    def put(self, key: str, source: Path, content_type: str) -> None:
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())

    def download(self, key: str, target: Path) -> None:
        source = self._path(key)
        if not source.is_file():
            raise FileNotFoundError(key)
        target.write_bytes(source.read_bytes())

    def read(self, key: str) -> bytes:
        target = self._path(key)
        if not target.is_file():
            raise FileNotFoundError(key)
        return target.read_bytes()

    def delete(self, key: str) -> None:
        target = self._path(key)
        target.unlink(missing_ok=True)
        parent = target.parent
        if parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                pass


class S3AudioStorage:
    def __init__(self, *, bucket: str, endpoint_url: str | None, region: str):
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region)

    def put(self, key: str, source: Path, content_type: str) -> None:
        self.client.upload_file(str(source), self.bucket, key, ExtraArgs={"ContentType": content_type})

    def download(self, key: str, target: Path) -> None:
        try:
            self.client.download_file(self.bucket, key, str(target))
        except Exception as error:
            self._raise_not_found(error, key)

    def read(self, key: str) -> bytes:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as error:
            self._raise_not_found(error, key)

    @staticmethod
    def _raise_not_found(error: Exception, key: str):
        response = getattr(error, "response", {})
        code = str(response.get("Error", {}).get("Code", ""))
        if code in {"404", "NoSuchKey", "NotFound"}:
            raise FileNotFoundError(key) from error
        raise error

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)


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
