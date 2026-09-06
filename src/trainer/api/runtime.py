from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from trainer.config import PROJECT_ROOT, account_public_url, owner_email
from trainer.infrastructure.audio import validate_duration, validate_personal_recording_duration
from trainer.infrastructure.database.account_repository import SQLiteAccountRepository
from trainer.infrastructure.database.core import connect as database_connect
from trainer.infrastructure.database.core import initialize as initialize_database
from trainer.infrastructure.database.material_repository import SQLiteMaterialRepository
from trainer.infrastructure.database.personal_recording_repository import SQLitePersonalRecordingRepository
from trainer.infrastructure.database.progress_repository import SQLiteProgressRepository
from trainer.infrastructure.database.recording_access_repository import SQLiteRecordingAccessRepository
from trainer.infrastructure.database.review_request_repository import SQLiteReviewRequestRepository
from trainer.infrastructure.images import encode_material_image
from trainer.infrastructure.mailer.account_links import MailAccountLinkSender
from trainer.infrastructure.storage import storage_from_env
from trainer.services.account_repository import AccountCleanupSummary
from trainer.services.accounts import AccountService
from trainer.services.materials import MaterialService
from trainer.services.personal_recordings import PersonalRecordingService
from trainer.services.progress import ProgressService
from trainer.services.recording_access import RecordingAccessService
from trainer.services.review_requests import ReviewRequestService
from trainer.services.storage_cleanup import UPLOAD_INTENT_GRACE_SECONDS, expire_recordings, process_cleanup_jobs

logger = logging.getLogger("trainer.storage_cleanup")

ROOT = PROJECT_ROOT
DATA_DIR = Path(os.environ.get("TRAINER_DATA_DIR", ROOT / "var")).resolve()
DB_PATH = DATA_DIR / "trainer.sqlite3"
AUDIO_DIR = DATA_DIR / "audio"
MATERIAL_ASSET_DIR = DATA_DIR / "material-assets"
# Physical name is retained for compatibility with existing local review snapshots.
REVIEW_ASSET_DIR = DATA_DIR / "assignment-assets"
SESSION_DAYS = 30
MAX_BODY = int(os.environ.get("TRAINER_MAX_JSON_BYTES", "1000000"))
MAX_AUDIO_BODY = int(os.environ.get("TRAINER_MAX_AUDIO_BYTES", "15000000"))


def connect() -> sqlite3.Connection:
    return database_connect(DB_PATH)


def progress_service() -> ProgressService:
    return ProgressService(SQLiteProgressRepository(connect))


def recording_access_service() -> RecordingAccessService:
    return RecordingAccessService(
        SQLiteRecordingAccessRepository(connect),
        owner_email=owner_email(),
    )


def review_request_service() -> ReviewRequestService:
    return ReviewRequestService(
        SQLiteReviewRequestRepository(
            connect,
            audio_root=AUDIO_DIR,
            material_root=MATERIAL_ASSET_DIR,
            review_asset_root=REVIEW_ASSET_DIR,
        ),
        project_root=ROOT,
        audio_root=AUDIO_DIR,
        material_asset_root=MATERIAL_ASSET_DIR,
        review_asset_root=REVIEW_ASSET_DIR,
        temporary_root=DATA_DIR / "tmp",
        max_audio_body=MAX_AUDIO_BODY,
        duration_validator=validate_duration,
    )


def material_service() -> MaterialService:
    return MaterialService(
        SQLiteMaterialRepository(connect),
        project_root=ROOT,
        asset_root=MATERIAL_ASSET_DIR,
        storage=storage_from_env(MATERIAL_ASSET_DIR),
        image_encoder=encode_material_image,
        editor_emails=os.environ.get("TRAINER_EDITOR_EMAILS", ""),
        max_image_body=min(MAX_AUDIO_BODY, 5_000_000),
    )


def personal_recording_service() -> PersonalRecordingService:
    return PersonalRecordingService(
        SQLitePersonalRecordingRepository(connect),
        storage_from_env(AUDIO_DIR),
        temporary_root=DATA_DIR / "tmp",
        max_audio_body=MAX_AUDIO_BODY,
        duration_validator=validate_personal_recording_duration,
        upload_intent_grace_seconds=UPLOAD_INTENT_GRACE_SECONDS,
    )


def _process_account_cleanup() -> AccountCleanupSummary:
    with connect() as database:
        summary = process_cleanup_jobs(
            database,
            audio_root=AUDIO_DIR,
            material_root=MATERIAL_ASSET_DIR,
            assignment_root=REVIEW_ASSET_DIR,
        )
    return AccountCleanupSummary(summary.completed, summary.failed, summary.pending)


def account_service() -> AccountService:
    return AccountService(
        SQLiteAccountRepository(connect),
        MailAccountLinkSender(DATA_DIR, account_public_url()),
        _process_account_cleanup,
        owner_email=owner_email(),
        session_days=SESSION_DAYS,
    )


def init_database(*, cleanup: bool = True) -> None:
    initialize_database(DATA_DIR, AUDIO_DIR, DB_PATH)
    MATERIAL_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_ASSET_DIR.mkdir(parents=True, exist_ok=True)
    if not cleanup:
        return
    try:
        with connect() as database:
            expired = expire_recordings(database)
            summary = process_cleanup_jobs(
                database,
                audio_root=AUDIO_DIR,
                material_root=MATERIAL_ASSET_DIR,
                assignment_root=REVIEW_ASSET_DIR,
            )
        logger.info(
            "Recording expiry and storage cleanup processed",
            extra={
                "event": "storage_cleanup_processed",
                "fields": {
                    "expired": expired,
                    "completed": summary.completed,
                    "failed": summary.failed,
                    "pending": summary.pending,
                },
            },
        )
    except Exception:
        logger.exception("Storage cleanup startup attempt failed", extra={"event": "storage_cleanup_startup_failed"})
