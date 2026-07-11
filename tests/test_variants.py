import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VariantsTest(unittest.TestCase):
    def test_all_variants_follow_current_speaking_format(self):
        index = json.loads((ROOT / "content/variants/index.json").read_text())
        self.assertEqual(len(index), 7)
        for item in index:
            with self.subTest(variant=item["id"]):
                document = json.loads((ROOT / item["file"]).read_text())
                self.assertEqual(document["id"], item["id"])
                self.assertEqual(document["year"], item["year"])
                self.assertEqual(document["totalMinutes"], 14)
                self.assertEqual(
                    [
                        (document["tasks"][str(task)]["prepSeconds"], document["tasks"][str(task)]["answerSeconds"])
                        for task in (1, 2, 3)
                    ],
                    [(90, 20), (120, 120), (180, 180)],
                )
                self.assertEqual(len(document["tasks"]["1"]["questions"]), 5)
                self.assertEqual(len(document["tasks"]["2"]["images"]), 3)
                self.assertIn("10–12 фраз", document["tasks"]["2"]["lead"])
                self.assertEqual(len(document["tasks"]["3"]["images"]), 2)
                self.assertEqual(len(document["tasks"]["3"]["prompts"]), 4)

    def test_referenced_images_exist_and_use_candidate_names(self):
        index = json.loads((ROOT / "content/variants/index.json").read_text())
        for item in index:
            document = json.loads((ROOT / item["file"]).read_text())
            references = [document["tasks"]["1"]["image"]]
            references += document["tasks"]["2"]["images"] + document["tasks"]["3"]["images"]
            for reference in references:
                with self.subTest(variant=item["id"], image=reference):
                    path = ROOT / "public" / reference
                    self.assertTrue(path.is_file())
                    self.assertRegex(path.name, r"^candidate-\d{2}\.webp$")
                    self.assertEqual(path.read_bytes()[:4], b"RIFF")

    def test_variant_images_are_optimized(self):
        images = list((ROOT / "public/assets/variants").glob("*/*.webp"))
        self.assertEqual(len(images), 42)
        self.assertFalse(list((ROOT / "public/assets/variants").glob("*/*.jpg")))
        self.assertLess(sum(image.stat().st_size for image in images), 3_000_000)


if __name__ == "__main__":
    unittest.main()
