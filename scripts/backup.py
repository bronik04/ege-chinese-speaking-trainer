from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import subprocess
import tarfile
import time
from contextlib import closing
from pathlib import Path


def create_backup(
    data_dir: Path,
    output_dir: Path,
    keep: int,
    database_url: str = "",
    audio_storage: str = "local",
) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = output_dir / stamp
    target.mkdir(parents=True, exist_ok=False)
    if database_url:
        subprocess.run(
            ["pg_dump", "--format=custom", f"--file={target / 'trainer.pgdump'}", database_url],
            check=True,
        )
    else:
        source_database = data_dir / "trainer.sqlite3"
        with (
            closing(sqlite3.connect(source_database)) as source,
            closing(sqlite3.connect(target / "trainer.sqlite3")) as destination,
        ):
            with source, destination:
                source.backup(destination)
                if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Backup integrity check failed")
    if audio_storage == "local":
        audio = data_dir / "audio"
        with tarfile.open(target / "audio.tar.gz", "w:gz") as archive:
            if audio.is_dir():
                archive.add(audio, arcname="audio")
    backups = sorted((path for path in output_dir.iterdir() if path.is_dir()), reverse=True)
    for expired in backups[keep:]:
        shutil.rmtree(expired)
    return target


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("var"))
    parser.add_argument("--output-dir", type=Path, default=Path("backups"))
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    print(
        create_backup(
            args.data_dir,
            args.output_dir,
            max(1, args.keep),
            os.environ.get("DATABASE_URL", ""),
            os.environ.get("TRAINER_AUDIO_STORAGE", "local"),
        )
    )


if __name__ == "__main__":
    main()
