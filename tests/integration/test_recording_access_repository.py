import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.infrastructure.database.recording_access_repository import (
    SQLiteRecordingAccessRepository,
)
from trainer.services.recording_access_repository import (
    LegacyRecordingRecord,
    ReviewAssetRecord,
    ReviewRecordingRecord,
    StoredFile,
)


class SQLiteRecordingAccessRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.database_path)
        self.repository = SQLiteRecordingAccessRepository(self.connect)
        with closing(self.connect()) as database, database:
            database.executescript(
                """
                INSERT INTO users(id,email,password_hash,display_name,role,created_at) VALUES
                    (1,'student@example.test','hash','Student','student',1),
                    (2,'teacher@example.test','hash','Teacher','teacher',1),
                    (3,'other@example.test','hash','Other','student',1);
                INSERT INTO study_groups(id,teacher_id,name,join_code,created_at)
                VALUES (10,2,'Archive','ABC234',1);
                INSERT INTO assignments(id,group_id,teacher_id,title,variant_id,tasks_json,created_at)
                VALUES (20,10,2,'Old work','demo-2026','[2]',1);
                INSERT INTO submissions(
                    id,assignment_id,student_id,attempt_number,status,run_json,submitted_at
                ) VALUES (30,20,1,1,'submitted','{}',1);
                INSERT INTO recordings(
                    id,submission_id,task_number,label,file_name,mime_type,size_bytes,created_at
                ) VALUES (40,30,2,'Legacy','30/legacy.webm','audio/webm',10,1);
                INSERT INTO review_requests(
                    id,student_id,kind,status,variant_id,run_json,submitted_at
                ) VALUES
                    (50,1,'task','queued','demo-2026','{}',1),
                    (51,3,'task','reviewed','demo-2026','{}',2);
                INSERT INTO review_request_items(id,request_id,task_number,task_snapshot_json)
                VALUES
                    (60,50,2,'{}'),
                    (61,51,2,'{}');
                INSERT INTO review_request_recordings(
                    id,item_id,label,storage_key,mime_type,size_bytes,duration_seconds,
                    created_at,expires_at
                ) VALUES (70,60,'Review','review/answer.ogg','audio/ogg',11,1.0,1,500);
                INSERT INTO review_request_assets(
                    id,request_id,storage_key,mime_type,size_bytes,created_at
                ) VALUES
                    (80,50,'review/image.webp','image/webp',12,1),
                    (81,51,'review/other.webp','image/webp',13,2);
                """
            )

    def tearDown(self):
        self.directory.cleanup()

    def connect(self, factory=sqlite3.Connection):
        database = sqlite3.connect(self.database_path, factory=factory)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def test_reads_exact_records_and_returns_none_for_missing_ids(self):
        self.assertEqual(
            self.repository.legacy_recording(40),
            LegacyRecordingRecord(StoredFile("30/legacy.webm", "audio/webm", 10), "submitted", 1, 2),
        )
        self.assertEqual(
            self.repository.review_recording(70),
            ReviewRecordingRecord(StoredFile("review/answer.ogg", "audio/ogg", 11), "queued", 1, 500),
        )
        self.assertEqual(
            self.repository.review_asset(80),
            ReviewAssetRecord(StoredFile("review/image.webp", "image/webp", 12), "queued", 1),
        )
        for missing in (0, 999):
            with self.subTest(missing=missing):
                self.assertIsNone(self.repository.legacy_recording(missing))
                self.assertIsNone(self.repository.review_recording(missing))
                self.assertIsNone(self.repository.review_asset(missing))

    def test_review_recording_returns_expiry_without_filtering_it(self):
        with closing(self.connect()) as database, database:
            database.execute("UPDATE review_request_recordings SET expires_at=1 WHERE id=70")

        self.assertEqual(
            self.repository.review_recording(70),
            ReviewRecordingRecord(StoredFile("review/answer.ogg", "audio/ogg", 11), "queued", 1, 1),
        )

    def test_review_asset_join_keeps_requests_isolated(self):
        self.assertEqual(self.repository.review_asset(80).student_id, 1)
        self.assertEqual(self.repository.review_asset(81).student_id, 3)

    def test_each_read_closes_its_connection(self):
        class TrackingConnection(sqlite3.Connection):
            instances = []

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.closed = False
                self.instances.append(self)

            def close(self):
                self.closed = True
                super().close()

        tracking = SQLiteRecordingAccessRepository(lambda: self.connect(factory=TrackingConnection))

        tracking.legacy_recording(40)
        tracking.review_recording(70)
        tracking.review_asset(80)

        self.assertEqual(len(TrackingConnection.instances), 3)
        self.assertTrue(all(connection.closed for connection in TrackingConnection.instances))
