from __future__ import annotations

import json


def safe_progress(value: str | None) -> dict:
    if not value:
        return {"runs": []}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"runs": []}
    return parsed if isinstance(parsed, dict) else {"runs": []}


__all__ = ["safe_progress"]
