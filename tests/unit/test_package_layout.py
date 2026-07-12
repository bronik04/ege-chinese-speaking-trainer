from __future__ import annotations

import importlib
import sys
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

    def test_worker_does_not_import_legacy_server(self):
        sys.modules.pop("trainer.workers.transcription", None)
        sys.modules.pop("legacy.server", None)

        importlib.import_module("trainer.workers.transcription")

        self.assertNotIn("legacy.server", sys.modules)

    def test_legacy_server_is_outside_the_main_runtime_path(self):
        root = Path(__file__).resolve().parents[2]

        self.assertFalse((root / "server.py").exists())
        self.assertTrue((root / "legacy/server.py").is_file())

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

        for legacy in ("index.html", "js", "data", "assets", "styles.css"):
            with self.subTest(legacy=legacy):
                self.assertFalse((root / legacy).exists(), legacy)


if __name__ == "__main__":
    unittest.main()
