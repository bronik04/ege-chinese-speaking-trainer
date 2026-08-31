from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from trainer.infrastructure.audio import validate_duration, validate_personal_recording_duration
from trainer.services.personal_recording_repository import PersonalRecordingAudioError


class AudioLimitTest(unittest.TestCase):
    @patch("trainer.infrastructure.audio.probe_duration", return_value=31.0)
    def test_enforces_exam_task_limit(self, _probe):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "не больше 30 секунд"):
                validate_duration(Path("answer.webm"), 1)

    @patch("trainer.infrastructure.audio.probe_duration", return_value=21.0)
    def test_configured_limit_can_only_reduce_exam_limit(self, _probe):
        with patch.dict(os.environ, {"TRAINER_MAX_AUDIO_SECONDS": "20"}, clear=True):
            with self.assertRaisesRegex(ValueError, "не больше 20 секунд"):
                validate_duration(Path("answer.webm"), 3)

    @patch("trainer.infrastructure.audio.validate_duration", return_value=12.5)
    def test_personal_recording_adapter_returns_valid_duration(self, _validate):
        self.assertEqual(validate_personal_recording_duration(Path("answer.webm"), 2), 12.5)

    @patch("trainer.infrastructure.audio.validate_duration", side_effect=OSError("ffprobe failed"))
    def test_personal_recording_adapter_translates_expected_probe_failure(self, _validate):
        with self.assertRaises(PersonalRecordingAudioError):
            validate_personal_recording_duration(Path("answer.webm"), 2)


if __name__ == "__main__":
    unittest.main()
