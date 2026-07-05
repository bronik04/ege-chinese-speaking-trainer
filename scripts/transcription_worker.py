#!/usr/bin/env python3
from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

import server
from backend.storage import storage_from_env
from backend.transcription import OpenAITranscriber, claim, complete, fail


def process_one(transcriber=None) -> bool:
    with server.connect() as database:
        job = claim(database)
    if not job:
        return False
    suffix = Path(job["file_name"]).suffix
    try:
        transcriber = transcriber or OpenAITranscriber()
        storage = storage_from_env(server.AUDIO_DIR)
        with tempfile.NamedTemporaryFile(suffix=suffix) as temporary:
            storage.download(job["file_name"], Path(temporary.name))
            text = transcriber.transcribe(Path(temporary.name))
        with server.connect() as database:
            complete(database, job["id"], job["recording_id"], text)
    except Exception as error:
        with server.connect() as database:
            fail(database, job, error)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Process audio transcription jobs")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    server.init_database()
    while True:
        processed = process_one()
        if args.once:
            return
        if not processed:
            time.sleep(max(0.2, args.poll_seconds))


if __name__ == "__main__":
    main()
