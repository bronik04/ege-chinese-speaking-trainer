from __future__ import annotations

import os
import tempfile
from pathlib import Path

import boto3

from trainer.infrastructure.storage import S3AudioStorage


def main() -> None:
    endpoint = os.environ["TRAINER_S3_ENDPOINT_URL"]
    bucket = os.environ.get("TRAINER_S3_BUCKET", "trainer-audio-test")
    region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    client = boto3.client("s3", endpoint_url=endpoint, region_name=region)
    try:
        client.create_bucket(Bucket=bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    storage = S3AudioStorage(bucket=bucket, endpoint_url=endpoint, region=region)
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "answer.webm"
        target = Path(directory) / "download.webm"
        source.write_bytes(b"minio-audio-smoke")
        storage.put("smoke/answer.webm", source, "audio/webm")
        storage.download("smoke/answer.webm", target)
        if target.read_bytes() != source.read_bytes() or storage.read("smoke/answer.webm") != source.read_bytes():
            raise RuntimeError("S3 round trip failed")
        storage.delete("smoke/answer.webm")


if __name__ == "__main__":
    main()
