from __future__ import annotations

import sqlite3
from collections.abc import Callable

from backend.database import INTEGRITY_ERRORS


def create_submission_with_retry(
    connect_factory: Callable,
    assignment_id: int,
    student_id: int,
    encoded_run: str,
    submitted_at: int,
    *,
    max_attempts: int = 3,
) -> tuple[int, int]:
    last_error: Exception | None = None
    for _ in range(max_attempts):
        try:
            with connect_factory() as database:
                attempt = database.execute(
                    "SELECT COALESCE(MAX(attempt_number), 0) + 1 AS number FROM submissions "
                    "WHERE assignment_id = ? AND student_id = ?",
                    (assignment_id, student_id),
                ).fetchone()["number"]
                cursor = database.execute(
                    """
                    INSERT INTO submissions(assignment_id, student_id, attempt_number, run_json, submitted_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (assignment_id, student_id, attempt, encoded_run, submitted_at),
                )
                return cursor.lastrowid, attempt
        except INTEGRITY_ERRORS as error:
            last_error = error
        except sqlite3.OperationalError as error:
            if "locked" not in str(error).lower():
                raise
            last_error = error
    raise RuntimeError("Could not allocate a unique submission attempt") from last_error
