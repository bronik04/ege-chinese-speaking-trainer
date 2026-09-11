from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.infrastructure.database.review_request_repository import SQLiteReviewRequestRepository


class SQLiteReviewRequestRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.database_path)
        with closing(self.connect()) as database, database:
            self.student_id = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                ("student@example.test", "hash", "Student", "student", 1),
            ).lastrowid
            self.uploading_id = self.add_request(database, "uploading", "uploading", submitted_at=None)
            self.queued_id = self.add_request(database, "queued", "queued", submitted_at=20)
            self.oldest_queued_id = self.add_request(database, "queued-oldest", "queued", submitted_at=10)
            self.reviewed_id = self.add_request(database, "reviewed", "reviewed", submitted_at=30, reviewed_at=40)
            item_id = database.execute(
                """INSERT INTO review_request_items
                   (request_id,task_number,task_snapshot_json,scores_json,total_score,max_score)
                   VALUES (?,?,?,?,?,?)""",
                (self.queued_id, 2, '{"title":"Task"}', '{"content":3}', 3, 7),
            ).lastrowid
            database.execute(
                """INSERT INTO review_request_recordings
                   (item_id,question_number,label,storage_key,mime_type,size_bytes,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (item_id, None, "Ответ", "private/audio.webm", "audio/webm", 12, 1, 4_000_000_000),
            )
            database.execute(
                """INSERT INTO review_request_assets(request_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (self.queued_id, "private/image.webp", "image/webp", 14, 1),
            )
        self.repository = SQLiteReviewRequestRepository(self.connect)

    def tearDown(self):
        self.directory.cleanup()

    def connect(self):
        database = sqlite3.connect(self.database_path)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def add_request(
        self,
        database: sqlite3.Connection,
        variant_id: str,
        status: str,
        *,
        submitted_at: int | None,
        reviewed_at: int | None = None,
    ) -> int:
        return database.execute(
            """INSERT INTO review_requests
               (student_id,kind,status,variant_id,run_json,submitted_at,reviewed_at)
               VALUES (?,?,?,?,?,?,?)""",
            (self.student_id, "task", status, variant_id, "{}", submitted_at, reviewed_at),
        ).lastrowid

    def test_read_contracts_keep_uploading_private_and_hide_storage_keys(self):
        student_rows = self.repository.student_requests(self.student_id)
        teacher_rows = self.repository.teacher_requests()
        detail = self.repository.teacher_detail(self.queued_id)

        self.assertEqual(
            {row["id"] for row in student_rows},
            {self.uploading_id, self.queued_id, self.oldest_queued_id, self.reviewed_id},
        )
        self.assertEqual(
            [row["id"] for row in teacher_rows],
            [self.oldest_queued_id, self.queued_id, self.reviewed_id],
        )
        self.assertEqual(detail["material"]["2"], {"title": "Task"})
        self.assertEqual(detail["items"][0]["recordings"][0]["url"], "/api/review-recordings/1")
        self.assertEqual(detail["assets"][0]["url"], "/api/review-assets/1")
        self.assertNotIn("storage_key", repr([student_rows, teacher_rows, detail]))
        self.assertNotIn("private/audio.webm", repr([student_rows, teacher_rows, detail]))

    def test_teacher_filters_preserve_timestamp_range(self):
        rows = self.repository.teacher_requests(submitted_from=15, submitted_before=25)

        self.assertEqual([row["id"] for row in rows], [self.queued_id])


if __name__ == "__main__":
    unittest.main()
