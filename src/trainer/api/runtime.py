from __future__ import annotations

import logging
import os
import re
import sqlite3
from pathlib import Path

from trainer.config import PROJECT_ROOT
from trainer.infrastructure.database.core import connect as database_connect
from trainer.infrastructure.database.core import initialize as initialize_database
from trainer.services.storage_cleanup import process_cleanup_jobs

logger = logging.getLogger("trainer.storage_cleanup")

ROOT = PROJECT_ROOT
DATA_DIR = Path(os.environ.get("TRAINER_DATA_DIR", ROOT / "var")).resolve()
DB_PATH = DATA_DIR / "trainer.sqlite3"
AUDIO_DIR = DATA_DIR / "audio"
MATERIAL_ASSET_DIR = DATA_DIR / "material-assets"
ASSIGNMENT_ASSET_DIR = DATA_DIR / "assignment-assets"
SESSION_DAYS = 30
MAX_BODY = int(os.environ.get("TRAINER_MAX_JSON_BYTES", "1000000"))
MAX_AUDIO_BODY = int(os.environ.get("TRAINER_MAX_AUDIO_BYTES", "15000000"))
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
GROUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def connect() -> sqlite3.Connection:
    return database_connect(DB_PATH)


def init_database() -> None:
    initialize_database(DATA_DIR, AUDIO_DIR, DB_PATH)
    MATERIAL_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    ASSIGNMENT_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with connect() as database:
            summary = process_cleanup_jobs(
                database,
                audio_root=AUDIO_DIR,
                material_root=MATERIAL_ASSET_DIR,
                assignment_root=ASSIGNMENT_ASSET_DIR,
            )
        logger.info(
            "Storage cleanup processed",
            extra={
                "event": "storage_cleanup_processed",
                "fields": {"completed": summary.completed, "failed": summary.failed, "pending": summary.pending},
            },
        )
    except Exception:
        logger.exception("Storage cleanup startup attempt failed", extra={"event": "storage_cleanup_startup_failed"})
