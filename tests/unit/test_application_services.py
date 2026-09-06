from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from trainer.api import runtime
from trainer.services.recordings import delete_recordings, read_recording, write_recording


class RecordingStorageServiceTest(unittest.TestCase):
    @patch("trainer.services.recordings.storage_from_env", side_effect=RuntimeError("factory failed"))
    def test_cleanup_suppresses_factory_failure(self, _factory):
        delete_recordings(Path("audio"), ["answer.webm"])

    @patch("trainer.services.recordings.storage_from_env")
    def test_read_write_and_delete_delegate_to_selected_storage(self, factory):
        storage = Mock()
        storage.read.return_value = b"audio"
        factory.return_value = storage
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webm"
            source.write_bytes(b"audio")
            write_recording(root, "1/answer.webm", source, "audio/webm")
            self.assertEqual(read_recording(root, "1/answer.webm"), b"audio")
            delete_recordings(root, ["1/answer.webm"])
        storage.put.assert_called_once_with("1/answer.webm", source, "audio/webm")
        storage.delete.assert_called_once_with("1/answer.webm")


class AccountServiceRuntimeTest(unittest.TestCase):
    def test_factory_composes_current_runtime_dependencies_without_cache(self):
        repository = object()
        sender = object()
        service = object()
        with (
            patch.object(runtime, "SQLiteAccountRepository", return_value=repository) as repository_type,
            patch.object(runtime, "MailAccountLinkSender", return_value=sender) as sender_type,
            patch.object(runtime, "AccountService", return_value=service) as service_type,
            patch.object(runtime, "account_public_url", return_value="https://trainer.example"),
            patch.object(runtime, "owner_email", return_value="owner@example.test"),
        ):
            first = runtime.account_service()
            second = runtime.account_service()

        self.assertIs(first, service)
        self.assertIs(second, service)
        self.assertEqual(repository_type.call_count, 2)
        repository_type.assert_called_with(runtime.connect)
        sender_type.assert_called_with(runtime.DATA_DIR, "https://trainer.example")
        service_type.assert_called_with(
            repository,
            sender,
            runtime._process_account_cleanup,
            owner_email="owner@example.test",
            session_days=runtime.SESSION_DAYS,
        )


class PersonalRecordingServiceRuntimeTest(unittest.TestCase):
    def test_factory_composes_current_runtime_dependencies_without_cache(self):
        repository = object()
        storage = object()
        service = object()
        with (
            patch.object(runtime, "SQLitePersonalRecordingRepository", return_value=repository) as repository_type,
            patch.object(runtime, "storage_from_env", return_value=storage) as storage_factory,
            patch.object(runtime, "PersonalRecordingService", return_value=service) as service_type,
        ):
            first = runtime.personal_recording_service()
            second = runtime.personal_recording_service()

        self.assertIs(first, service)
        self.assertIs(second, service)
        self.assertEqual(repository_type.call_count, 2)
        repository_type.assert_called_with(runtime.connect)
        storage_factory.assert_called_with(runtime.AUDIO_DIR)
        service_type.assert_called_with(
            repository,
            storage,
            temporary_root=runtime.DATA_DIR / "tmp",
            max_audio_body=runtime.MAX_AUDIO_BODY,
            duration_validator=runtime.validate_personal_recording_duration,
            upload_intent_grace_seconds=runtime.UPLOAD_INTENT_GRACE_SECONDS,
        )


class RecordingAccessRuntimeTest(unittest.TestCase):
    def test_factory_composes_uncached_repository_without_storage(self):
        repository, service = object(), object()
        with (
            patch.object(
                runtime,
                "SQLiteRecordingAccessRepository",
                return_value=repository,
            ) as repository_type,
            patch.object(
                runtime,
                "RecordingAccessService",
                return_value=service,
            ) as service_type,
            patch.object(runtime, "owner_email", return_value="owner@example.test"),
            patch.object(runtime, "storage_from_env") as storage_factory,
        ):
            first = runtime.recording_access_service()
            second = runtime.recording_access_service()

        self.assertIs(first, service)
        self.assertIs(second, service)
        self.assertEqual(repository_type.call_count, 2)
        self.assertEqual(service_type.call_count, 2)
        repository_type.assert_called_with(runtime.connect)
        service_type.assert_called_with(repository, owner_email="owner@example.test")
        storage_factory.assert_not_called()


class StorageCleanupRuntimeTest(unittest.TestCase):
    def test_factory_composes_uncached_repository_and_lazy_storage_factories(self):
        repository = object()
        service = object()
        with (
            patch.object(
                runtime,
                "SQLiteStorageCleanupRepository",
                return_value=repository,
            ) as repository_type,
            patch.object(runtime, "StorageCleanupService", return_value=service) as service_type,
            patch.object(runtime, "storage_from_env") as storage_factory,
        ):
            first = runtime.storage_cleanup_service()
            second = runtime.storage_cleanup_service()

            self.assertIs(first, service)
            self.assertIs(second, service)
            self.assertEqual(repository_type.call_args_list, [call(runtime.connect), call(runtime.connect)])
            self.assertEqual(service_type.call_count, 2)
            storage_factory.assert_not_called()

            factories = service_type.call_args.kwargs
            factories["audio_storage"]()
            factories["material_storage"]()
            factories["assignment_storage"]()

        self.assertEqual(
            storage_factory.call_args_list,
            [call(runtime.AUDIO_DIR), call(runtime.MATERIAL_ASSET_DIR), call(runtime.REVIEW_ASSET_DIR)],
        )

    @patch("trainer.api.runtime.initialize_database")
    @patch.object(runtime.logger, "exception")
    def test_startup_cleanup_failure_is_best_effort(self, log_error, _initialize):
        service = Mock()
        service.expire_batch.side_effect = OSError("storage unavailable")
        with patch.object(runtime, "storage_cleanup_service", return_value=service):
            runtime.init_database()

        service.process_batch.assert_not_called()
        log_error.assert_called_once_with(
            "Storage cleanup startup attempt failed",
            extra={"event": "storage_cleanup_startup_failed"},
        )

    def test_review_factory_injects_cleanup_callback_without_repository_roots(self):
        repository = object()
        service = object()
        with (
            patch.object(runtime, "SQLiteReviewRequestRepository", return_value=repository) as repository_type,
            patch.object(runtime, "ReviewRequestService", return_value=service) as service_type,
        ):
            self.assertIs(runtime.review_request_service(), service)

        repository_type.assert_called_once_with(runtime.connect)
        self.assertIs(service_type.call_args.args[0], repository)
        self.assertIs(service_type.call_args.kwargs["cleanup_runner"], runtime._process_storage_cleanup)


class ProgressServiceRuntimeTest(unittest.TestCase):
    def test_factory_composes_uncached_repository_without_external_services(self):
        repository, service = object(), object()
        with (
            patch.object(runtime, "SQLiteProgressRepository", return_value=repository) as repository_type,
            patch.object(runtime, "ProgressService", return_value=service) as service_type,
            patch.object(runtime, "storage_from_env") as storage_factory,
            patch.object(runtime, "MailAccountLinkSender") as mail_sender,
        ):
            self.assertIs(runtime.progress_service(), service)
            self.assertIs(runtime.progress_service(), service)
        self.assertEqual(repository_type.call_count, 2)
        self.assertEqual(service_type.call_count, 2)
        repository_type.assert_called_with(runtime.connect)
        service_type.assert_called_with(repository)
        storage_factory.assert_not_called()
        mail_sender.assert_not_called()


if __name__ == "__main__":
    unittest.main()
