import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from trainer.infrastructure.audio import validate_duration
from trainer.infrastructure.exports import submissions_csv, submissions_pdf


class AudioValidationTest(unittest.TestCase):
    def test_real_audio_duration_is_probed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            rate = 8000
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, rate, rate, "NONE", "not compressed"))
                audio.writeframes(b"".join(struct.pack("<h", int(500 * math.sin(index / 20))) for index in range(rate)))
            self.assertAlmostEqual(validate_duration(path, 1), 1.0, delta=0.1)


class ExportTest(unittest.TestCase):
    def setUp(self):
        self.items = [
            {
                "groupName": "11 класс",
                "studentName": "Анна",
                "studentEmail": "anna@example.test",
                "title": "Пробная работа",
                "attempt": 1,
                "status": "graded",
                "submittedAt": 1000,
                "review": {"total": 18, "maximum": 20},
            }
        ]

    def test_csv_is_excel_compatible_utf8(self):
        document = submissions_csv(self.items)
        self.assertTrue(document.startswith(b"\xef\xbb\xbf"))
        self.assertIn("Анна".encode(), document)

    def test_pdf_is_generated(self):
        self.assertTrue(submissions_pdf(self.items).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
