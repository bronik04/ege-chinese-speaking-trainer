import json
import os
import secrets
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

import asgi
from trainer import main as trainer_main
from trainer.api import dependencies, routes, runtime
from trainer.api.controllers import auth, recordings, review_requests
from trainer.api.errors import ApiError
from trainer.api.results import FileResult, RequestContext
from trainer.api.security import request_has_same_origin
from trainer.domain.accounts import password_hash, password_matches


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
        runtime.ASSIGNMENT_ASSET_DIR = root / "assignment-assets"
        auth.MATERIAL_ASSET_DIR = runtime.MATERIAL_ASSET_DIR
        auth.ASSIGNMENT_ASSET_DIR = runtime.ASSIGNMENT_ASSET_DIR
        dependencies.DATA_DIR = root
        dependencies.AUDIO_DIR = runtime.AUDIO_DIR
        recordings.DATA_DIR = root
        recordings.AUDIO_DIR = runtime.AUDIO_DIR
        cls.original_validate_duration = review_requests.validate_duration
        review_requests.validate_duration = lambda path, task: 1.0
        cls.client_context = TestClient(asgi.app)
        cls.client = cls.client_context.__enter__()
        cls.origin = "http://testserver"

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        review_requests.validate_duration = cls.original_validate_duration
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
        self.assertEqual(sum(len(item["recordings"]) for item in review_request["items"]), 6)

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

            def execute(self, statement, parameters=()):
                cursor = self.database.execute(statement, parameters)
                self.execute_calls += 1
                if self.execute_calls == 1:
                    status_selected.set()
                    if not resume_upload.wait(5):
                        raise AssertionError("completion did not release the concurrent upload")
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
                "SELECT id FROM users WHERE email LIKE 'review-delete-%' ORDER BY id DESC LIMIT 1"
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
        review_audio_path = runtime.AUDIO_DIR / audio_key
        review_asset_path = runtime.ASSIGNMENT_ASSET_DIR / asset_key
        self.assertTrue(review_audio_path.is_file())
        self.assertTrue(review_asset_path.is_file())

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

        status, deleted, _ = self.request("DELETE", "/api/account", {"password": "student123"}, student_cookie)
        self.assertEqual(status, 200, deleted)
        self.assertFalse(review_audio_path.exists())
        self.assertFalse(review_asset_path.exists())

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

    @unittest.skip("Legacy group and assignment flow was retired in favor of direct review requests")
    def test_teacher_student_progress_flow(self):
        teacher = {
            "email": "teacher@example.test",
            "password": "teacher123",
            "displayName": "Ли Лаоши",
        }
        status, _, headers = self.request("POST", "/api/auth/register", teacher)
        self.assertEqual(status, 201)
        teacher_cookie = self.cookie_from(headers)

        status, blocked, _ = self.request("POST", "/api/teacher/groups", {"name": "11 класс"}, teacher_cookie)
        self.assertEqual(status, 403)
        self.assertEqual(blocked["code"], "email_verification_required")
        verification_token = self.token_from_outbox(teacher["email"], "verify")
        status, _, _ = self.request("POST", "/api/auth/email/confirm", {"token": verification_token})
        self.assertEqual(status, 200)

        student = {
            "email": "student-workflow@example.test",
            "password": "student123",
            "displayName": "Анна Петрова",
        }
        status, _, headers = self.request("POST", "/api/auth/register", student)
        self.assertEqual(status, 201)
        student_cookie = self.cookie_from(headers)

        author = {
            "email": "snapshot-author@example.test",
            "password": "author123",
            "displayName": "Автор материала",
        }
        status, _, headers = self.request("POST", "/api/auth/register", author)
        self.assertEqual(status, 201)
        author_cookie = self.cookie_from(headers)

        status, group_payload, _ = self.request("POST", "/api/teacher/groups", {"name": "11 класс"}, teacher_cookie)
        self.assertEqual(status, 201)
        code = group_payload["group"]["code"]

        status, _, _ = self.request("POST", "/api/groups/join", {"code": code}, student_cookie)
        self.assertEqual(status, 200)
        with runtime.connect() as database:
            author_id = database.execute("SELECT id FROM users WHERE email=?", (author["email"],)).fetchone()["id"]
            material_id = database.execute(
                """INSERT INTO materials(slug,owner_id,kind,task_number,title,year,source,status,content_json,
                                          created_at,updated_at,published_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("snapshot-task", author_id, "task", 2, "Snapshot task", 2027, "Author", "published", "{}", 1, 1, 1),
            ).lastrowid
            storage_key = f"materials/{material_id}/source.webp"
            asset_id = database.execute(
                """INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (material_id, storage_key, "image/webp", 14, 1),
            ).lastrowid
            material_content = {"2": {"images": [f"/api/material-assets/{asset_id}"] * 3}}
            database.execute(
                "UPDATE materials SET content_json=? WHERE id=?",
                (json.dumps(material_content), material_id),
            )
        material_path = runtime.MATERIAL_ASSET_DIR / storage_key
        material_path.parent.mkdir(parents=True, exist_ok=True)
        material_path.write_bytes(b"snapshot-image")
        status, snapshot_assignment, _ = self.request(
            "POST",
            "/api/teacher/assignments",
            {
                "groupId": group_payload["group"]["id"],
                "title": "Авторское задание",
                "variantId": "snapshot-task",
                "tasks": [2],
                "dueAt": None,
            },
            teacher_cookie,
        )
        self.assertEqual(status, 201)
        status, snapshot_assignments, _ = self.request("GET", "/api/student/assignments", cookie=student_cookie)
        self.assertEqual(status, 200)
        snapshot = next(
            item
            for item in snapshot_assignments["assignments"]
            if item["id"] == snapshot_assignment["assignment"]["id"]
        )
        snapshot_asset_url = snapshot["material"]["tasks"]["2"]["images"][0]
        self.assertRegex(snapshot_asset_url, r"^/api/assignment-assets/\d+$")
        status, image_data, content_type = self.request_bytes(snapshot_asset_url, student_cookie)
        self.assertEqual(status, 200, image_data)
        self.assertEqual(image_data, b"snapshot-image")
        self.assertEqual(content_type, "image/webp")
        status, _, _ = self.request_bytes(snapshot_asset_url, teacher_cookie)
        self.assertEqual(status, 200)

        outsider = {
            "email": "snapshot-outsider@example.test",
            "password": "outsider123",
            "displayName": "Посторонний пользователь",
        }
        status, _, headers = self.request("POST", "/api/auth/register", outsider)
        self.assertEqual(status, 201)
        outsider_cookie = self.cookie_from(headers)
        status, _, _ = self.request_bytes(snapshot_asset_url, outsider_cookie)
        self.assertEqual(status, 404)

        status, repeated_snapshot, _ = self.request(
            "POST",
            f"/api/teacher/assignments/{snapshot_assignment['assignment']['id']}/resend",
            {},
            teacher_cookie,
        )
        self.assertEqual(status, 201)
        status, repeated_assignments, _ = self.request("GET", "/api/student/assignments", cookie=student_cookie)
        self.assertEqual(status, 200)
        repeated_material = next(
            item["material"]
            for item in repeated_assignments["assignments"]
            if item["id"] == repeated_snapshot["assignment"]["id"]
        )
        repeated_asset_url = repeated_material["tasks"]["2"]["images"][0]
        self.assertRegex(repeated_asset_url, r"^/api/assignment-assets/\d+$")
        self.assertNotEqual(repeated_asset_url, snapshot_asset_url)

        with runtime.connect() as database:
            database.execute("UPDATE materials SET status='draft' WHERE id=?", (material_id,))
        status, image_data, _ = self.request_bytes(snapshot_asset_url, student_cookie)
        self.assertEqual(status, 200, image_data)

        status, _, _ = self.request("DELETE", "/api/account", {"password": author["password"]}, author_cookie)
        self.assertEqual(status, 200)
        status, image_data, _ = self.request_bytes(snapshot_asset_url, student_cookie)
        self.assertEqual(status, 200, image_data)
        status, invalid_assignment, _ = self.request(
            "POST",
            "/api/teacher/assignments",
            {
                "groupId": group_payload["group"]["id"],
                "title": "Несуществующий вариант",
                "variantId": "missing-variant",
                "tasks": [1],
                "dueAt": None,
            },
            teacher_cookie,
        )
        self.assertEqual(status, 400)
        self.assertEqual(invalid_assignment["code"], "invalid_assignment_material")
        status, assignment_payload, _ = self.request(
            "POST",
            "/api/teacher/assignments",
            {
                "groupId": group_payload["group"]["id"],
                "title": "Пробный вариант",
                "variantId": "demo-2026",
                "tasks": [1, 2],
                "dueAt": 1,
            },
            teacher_cookie,
        )
        self.assertEqual(status, 201)
        assignment_id = assignment_payload["assignment"]["id"]
        status, assignments, _ = self.request("GET", "/api/student/assignments", cookie=student_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(assignments["assignments"][0]["id"], assignment_id)
        self.assertEqual(assignments["assignments"][0]["material"]["id"], "demo-2026")
        self.assertFalse(assignments["assignments"][0]["materialUnavailable"])
        status, teacher_assignments, _ = self.request("GET", "/api/teacher/assignments", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        self.assertIn(assignment_id, {item["id"] for item in teacher_assignments["assignments"]})
        status, _, _ = self.request(
            "PUT",
            f"/api/teacher/assignments/{assignment_id}",
            {"title": "Обновлённый вариант", "dueAt": 1},
            teacher_cookie,
        )
        self.assertEqual(status, 200)
        status, repeated, _ = self.request(
            "POST", f"/api/teacher/assignments/{assignment_id}/resend", {}, teacher_cookie
        )
        self.assertEqual(status, 201)
        self.assertNotEqual(repeated["assignment"]["id"], assignment_id)

        # Назначения, выданные до появления снимков материала, хранят NULL.
        # Повтор такого задания должен отвечать понятной ошибкой, а не 500.
        with runtime.connect() as database:
            database.execute(
                "UPDATE assignments SET material_snapshot_json = NULL WHERE id = ?",
                (repeated["assignment"]["id"],),
            )
        status, legacy_resend, _ = self.request(
            "POST", f"/api/teacher/assignments/{repeated['assignment']['id']}/resend", {}, teacher_cookie
        )
        self.assertEqual(status, 409)
        self.assertEqual(legacy_resend["code"], "assignment_material_unavailable")

        status, submission_payload, _ = self.request(
            "POST",
            f"/api/assignments/{assignment_id}/submissions",
            {"run": {"variantId": "demo-2026", "tasks": [1, 2], "fastMode": True}},
            student_cookie,
        )
        self.assertEqual(status, 201)
        submission_id = submission_payload["submission"]["id"]
        self.assertEqual(submission_payload["submission"]["status"], "uploading")
        self.assertEqual(submission_payload["submission"]["dueAt"], 1)
        with runtime.connect() as database:
            stored_run = json.loads(
                database.execute("SELECT run_json FROM submissions WHERE id = ?", (submission_id,)).fetchone()[
                    "run_json"
                ]
            )
        self.assertFalse(stored_run["fastMode"])
        status, recording_payload = self.request_audio(
            f"/api/submissions/{submission_id}/recordings?task=2&label=Answer", b"test-audio", student_cookie
        )
        self.assertEqual(status, 201)
        recording_id = recording_payload["recording"]["id"]
        status, replacement_payload = self.request_audio(
            f"/api/submissions/{submission_id}/recordings?task=2&label=Answer", b"replacement-audio", student_cookie
        )
        self.assertEqual(status, 201)
        recording_id = replacement_payload["recording"]["id"]
        with runtime.connect() as database:
            self.assertEqual(
                database.execute(
                    "SELECT COUNT(*) FROM recordings WHERE submission_id = ? AND task_number = 2", (submission_id,)
                ).fetchone()[0],
                1,
            )
            self.assertEqual(database.execute("SELECT COUNT(*) FROM storage_cleanup_jobs").fetchone()[0], 1)
        status, _, _ = self.request_bytes(f"/api/recordings/{recording_id}", teacher_cookie)
        self.assertEqual(status, 404)
        status, teacher_submissions, _ = self.request("GET", "/api/teacher/submissions", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(teacher_submissions["submissions"], [])
        status, incomplete, _ = self.request("POST", f"/api/submissions/{submission_id}/complete", {}, student_cookie)
        self.assertEqual(status, 409)
        self.assertEqual(incomplete["code"], "submission_incomplete")
        for question in range(1, 6):
            status, _ = self.request_audio(
                f"/api/submissions/{submission_id}/recordings?task=1&question={question}&label=Question",
                b"test-audio",
                student_cookie,
            )
            self.assertEqual(status, 201)
        status, _, _ = self.request("POST", f"/api/submissions/{submission_id}/complete", {}, student_cookie)
        self.assertEqual(status, 200)
        status, rejected_upload = self.request_audio(
            f"/api/submissions/{submission_id}/recordings?task=2&label=Answer", b"test-audio", student_cookie
        )
        self.assertEqual(status, 409)
        self.assertEqual(rejected_upload["code"], "submission_not_uploading")

        status, audio_data, content_type = self.request_bytes(f"/api/recordings/{recording_id}", teacher_cookie)
        self.assertEqual(status, 200, audio_data)
        self.assertEqual(audio_data, b"replacement-audio")
        self.assertEqual(content_type, "audio/webm")
        status, teacher_submissions, _ = self.request("GET", "/api/teacher/submissions", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        self.assertTrue(teacher_submissions["submissions"][0]["late"])
        self.assertEqual(len(teacher_submissions["submissions"][0]["recordings"]), 6)
        status, history, _ = self.request("GET", f"/api/teacher/submissions/{submission_id}", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(history["attempts"][0]["id"], submission_id)
        status, csv_data, csv_type = self.request_bytes("/api/teacher/export.csv?status=submitted", teacher_cookie)
        self.assertEqual(status, 200)
        self.assertIn("text/csv", csv_type)
        self.assertIn("Обновлённый вариант".encode(), csv_data)
        review_scores = {
            "1": {"question1": 1, "question2": 1, "question3": 1, "question4": 1, "question5": 1},
            "2": {"content": 3, "organization": 2, "language": 2},
        }
        status, review, _ = self.request(
            "POST",
            f"/api/submissions/{submission_id}/review",
            {"scores": review_scores, "comment": "Отличная работа"},
            teacher_cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(review["review"], {"total": 12, "maximum": 12})
        progress = {
            "version": 1,
            "updatedAt": "2026-07-04T12:00:00.000Z",
            "settings": {},
            "activeRun": None,
            "runs": [{"id": "run-1", "status": "completed", "completedTasks": [1, 2]}],
        }
        status, _, _ = self.request("PUT", "/api/progress", {"progress": progress}, student_cookie)
        self.assertEqual(status, 200)

        status, dashboard, _ = self.request("GET", "/api/teacher/dashboard", cookie=teacher_cookie)
        self.assertEqual(status, 200)
        visible_student = dashboard["groups"][0]["students"][0]
        self.assertEqual(visible_student["name"], "Анна Петрова")
        self.assertEqual(visible_student["completedRuns"], 1)
        self.assertEqual(visible_student["completedTasks"], 2)

        with runtime.connect() as database:
            file_name = database.execute("SELECT file_name FROM recordings WHERE id = ?", (recording_id,)).fetchone()[
                "file_name"
            ]
        audio_path = runtime.AUDIO_DIR / file_name
        self.assertTrue(audio_path.is_file())
        status, _, _ = self.request("DELETE", "/api/account", {"password": "student123"}, student_cookie)
        self.assertEqual(status, 200)
        self.assertFalse(audio_path.exists())
        status, _, _ = self.request("GET", "/api/auth/me", cookie=student_cookie)
        self.assertEqual(status, 401)
        with runtime.connect() as database:
            deleted = database.execute("SELECT id FROM users WHERE email = ?", (student["email"],)).fetchone()
            deletion_event = database.execute(
                "SELECT user_id FROM audit_log WHERE email = ? AND action = 'account_deleted'", (student["email"],)
            ).fetchone()
        self.assertIsNone(deleted)
        self.assertIsNone(deletion_event["user_id"])
        self.assertTrue(list(runtime.ASSIGNMENT_ASSET_DIR.rglob("*.webp")))
        status, _, _ = self.request("DELETE", "/api/account", {"password": teacher["password"]}, teacher_cookie)
        self.assertEqual(status, 200)
        self.assertEqual(list(runtime.ASSIGNMENT_ASSET_DIR.rglob("*.webp")), [])

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
