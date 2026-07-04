from __future__ import annotations

import argparse
import shutil
import sqlite3
import tarfile
import time
from pathlib import Path


def create_backup(data_dir: Path, output_dir: Path, keep: int) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    target = output_dir / stamp
    target.mkdir(parents=True, exist_ok=False)
    source_database = data_dir / "trainer.sqlite3"
    with sqlite3.connect(source_database) as source, sqlite3.connect(target / "trainer.sqlite3") as destination:
        source.backup(destination)
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
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
    print(create_backup(args.data_dir, args.output_dir, max(1, args.keep)))


if __name__ == "__main__":
    main()
