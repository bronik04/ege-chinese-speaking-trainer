from __future__ import annotations

import ast
import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "trainer"


def imported_modules(directory: Path) -> set[str]:
    modules: set[str] = set()
    for path in directory.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
    return modules


class ArchitectureBoundaryTest(unittest.TestCase):
    def test_transitional_backend_namespace_is_removed(self):
        self.assertFalse((PACKAGE / "backend").exists())
        self.assertNotIn("trainer.backend", "\n".join(imported_modules(PACKAGE)))

    def test_domain_has_no_transport_or_external_adapter_dependencies(self):
        imports = imported_modules(PACKAGE / "domain")
        forbidden = ("trainer.api", "fastapi", "boto3", "openai", "smtplib")
        self.assertFalse(any(module.startswith(forbidden) for module in imports), imports)

    def test_infrastructure_does_not_depend_on_api(self):
        imports = imported_modules(PACKAGE / "infrastructure")
        self.assertFalse(any(module.startswith("trainer.api") for module in imports), imports)

    def test_controller_keeps_route_and_legacy_actions(self):
        controller = importlib.import_module("trainer.api.controller").ApiController
        actions = {
            "auth_login",
            "auth_register",
            "teacher_group_create",
            "group_join",
            "teacher_assignment_create",
            "submission_create",
            "recording_create",
            "review_submission",
            "material_create",
            "material_publish",
        }
        self.assertTrue(all(callable(getattr(controller, action, None)) for action in actions))


if __name__ == "__main__":
    unittest.main()
