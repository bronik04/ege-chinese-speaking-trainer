from __future__ import annotations

from trainer.api import runtime
from trainer.services.storage_cleanup import process_cleanup_jobs


def main() -> int:
    runtime.init_database()
    with runtime.connect() as database:
        summary = process_cleanup_jobs(
            database,
            audio_root=runtime.AUDIO_DIR,
            material_root=runtime.MATERIAL_ASSET_DIR,
            assignment_root=runtime.ASSIGNMENT_ASSET_DIR,
            limit=500,
        )
    print(f"completed={summary.completed} failed={summary.failed} pending={summary.pending}")
    return int(bool(summary.failed or summary.pending))


if __name__ == "__main__":
    raise SystemExit(main())
