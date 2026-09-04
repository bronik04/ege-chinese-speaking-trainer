import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from typing import Any

from trainer.services.progress_repository import ProgressRecord


class SQLiteProgressRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect

    def get(self, user_id: int) -> ProgressRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT progress_json,updated_at FROM user_progress WHERE user_id=?", (user_id,)
            ).fetchone()
        return ProgressRecord(json.loads(row["progress_json"]), row["updated_at"]) if row else None

    def save(self, user_id: int, document: dict[str, Any], updated_at: int) -> None:
        encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        with closing(self._connect()) as database:
            try:
                database.execute(
                    """INSERT INTO user_progress(user_id,progress_json,updated_at) VALUES (?,?,?)
                       ON CONFLICT(user_id) DO UPDATE SET progress_json=excluded.progress_json,
                       updated_at=excluded.updated_at""",
                    (user_id, encoded, updated_at),
                )
                database.commit()
            except BaseException:
                database.rollback()
                raise
