import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ReferenceLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = json.loads((ROOT / "data/reference/library.json").read_text(encoding="utf-8"))

    def test_all_exam_tasks_have_reference_materials(self):
        tasks = self.library["tasks"]
        self.assertEqual([task["id"] for task in tasks], ["task-1", "task-2", "task-3"])
        for task in tasks:
            self.assertTrue(task["title"])
            self.assertTrue(task["tips"])
            self.assertTrue(task["groups"])
            self.assertTrue(task["criteria"])
            self.assertGreater(sum(len(group["items"]) for group in task["groups"]), 5)

        self.assertEqual(
            [sum(criterion["maximum"] for criterion in task["criteria"]) for task in tasks],
            [5, 7, 8],
        )

    def test_phrases_and_examples_have_required_content(self):
        for task in self.library["tasks"]:
            for group in task["groups"]:
                for item in group["items"]:
                    self.assertTrue(item["ru"].strip())
                    self.assertTrue(item["zh"].strip())
            for example in task["examples"]:
                self.assertTrue(example["paragraphs"])
                self.assertTrue(example["criteria"])


if __name__ == "__main__":
    unittest.main()
