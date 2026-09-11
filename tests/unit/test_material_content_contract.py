from __future__ import annotations

import copy
import unittest

from trainer.domain.materials import (
    MaterialContentValidationError,
    normalize_material_draft_content,
)


def full_draft() -> dict:
    return {
        "3": {"imageLabels": ["", ""], "images": ["", ""], "title": ""},
        "1": {
            "questions": ["", "", "", "", ""],
            "imageAlt": "",
            "banner": "",
            "image": "",
            "situation": "",
        },
        "2": {"images": ["", "", ""]},
    }


class MaterialContentContractTest(unittest.TestCase):
    def test_full_draft_is_canonical_and_input_is_unchanged(self):
        raw = full_draft()
        original = copy.deepcopy(raw)

        normalized = normalize_material_draft_content("full", None, raw)

        self.assertEqual(list(normalized), ["1", "2", "3"])
        self.assertEqual(
            list(normalized["1"]),
            ["situation", "banner", "questions", "image", "imageAlt"],
        )
        self.assertEqual(list(normalized["3"]), ["title", "images", "imageLabels"])
        self.assertEqual(raw, original)
        self.assertIsNot(normalized, raw)
        self.assertIsNot(normalized["1"]["questions"], raw["1"]["questions"])

    def test_single_task_accepts_only_the_selected_key(self):
        normalized = normalize_material_draft_content(
            "task",
            2,
            {"2": {"images": ["one", "two", "three"]}},
        )

        self.assertEqual(normalized, {"2": {"images": ["one", "two", "three"]}})

    def test_invalid_structures_are_rejected(self):
        cases = (
            ("not-object", "full", None, []),
            (
                "full-missing-task",
                "full",
                None,
                {"1": full_draft()["1"], "2": full_draft()["2"]},
            ),
            ("full-has-task-number", "full", 2, full_draft()),
            ("single-wrong-key", "task", 2, {"3": full_draft()["3"]}),
            ("single-missing-number", "task", None, {"2": full_draft()["2"]}),
            (
                "unknown-task",
                "task",
                2,
                {"2": full_draft()["2"], "4": {}},
            ),
            (
                "extra-field",
                "task",
                2,
                {"2": {"images": ["", "", ""], "lead": "fixed"}},
            ),
            (
                "wrong-string-type",
                "task",
                3,
                {
                    "3": {
                        "title": 7,
                        "images": ["", ""],
                        "imageLabels": ["", ""],
                    }
                },
            ),
            ("wrong-list-type", "task", 2, {"2": {"images": ""}}),
            ("wrong-list-length", "task", 2, {"2": {"images": ["", ""]}}),
            (
                "wrong-item-type",
                "task",
                2,
                {"2": {"images": ["", 2, ""]}},
            ),
            (
                "too-long",
                "task",
                3,
                {
                    "3": {
                        "title": "x" * 151,
                        "images": ["", ""],
                        "imageLabels": ["", ""],
                    }
                },
            ),
        )
        for label, kind, task_number, raw in cases:
            with self.subTest(label=label), self.assertRaises(MaterialContentValidationError):
                normalize_material_draft_content(kind, task_number, raw)


if __name__ == "__main__":
    unittest.main()
