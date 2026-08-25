import unittest

from trainer.domain.grading import validate_scores
from trainer.domain.review_requests import required_recording_positions, validate_review_selection


class GradingTest(unittest.TestCase):
    def test_full_exam_maximum_is_twenty(self):
        scores = {
            "1": {f"question{number}": 1 for number in range(1, 6)},
            "2": {"content": 3, "organization": 2, "language": 2},
            "3": {"content": 3, "organization": 2, "language": 3},
        }
        _, total, maximum = validate_scores(scores, [1, 2, 3])
        self.assertEqual((total, maximum), (20, 20))

    def test_zero_content_resets_other_task_scores(self):
        normalized, total, maximum = validate_scores({"2": {"content": 0, "organization": 2, "language": 2}}, [2])
        self.assertEqual(normalized["2"], {"content": 0, "organization": 0, "language": 0})
        self.assertEqual((total, maximum), (0, 7))

    def test_out_of_range_score_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_scores({"3": {"content": 4, "organization": 2, "language": 3}}, [3])


class ReviewRequestSelectionTest(unittest.TestCase):
    def test_accepts_a_single_task_review_selection(self):
        selection = validate_review_selection("task", [2])
        self.assertEqual(selection.kind, "task")
        self.assertEqual(selection.tasks, (2,))

    def test_accepts_a_complete_attempt_selection(self):
        selection = validate_review_selection("attempt", [1, 2, 3])
        self.assertEqual(selection.kind, "attempt")
        self.assertEqual(selection.tasks, (1, 2, 3))

    def test_rejects_empty_task_selection(self):
        with self.assertRaises(ValueError):
            validate_review_selection("attempt", [])

    def test_rejects_a_non_string_request_kind(self):
        with self.assertRaises(ValueError):
            validate_review_selection([], [2])

    def test_rejects_duplicate_task_selection(self):
        with self.assertRaises(ValueError):
            validate_review_selection("attempt", [1, 1])

    def test_rejects_out_of_range_task_selection(self):
        with self.assertRaises(ValueError):
            validate_review_selection("attempt", [4])

    def test_rejects_multiple_tasks_for_a_single_task_request(self):
        with self.assertRaises(ValueError):
            validate_review_selection("task", [1, 2])

    def test_requires_all_recordings_for_selected_tasks(self):
        self.assertEqual(
            required_recording_positions([1, 3]),
            {(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (3, None)},
        )


if __name__ == "__main__":
    unittest.main()
