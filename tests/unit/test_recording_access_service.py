import unittest
from unittest.mock import Mock

from trainer.services.recording_access import RecordingAccessError, RecordingAccessService
from trainer.services.recording_access_repository import (
    LegacyRecordingRecord,
    RecordingActor,
    ReviewAssetRecord,
    ReviewRecordingRecord,
    StoredFile,
)

FILE = StoredFile("private/file.webm", "audio/webm", 10)
STUDENT = RecordingActor(7, "student", "student@example.test", False)
TEACHER = RecordingActor(8, "teacher", " Owner@Example.Test ", True)
OUTSIDER = RecordingActor(9, "student", "other@example.test", False)


class RecordingAccessServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = Mock()
        self.service = RecordingAccessService(
            self.repository,
            owner_email="owner@example.test",
            clock=lambda: 100,
        )

    def assert_reason(self, reason, call):
        with self.assertRaises(RecordingAccessError) as raised:
            call()
        self.assertEqual(raised.exception.reason, reason)

    def test_legacy_participants_and_uploading_visibility(self):
        self.repository.legacy_recording.return_value = LegacyRecordingRecord(FILE, "submitted", 7, 8)
        self.assertEqual(self.service.legacy_recording(3, STUDENT), FILE)
        self.assertEqual(self.service.legacy_recording(3, TEACHER), FILE)
        self.assert_reason(
            "legacy_recording_not_found",
            lambda: self.service.legacy_recording(3, OUTSIDER),
        )

        self.repository.legacy_recording.return_value = LegacyRecordingRecord(FILE, "uploading", 7, 8)
        self.assertEqual(self.service.legacy_recording(3, STUDENT), FILE)
        self.assert_reason(
            "legacy_recording_not_found",
            lambda: self.service.legacy_recording(3, TEACHER),
        )

    def test_review_recording_expiry_applies_to_student_and_owner(self):
        for expires_at, allowed in ((101, True), (100, False), (99, False)):
            self.repository.review_recording.return_value = ReviewRecordingRecord(FILE, "queued", 7, expires_at)
            for actor in (STUDENT, TEACHER):
                with self.subTest(expires_at=expires_at, actor=actor):
                    if allowed:
                        self.assertEqual(self.service.review_recording(4, actor), FILE)
                    else:
                        self.assert_reason(
                            "review_recording_not_found",
                            lambda actor=actor: self.service.review_recording(4, actor),
                        )

    def test_review_owner_requires_every_identity_and_status_condition(self):
        allowed = ReviewRecordingRecord(FILE, "queued", 7, 101)
        self.repository.review_recording.return_value = allowed
        self.assertEqual(self.service.review_recording(4, STUDENT), FILE)
        self.assertEqual(self.service.review_recording(4, TEACHER), FILE)
        denied = (
            RecordingActor(8, "student", "owner@example.test", True),
            RecordingActor(8, "teacher", "owner@example.test", False),
            RecordingActor(8, "teacher", "other@example.test", True),
        )
        for actor in denied:
            with self.subTest(actor=actor):
                self.assert_reason(
                    "review_recording_not_found",
                    lambda actor=actor: self.service.review_recording(4, actor),
                )
        for status in ("uploading", "deleted", ""):
            self.repository.review_recording.return_value = ReviewRecordingRecord(FILE, status, 7, 101)
            self.assert_reason(
                "review_recording_not_found",
                lambda: self.service.review_recording(4, TEACHER),
            )

    def test_review_asset_has_no_expiry_but_keeps_owner_rules(self):
        self.repository.review_asset.return_value = ReviewAssetRecord(FILE, "uploading", 7)
        self.assertEqual(self.service.review_asset(5, STUDENT), FILE)
        self.assert_reason("review_asset_not_found", lambda: self.service.review_asset(5, TEACHER))
        self.repository.review_asset.return_value = ReviewAssetRecord(FILE, "reviewed", 7)
        self.assertEqual(self.service.review_asset(5, TEACHER), FILE)
        self.assert_reason("review_asset_not_found", lambda: self.service.review_asset(5, OUTSIDER))

    def test_missing_rows_empty_owner_and_repository_errors(self):
        for method, reason in (
            ("legacy_recording", "legacy_recording_not_found"),
            ("review_recording", "review_recording_not_found"),
            ("review_asset", "review_asset_not_found"),
        ):
            getattr(self.repository, method).return_value = None
            self.assert_reason(
                reason,
                lambda method=method: getattr(self.service, method)(1, STUDENT),
            )
        empty_owner = RecordingAccessService(self.repository, owner_email="", clock=lambda: 100)
        self.repository.review_asset.return_value = ReviewAssetRecord(FILE, "queued", 7)
        self.assert_reason("review_asset_not_found", lambda: empty_owner.review_asset(5, TEACHER))
        self.repository.legacy_recording.side_effect = OSError("database down")
        with self.assertRaisesRegex(OSError, "database down"):
            self.service.legacy_recording(3, STUDENT)
