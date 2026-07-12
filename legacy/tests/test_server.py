import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from legacy import server
from trainer.api import runtime


class LegacyServerSmokeTest(unittest.TestCase):
    def test_health_endpoint_remains_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server.DATA_DIR = root
            server.DB_PATH = root / "trainer.sqlite3"
            server.AUDIO_DIR = root / "audio"
            runtime.DATA_DIR = server.DATA_DIR
            runtime.DB_PATH = server.DB_PATH
            runtime.AUDIO_DIR = server.AUDIO_DIR
            server.init_database()
            httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.TrainerHandler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(*httpd.server_address, timeout=3)
                connection.request("GET", "/api/health")
                response = connection.getresponse()
                payload = json.loads(response.read())
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertTrue(payload["ok"])
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
