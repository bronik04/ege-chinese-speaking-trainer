from __future__ import annotations

import json
import secrets
import subprocess
import tempfile
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from api.runtime import AUDIO_DIR, DATA_DIR, MAX_AUDIO_BODY, connect
from backend.audio import validate_duration
from backend.storage import storage_from_env
from backend.transcription import enabled as transcription_enabled
from backend.transcription import enqueue as enqueue_transcription


class RecordingControllerMixin:
    def recording_create(self, submission_id: int) -> None:
        user = self.require_role("student")
        if not user:
            return
        query = parse_qs(urlparse(self.path).query)
        try:
            task = int(query.get("task", [""])[0])
            question_value = query.get("question", [None])[0]
            question = int(question_value) if question_value else None
        except (TypeError, ValueError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Некорректный номер записи")
            return
        label = str(query.get("label", [f"Задание {task}"])[0])[:160]
        mime_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
        extensions = {"audio/webm": "webm", "audio/mp4": "m4a", "audio/ogg": "ogg", "audio/wav": "wav"}
        if task not in {1, 2, 3} or mime_type not in extensions:
            self.send_error_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "Неподдерживаемый формат аудио")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= MAX_AUDIO_BODY:
            self.send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Запись превышает 15 МБ")
            return
        with connect() as database:
            row = database.execute(
                """
                SELECT submissions.id, assignments.tasks_json FROM submissions
                JOIN assignments ON assignments.id = submissions.assignment_id
                WHERE submissions.id = ? AND submissions.student_id = ?
                """,
                (submission_id, user["id"]),
            ).fetchone()
            if not row or task not in json.loads(row["tasks_json"]):
                self.send_error_json(HTTPStatus.FORBIDDEN, "Запись не относится к этой попытке")
                return
        data = self.rfile.read(length)
        relative = f"{submission_id}/{secrets.token_urlsafe(18)}.{extensions[mime_type]}"
        temporary_dir = DATA_DIR / "tmp"
        temporary_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=temporary_dir, suffix=f".{extensions[mime_type]}", delete=False) as file:
            file.write(data)
            temporary_path = Path(file.name)
        try:
            duration = validate_duration(temporary_path, task)
        except (OSError, ValueError, subprocess.SubprocessError):
            temporary_path.unlink(missing_ok=True)
            self.send_error_json(HTTPStatus.UNPROCESSABLE_ENTITY, "Некорректная или слишком длинная аудиозапись")
            return
        storage = storage_from_env(AUDIO_DIR)
        try:
            storage.put(relative, temporary_path, mime_type)
            with connect() as database:
                cursor = database.execute(
                    """
                    INSERT INTO recordings(submission_id, task_number, question_number, label, file_name, mime_type,
                                           size_bytes, duration_seconds, transcript_status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        submission_id,
                        task,
                        question,
                        label,
                        relative,
                        mime_type,
                        len(data),
                        duration,
                        "pending" if transcription_enabled() else "disabled",
                        int(time.time()),
                    ),
                )
                if transcription_enabled():
                    enqueue_transcription(database, cursor.lastrowid)
                self.audit(
                    database,
                    "recording_uploaded",
                    user_id=user["id"],
                    email=user["email"],
                    details={"submissionId": submission_id, "task": task, "size": len(data)},
                )
        except Exception:
            try:
                storage.delete(relative)
            except Exception:
                pass
            raise
        finally:
            temporary_path.unlink(missing_ok=True)
        self.send_json({"recording": {"id": cursor.lastrowid}}, HTTPStatus.CREATED)

    def recording_get(self, recording_id: int) -> None:
        user = self.current_user()
        if not user:
            self.send_error_json(HTTPStatus.UNAUTHORIZED, "Authentication required")
            return
        with connect() as database:
            row = database.execute(
                """
                SELECT recordings.file_name, recordings.mime_type, recordings.size_bytes,
                       submissions.student_id, assignments.teacher_id
                FROM recordings JOIN submissions ON submissions.id = recordings.submission_id
                JOIN assignments ON assignments.id = submissions.assignment_id
                WHERE recordings.id = ?
                """,
                (recording_id,),
            ).fetchone()
        if not row or user["id"] not in {row["student_id"], row["teacher_id"]}:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Запись не найдена")
            return
        try:
            data = storage_from_env(AUDIO_DIR).read(row["file_name"])
        except (FileNotFoundError, OSError, ValueError):
            self.send_error_json(HTTPStatus.NOT_FOUND, "Файл записи не найден")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", row["mime_type"])
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)
