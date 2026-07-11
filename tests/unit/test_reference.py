import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts.validate_content import ContentValidationError, validate_repository

ROOT = Path(__file__).resolve().parents[2]


class ReferenceLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = json.loads((ROOT / "content/reference/library.json").read_text(encoding="utf-8"))

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

    def test_reference_schema_requires_examples_and_criteria(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "content", root / "content")
            shutil.copytree(ROOT / "public", root / "public")
            library_path = root / "content/reference/library.json"
            library = json.loads(library_path.read_text(encoding="utf-8"))
            del library["tasks"][0]["examples"]
            library_path.write_text(json.dumps(library), encoding="utf-8")

            with self.assertRaisesRegex(ContentValidationError, "examples"):
                validate_repository(root, schema_root=ROOT / "schemas")


if __name__ == "__main__":
    unittest.main()
