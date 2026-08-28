from __future__ import annotations

from time import time

from trainer.api import runtime
from trainer.services.storage_cleanup import CleanupSummary, expire_recordings, process_cleanup_jobs


def main() -> int:
    runtime.init_database(cleanup=False)
    cleanup_cutoff = int(time())
    with runtime.connect() as database:
        expired = 0
        while True:
            batch = expire_recordings(database, limit=500, now=cleanup_cutoff)
            expired += batch
            if batch < 500:
                break
        completed = 0
        failed = 0
        pending = 0
        while True:
            batch = process_cleanup_jobs(
                database,
                audio_root=runtime.AUDIO_DIR,
                material_root=runtime.MATERIAL_ASSET_DIR,
                assignment_root=runtime.ASSIGNMENT_ASSET_DIR,
                limit=500,
                now=cleanup_cutoff,
            )
            completed += batch.completed
            failed += batch.failed
            pending = batch.pending
            if batch.completed + batch.failed < 500 or not pending:
                break
        summary = CleanupSummary(completed=completed, failed=failed, pending=pending)
    print(f"expired={expired} completed={summary.completed} failed={summary.failed} pending={summary.pending}")
    return int(bool(summary.failed or summary.pending))


if __name__ == "__main__":
    raise SystemExit(main())
