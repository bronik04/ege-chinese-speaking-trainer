import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from trainer.infrastructure.audio import validate_duration


class AudioValidationTest(unittest.TestCase):
    def test_real_audio_duration_is_probed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.wav"
            rate = 8000
            with wave.open(str(path), "wb") as audio:
                audio.setparams((1, 2, rate, rate, "NONE", "not compressed"))
                audio.writeframes(b"".join(struct.pack("<h", int(500 * math.sin(index / 20))) for index in range(rate)))
            self.assertAlmostEqual(validate_duration(path, 1), 1.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
