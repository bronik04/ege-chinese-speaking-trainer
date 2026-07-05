from __future__ import annotations

import os
import time

from backend.postgres import connect, initialize


def main() -> None:
    url = os.environ["TEST_DATABASE_URL"]
    initialize(url)
    email = f"postgres-smoke-{time.time_ns()}@example.test"
    with connect(url) as database:
        user_id = database.execute(
            "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
            (email, "test", "Smoke", "student", int(time.time())),
        ).lastrowid
        row = database.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        database.execute("DELETE FROM users WHERE id = ?", (user_id,))
    if row["email"] != email:
        raise RuntimeError("PostgreSQL round trip failed")


if __name__ == "__main__":
    main()
