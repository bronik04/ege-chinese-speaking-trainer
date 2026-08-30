import json
import os
import secrets
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import asgi
from trainer import main as trainer_main
from trainer.api import dependencies, routes, runtime
from trainer.api.controllers import auth, personal_recordings, recordings, review_requests
from trainer.api.errors import ApiError
from trainer.api.results import FileResult, RequestContext
from trainer.api.schemas import PersonalRecordingUpload
from trainer.api.security import request_has_same_origin
from trainer.domain.accounts import password_hash, password_matches
from trainer.domain.recording_retention import expires_at
from trainer.infrastructure.database.queries import review_requests as review_request_queries
from trainer.services.storage_cleanup import process_cleanup_jobs


class SecurityHelpersTest(unittest.TestCase):
    def test_password_hash_round_trip(self):
        encoded = password_hash("correct horse battery staple")
        self.assertTrue(password_matches("correct horse battery staple", encoded))
        self.assertFalse(password_matches("wrong password", encoded))

    def test_same_origin_requires_browser_source(self):
        host = "127.0.0.1:8080"
        self.assertTrue(request_has_same_origin(host, "http://127.0.0.1:8080", None, "same-origin"))
        self.assertTrue(request_has_same_origin(host, None, "http://127.0.0.1:8080/page", "same-origin"))
        self.assertFalse(request_has_same_origin(host, None, None, None))
        self.assertFalse(request_has_same_origin(host, "https://evil.example", None, "cross-site"))


class FileResponseTest(unittest.IsolatedAsyncioTestCase):
    stored = FileResult(key="answer.webm", mime_type="audio/webm", size_bytes=10)

    @staticmethod
    async def response_body(response):
        return b"".join([chunk async for chunk in response.body_iterator])

    async def test_remote_recording_without_range_streams_full_body_with_exact_length(self):
        def remote_path(_root, _key):
            return None

        def full_stream(_root, _key, *, start=None, end=None):
            self.assertIsNone(start)
            self.assertIsNone(end)
            return iter([b"0123", b"456789"])

        with (
            patch.object(routes, "storage_local_path", remote_path),
            patch.object(routes, "stream_recording", full_stream),
        ):
            response = routes.file_response(self.stored)
            body = await self.response_body(response)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-length"], "10")
        self.assertEqual(body, b"0123456789")

    async def test_remote_recording_range_streams_exact_inclusive_bounds(self):
        stream_calls = []

        def remote_path(_root, _key):
            return None

        def ranged_stream(_root, key, *, start=None, end=None):
            stream_calls.append((key, start, end))
            return iter([b"23", b"45"])

        with (
            patch.object(routes, "storage_local_path", remote_path),
            patch.object(routes, "stream_recording", ranged_stream),
        ):
            response = routes.file_response(self.stored, "bytes=2-5")
            body = await self.response_body(response)

        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.headers["accept-ranges"], "bytes")
        self.assertEqual(response.headers["content-range"], "bytes 2-5/10")
        self.assertEqual(response.headers["content-length"], "4")
        self.assertEqual(body, b"2345")
        self.assertEqual(stream_calls, [("answer.webm", 2, 5)])

    def test_multiple_ranges_return_empty_416_without_accessing_storage(self):
        storage_calls = []

        def unexpected_local_path(*args, **kwargs):
            storage_calls.append(("local_path", args, kwargs))
            return None

        def unexpected_stream(*args, **kwargs):
            storage_calls.append(("stream", args, kwargs))
            return iter([b"unexpected"])

        with (
            patch.object(routes, "storage_local_path", unexpected_local_path),
            patch.object(routes, "stream_recording", unexpected_stream),
        ):
            response = routes.file_response(self.stored, "bytes=0-1,4-5")

        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.headers["content-range"], "bytes */10")
        self.assertEqual(response.body, b"")
        self.assertEqual(storage_calls, [])


class ApiFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_owner_email = os.environ.get("TRAINER_OWNER_EMAIL")
        os.environ["TRAINER_OWNER_EMAIL"] = "teacher@example.test"
        cls.temp_dir = tempfile.TemporaryDirectory()
        root = Path(cls.temp_dir.name)
        runtime.DATA_DIR = root
        runtime.DB_PATH = root / "trainer.sqlite3"
        runtime.AUDIO_DIR = root / "audio"
        runtime.MATERIAL_ASSET_DIR = root / "material-assets"
        runtime.REVIEW_ASSET_DIR = root / "assignment-assets"
        auth.MATERIAL_ASSET_DIR = runtime.MATERIAL_ASSET_DIR
        dependencies.DATA_DIR = root
        dependencies.AUDIO_DIR = runtime.AUDIO_DIR
        recordings.DATA_DIR = root
        recordings.AUDIO_DIR = runtime.AUDIO_DIR
        cls.original_validate_duration = runtime.validate_duration
        runtime.validate_duration = lambda path, task: 1.0
        cls.original_personal_validate_duration = personal_recordings.validate_duration
        personal_recordings.validate_duration = lambda path, task: 1.0
        cls.client_context = TestClient(asgi.app)
        cls.client = cls.client_context.__enter__()
        cls.origin = "http://testserver"

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        runtime.validate_duration = cls.original_validate_duration
        personal_recordings.validate_duration = cls.original_personal_validate_duration
        if cls.original_owner_email is None:
            os.environ.pop("TRAINER_OWNER_EMAIL", None)
        else:
            os.environ["TRAINER_OWNER_EMAIL"] = cls.original_owner_email
        cls.temp_dir.cleanup()

    def request(self, method, path, payload=None, cookie=None, include_origin=True):
        headers = {}
        if include_origin:
            headers["Origin"] = self.origin
            headers["Sec-Fetch-Site"] = "same-origin"
        if cookie:
            headers["Cookie"] = cookie
        self.client.cookies.clear()
        response = self.client.request(method, path, json=payload, headers=headers)
        return response.status_code, response.json() if response.content else {}, dict(response.headers)

    def request_audio(self, path, data, cookie):
        self.client.cookies.clear()
        response = self.client.post(
            path,
            content=data,
            headers={
                "Content-Type": "audio/webm",
                "Origin": self.origin,
                "Sec-Fetch-Site": "same-origin",
                "Cookie": cookie,
            },
        )
        return response.status_code, response.json()

    def request_bytes(self, path, cookie):
        self.client.cookies.clear()
        response = self.client.get(path, headers={"Cookie": cookie})
        return response.status_code, response.content, response.headers.get("Content-Type")

    def request_raw(self, path, cookie, headers=None):
        self.client.cookies.clear()
        response = self.client.get(path, headers={"Cookie": cookie, **(headers or {})})
        return response.status_code, dict(response.headers), response.content

    def create_recording(self):
        email = f"range-{secrets.token_hex(4)}@example.test"
        status, _, headers = self.request(
            "POST",
            "/api/auth/register",
            {"email": email, "password": "password123", "displayName": "Range"},
        )
        self.assertEqual(status, 201)
        cookie = self.cookie_from(headers)
        with runtime.connect() as database:
            student_id = database.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
            teacher_id = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                (f"range-teacher-{secrets.token_hex(4)}@example.test", "x", "Teacher", "teacher", 1),
            ).lastrowid
            group_id = database.execute(
                "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
                (teacher_id, "Group", secrets.token_hex(4).upper()[:6], 1),
            ).lastrowid
            database.execute(
                "INSERT INTO group_members(group_id,user_id,joined_at) VALUES (?,?,?)", (group_id, student_id, 1)
            )
            assignment_id = database.execute(
                "INSERT INTO assignments(group_id,teacher_id,title,variant_id,tasks_json,created_at) VALUES (?,?,?,?,?,?)",
                (group_id, teacher_id, "Work", "demo-2026", "[2]", 1),
            ).lastrowid
            submission_id = database.execute(
                """
                INSERT INTO submissions(assignment_id,student_id,attempt_number,status,run_json,submitted_at)
                VALUES (?,?,?,?,?,?)
                """,
                (assignment_id, student_id, 1, "uploading", "{}", None),
            ).lastrowid
        relative = f"{submission_id}/archive-recording.webm"
        runtime.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        (runtime.AUDIO_DIR / relative).parent.mkdir(parents=True, exist_ok=True)
        (runtime.AUDIO_DIR / relative).write_bytes(b"0123456789")
        with runtime.connect() as database:
            recording_id = database.execute(
                """INSERT INTO recordings(submission_id,task_number,question_number,label,file_name,mime_type,
                                             size_bytes,duration_seconds,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (submission_id, 2, None, "Archived range recording", relative, "audio/webm", 10, 1, 1),
            ).lastrowid
        return recording_id, cookie

    @staticmethod
    def cookie_from(headers):
        return headers["set-cookie"].split(";", 1)[0]

    @classmethod
    def token_from_outbox(cls, email, parameter):
        entries = [json.loads(line) for line in (runtime.DATA_DIR / "outbox.log").read_text().splitlines()]
        message = next(
            entry for entry in reversed(entries) if entry["to"] == email and f"?{parameter}=" in entry["body"]
        )
        url = message["body"].strip().splitlines()[-1]
        return parse_qs(urlparse(url).query)[parameter][0]

    def verified_owner_cookie(self):
        credentials = {"email": "teacher@example.test", "password": "teacher123"}
        status, _, headers = self.request(
            "POST",
            "/api/auth/register",
            {**credentials, "displayName": "Ли Лаоши"},
        )
        created = status == 201
        if status == 409:
            status, _, headers = self.request("POST", "/api/auth/login", credentials)
        self.assertIn(status, {200, 201})
        with runtime.connect() as database:
            database.execute(
                "UPDATE users SET email_verified_at=COALESCE(email_verified_at, 1) WHERE email=?",
                (credentials["email"],),
            )
        if created:
            self.addCleanup(self.delete_test_user, credentials["email"])
        return self.cookie_from(headers)

    @staticmethod
    def delete_test_user(email):
        with runtime.connect() as database:
            database.execute("DELETE FROM users WHERE email=?", (email,))

    def register_student(self, prefix):
        email = f"{prefix}-{secrets.token_hex(4)}@example.test"
        status, _, headers = self.request(
            "POST",
            "/api/auth/register",
            {"email": email, "password": "student123", "displayName": prefix.title()},
        )
        self.assertEqual(status, 201)
        return self.cookie_from(headers)

    def test_student_queues_single_task_for_owner_review(self):
        owner_cookie = self.verified_owner_cookie()
        student_cookie = self.register_student("review-single")
        other_student_cookie = self.register_student("review-other")

        status, created, _ = self.request(
            "POST",
            "/api/review-requests",
            {
                "kind": "task",
                "variantId": "demo-2026",
                "tasks": [2],
                "run": {"id": "review-task-2", "status": "completed", "completedTasks": [2]},
            },
            student_cookie,
        )
        self.assertEqual(status, 201, created)
        request_id = created["reviewRequest"]["id"]
        self.assertEqual(created["reviewRequest"]["status"], "uploading")

        status, owner_queue, _ = self.request("GET", "/api/teacher/review-requests", cookie=owner_cookie)
        self.assertEqual(status, 200)
        self.assertNotIn(request_id, {item["id"] for item in owner_queue["requests"]})

        status, recording = self.request_audio(
            f"/api/review-requests/{request_id}/recordings?task=2&label=Ответ",
            b"0123456789",
            student_cookie,
        )
        self.assertEqual(status, 201, recording)
        recording_id = recording["recording"]["id"]
        with runtime.connect() as database:
            created_at, recording_expires_at = database.execute(
                "SELECT created_at,expires_at FROM review_request_recordings WHERE id=?", (recording_id,)
            ).fetchone()
        self.assertEqual(recording_expires_at, expires_at(created_at))

        status, hidden_detail, _ = self.request(
            "GET", f"/api/teacher/review-requests/{request_id}", cookie=other_student_cookie
        )
        self.assertEqual(status, 404, hidden_detail)
        status, _, _ = self.request_bytes(f"/api/review-recordings/{recording_id}", other_student_cookie)
        self.assertEqual(status, 404)

        status, completed, _ = self.request("POST", f"/api/review-requests/{request_id}/complete", {}, student_cookie)
        self.assertEqual(status, 200, completed)
        self.assertEqual(completed["reviewRequest"]["status"], "queued")

        status, owner_queue, _ = self.request("GET", "/api/teacher/review-requests", cookie=owner_cookie)
        self.assertEqual(status, 200)
        queued = next(item for item in owner_queue["requests"] if item["id"] == request_id)
        self.assertEqual(queued["status"], "queued")
        status, history, _ = self.request("GET", "/api/student/review-requests", cookie=student_cookie)
        self.assertEqual(status, 200)
        queued_student_item = next(item for item in history["requests"] if item["id"] == request_id)
        self.assertNotIn("total", queued_student_item)
        self.assertNotIn("maximum", queued_student_item)

        status, headers, body = self.request_raw(
            f"/api/review-recordings/{recording_id}", owner_cookie, headers={"Range": "bytes=2-5"}
        )
        self.assertEqual(status, 206)
        self.assertEqual(headers["content-range"], "bytes 2-5/10")
        self.assertEqual(body, b"2345")

        scores = {"2": {"content": 3, "organization": 2, "language": 2}}
        status, blocked, _ = self.request(
            "PUT", f"/api/teacher/review-requests/{request_id}/scores", {"scores": scores}, student_cookie
        )
        self.assertEqual(status, 403, blocked)
        status, reviewed, _ = self.request(
            "PUT", f"/api/teacher/review-requests/{request_id}/scores", {"scores": scores}, owner_cookie
        )
        self.assertEqual(status, 200, reviewed)
        self.assertEqual(reviewed["reviewRequest"]["status"], "reviewed")
        self.assertEqual(reviewed["reviewRequest"]["total"], 7)
        self.assertEqual(reviewed["reviewRequest"]["maximum"], 7)
        self.assertNotIn("comment", json.dumps(reviewed))

        status, history, _ = self.request("GET", "/api/student/review-requests", cookie=student_cookie)
        self.assertEqual(status, 200)
        student_item = next(item for item in history["requests"] if item["id"] == request_id)
        self.assertEqual((student_item["total"], student_item["maximum"]), (7, 7))

        corrected_scores = {"2": {"content": 2, "organization": 1, "language": 1}}
        status, corrected, _ = self.request(
            "PUT",
            f"/api/teacher/review-requests/{request_id}/scores",
            {"scores": corrected_scores},
            owner_cookie,
        )
        self.assertEqual(status, 200, corrected)
        self.assertEqual((corrected["reviewRequest"]["total"], corrected["reviewRequest"]["maximum"]), (4, 7))

        with runtime.connect() as database:
            database.execute("UPDATE review_request_recordings SET expires_at=100 WHERE id=?", (recording_id,))
        with (
            patch.object(recordings.time, "time", return_value=100),
            patch.object(review_request_queries.time, "time", return_value=100),
        ):
            self.assertEqual(self.request_bytes(f"/api/review-recordings/{recording_id}", student_cookie)[0], 404)
            self.assertEqual(self.request_bytes(f"/api/review-recordings/{recording_id}", owner_cookie)[0], 404)
            status, expired_history, _ = self.request("GET", "/api/student/review-requests", cookie=student_cookie)
            expired_item = next(item for item in expired_history["requests"] if item["id"] == request_id)
            self.assertEqual(expired_item["items"][0]["recordings"], [])
            status, expired_detail, _ = self.request(
                "GET", f"/api/teacher/review-requests/{request_id}", cookie=owner_cookie
            )
            self.assertEqual(expired_detail["reviewRequest"]["items"][0]["recordings"], [])

    def test_personal_recordings_are_private_owner_bound_and_expire(self):
        student_cookie = self.register_student("personal-recording")
        other_student_cookie = self.register_student("personal-recording-other")
        upload_path = (
            "/api/personal-recordings?runId=run-1&variantId=demo-2026&taskNumber=2&questionNumber=1&label=Answer"
        )

        status, payload = self.request_audio(upload_path, b"0123456789", student_cookie)
        self.assertEqual(status, 201, payload)
        recording = payload["recording"]
        self.assertEqual(
            set(recording),
            {"id", "runId", "variantId", "taskNumber", "questionNumber", "label", "createdAt", "expiresAt"},
        )
        recording_id = recording["id"]

        with runtime.connect() as database:
            storage_key = database.execute(
                "SELECT storage_key FROM personal_recordings WHERE id=?", (recording_id,)
            ).fetchone()["storage_key"]
            cleanup_jobs = database.execute(
                "SELECT COUNT(*) FROM storage_cleanup_jobs WHERE audio_keys_json LIKE ?",
                (f'%"{storage_key}"%',),
            ).fetchone()[0]
        self.assertEqual(cleanup_jobs, 0)

        status, listed, _ = self.request("GET", "/api/personal-recordings", cookie=student_cookie)
        self.assertEqual(status, 200, listed)
        self.assertEqual(listed["recordings"], [recording])
        self.assertNotIn("storageKey", json.dumps(listed))

        status, body, mime_type = self.request_bytes(f"/api/personal-recordings/{recording_id}", student_cookie)
        self.assertEqual((status, body, mime_type), (200, b"0123456789", "audio/webm"))
        self.assertEqual(self.request("GET", "/api/personal-recordings")[0], 401)
        self.assertEqual(self.request_bytes(f"/api/personal-recordings/{recording_id}", other_student_cookie)[0], 404)

        status, duplicate = self.request_audio(upload_path, b"second", student_cookie)
        self.assertEqual(status, 409, duplicate)
        self.assertEqual(duplicate["code"], "personal_recording_exists")

        status, invalid_metadata, _ = self.request(
            "POST",
            "/api/personal-recordings?runId=run-2&variantId=demo-2026&taskNumber=2&label=Answer",
            cookie=student_cookie,
        )
        self.assertEqual(status, 422, invalid_metadata)
        self.client.cookies.clear()
        invalid_mime = self.client.post(
            "/api/personal-recordings?runId=run-2&variantId=demo-2026&taskNumber=2&questionNumber=1&label=Answer",
            content=b"not-audio",
            headers={
                "Content-Type": "text/plain",
                "Origin": self.origin,
                "Sec-Fetch-Site": "same-origin",
                "Cookie": student_cookie,
            },
        )
        self.assertEqual(invalid_mime.status_code, 415, invalid_mime.json())

        status, invalid_position = self.request_audio(
            "/api/personal-recordings?runId=run-3&variantId=demo-2026&taskNumber=2&questionNumber=2&label=Answer",
            b"invalid-position",
            student_cookie,
        )
        self.assertEqual(status, 400, invalid_position)

        with runtime.connect() as database:
            row = database.execute(
                "SELECT storage_key,created_at,expires_at FROM personal_recordings WHERE id=?", (recording_id,)
            ).fetchone()
            database.execute("UPDATE personal_recordings SET expires_at=0 WHERE id=?", (recording_id,))
        self.assertTrue(row["storage_key"].startswith("personal-recordings/"))
        self.assertTrue((runtime.AUDIO_DIR / row["storage_key"]).is_file())
        self.assertFalse((runtime.ROOT / "public" / row["storage_key"]).exists())
        self.assertEqual(row["expires_at"], expires_at(row["created_at"]))
        self.assertEqual(self.request_bytes(f"/api/personal-recordings/{recording_id}", student_cookie)[0], 404)

    def test_personal_recording_has_durable_cleanup_intent_before_storage_write(self):
        payload = PersonalRecordingUpload(
            runId="durable-run",
            variantId="demo-2026",
            taskNumber=2,
            questionNumber=1,
            label="Answer",
        )
        user = {"id": 1, "email": "student@example.test", "role": "student"}
        original_connect = runtime.connect
        connect_calls = 0
        with original_connect() as database:
            jobs_before = database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0]

        def fail_second_connect():
            nonlocal connect_calls
            connect_calls += 1
            if connect_calls == 2:
                raise sqlite3.OperationalError("database unavailable after storage write")
            return original_connect()

        with (
            patch.object(personal_recordings.runtime, "connect", side_effect=fail_second_connect),
            patch.object(personal_recordings, "validate_duration", return_value=1.0),
            patch.object(
                personal_recordings,
                "create_personal_recording",
                side_effect=sqlite3.OperationalError("metadata insert failed"),
            ),
            self.assertRaises(sqlite3.OperationalError),
        ):
            personal_recordings.personal_recording_create(
                payload,
                b"durable-audio",
                "audio/webm",
                user,
                RequestContext(client_ip="127.0.0.1", user_agent="test"),
            )

        with original_connect() as database:
            jobs = database.execute("SELECT audio_keys_json FROM storage_cleanup_jobs").fetchall()
        self.assertEqual(len(jobs), jobs_before + 1)
        self.assertIn("personal-recordings/1/", jobs[-1]["audio_keys_json"])

    def test_personal_recording_upload_intent_is_not_processed_while_metadata_is_committing(self):
        with runtime.connect() as database:
            user_id = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                (f"personal-cleanup-{secrets.token_hex(4)}@example.test", "hash", "Student", "student", 1),
            ).lastrowid
        user = {"id": user_id, "role": "student"}
        payload = PersonalRecordingUpload(
            runId="concurrent-cleanup-run",
            variantId="demo-2026",
            taskNumber=2,
            questionNumber=1,
            label="Answer",
        )
        original_write = personal_recordings.write_recording
        cleanup_summaries = []

        def write_while_cleanup_runs(root, storage_key, source, mime_type):
            original_write(root, storage_key, source, mime_type)
            with runtime.connect() as database:
                cleanup_summaries.append(
                    process_cleanup_jobs(
                        database,
                        audio_root=runtime.AUDIO_DIR,
                        material_root=runtime.MATERIAL_ASSET_DIR,
                        assignment_root=runtime.REVIEW_ASSET_DIR,
                        now=int(time.time()),
                    )
                )

        with (
            patch.object(personal_recordings, "validate_duration", return_value=1.0),
            patch.object(personal_recordings, "write_recording", side_effect=write_while_cleanup_runs),
        ):
            result = personal_recordings.personal_recording_create(
                payload,
                b"concurrent-audio",
                "audio/webm",
                user,
                RequestContext(client_ip="127.0.0.1", user_agent="test"),
            )

        with runtime.connect() as database:
            row = database.execute(
                "SELECT storage_key FROM personal_recordings WHERE id=?", (result.payload["recording"]["id"],)
            ).fetchone()
            intent_count = database.execute(
                "SELECT COUNT(*) FROM storage_cleanup_jobs WHERE audio_keys_json LIKE ?",
                (f'%"{row["storage_key"]}"%',),
            ).fetchone()[0]
        self.assertEqual((cleanup_summaries[0].completed, cleanup_summaries[0].failed), (0, 0))
        self.assertGreaterEqual(cleanup_summaries[0].pending, 1)
        self.assertEqual(intent_count, 0)
        self.assertTrue((runtime.AUDIO_DIR / row["storage_key"]).is_file())

    def test_personal_recording_removes_temporary_file_when_cleanup_intent_fails(self):
        payload = PersonalRecordingUpload(
            runId="failed-intent-run",
            variantId="demo-2026",
            taskNumber=2,
            questionNumber=1,
            label="Answer",
        )
        temporary_directory = runtime.DATA_DIR / "tmp"
        before = set(temporary_directory.glob("personal-recording-*"))
        with (
            patch.object(personal_recordings.runtime, "connect", side_effect=sqlite3.OperationalError("database down")),
            patch.object(personal_recordings, "validate_duration", return_value=1.0),
            self.assertRaises(sqlite3.OperationalError),
        ):
            personal_recordings.personal_recording_create(
                payload,
                b"temporary-audio",
                "audio/webm",
                {"id": 1, "role": "student"},
                RequestContext(client_ip="127.0.0.1", user_agent="test"),
            )
        self.assertEqual(set(temporary_directory.glob("personal-recording-*")), before)

    def test_student_queues_complete_attempt_for_owner_review(self):
        owner_cookie = self.verified_owner_cookie()
        student_cookie = self.register_student("review-attempt")
        status, created, _ = self.request(
            "POST",
            "/api/review-requests",
            {
                "kind": "attempt",
                "variantId": "demo-2026",
                "tasks": [1, 2],
                "run": {"id": "review-attempt-1-2", "status": "completed", "completedTasks": [1, 2]},
            },
            student_cookie,
        )
        self.assertEqual(status, 201, created)
        request_id = created["reviewRequest"]["id"]

        for question in range(1, 5):
            status, recording = self.request_audio(
                f"/api/review-requests/{request_id}/recordings?task=1&question={question}&label=Вопрос",
                f"question-{question}".encode(),
                student_cookie,
            )
            self.assertEqual(status, 201, recording)

        status, incomplete, _ = self.request("POST", f"/api/review-requests/{request_id}/complete", {}, student_cookie)
        self.assertEqual(status, 409, incomplete)
        self.assertEqual(incomplete["code"], "review_request_incomplete")
        self.assertEqual(incomplete["missing"], [{"task": 1, "question": 5}, {"task": 2}])
        status, owner_queue, _ = self.request("GET", "/api/teacher/review-requests", cookie=owner_cookie)
        self.assertNotIn(request_id, {item["id"] for item in owner_queue["requests"]})

        status, _ = self.request_audio(
            f"/api/review-requests/{request_id}/recordings?task=1&question=5&label=Вопрос",
            b"question-5",
            student_cookie,
        )
        self.assertEqual(status, 201)
        status, _ = self.request_audio(
            f"/api/review-requests/{request_id}/recordings?task=2&label=Ответ",
            b"task-2",
            student_cookie,
        )
        self.assertEqual(status, 201)

        status, completed, _ = self.request("POST", f"/api/review-requests/{request_id}/complete", {}, student_cookie)
        self.assertEqual(status, 200, completed)
        status, detail, _ = self.request("GET", f"/api/teacher/review-requests/{request_id}", cookie=owner_cookie)
        self.assertEqual(status, 200, detail)
        review_request = detail["reviewRequest"]
        self.assertEqual(review_request["status"], "queued")
        self.assertEqual(review_request["tasks"], [1, 2])
        self.assertEqual(set(review_request["material"]), {"1", "2"})
        material_json = json.dumps(review_request["material"])
        self.assertNotIn("assets/variants/", material_json)
        self.assertRegex(material_json, r"/api/review-assets/\d+")
        self.assertEqual(sum(len(item["recordings"]) for item in review_request["items"]), 6)

    def test_student_discards_only_own_uploading_review_and_private_blobs(self):
        student_cookie = self.register_student("review-discard")
        status, created, _ = self.request(
            "POST",
            "/api/review-requests",
            {
                "kind": "task",
                "variantId": "demo-2026",
                "tasks": [2],
                "run": {"id": "review-discard", "status": "completed", "completedTasks": [2]},
            },
            student_cookie,
        )
        self.assertEqual(status, 201, created)
        request_id = created["reviewRequest"]["id"]
        status, _ = self.request_audio(
            f"/api/review-requests/{request_id}/recordings?task=2&label=Ответ",
            b"private-audio",
            student_cookie,
        )
        self.assertEqual(status, 201)
        with runtime.connect() as database:
            audio_key = database.execute(
                """SELECT review_request_recordings.storage_key FROM review_request_recordings
                   JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
                   WHERE review_request_items.request_id=?""",
                (request_id,),
            ).fetchone()["storage_key"]
            asset_keys = [
                row["storage_key"]
                for row in database.execute(
                    "SELECT storage_key FROM review_request_assets WHERE request_id=?", (request_id,)
                ).fetchall()
            ]
        self.assertTrue(asset_keys)

        other_student_cookie = self.register_student("review-discard-other")
        status, hidden, _ = self.request("DELETE", f"/api/review-requests/{request_id}", cookie=other_student_cookie)
        self.assertEqual(status, 404, hidden)
        self.assertEqual(hidden["code"], "review_request_not_found")

        status, discarded, _ = self.request("DELETE", f"/api/review-requests/{request_id}", cookie=student_cookie)

        self.assertEqual(status, 200, discarded)
        with runtime.connect() as database:
            self.assertIsNone(database.execute("SELECT id FROM review_requests WHERE id=?", (request_id,)).fetchone())
        self.assertFalse((runtime.AUDIO_DIR / audio_key).exists())
        self.assertTrue(all(not (runtime.REVIEW_ASSET_DIR / key).exists() for key in asset_keys))

        status, queued_created, _ = self.request(
            "POST",
            "/api/review-requests",
            {
                "kind": "task",
                "variantId": "demo-2026",
                "tasks": [2],
                "run": {"id": "review-no-discard", "status": "completed", "completedTasks": [2]},
            },
            student_cookie,
        )
        queued_id = queued_created["reviewRequest"]["id"]
        self.request_audio(
            f"/api/review-requests/{queued_id}/recordings?task=2&label=Ответ", b"queued-audio", student_cookie
        )
        status, _, _ = self.request("POST", f"/api/review-requests/{queued_id}/complete", {}, student_cookie)
        self.assertEqual(status, 200)

        status, conflict, _ = self.request("DELETE", f"/api/review-requests/{queued_id}", cookie=student_cookie)
        self.assertEqual(status, 409, conflict)
        self.assertEqual(conflict["code"], "review_request_not_uploading")

    def test_discard_and_complete_cannot_both_win_after_status_was_read(self):
        student_cookie = self.register_student("review-discard-complete-race")
        status, created, _ = self.request(
            "POST",
            "/api/review-requests",
            {
                "kind": "task",
                "variantId": "demo-2026",
                "tasks": [2],
                "run": {"id": "discard-complete-race", "status": "completed", "completedTasks": [2]},
            },
            student_cookie,
        )
        self.assertEqual(status, 201, created)
        request_id = created["reviewRequest"]["id"]
        status, _ = self.request_audio(
            f"/api/review-requests/{request_id}/recordings?task=2&label=Ответ",
            b"complete-race-audio",
            student_cookie,
        )
        self.assertEqual(status, 201)
        with runtime.connect() as database:
            student = dict(
                database.execute(
                    """SELECT id,email,display_name,role,email_verified_at FROM users
                       WHERE email LIKE 'review-discard-complete-race-%' ORDER BY id DESC LIMIT 1"""
                ).fetchone()
            )
        user = {
            "id": student["id"],
            "email": student["email"],
            "displayName": student["display_name"],
            "role": student["role"],
            "emailVerified": student["email_verified_at"] is not None,
        }

        original_connect = runtime.connect
        delete_reached = threading.Event()
        resume_discard = threading.Event()
        complete_finished = threading.Event()
        discard_outcome = {}
        complete_outcome = {}
        discard_connections = 0

        class PausedDiscardConnection:
            def __init__(self, database):
                self.database = database

            def __enter__(self):
                self.database.__enter__()
                return self

            def __exit__(self, *arguments):
                return self.database.__exit__(*arguments)

            def commit(self):
                return self.database.commit()

            def rollback(self):
                return self.database.rollback()

            def close(self):
                return self.database.close()

            def execute(self, statement, parameters=()):
                if statement.strip().startswith("DELETE FROM review_requests"):
                    delete_reached.set()
                    if not resume_discard.wait(5):
                        raise AssertionError("discard was not released")
                return self.database.execute(statement, parameters)

        def interleaved_connect():
            nonlocal discard_connections
            database = original_connect()
            if threading.current_thread().name != "review-discard":
                return database
            discard_connections += 1
            return PausedDiscardConnection(database) if discard_connections == 1 else database

        def discard():
            try:
                discard_outcome["result"] = review_requests.review_request_discard(
                    request_id,
                    user,
                    RequestContext(client_ip="127.0.0.1", user_agent="discard-race-test"),
                )
            except Exception as error:
                discard_outcome["error"] = error

        def complete():
            try:
                complete_outcome["result"] = review_requests.review_request_complete(
                    request_id,
                    user,
                    RequestContext(client_ip="127.0.0.1", user_agent="complete-race-test"),
                )
            except Exception as error:
                complete_outcome["error"] = error
            finally:
                complete_finished.set()

        with patch.object(runtime, "connect", interleaved_connect):
            discard_thread = threading.Thread(target=discard, name="review-discard")
            discard_thread.start()
            self.assertTrue(delete_reached.wait(5), "discard did not reach its delete")
            complete_thread = threading.Thread(target=complete, name="review-complete")
            complete_thread.start()
            completed_before_discard = complete_finished.wait(2)
            resume_discard.set()
            discard_thread.join(5)
            complete_thread.join(5)

        self.assertFalse(discard_thread.is_alive())
        self.assertFalse(complete_thread.is_alive())
        self.assertFalse(completed_before_discard, "complete changed status while discard owned the request")
        self.assertIn("result", discard_outcome)
        self.assertNotIn("result", complete_outcome)
        self.assertIsInstance(complete_outcome.get("error"), ApiError)
        self.assertEqual(complete_outcome["error"].code, "review_request_not_found")
        with runtime.connect() as database:
            self.assertIsNone(database.execute("SELECT id FROM review_requests WHERE id=?", (request_id,)).fetchone())

    def test_discard_collects_keys_before_concurrent_replacement_can_commit(self):
        student_cookie = self.register_student("review-discard-upload-race")
        status, created, _ = self.request(
            "POST",
            "/api/review-requests",
            {
                "kind": "task",
                "variantId": "demo-2026",
                "tasks": [2],
                "run": {"id": "discard-upload-race", "status": "completed", "completedTasks": [2]},
            },
            student_cookie,
        )
        self.assertEqual(status, 201, created)
        request_id = created["reviewRequest"]["id"]
        status, _ = self.request_audio(
            f"/api/review-requests/{request_id}/recordings?task=2&label=Первый",
            b"initial-race-audio",
            student_cookie,
        )
        self.assertEqual(status, 201)
        with runtime.connect() as database:
            student = dict(
                database.execute(
                    """SELECT id,email,display_name,role,email_verified_at FROM users
                       WHERE email LIKE 'review-discard-upload-race-%' ORDER BY id DESC LIMIT 1"""
                ).fetchone()
            )
        user = {
            "id": student["id"],
            "email": student["email"],
            "displayName": student["display_name"],
            "role": student["role"],
            "emailVerified": student["email_verified_at"] is not None,
        }

        original_connect = runtime.connect
        delete_reached = threading.Event()
        resume_discard = threading.Event()
        upload_finished = threading.Event()
        discard_outcome = {}
        upload_outcome = {}
        discard_connections = 0

        class PausedDiscardConnection:
            def __init__(self, database):
                self.database = database

            def __enter__(self):
                self.database.__enter__()
                return self

            def __exit__(self, *arguments):
                return self.database.__exit__(*arguments)

            def commit(self):
                return self.database.commit()

            def rollback(self):
                return self.database.rollback()

            def close(self):
                return self.database.close()

            def execute(self, statement, parameters=()):
                if statement.strip().startswith("DELETE FROM review_requests"):
                    delete_reached.set()
                    if not resume_discard.wait(5):
                        raise AssertionError("discard was not released")
                return self.database.execute(statement, parameters)

        def interleaved_connect():
            nonlocal discard_connections
            database = original_connect()
            if threading.current_thread().name != "review-discard":
                return database
            discard_connections += 1
            return PausedDiscardConnection(database) if discard_connections == 1 else database

        def discard():
            try:
                discard_outcome["result"] = review_requests.review_request_discard(
                    request_id,
                    user,
                    RequestContext(client_ip="127.0.0.1", user_agent="discard-upload-race-test"),
                )
            except Exception as error:
                discard_outcome["error"] = error

        def replace_recording():
            try:
                upload_outcome["result"] = review_requests.review_recording_create(
                    request_id,
                    {"task": "2", "question": None, "label": "Замена"},
                    b"replacement-race-audio",
                    "audio/webm",
                    user,
                    RequestContext(client_ip="127.0.0.1", user_agent="discard-upload-race-test"),
                )
            except Exception as error:
                upload_outcome["error"] = error
            finally:
                upload_finished.set()

        with patch.object(runtime, "connect", interleaved_connect):
            discard_thread = threading.Thread(target=discard, name="review-discard")
            discard_thread.start()
            self.assertTrue(delete_reached.wait(5), "discard did not reach its delete")
            upload_thread = threading.Thread(target=replace_recording, name="review-upload")
            upload_thread.start()
            uploaded_before_discard = upload_finished.wait(2)
            resume_discard.set()
            discard_thread.join(5)
            upload_thread.join(5)

        self.assertFalse(discard_thread.is_alive())
        self.assertFalse(upload_thread.is_alive())
        self.assertFalse(uploaded_before_discard, "replacement committed after discard scanned storage keys")
        self.assertIn("result", discard_outcome)
        self.assertNotIn("result", upload_outcome)
        self.assertIsInstance(upload_outcome.get("error"), ApiError)
        self.assertEqual(upload_outcome["error"].code, "review_request_not_found")
        with runtime.connect() as database:
            process_cleanup_jobs(
                database,
                audio_root=runtime.AUDIO_DIR,
                material_root=runtime.MATERIAL_ASSET_DIR,
                assignment_root=runtime.REVIEW_ASSET_DIR,
            )
            self.assertIsNone(database.execute("SELECT id FROM review_requests WHERE id=?", (request_id,)).fetchone())
        self.assertEqual(list((runtime.AUDIO_DIR / f"review-requests/{request_id}").glob("*")), [])

    def test_completion_prevents_concurrent_review_recording_replacement(self):
        student_cookie = self.register_student("review-race")
        status, created, _ = self.request(
            "POST",
            "/api/review-requests",
            {
                "kind": "task",
                "variantId": "demo-2026",
                "tasks": [2],
                "run": {"id": "review-race", "status": "completed", "completedTasks": [2]},
            },
            student_cookie,
        )
        self.assertEqual(status, 201, created)
        request_id = created["reviewRequest"]["id"]
        status, initial = self.request_audio(
            f"/api/review-requests/{request_id}/recordings?task=2&label=Первый",
            b"original-audio",
            student_cookie,
        )
        self.assertEqual(status, 201, initial)
        with runtime.connect() as database:
            student = dict(
                database.execute(
                    """SELECT id,email,display_name,role,email_verified_at FROM users
                       WHERE email LIKE 'review-race-%' ORDER BY id DESC LIMIT 1"""
                ).fetchone()
            )
            initial_row = database.execute(
                """SELECT review_request_recordings.id,review_request_recordings.storage_key
                   FROM review_request_recordings
                   JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
                   WHERE review_request_items.request_id=?""",
                (request_id,),
            ).fetchone()
            initial_recording_id = initial_row["id"]
            initial_key = initial_row["storage_key"]
        user = {
            "id": student["id"],
            "email": student["email"],
            "displayName": student["display_name"],
            "role": student["role"],
            "emailVerified": student["email_verified_at"] is not None,
        }

        original_connect = runtime.connect
        status_selected = threading.Event()
        resume_upload = threading.Event()
        upload_outcome = {}

        class InterleavedConnection:
            def __init__(self, database):
                self.database = database
                self.execute_calls = 0

            def __enter__(self):
                self.database.__enter__()
                return self

            def __exit__(self, *arguments):
                return self.database.__exit__(*arguments)

            def commit(self):
                return self.database.commit()

            def rollback(self):
                return self.database.rollback()

            def close(self):
                return self.database.close()

            def execute(self, statement, parameters=()):
                if self.execute_calls == 0 and statement.strip() == "BEGIN IMMEDIATE":
                    status_selected.set()
                    if not resume_upload.wait(5):
                        raise AssertionError("completion did not release the concurrent upload")
                cursor = self.database.execute(statement, parameters)
                self.execute_calls += 1
                return cursor

        upload_connections = 0

        def interleaved_connect():
            nonlocal upload_connections
            database = original_connect()
            if "review-upload" not in threading.current_thread().name:
                return database
            upload_connections += 1
            return InterleavedConnection(database) if upload_connections == 2 else database

        def replace_recording():
            try:
                upload_outcome["result"] = review_requests.review_recording_create(
                    request_id,
                    {"task": "2", "question": None, "label": "Замена"},
                    b"replacement-audio",
                    "audio/webm",
                    user,
                    RequestContext(client_ip="127.0.0.1", user_agent="race-test"),
                )
            except Exception as error:
                upload_outcome["error"] = error

        with patch.object(runtime, "connect", interleaved_connect):
            upload_thread = threading.Thread(target=replace_recording, name="review-upload")
            upload_thread.start()
            self.assertTrue(status_selected.wait(5), "upload did not reach the guarded transition")
            try:
                status, completed, _ = self.request(
                    "POST", f"/api/review-requests/{request_id}/complete", {}, student_cookie
                )
                self.assertEqual(status, 200, completed)
            finally:
                resume_upload.set()
            upload_thread.join(5)
        self.assertFalse(upload_thread.is_alive())

        with runtime.connect() as database:
            request_status = database.execute(
                "SELECT status FROM review_requests WHERE id=?", (request_id,)
            ).fetchone()["status"]
            stored = database.execute(
                """SELECT review_request_recordings.id,review_request_recordings.storage_key
                   FROM review_request_recordings
                   JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
                   WHERE review_request_items.request_id=?""",
                (request_id,),
            ).fetchone()
        self.assertEqual(request_status, "queued")
        self.assertEqual((stored["id"], stored["storage_key"]), (initial_recording_id, initial_key))
        self.assertEqual((runtime.AUDIO_DIR / initial_key).read_bytes(), b"original-audio")
        self.assertEqual(
            list((runtime.AUDIO_DIR / f"review-requests/{request_id}").glob("*")),
            [runtime.AUDIO_DIR / initial_key],
        )
        self.assertIsInstance(upload_outcome.get("error"), ApiError)
        self.assertEqual(upload_outcome["error"].code, "review_request_not_uploading")
        self.assertNotIn("result", upload_outcome)

    def test_account_deletion_persists_cleanup_job_when_immediate_cleanup_fails(self):
        # Удаление файлов идёт после коммита, поэтому отказ хранилища не должен
        # ни отменять удаление аккаунта, ни терять задание на повторную очистку.
        email = "storage-failure@example.test"
        status, _, headers = self.request(
            "POST",
            "/api/auth/register",
            {"email": email, "password": "password123", "displayName": "Ученик"},
        )
        self.assertEqual(status, 201)
        cookie = self.cookie_from(headers)

        original = auth.process_cleanup_jobs

        def failing_cleanup(*_arguments, **_kwargs):
            raise OSError("storage down")

        auth.process_cleanup_jobs = failing_cleanup
        try:
            status, _, _ = self.request("DELETE", "/api/account", {"password": "password123"}, cookie)
        finally:
            auth.process_cleanup_jobs = original

        self.assertEqual(status, 200)
        with runtime.connect() as database:
            self.assertIsNone(database.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone())
            self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 1)

    def test_account_deletion_removes_private_review_recording_and_snapshot(self):
        owner_cookie = self.verified_owner_cookie()
        student_cookie = self.register_student("review-delete")
        other_student_cookie = self.register_student("review-delete-other")
        with runtime.connect() as database:
            student_id = database.execute(
                """SELECT id FROM users WHERE email LIKE 'review-delete-%'
                   AND email NOT LIKE 'review-delete-other-%' ORDER BY id DESC LIMIT 1"""
            ).fetchone()["id"]
            material_id = database.execute(
                """INSERT INTO materials(slug,owner_id,kind,task_number,title,year,source,status,content_json,
                                          created_at,updated_at,published_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    f"review-delete-{student_id}",
                    student_id,
                    "task",
                    2,
                    "Review delete",
                    2027,
                    "Author",
                    "published",
                    "{}",
                    1,
                    1,
                    1,
                ),
            ).lastrowid
            source_key = f"materials/{material_id}/source.webp"
            asset_id = database.execute(
                """INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (material_id, source_key, "image/webp", 14, 1),
            ).lastrowid
            database.execute(
                "UPDATE materials SET content_json=? WHERE id=?",
                (json.dumps({"2": {"images": [f"/api/material-assets/{asset_id}"] * 3}}), material_id),
            )
            slug = database.execute("SELECT slug FROM materials WHERE id=?", (material_id,)).fetchone()["slug"]
        source_path = runtime.MATERIAL_ASSET_DIR / source_key
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"snapshot-image")

        status, created, _ = self.request(
            "POST",
            "/api/review-requests",
            {
                "kind": "task",
                "variantId": slug,
                "tasks": [2],
                "run": {"id": "delete-review", "status": "completed", "completedTasks": [2]},
            },
            student_cookie,
        )
        self.assertEqual(status, 201, created)
        request_id = created["reviewRequest"]["id"]
        status, recording = self.request_audio(
            f"/api/review-requests/{request_id}/recordings?task=2&label=Ответ",
            b"private-review-audio",
            student_cookie,
        )
        self.assertEqual(status, 201, recording)
        with runtime.connect() as database:
            audio_key = database.execute(
                """SELECT review_request_recordings.storage_key FROM review_request_recordings
                   JOIN review_request_items ON review_request_items.id=review_request_recordings.item_id
                   WHERE review_request_items.request_id=?""",
                (request_id,),
            ).fetchone()["storage_key"]
            review_asset = database.execute(
                "SELECT id,storage_key FROM review_request_assets WHERE request_id=?", (request_id,)
            ).fetchone()
            review_asset_id = review_asset["id"]
            asset_key = review_asset["storage_key"]
            personal_key = f"personal-recordings/{student_id}/account-delete.webm"
            database.execute(
                """INSERT INTO personal_recordings(student_id,run_id,variant_id,task_number,question_number,
                   label,storage_key,mime_type,size_bytes,duration_seconds,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    student_id,
                    "account-delete",
                    "demo-2026",
                    2,
                    1,
                    "Личный ответ",
                    personal_key,
                    "audio/webm",
                    1,
                    1.0,
                    1,
                    expires_at(1),
                ),
            )
        review_audio_path = runtime.AUDIO_DIR / audio_key
        review_asset_path = runtime.REVIEW_ASSET_DIR / asset_key
        personal_audio_path = runtime.AUDIO_DIR / personal_key
        personal_audio_path.parent.mkdir(parents=True, exist_ok=True)
        personal_audio_path.write_bytes(b"personal-audio")
        self.assertTrue(review_audio_path.is_file())
        self.assertTrue(review_asset_path.is_file())
        self.assertTrue(personal_audio_path.is_file())

        status, _, _ = self.request_bytes(f"/api/review-assets/{review_asset_id}", owner_cookie)
        self.assertEqual(status, 404)
        status, body, content_type = self.request_bytes(f"/api/review-assets/{review_asset_id}", student_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(body, b"snapshot-image")
        self.assertEqual(content_type, "image/webp")
        status, completed, _ = self.request("POST", f"/api/review-requests/{request_id}/complete", {}, student_cookie)
        self.assertEqual(status, 200, completed)
        status, headers, body = self.request_raw(
            f"/api/review-assets/{review_asset_id}", owner_cookie, headers={"Range": "bytes=0-7"}
        )
        self.assertEqual(status, 206)
        self.assertEqual(headers["content-range"], "bytes 0-7/14")
        self.assertEqual(body, b"snapshot")
        status, _, _ = self.request_bytes(f"/api/review-assets/{review_asset_id}", other_student_cookie)
        self.assertEqual(status, 404)

        cleanup_job = {}
        original_cleanup = auth.process_cleanup_jobs

        def inspect_cleanup(database, **kwargs):
            cleanup_job["audio"] = json.loads(
                database.execute(
                    "SELECT audio_keys_json FROM storage_cleanup_jobs ORDER BY id DESC LIMIT 1"
                ).fetchone()[0]
            )
            return original_cleanup(database, **kwargs)

        auth.process_cleanup_jobs = inspect_cleanup
        try:
            status, deleted, _ = self.request("DELETE", "/api/account", {"password": "student123"}, student_cookie)
        finally:
            auth.process_cleanup_jobs = original_cleanup
        self.assertEqual(status, 200, deleted)
        self.assertIn(personal_key, cleanup_job["audio"])
        self.assertFalse(review_audio_path.exists())
        self.assertFalse(review_asset_path.exists())
        self.assertFalse(personal_audio_path.exists())

    def test_review_recording_upload_uses_audio_body_limit(self):
        self.assertEqual(
            trainer_main._body_limit_for_request("POST", "/api/review-requests/42/recordings"),
            runtime.MAX_AUDIO_BODY,
        )

    def test_account_verification_password_reset_and_audit(self):
        email = "security@example.test"
        account = {
            "email": email,
            "password": "original123",
            "displayName": "Чэнь Мин",
        }
        status, payload, headers = self.request("POST", "/api/auth/register", account)
        self.assertEqual(status, 201)
        self.assertFalse(payload["user"]["emailVerified"])
        cookie = self.cookie_from(headers)

        verification_token = self.token_from_outbox(email, "verify")
        status, _, _ = self.request("POST", "/api/auth/email/confirm", {"token": verification_token})
        self.assertEqual(status, 200)
        status, me, _ = self.request("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertTrue(me["user"]["emailVerified"])

        status, _, _ = self.request("POST", "/api/auth/password/request", {"email": email})
        self.assertEqual(status, 200)
        reset_token = self.token_from_outbox(email, "reset")
        status, _, _ = self.request(
            "POST", "/api/auth/password/reset", {"token": reset_token, "password": "replacement123"}
        )
        self.assertEqual(status, 200)
        status, _, _ = self.request("GET", "/api/auth/me", cookie=cookie)
        self.assertEqual(status, 401)
        status, _, _ = self.request("POST", "/api/auth/login", {"email": email, "password": "replacement123"})
        self.assertEqual(status, 200)

        status, _, headers = self.request("POST", "/api/auth/login", {"email": email, "password": "replacement123"})
        new_cookie = self.cookie_from(headers)
        status, audit, _ = self.request("GET", "/api/account/audit", cookie=new_cookie)
        self.assertEqual(status, 200)
        actions = {event["action"] for event in audit["events"]}
        self.assertIn("email_verified", actions)
        self.assertIn("password_reset_completed", actions)
        self.assertIn("login_succeeded", actions)

    def test_legacy_assignment_routes_are_not_active(self):
        student_cookie = self.register_student("retired-routes")
        progress = {
            "version": 1,
            "updatedAt": "2026-08-19T12:00:00.000Z",
            "settings": {"fastMode": False},
            "activeRun": None,
            "runs": [{"id": "direct-progress", "status": "completed", "completedTasks": [1]}],
        }
        for path, payload in (
            ("/api/teacher/groups", {"name": "Retired group"}),
            ("/api/groups/join", {"code": "ABC123"}),
            (
                "/api/teacher/assignments",
                {"groupId": 1, "title": "Retired assignment", "variantId": "demo-2026", "tasks": [1]},
            ),
            ("/api/assignments/1/submissions", {"run": {"id": "retired-run"}}),
        ):
            status, body, _ = self.request("POST", path, payload, student_cookie)
            self.assertEqual(status, 404, body)
            self.assertEqual(body["code"], "not_found")

        status, written, _ = self.request("PUT", "/api/progress", {"progress": progress}, student_cookie)
        self.assertEqual(status, 200, written)
        status, restored, _ = self.request("GET", "/api/progress", cookie=student_cookie)
        self.assertEqual(status, 200, restored)
        self.assertEqual(restored["progress"], progress)

    def test_owner_registration_derives_teacher_role(self):
        original_owner_email = os.environ.get("TRAINER_OWNER_EMAIL")
        os.environ["TRAINER_OWNER_EMAIL"] = "owner@example.test"
        try:
            status, owner, _ = self.request(
                "POST",
                "/api/auth/register",
                {"email": "owner@example.test", "password": "password123", "displayName": "Owner"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(owner["user"]["role"], "teacher")

            status, student, _ = self.request(
                "POST",
                "/api/auth/register",
                {"email": "student@example.test", "password": "password123", "displayName": "Student"},
            )
            self.assertEqual(status, 201)
            self.assertEqual(student["user"]["role"], "student")

            status, rejected, _ = self.request(
                "POST",
                "/api/auth/register",
                {
                    "email": "impostor@example.test",
                    "password": "password123",
                    "displayName": "Impostor",
                    "role": "teacher",
                },
            )
            self.assertEqual(status, 422)
            self.assertEqual(rejected["code"], "request_validation_failed")
        finally:
            if original_owner_email is None:
                os.environ.pop("TRAINER_OWNER_EMAIL", None)
            else:
                os.environ["TRAINER_OWNER_EMAIL"] = original_owner_email

    def test_migrations_are_recorded(self):
        with runtime.connect() as database:
            versions = [
                row["version"] for row in database.execute("SELECT version FROM schema_migrations ORDER BY version")
            ]
        self.assertEqual(versions, [1, 2, 3, 4, 5, 6, 7])
        with runtime.connect() as database:
            columns = {row["name"] for row in database.execute("PRAGMA table_info(assignments)")}
        self.assertIn("material_snapshot_json", columns)

    def test_mutation_without_origin_is_rejected(self):
        status, payload, _ = self.request(
            "POST",
            "/api/auth/login",
            {"email": "nobody@example.test", "password": "password123"},
            include_origin=False,
        )
        self.assertEqual(status, 403)
        self.assertEqual(payload["code"], "invalid_origin")
        self.assertEqual(payload["message"], "Invalid request origin")

    def test_login_endpoint_returns_rate_limit(self):
        payload = {"email": "rate-limit@example.test", "password": "password123"}
        for _ in range(8):
            status, _, _ = self.request("POST", "/api/auth/login", payload)
            self.assertEqual(status, 401)
        status, body, headers = self.request("POST", "/api/auth/login", payload)
        self.assertEqual(status, 429)
        self.assertIn("retry-after", headers)
        self.assertGreater(body["retryAfter"], 0)

    def test_recording_row_has_no_transcription_columns(self):
        source = (Path(__file__).resolve().parents[2] / "src/trainer/api/controllers/recordings.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("transcript_status", source)
        self.assertNotIn("enqueue_transcription", source)

    def test_recording_supports_range_requests(self):
        recording_id, cookie = self.create_recording()
        status, headers, body = self.request_raw(
            f"/api/recordings/{recording_id}", cookie, headers={"Range": "bytes=0-3"}
        )
        self.assertEqual(status, 206)
        self.assertEqual(headers["content-range"], "bytes 0-3/10")
        self.assertEqual(headers["content-length"], "4")
        self.assertEqual(body, b"0123")

    def test_recording_returns_suffix_range_with_precise_headers(self):
        recording_id, cookie = self.create_recording()
        status, headers, body = self.request_raw(
            f"/api/recordings/{recording_id}", cookie, headers={"Range": "bytes=-4"}
        )
        self.assertEqual(status, 206)
        self.assertEqual(headers["accept-ranges"], "bytes")
        self.assertEqual(headers["content-range"], "bytes 6-9/10")
        self.assertEqual(headers["content-length"], "4")
        self.assertEqual(body, b"6789")

    def test_recording_rejects_multiple_ranges_without_reading_audio(self):
        recording_id, cookie = self.create_recording()
        status, headers, body = self.request_raw(
            f"/api/recordings/{recording_id}", cookie, headers={"Range": "bytes=0-1,4-5"}
        )
        self.assertEqual(status, 416)
        self.assertEqual(headers["content-range"], "bytes */10")
        self.assertEqual(body, b"")

    def test_recording_rejects_repeated_range_headers_without_reading_audio(self):
        recording_id, cookie = self.create_recording()
        storage_calls = []

        def local_path(*args, **kwargs):
            storage_calls.append(("local_path", args, kwargs))
            return None

        def stream(*args, **kwargs):
            storage_calls.append(("stream", args, kwargs))
            return iter([b"unexpected"])

        request = self.client.build_request(
            "GET",
            f"/api/recordings/{recording_id}",
            headers=[("Cookie", cookie), ("Range", "bytes=0-1"), ("Range", "bytes=4-5")],
        )
        with (
            patch.object(routes, "storage_local_path", local_path),
            patch.object(routes, "stream_recording", stream),
        ):
            response = self.client.send(request)

        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.headers["content-range"], "bytes */10")
        self.assertEqual(response.content, b"")
        self.assertEqual(storage_calls, [])


if __name__ == "__main__":
    unittest.main()
