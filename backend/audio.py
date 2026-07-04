from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

TASK_AUDIO_LIMITS = {1: 30.0, 2: 150.0, 3: 210.0}


def probe_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True,
        check=True,
        text=True,
        timeout=10,
    )
    return float(json.loads(result.stdout)["format"]["duration"])


def validate_duration(path: Path, task: int) -> float:
    duration = probe_duration(path)
    configured = float(os.environ.get("TRAINER_MAX_AUDIO_SECONDS", TASK_AUDIO_LIMITS[task]))
    maximum = min(configured, TASK_AUDIO_LIMITS[task])
    if duration <= 0 or duration > maximum:
        raise ValueError(f"Длительность записи должна быть не больше {int(maximum)} секунд")
    return duration
