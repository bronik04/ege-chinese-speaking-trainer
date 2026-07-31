from __future__ import annotations

import ast
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
        forbidden = ("trainer.api", "fastapi", "boto3", "openai", "smtplib", "os")
        self.assertFalse(any(module.startswith(forbidden) for module in imports), imports)

    def test_infrastructure_does_not_depend_on_api(self):
        imports = imported_modules(PACKAGE / "infrastructure")
        self.assertFalse(any(module.startswith("trainer.api") for module in imports), imports)

    def test_api_dependencies_delegates_sql_mailer_and_storage_policy(self):
        path = PACKAGE / "api" / "dependencies.py"
        source = path.read_text(encoding="utf-8")
        dependency_tree = ast.parse(source, filename=str(path))
        imports = {
            node.module for node in ast.walk(dependency_tree) if isinstance(node, ast.ImportFrom) and node.module
        }
        imports.update(
            alias.name for node in ast.walk(dependency_tree) if isinstance(node, ast.Import) for alias in node.names
        )
        direct_calls = {
            node.func.attr
            for node in ast.walk(dependency_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertNotIn("execute", direct_calls)
        self.assertNotIn("trainer.infrastructure.mailer", imports)
        self.assertNotIn("trainer.infrastructure.storage", imports)
        self.assertNotIn("sqlite3", {node.id for node in ast.walk(dependency_tree) if isinstance(node, ast.Name)})

    def test_target_controllers_do_not_select_storage_backend(self):
        for name in ("auth.py", "recordings.py", "work.py"):
            with self.subTest(name=name):
                source = (PACKAGE / "api" / "controllers" / name).read_text(encoding="utf-8")
                self.assertNotIn("storage_from_env", source)

    def test_shim_is_removed(self):
        for name in ("http.py", "controller.py", "transport.py"):
            with self.subTest(name=name):
                self.assertFalse((PACKAGE / "api" / name).exists())

    def test_controllers_do_not_depend_on_the_web_framework(self):
        imports = imported_modules(PACKAGE / "api" / "controllers")
        forbidden = ("fastapi", "starlette")
        self.assertFalse(any(module.startswith(forbidden) for module in imports), imports)


if __name__ == "__main__":
    unittest.main()
