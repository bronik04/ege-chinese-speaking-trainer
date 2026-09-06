import json
import sqlite3
from collections.abc import Callable
from contextlib import closing

from trainer.services.progress_repository import ProgressDataError, ProgressRecord


class SQLiteProgressRepository:
    def __init__(self, connect: Callable[[], sqlite3.Connection]):
        self._connect = connect

    def get(self, user_id: int) -> ProgressRecord | None:
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT progress_json,updated_at FROM user_progress WHERE user_id=?", (user_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            document = json.loads(row["progress_json"])
        except (json.JSONDecodeError, TypeError) as error:
            raise ProgressDataError("Stored progress JSON is unreadable") from error
        if type(document) is not dict:
            raise ProgressDataError("Stored progress root is not an object")
        return ProgressRecord(document, row["updated_at"])

    def save(self, user_id: int, document: dict[str, object], updated_at: int) -> None:
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
