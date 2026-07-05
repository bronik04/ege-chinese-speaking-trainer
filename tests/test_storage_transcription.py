import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.database import connect, initialize
from backend.postgres import POSTGRES_SCHEMA, Connection
from backend.storage import LocalAudioStorage, S3AudioStorage, storage_from_env
from backend.transcription import claim, complete, enqueue, fail


class LocalStorageTest(unittest.TestCase):
    def test_round_trip_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webm"
            target = root / "download.webm"
            source.write_bytes(b"audio")
            storage = LocalAudioStorage(root / "audio")
            storage.put("12/answer.webm", source, "audio/webm")
            self.assertEqual(storage.read("12/answer.webm"), b"audio")
            storage.download("12/answer.webm", target)
            self.assertEqual(target.read_bytes(), b"audio")
            storage.delete("12/answer.webm")
            with self.assertRaises(FileNotFoundError):
                storage.read("12/answer.webm")

    def test_rejects_path_escape_and_unknown_backend(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = LocalAudioStorage(Path(directory))
            with self.assertRaises(ValueError):
                storage.read("../secret")
            with patch.dict(os.environ, {"TRAINER_AUDIO_STORAGE": "unknown"}):
                with self.assertRaises(RuntimeError):
                    storage_from_env(Path(directory))


class S3StorageTest(unittest.TestCase):
    @patch("boto3.client")
    def test_uses_private_s3_object_operations(self, client_factory):
        client = Mock()
        client.get_object.return_value = {"Body": Mock(read=Mock(return_value=b"audio"))}
        client_factory.return_value = client
        storage = S3AudioStorage(bucket="answers", endpoint_url="https://account.r2.example", region="auto")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "answer.webm"
            source.write_bytes(b"audio")
            storage.put("1/answer.webm", source, "audio/webm")
        self.assertEqual(storage.read("1/answer.webm"), b"audio")
        storage.delete("1/answer.webm")
        client_factory.assert_called_once_with("s3", endpoint_url="https://account.r2.example", region_name="auto")
        client.upload_file.assert_called_once()
        client.get_object.assert_called_once_with(Bucket="answers", Key="1/answer.webm")
        client.delete_object.assert_called_once_with(Bucket="answers", Key="1/answer.webm")


class TranscriptionQueueTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "trainer.sqlite3"
        initialize(self.root, self.root / "audio", self.path)
        with connect(self.path) as database:
            teacher = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                ("teacher@example.test", "x", "Teacher", "teacher", 1),
            ).lastrowid
            student = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                ("student@example.test", "x", "Student", "student", 1),
            ).lastrowid
            group = database.execute(
                "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
                (teacher, "Group", "ABC123", 1),
            ).lastrowid
            assignment = database.execute(
                "INSERT INTO assignments(group_id,teacher_id,title,variant_id,tasks_json,created_at) VALUES (?,?,?,?,?,?)",
                (group, teacher, "Work", "2026", "[1]", 1),
            ).lastrowid
            submission = database.execute(
                "INSERT INTO submissions(assignment_id,student_id,attempt_number,run_json,submitted_at) VALUES (?,?,?,?,?)",
                (assignment, student, 1, "{}", 1),
            ).lastrowid
            self.recording = database.execute(
                """INSERT INTO recordings(submission_id,task_number,label,file_name,mime_type,size_bytes,
                                            transcript_status,created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (submission, 1, "Answer", "answer.webm", "audio/webm", 5, "pending", 1),
            ).lastrowid

    def tearDown(self):
        self.directory.cleanup()

    def test_claim_and_complete(self):
        with connect(self.path) as database:
            enqueue(database, self.recording, now=10)
        with connect(self.path) as database:
            job = claim(database, now=10)
            self.assertEqual(job["recording_id"], self.recording)
            complete(database, job["id"], self.recording, "你好", now=11)
        with connect(self.path) as database:
            row = database.execute(
                "SELECT transcript_status, transcript_text FROM recordings WHERE id = ?", (self.recording,)
            ).fetchone()
        self.assertEqual(dict(row), {"transcript_status": "completed", "transcript_text": "你好"})

    def test_worker_downloads_and_transcribes_recording(self):
        from scripts import transcription_worker

        audio_root = self.root / "audio"
        audio_root.mkdir(exist_ok=True)
        (audio_root / "answer.webm").write_bytes(b"audio")
        with connect(self.path) as database:
            enqueue(database, self.recording, now=10)
            database.execute("UPDATE transcription_jobs SET available_at = 0 WHERE recording_id = ?", (self.recording,))

        transcriber = Mock()
        transcriber.transcribe.return_value = "这是学生的回答"
        with (
            patch.object(transcription_worker.server, "connect", side_effect=lambda: connect(self.path)),
            patch.object(transcription_worker.server, "AUDIO_DIR", audio_root),
        ):
            self.assertTrue(transcription_worker.process_one(transcriber))

        with connect(self.path) as database:
            row = database.execute(
                "SELECT transcript_status, transcript_text FROM recordings WHERE id = ?", (self.recording,)
            ).fetchone()
        self.assertEqual(row["transcript_status"], "completed")
        self.assertEqual(row["transcript_text"], "这是学生的回答")
        transcriber.transcribe.assert_called_once()

    def test_failure_is_retried_then_stopped(self):
        with connect(self.path) as database:
            enqueue(database, self.recording, now=10)
        with connect(self.path) as database:
            job = claim(database, now=10)
            fail(database, job, RuntimeError("temporary"), max_attempts=2, now=11)
        with connect(self.path) as database:
            retried = claim(database, now=30)
            fail(database, retried, RuntimeError("final"), max_attempts=2, now=31)
            status = database.execute(
                "SELECT status FROM transcription_jobs WHERE recording_id = ?", (self.recording,)
            ).fetchone()["status"]
        self.assertEqual(status, "failed")


class PostgresCompatibilityTest(unittest.TestCase):
    def test_placeholder_and_ignore_translation(self):
        self.assertEqual(Connection._translate("SELECT * FROM users WHERE id = ?"), "SELECT * FROM users WHERE id = %s")
        translated = Connection._translate("INSERT OR IGNORE INTO group_members VALUES (?, ?, ?)")
        self.assertIn("ON CONFLICT DO NOTHING", translated)
        self.assertIn("%s", translated)

    def test_schema_contains_scaling_tables(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS transcription_jobs", POSTGRES_SCHEMA)
        self.assertIn("CREATE TABLE IF NOT EXISTS recordings", POSTGRES_SCHEMA)


if __name__ == "__main__":
    unittest.main()
