from __future__ import annotations

import os
from pathlib import Path

_SOURCE_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(os.environ.get("TRAINER_PROJECT_ROOT", _SOURCE_PROJECT_ROOT)).resolve()


def account_public_url() -> str:
    return os.environ.get("TRAINER_PUBLIC_URL", "").rstrip("/") or "http://127.0.0.1:8080"


def owner_email() -> str:
    return os.environ.get("TRAINER_OWNER_EMAIL", "").strip().lower()
