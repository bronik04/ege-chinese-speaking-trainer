import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from trainer.infrastructure.storage import LocalAudioStorage, S3AudioStorage, storage_from_env
from trainer.services.recordings import stream_recording


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

    def test_local_path_and_stream_match_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webm"
            source.write_bytes(b"audio-bytes")
            storage = LocalAudioStorage(root / "audio")
            storage.put("12/answer.webm", source, "audio/webm")

            path = storage.local_path("12/answer.webm")
            self.assertIsNotNone(path)
            self.assertEqual(path.read_bytes(), b"audio-bytes")
            self.assertIsNone(storage.local_path("12/missing.webm"))

            self.assertEqual(b"".join(storage.stream("12/answer.webm")), b"audio-bytes")
            with self.assertRaises(FileNotFoundError):
                list(storage.stream("12/missing.webm"))

    def test_local_stream_reads_only_the_requested_byte_range(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webm"
            source.write_bytes(b"0123456789")
            storage = LocalAudioStorage(root / "audio")
            storage.put("1/answer.webm", source, "audio/webm")

            self.assertEqual(b"".join(storage.stream("1/answer.webm", start=2, end=5)), b"2345")

    @patch("trainer.services.recordings.storage_from_env")
    def test_stream_recording_forwards_optional_byte_bounds(self, storage_from_env):
        storage = storage_from_env.return_value

        stream_recording(Path("/audio"), "1/answer.webm", start=2, end=5)

        storage.stream.assert_called_once_with("1/answer.webm", start=2, end=5)


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

    @patch("boto3.client")
    def test_local_path_is_none_and_stream_matches_read(self, client_factory):
        client = Mock()
        client.get_object.return_value = {"Body": Mock(iter_chunks=Mock(return_value=iter([b"audio", b"-bytes"])))}
        client_factory.return_value = client
        storage = S3AudioStorage(bucket="answers", endpoint_url="https://account.r2.example", region="auto")

        self.assertIsNone(storage.local_path("1/answer.webm"))
        self.assertEqual(b"".join(storage.stream("1/answer.webm")), b"audio-bytes")

    @patch("boto3.client")
    def test_s3_stream_passes_the_inclusive_range_to_get_object(self, client_factory):
        client = Mock()
        client.get_object.return_value = {"Body": Mock(iter_chunks=Mock(return_value=iter([b"2345"])))}
        client_factory.return_value = client
        storage = S3AudioStorage(bucket="answers", endpoint_url=None, region="auto")

        self.assertEqual(b"".join(storage.stream("1/answer.webm", start=2, end=5)), b"2345")
        client.get_object.assert_called_once_with(Bucket="answers", Key="1/answer.webm", Range="bytes=2-5")


if __name__ == "__main__":
    unittest.main()
