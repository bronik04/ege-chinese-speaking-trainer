import json
import logging
import unittest

from trainer.infrastructure.observability import ErrorMonitor, JsonFormatter, reset_request_id, set_request_id


class ObservabilityTest(unittest.TestCase):
    def test_json_formatter_includes_event_fields_and_request_id(self):
        token = set_request_id("unit-request-123")
        try:
            record = logging.LogRecord("trainer.test", logging.ERROR, __file__, 1, "Failure", (), None)
            record.event = "test_failed"
            record.fields = {"status": 500}
            payload = json.loads(JsonFormatter().format(record))
        finally:
            reset_request_id(token)
        self.assertEqual(payload["event"], "test_failed")
        self.assertEqual(payload["requestId"], "unit-request-123")
        self.assertEqual(payload["status"], 500)

    def test_error_monitor_counts_client_and_server_failures(self):
        monitor = ErrorMonitor()
        monitor.observe(404)
        monitor.observe(422)
        monitor.observe(500)
        snapshot = monitor.snapshot()
        self.assertEqual(snapshot["responses4xx"], 2)
        self.assertEqual(snapshot["responses5xx"], 1)
        self.assertIsNotNone(snapshot["lastFailureAt"])


if __name__ == "__main__":
    unittest.main()
