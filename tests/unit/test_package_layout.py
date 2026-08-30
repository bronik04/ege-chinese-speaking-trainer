from __future__ import annotations

import importlib
import subprocess
import unittest
from pathlib import Path


class PackageLayoutTest(unittest.TestCase):
    def test_canonical_and_compatibility_entrypoints_share_app(self):
        compatibility = importlib.import_module("asgi")
        canonical = importlib.import_module("trainer.main")

        self.assertIs(compatibility.app, canonical.app)

    def test_project_root_points_to_repository(self):
        config = importlib.import_module("trainer.config")

        self.assertEqual(config.PROJECT_ROOT, Path(__file__).resolve().parents[2])

    def test_legacy_runtime_is_removed(self):
        root = Path(__file__).resolve().parents[2]

        self.assertFalse((root / "server.py").exists())
        self.assertFalse((root / "legacy").exists())

    def test_retired_assignment_runtime_is_removed(self):
        root = Path(__file__).resolve().parents[2]
        for relative in (
            "src/trainer/api/routes/work.py",
            "src/trainer/api/controllers/work.py",
            "src/trainer/infrastructure/database/queries/combined.py",
            "src/trainer/infrastructure/database/queries/assignments.py",
            "src/trainer/infrastructure/database/queries/groups.py",
            "src/trainer/infrastructure/database/queries/submissions.py",
            "src/trainer/infrastructure/database/submissions.py",
            "src/trainer/infrastructure/exports.py",
            "src/trainer/services/assignment_assets.py",
        ):
            self.assertFalse((root / relative).exists(), relative)

        source = (root / "src/trainer/api/schemas.py").read_text(encoding="utf-8")
        for name in (
            "GroupRequest",
            "JoinGroupRequest",
            "AssignmentRequest",
            "AssignmentUpdateRequest",
            "SubmissionRequest",
            "SubmissionCompleteRequest",
            "ReviewRequest",
        ):
            self.assertNotIn(f"class {name}(", source)

    def test_frontend_content_and_public_files_are_separated(self):
        root = Path(__file__).resolve().parents[2]
        expected = (
            "frontend/pages/index.html",
            "frontend/js/account/account-controller.js",
            "frontend/js/runner/app.js",
            "frontend/js/materials/material-editor.js",
            "frontend/js/catalog/variants-page.js",
            "frontend/js/reference/reference-page.js",
            "frontend/styles/base.css",
            "content/reference/library.json",
            "content/variants/index.json",
            "public/assets/logo.svg",
        )
        for relative in expected:
            with self.subTest(relative=relative):
                self.assertTrue((root / relative).is_file(), relative)

        legacy_paths = ("index.html", "js", "data", "assets", "styles.css")
        tracked_legacy = subprocess.run(
            ["git", "ls-files", "--", *legacy_paths],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
        self.assertEqual(tracked_legacy, [])


if __name__ == "__main__":
    unittest.main()
