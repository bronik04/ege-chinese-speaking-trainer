from __future__ import annotations

from pathlib import Path


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
