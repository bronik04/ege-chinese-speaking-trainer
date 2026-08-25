from __future__ import annotations

import json
import time
from http import HTTPStatus

from trainer.api.errors import ApiError, default_error_code
from trainer.api.results import ActionResult
from trainer.api.runtime import connect
from trainer.api.schemas import ProgressRequest


def progress_get(user: dict) -> ActionResult:
    with connect() as database:
        row = database.execute(
            "SELECT progress_json, updated_at FROM user_progress WHERE user_id = ?", (user["id"],)
        ).fetchone()
    progress = json.loads(row["progress_json"]) if row else None
    return ActionResult({"progress": progress, "updatedAt": row["updated_at"] if row else None})


def progress_put(payload: ProgressRequest, user: dict) -> ActionResult:
    progress = payload.progress
    if not isinstance(progress, dict) or progress.get("version") != 1:
        raise ApiError(default_error_code(HTTPStatus.BAD_REQUEST), "Invalid progress document", HTTPStatus.BAD_REQUEST)
    runs = progress.get("runs", [])
    if not isinstance(runs, list) or len(runs) > 200:
        raise ApiError(
            default_error_code(HTTPStatus.BAD_REQUEST), "Progress history is too large", HTTPStatus.BAD_REQUEST
        )
    encoded = json.dumps(progress, ensure_ascii=False, separators=(",", ":"))
    now = int(time.time())
    with connect() as database:
        database.execute(
            """
            INSERT INTO user_progress(user_id, progress_json, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET progress_json = excluded.progress_json,
                updated_at = excluded.updated_at
            """,
            (user["id"], encoded, now),
        )
    return ActionResult({"ok": True, "updatedAt": now})
