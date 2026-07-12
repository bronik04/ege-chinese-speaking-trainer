import tempfile
import unittest
from pathlib import Path

from scripts.check_repository_hygiene import check_repository


class RepositoryHygieneTest(unittest.TestCase):
    def test_allows_placeholder_environment_example(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text("POSTGRES_PASSWORD=replace-with-a-long-random-password\n")

            self.assertEqual(check_repository(root, [".env.example"]), [])

    def test_rejects_runtime_secret_and_private_key_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env").write_text("OPENAI_API_KEY=real-secret\n")
            (root / "var").mkdir()
            (root / "var/trainer.sqlite3").write_bytes(b"database")
            private_key_marker = "-----BEGIN " + "PRIVATE KEY-----"
            (root / "certificate.pem").write_text(f"{private_key_marker}\nsecret\n")

            failures = check_repository(root, [".env", "var/trainer.sqlite3", "certificate.pem"])

            self.assertEqual(len(failures), 3)
            self.assertTrue(any(".env" in failure for failure in failures))
            self.assertTrue(any("var/trainer.sqlite3" in failure for failure in failures))
            self.assertTrue(any("private key" in failure.lower() for failure in failures))


if __name__ == "__main__":
    unittest.main()
