from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.infrastructure.database.storage_cleanup_repository import (
    SQLiteStorageCleanupQueue,
    SQLiteStorageCleanupRepository,
)
from trainer.services.storage_cleanup_repository import CleanupKeys, CleanupOutcome


class SQLiteStorageCleanupRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.database_path)
        self.repository = SQLiteStorageCleanupRepository(self.connect)

    def tearDown(self):
        self.directory.cleanup()

    def connect(self):
        database = sqlite3.connect(self.database_path)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def enqueue(self, keys: CleanupKeys, *, now: int = 100, available_at: int | None = None) -> int:
        with closing(self.connect()) as database, database:
            return SQLiteStorageCleanupQueue(database).enqueue(keys, now=now, available_at=available_at)

    def seed_recording_pair(self, *, personal_expiry: int = 20, review_expiry: int = 10):
        with closing(self.connect()) as database, database:
            student_id = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                ("student@example.test", "hash", "Student", "student", 1),
            ).lastrowid
            database.execute(
                """INSERT INTO personal_recordings(
                       student_id,run_id,variant_id,task_number,question_number,label,storage_key,
                       mime_type,size_bytes,duration_seconds,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (student_id, "run", "demo", 2, 1, "Personal", "shared.webm", "audio/webm", 1, 1.0, 1, personal_expiry),
            )
            request_id = database.execute(
                "INSERT INTO review_requests(student_id,kind,status,variant_id,run_json) VALUES (?,?,?,?,?)",
                (student_id, "task", "queued", "demo", "{}"),
            ).lastrowid
            item_id = database.execute(
                "INSERT INTO review_request_items(request_id,task_number,task_snapshot_json) VALUES (?,?,?)",
                (request_id, 2, "{}"),
            ).lastrowid
            database.execute(
                """INSERT INTO review_request_recordings(
                       item_id,question_number,label,storage_key,mime_type,size_bytes,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (item_id, None, "Review", "shared.webm", "audio/webm", 1, 1, review_expiry),
            )

    def test_transaction_queue_deduplicates_and_cancels_without_committing(self):
        with closing(self.connect()) as database:
            queue = SQLiteStorageCleanupQueue(database)
            job_id = queue.enqueue(
                CleanupKeys(("audio", "audio", ""), ("material",), ("assignment",)),
                now=100,
                available_at=200,
            )
            row = database.execute(
                """SELECT audio_keys_json,material_keys_json,assignment_keys_json,created_at,available_at
                   FROM storage_cleanup_jobs WHERE id=?""",
                (job_id,),
            ).fetchone()
            self.assertEqual(json.loads(row["audio_keys_json"]), ["audio"])
            self.assertEqual(json.loads(row["material_keys_json"]), ["material"])
            self.assertEqual(json.loads(row["assignment_keys_json"]), ["assignment"])
            self.assertEqual((row["created_at"], row["available_at"]), (100, 200))
            self.assertTrue(queue.cancel(job_id))
            self.assertFalse(queue.cancel(job_id))
            database.rollback()

        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 0)

    def test_expiry_removes_shared_oldest_rows_and_enqueues_one_key(self):
        self.seed_recording_pair(personal_expiry=10, review_expiry=10)

        self.assertEqual(self.repository.expire_recordings(now=10, limit=2), 2)

        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 0)
            self.assertEqual(database.execute("SELECT COUNT(*) FROM review_request_recordings").fetchone()[0], 0)
            row = database.execute("SELECT audio_keys_json FROM storage_cleanup_jobs").fetchone()
        self.assertEqual(json.loads(row["audio_keys_json"]), ["shared.webm"])

    def test_expiry_orders_tables_together_and_rolls_back_queue_failure(self):
        self.seed_recording_pair(personal_expiry=20, review_expiry=10)

        self.assertEqual(self.repository.expire_recordings(now=20, limit=1), 1)
        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM review_request_recordings").fetchone()[0], 0)
            self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 1)

        with patch.object(SQLiteStorageCleanupQueue, "enqueue", side_effect=OSError("queue down")):
            with self.assertRaisesRegex(OSError, "queue down"):
                self.repository.expire_recordings(now=20, limit=1)

        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 1)

    def test_claim_uses_lease_and_ignores_stale_outcomes(self):
        first_id = self.enqueue(CleanupKeys(audio=("first",)))
        second_id = self.enqueue(CleanupKeys(audio=("second",)))

        first_claim = self.repository.claim_jobs(now=100, lease_until=3700, limit=1)
        second_claim = self.repository.claim_jobs(now=100, lease_until=3700, limit=10)

        self.assertEqual([job.id for job in first_claim], [first_id])
        self.assertEqual([job.id for job in second_claim], [second_id])
        self.assertEqual(self.repository.claim_jobs(now=101, lease_until=3701, limit=10), [])

        reclaimed = self.repository.claim_jobs(now=3700, lease_until=7300, limit=10)
        self.assertEqual({job.id for job in reclaimed}, {first_id, second_id})

        stale = self.repository.finish_jobs(
            [CleanupOutcome(first_id)],
            lease_until=3700,
            now=3700,
            retry_at=7300,
        )
        self.assertEqual((stale.completed, stale.failed, stale.pending), (0, 0, 2))

        current = self.repository.finish_jobs(
            [CleanupOutcome(first_id), CleanupOutcome(second_id, "OSError: unavailable")],
            lease_until=7300,
            now=3701,
            retry_at=8000,
        )
        self.assertEqual((current.completed, current.failed, current.pending), (1, 1, 1))
        with closing(self.connect()) as database:
            row = database.execute(
                "SELECT attempts,last_error,available_at FROM storage_cleanup_jobs WHERE id=?",
                (second_id,),
            ).fetchone()
        self.assertEqual((row["attempts"], row["last_error"], row["available_at"]), (1, "OSError: unavailable", 8000))

    def test_malformed_payload_is_claimed_as_a_retryable_job_error(self):
        with closing(self.connect()) as database, database:
            job_id = database.execute(
                """INSERT INTO storage_cleanup_jobs(
                       audio_keys_json,material_keys_json,assignment_keys_json,attempts,
                       created_at,updated_at,available_at)
                   VALUES (?,?,?,?,?,?,?)""",
                ("not-json", "[]", "[]", 0, 100, 100, 100),
            ).lastrowid

        jobs = self.repository.claim_jobs(now=100, lease_until=3700, limit=10)

        self.assertEqual(len(jobs), 1)
        self.assertEqual((jobs[0].id, jobs[0].keys, jobs[0].lease_until), (job_id, CleanupKeys(), 3700))
        self.assertTrue(jobs[0].error.startswith("JSONDecodeError:"), jobs[0].error)


if __name__ == "__main__":
    unittest.main()
