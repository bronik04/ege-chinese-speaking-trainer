from __future__ import annotations

import os
import time

from trainer.infrastructure.database.postgres import connect, initialize


def main() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    initialize(url)
    email = f"postgres-smoke-{time.time_ns()}@example.test"
    with connect(url) as database:
        teacher_id = database.execute(
            "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
            (f"teacher-{email}", "test", "Teacher", "teacher", int(time.time())),
        ).lastrowid
        user_id = database.execute(
            "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
            (email, "test", "Smoke", "student", int(time.time())),
        ).lastrowid
        group_id = database.execute(
            "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
            (teacher_id, "Smoke", str(time.time_ns())[-6:], int(time.time())),
        ).lastrowid
        snapshot = '{"id":"demo-2026","tasks":{"1":{}}}'
        assignment_id = database.execute(
            """INSERT INTO assignments(group_id,teacher_id,title,variant_id,tasks_json,created_at,material_snapshot_json)
               VALUES (?,?,?,?,?,?,?)""",
            (group_id, teacher_id, "Smoke", "demo-2026", "[1]", int(time.time()), snapshot),
        ).lastrowid
        row = database.execute(
            "SELECT users.email, assignments.material_snapshot_json FROM users CROSS JOIN assignments "
            "WHERE users.id = ? AND assignments.id = ?",
            (user_id, assignment_id),
        ).fetchone()
        database.execute("DELETE FROM users WHERE id = ?", (teacher_id,))
        database.execute("DELETE FROM users WHERE id = ?", (user_id,))
    if row["email"] != email or row["material_snapshot_json"] != snapshot:
        raise RuntimeError("PostgreSQL round trip failed")


if __name__ == "__main__":
    main()
