from __future__ import annotations

import os
from pathlib import Path

_SOURCE_PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = Path(os.environ.get("TRAINER_PROJECT_ROOT", _SOURCE_PROJECT_ROOT)).resolve()
