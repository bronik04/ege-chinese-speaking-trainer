from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from trainer.config import PROJECT_ROOT
from trainer.infrastructure.database.core import connect as database_connect
from trainer.infrastructure.database.core import initialize as initialize_database

ROOT = PROJECT_ROOT
DATA_DIR = Path(os.environ.get("TRAINER_DATA_DIR", ROOT / "var")).resolve()
DB_PATH = DATA_DIR / "trainer.sqlite3"
AUDIO_DIR = DATA_DIR / "audio"
MATERIAL_ASSET_DIR = DATA_DIR / "material-assets"
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
