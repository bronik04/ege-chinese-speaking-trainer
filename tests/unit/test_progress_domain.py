import copy
import json
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from trainer.domain.progress import (
    ProgressValidationError,
    completed_run_to_dict,
    normalize_progress,
    parse_completed_run,
    progress_to_dict,
)

FIXTURES = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "progress_v1_migration_cases.json").read_text(encoding="utf-8")
)["cases"]


def active_run(run_id="run-active"):
    return {
        "id": run_id,
        "variantId": "open-2026",
        "variantLabel": "Открытый вариант 2026",
        "mode": "practice",
        "tasks": [2],
        "completedTasks": [],
        "currentTask": 2,
        "phase": "idle",
        "fastMode": False,
        "startedAt": "2026-09-06T10:00:00Z",
    }


def completed_run(run_id="run-1"):
    return {
        **active_run(run_id),
        "completedTasks": [2],
        "phase": "answer",
        "status": "completed",
        "completedAt": "2026-09-06T10:05:00Z",
        "recordingsCount": 1,
    }


def valid_v2():
    return {
        "version": 2,
        "updatedAt": "2026-09-06T10:15:30Z",
        "settings": {"lastVariant": "open-2026", "fastMode": False},
        "runs": [completed_run()],
        "activeRun": active_run(),
    }


class ProgressDomainTest(unittest.TestCase):
    def assert_invalid(self, document, reason="invalid_document"):
        original = copy.deepcopy(document)
        with self.assertRaises(ProgressValidationError) as raised:
            normalize_progress(document)
        self.assertEqual(raised.exception.reason, reason)
        self.assertEqual(document, original)

    def test_shared_v1_migration_cases(self):
        for case in FIXTURES:
            with self.subTest(case=case["name"]):
                source = copy.deepcopy(case["input"])
                if reason := case.get("expectedError"):
                    with self.assertRaises(ProgressValidationError) as raised:
                        normalize_progress(source)
                    self.assertEqual(raised.exception.reason, reason)
                else:
                    self.assertEqual(progress_to_dict(normalize_progress(source)), case["expected"])
                self.assertEqual(source, case["input"])

    def test_completed_run_public_boundary_is_canonical_and_immutable(self):
        source = completed_run("public-run")
        source.update(
            mode="exam",
            tasks=[3, 1, 2],
            completedTasks=[2, 3, 1],
            currentTask=3,
            startedAt="2026-09-06T13:00:00+03:00",
            completedAt="2026-09-06T13:05:00+03:00",
        )
        original = copy.deepcopy(source)

        result = completed_run_to_dict(parse_completed_run(source))

        self.assertEqual(result["tasks"], [1, 2, 3])
        self.assertEqual(result["completedTasks"], [1, 2, 3])
        self.assertEqual(result["startedAt"], "2026-09-06T10:00:00.000Z")
        self.assertEqual(result["completedAt"], "2026-09-06T10:05:00.000Z")
        self.assertEqual(source, original)

    def test_completed_run_public_boundary_rejects_invalid_structure(self):
        source = completed_run()
        source["unknown"] = True

        with self.assertRaises(ProgressValidationError) as raised:
            parse_completed_run(source)

        self.assertEqual(raised.exception.reason, "invalid_document")

    def test_python_requires_an_exact_integer_version(self):
        for document in (None, [], {}, {"version": 1.0}, {"version": "1"}, {"version": True}):
            with self.subTest(document=document):
                self.assert_invalid(document)

    def test_v1_requires_a_bounded_history_list(self):
        self.assert_invalid({"version": 1, "runs": None})
        self.assert_invalid({"version": 1, "runs": {}}, "invalid_document")
        self.assert_invalid({"version": 1, "runs": [None] * 201}, "history_too_large")

    def test_v1_discards_bad_runs_and_duplicate_ids_without_losing_good_history(self):
        first = completed_run("same")
        second = {**completed_run("same"), "variantLabel": "Поздний дубль"}
        source = {
            "version": 1,
            "runs": [None, first, {"id": "broken"}, second],
            "activeRun": {"id": "broken"},
        }
        result = progress_to_dict(normalize_progress(source))
        self.assertEqual([run["id"] for run in result["runs"]], ["same"])
        self.assertEqual(result["runs"][0]["variantLabel"], "Открытый вариант 2026")
        self.assertIsNone(result["activeRun"])

    def test_v1_keeps_only_the_first_hundred_valid_runs(self):
        source = {"version": 1, "runs": [completed_run(f"run-{index}") for index in range(200)]}
        result = progress_to_dict(normalize_progress(source))
        self.assertEqual(len(result["runs"]), 100)
        self.assertEqual(result["runs"][0]["id"], "run-0")
        self.assertEqual(result["runs"][-1]["id"], "run-99")

    def test_v1_preserves_a_valid_active_run(self):
        source = {"version": 1, "activeRun": active_run("continue-me")}
        result = progress_to_dict(normalize_progress(source))
        self.assertEqual(result["activeRun"]["id"], "continue-me")
        self.assertEqual(result["activeRun"]["startedAt"], "2026-09-06T10:00:00.000Z")

    def test_v2_rejects_extra_fields_at_every_level(self):
        root = valid_v2()
        root["extra"] = True
        settings = valid_v2()
        settings["settings"]["extra"] = True
        run = valid_v2()
        run["runs"][0]["extra"] = True
        for document in (root, settings, run):
            with self.subTest(document=document):
                self.assert_invalid(document)

    def test_v2_rejects_type_coercion_and_out_of_bounds_values(self):
        cases = []
        for field, value in (("id", ""), ("variantId", "x" * 81), ("variantLabel", "x" * 161)):
            document = valid_v2()
            document["runs"][0][field] = value
            cases.append(document)
        for field, value in (("fastMode", 0), ("currentTask", True), ("recordingsCount", True)):
            document = valid_v2()
            document["runs"][0][field] = value
            cases.append(document)
        for recordings_count in (-1, 101):
            document = valid_v2()
            document["runs"][0]["recordingsCount"] = recordings_count
            cases.append(document)
        for document in cases:
            with self.subTest(document=document):
                self.assert_invalid(document)

    def test_v2_canonicalizes_unique_tasks_and_enforces_mode_cardinality(self):
        document = valid_v2()
        run = completed_run("exam")
        run.update(tasks=[3, 1, 2], completedTasks=[2, 3, 1], currentTask=3, mode="exam")
        document["runs"] = [run]
        result = progress_to_dict(normalize_progress(document))["runs"][0]
        self.assertEqual(result["tasks"], [1, 2, 3])
        self.assertEqual(result["completedTasks"], [1, 2, 3])

        for mode, tasks in (("exam", [1, 2]), ("practice", [1, 2]), ("practice", [])):
            invalid = valid_v2()
            invalid["runs"][0].update(
                mode=mode, tasks=tasks, completedTasks=tasks, currentTask=tasks[0] if tasks else 1
            )
            with self.subTest(mode=mode, tasks=tasks):
                self.assert_invalid(invalid)

    def test_v2_rejects_duplicate_and_invalid_task_relationships(self):
        cases = []
        for field, value in (
            ("tasks", [2, 2]),
            ("tasks", ["2"]),
            ("completedTasks", [3]),
            ("currentTask", 3),
        ):
            document = valid_v2()
            document["runs"][0][field] = value
            cases.append(document)
        for document in cases:
            with self.subTest(document=document):
                self.assert_invalid(document)

    def test_v2_enforces_modes_phases_statuses_and_completion(self):
        cases = []
        for field, value in (("mode", "quick"), ("phase", "done"), ("status", "failed")):
            document = valid_v2()
            document["runs"][0][field] = value
            cases.append(document)
        incomplete = valid_v2()
        incomplete["runs"][0]["completedTasks"] = []
        cases.append(incomplete)
        interrupted = valid_v2()
        interrupted["runs"][0].update(status="interrupted", completedTasks=[])
        self.assertEqual(progress_to_dict(normalize_progress(interrupted))["runs"][0]["status"], "interrupted")
        for document in cases:
            with self.subTest(document=document):
                self.assert_invalid(document)

    def test_v2_validates_and_canonicalizes_timezone_aware_timestamps(self):
        document = valid_v2()
        document["updatedAt"] = "2026-09-06T13:15:30+03:00"
        document["activeRun"]["startedAt"] = "2026-09-06T13:00:00+03:00"
        result = progress_to_dict(normalize_progress(document))
        self.assertEqual(result["updatedAt"], "2026-09-06T10:15:30.000Z")
        self.assertEqual(result["activeRun"]["startedAt"], "2026-09-06T10:00:00.000Z")

        for value in (None, "not-a-date", "2026-09-06T10:00:00", "2026-09-06 10:00:00+00:00"):
            invalid = valid_v2()
            invalid["updatedAt"] = value
            with self.subTest(value=value):
                self.assert_invalid(invalid)
        backwards = valid_v2()
        backwards["runs"][0]["completedAt"] = "2026-09-06T09:59:59Z"
        self.assert_invalid(backwards)

    def test_v2_limits_and_deduplicates_history(self):
        duplicate = valid_v2()
        duplicate["runs"] = [completed_run("same"), completed_run("same")]
        self.assert_invalid(duplicate)
        oversized = valid_v2()
        oversized["runs"] = [completed_run(f"run-{index}") for index in range(101)]
        self.assert_invalid(oversized)

    def test_v2_models_are_frozen_and_serialization_returns_fresh_collections(self):
        model = normalize_progress(valid_v2())
        with self.assertRaises(FrozenInstanceError):
            model.updated_at = "changed"
        first = progress_to_dict(model)
        first["settings"]["fastMode"] = True
        first["runs"].clear()
        second = progress_to_dict(model)
        self.assertFalse(second["settings"]["fastMode"])
        self.assertEqual(len(second["runs"]), 1)


if __name__ == "__main__":
    unittest.main()
