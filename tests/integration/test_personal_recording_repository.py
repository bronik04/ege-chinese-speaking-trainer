from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.infrastructure.database.personal_recording_repository import SQLitePersonalRecordingRepository
from trainer.infrastructure.database.storage_cleanup_repository import SQLiteStorageCleanupQueue
from trainer.services.personal_recording_repository import (
    PersonalRecordingConflictError,
    PersonalRecordingData,
    PersonalRecordingIntentError,
)


class SQLitePersonalRecordingRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.database_path)
        self.repository = SQLitePersonalRecordingRepository(self.connect)
        with closing(self.connect()) as database, database:
            self.student_id = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                ("student@example.test", "hash", "Student", "student", 1),
            ).lastrowid
            self.other_id = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                ("other@example.test", "hash", "Other", "student", 1),
            ).lastrowid
        self.data = PersonalRecordingData("run-1", "demo-2026", 2, 1, "Answer")

    def tearDown(self):
        self.directory.cleanup()

    def connect(self):
        database = sqlite3.connect(self.database_path)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def create_intent(self, key="personal-recordings/1/answer.webm"):
        return self.repository.create_upload_intent(key, 1000, 1060)

    def test_upload_intent_is_committed_before_the_method_returns(self):
        intent_id = self.create_intent()

        with closing(self.connect()) as database:
            row = database.execute(
                "SELECT id,audio_keys_json,created_at,available_at FROM storage_cleanup_jobs WHERE id=?",
                (intent_id,),
            ).fetchone()
        self.assertEqual(json.loads(row["audio_keys_json"]), ["personal-recordings/1/answer.webm"])
        self.assertEqual((row["created_at"], row["available_at"]), (1000, 1060))

    def test_upload_intent_rolls_back_when_transaction_queue_fails(self):
        with patch.object(SQLiteStorageCleanupQueue, "enqueue", side_effect=OSError("queue down")):
            with self.assertRaisesRegex(OSError, "queue down"):
                self.create_intent()

        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 0)

    def test_finalize_inserts_metadata_and_deletes_intent_atomically(self):
        intent_id = self.create_intent()

        record = self.repository.finalize_recording(
            self.student_id,
            self.data,
            "personal-recordings/1/answer.webm",
            "audio/webm",
            42,
            12.5,
            intent_id,
            1000,
        )

        self.assertEqual(
            (
                record.run_id,
                record.variant_id,
                record.task_number,
                record.question_number,
                record.label,
                record.created_at,
            ),
            ("run-1", "demo-2026", 2, 1, "Answer", 1000),
        )
        with closing(self.connect()) as database:
            row = database.execute("SELECT * FROM personal_recordings WHERE id=?", (record.id,)).fetchone()
            intent = database.execute("SELECT id FROM storage_cleanup_jobs WHERE id=?", (intent_id,)).fetchone()
        self.assertEqual(
            (row["student_id"], row["storage_key"], row["duration_seconds"]),
            (self.student_id, "personal-recordings/1/answer.webm", 12.5),
        )
        self.assertIsNone(intent)

    def test_missing_intent_rolls_back_metadata_insert(self):
        with self.assertRaises(PersonalRecordingIntentError):
            self.repository.finalize_recording(
                self.student_id,
                self.data,
                "personal-recordings/1/missing-intent.webm",
                "audio/webm",
                42,
                12.5,
                404,
                1000,
            )

        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 0)

    def test_finalize_uses_transaction_queue_to_cancel_intent(self):
        intent_id = self.create_intent()

        with patch.object(SQLiteStorageCleanupQueue, "cancel", return_value=False):
            with self.assertRaises(PersonalRecordingIntentError):
                self.repository.finalize_recording(
                    self.student_id,
                    self.data,
                    "personal-recordings/1/answer.webm",
                    "audio/webm",
                    42,
                    12.5,
                    intent_id,
                    1000,
                )

        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 0)
            self.assertIsNotNone(
                database.execute("SELECT id FROM storage_cleanup_jobs WHERE id=?", (intent_id,)).fetchone()
            )

    def test_conflict_keeps_the_new_cleanup_intent(self):
        first_intent = self.create_intent("personal-recordings/1/first.webm")
        self.repository.finalize_recording(
            self.student_id,
            self.data,
            "personal-recordings/1/first.webm",
            "audio/webm",
            1,
            1.0,
            first_intent,
            1000,
        )
        second_intent = self.create_intent("personal-recordings/1/second.webm")

        with self.assertRaises(PersonalRecordingConflictError):
            self.repository.finalize_recording(
                self.student_id,
                self.data,
                "personal-recordings/1/second.webm",
                "audio/webm",
                1,
                1.0,
                second_intent,
                1001,
            )

        with closing(self.connect()) as database:
            self.assertEqual(database.execute("SELECT COUNT(*) FROM personal_recordings").fetchone()[0], 1)
            self.assertIsNotNone(
                database.execute("SELECT id FROM storage_cleanup_jobs WHERE id=?", (second_intent,)).fetchone()
            )

    def test_reads_filter_owner_and_expiry_and_return_typed_records(self):
        with closing(self.connect()) as database, database:
            current_id = database.execute(
                """INSERT INTO personal_recordings(
                       student_id,run_id,variant_id,task_number,question_number,label,storage_key,
                       mime_type,size_bytes,duration_seconds,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.student_id,
                    "current",
                    "demo",
                    1,
                    2,
                    "Current",
                    "current.webm",
                    "audio/webm",
                    10,
                    1.0,
                    1000,
                    2000,
                ),
            ).lastrowid
            database.execute(
                """INSERT INTO personal_recordings(
                       student_id,run_id,variant_id,task_number,question_number,label,storage_key,
                       mime_type,size_bytes,duration_seconds,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    self.student_id,
                    "expired",
                    "demo",
                    1,
                    3,
                    "Expired",
                    "expired.webm",
                    "audio/webm",
                    11,
                    1.0,
                    900,
                    999,
                ),
            )

        records = self.repository.recordings(self.student_id, 1000)
        access = self.repository.recording_file(current_id, self.student_id, 1000)

        self.assertEqual([record.run_id for record in records], ["current"])
        self.assertEqual((access.storage_key, access.mime_type, access.size_bytes), ("current.webm", "audio/webm", 10))
        self.assertIsNone(self.repository.recording_file(current_id, self.other_id, 1000))
        self.assertIsNone(self.repository.recording_file(current_id, self.student_id, 2000))


if __name__ == "__main__":
    unittest.main()
