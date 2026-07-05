import unittest

from backend.grading import validate_scores


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


if __name__ == "__main__":
    unittest.main()
