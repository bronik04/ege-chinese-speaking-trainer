from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "trainer"


def file_imports(path: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def imported_modules(directory: Path) -> set[str]:
    modules: set[str] = set()
    for path in directory.rglob("*.py"):
        modules.update(file_imports(path))
    return modules


class ArchitectureBoundaryTest(unittest.TestCase):
    def test_progress_boundary_and_retired_names(self):
        for area in ("controllers", "routes"):
            self.assertFalse((PACKAGE / "api" / area / "groups.py").exists())
        controller = PACKAGE / "api" / "controllers" / "progress.py"
        source = controller.read_text(encoding="utf-8")
        for token in (".execute(", "connect", "import json", "import time", "trainer.infrastructure", "trainer.domain"):
            self.assertNotIn(token, source)
        for relative in ("domain/progress.py", "services/progress.py", "services/progress_repository.py"):
            imports = file_imports(PACKAGE / relative)
            self.assertFalse(
                any(item.startswith(("trainer.api", "trainer.infrastructure", "sqlite3")) for item in imports)
            )
        runtime_source = (PACKAGE / "api" / "runtime.py").read_text(encoding="utf-8")
        self.assertNotIn("GROUP_CODE_ALPHABET", runtime_source)
        self.assertNotIn("EMAIL_RE", runtime_source)

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
        for name in ("auth.py", "recordings.py"):
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

    def test_review_request_controller_has_no_database_access(self):
        path = PACKAGE / "api" / "controllers" / "review_requests.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        direct_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        self.assertFalse(
            any(module.startswith("trainer.infrastructure.database") for module in file_imports(path)),
            file_imports(path),
        )
        self.assertNotIn("execute", direct_calls)
        self.assertNotIn("runtime.connect", source)

    def test_review_request_boundary_dependency_direction(self):
        service_imports = file_imports(PACKAGE / "services" / "review_requests.py")
        port_imports = file_imports(PACKAGE / "services" / "review_request_repository.py")
        adapter_imports = file_imports(PACKAGE / "infrastructure" / "database" / "review_request_repository.py")

        self.assertFalse(any(module.startswith("trainer.api") for module in service_imports), service_imports)
        self.assertFalse(
            any(module.startswith("trainer.infrastructure.database") for module in service_imports),
            service_imports,
        )
        self.assertNotIn("sqlite3", port_imports)
        self.assertFalse(any(module.startswith("trainer.infrastructure") for module in port_imports), port_imports)
        self.assertFalse(any(module.startswith("trainer.api") for module in adapter_imports), adapter_imports)

    def test_material_delegated_controller_functions_have_no_database_access(self):
        path = PACKAGE / "api" / "controllers" / "materials.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        targets = {
            "materials_list",
            "materials_mine",
            "material_get",
            "material_create",
            "material_update",
            "material_publish",
            "material_delete",
            "material_asset_create",
            "material_asset_get",
        }
        functions = {
            node.name: node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in targets
        }

        self.assertEqual(set(functions), targets)
        for name, function in functions.items():
            with self.subTest(name=name):
                direct_calls = {
                    node.func.attr
                    for node in ast.walk(function)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                }
                names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
                self.assertNotIn("execute", direct_calls)
                self.assertNotIn("connect", names)

    def test_material_controller_has_no_database_storage_or_image_processing(self):
        path = PACKAGE / "api" / "controllers" / "materials.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        direct_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        imports = file_imports(path)

        self.assertFalse(any(module.startswith("trainer.infrastructure") for module in imports), imports)
        self.assertFalse(any(module.startswith("trainer.domain") for module in imports), imports)
        self.assertNotIn("PIL", imports)
        self.assertNotIn("json", imports)
        self.assertNotIn("execute", direct_calls)
        self.assertNotIn("runtime.connect", source)
        self.assertNotIn("write_bytes", direct_calls)
        self.assertNotIn("_material_metadata", source)
        self.assertNotIn("_material_index_payload", source)

    def test_material_boundary_dependency_direction(self):
        service_imports = file_imports(PACKAGE / "services" / "materials.py")
        port_imports = file_imports(PACKAGE / "services" / "material_repository.py")
        adapter_imports = file_imports(PACKAGE / "infrastructure" / "database" / "material_repository.py")
        image_imports = file_imports(PACKAGE / "infrastructure" / "images.py")

        self.assertFalse(any(module.startswith("trainer.api") for module in service_imports), service_imports)
        self.assertFalse(
            any(module.startswith("trainer.infrastructure.database") for module in service_imports),
            service_imports,
        )
        self.assertNotIn("sqlite3", port_imports)
        self.assertFalse(any(module.startswith("trainer.infrastructure") for module in port_imports), port_imports)
        self.assertFalse(any(module.startswith("trainer.api") for module in adapter_imports | image_imports))

    def test_account_port_has_no_adapter_dependencies(self):
        path = PACKAGE / "services" / "account_repository.py"
        self.assertTrue(path.is_file())
        imports = file_imports(path)
        self.assertNotIn("sqlite3", imports)
        self.assertFalse(any(module.startswith("trainer.api") for module in imports), imports)
        self.assertFalse(any(module.startswith("trainer.infrastructure") for module in imports), imports)

    def test_database_adapters_do_not_import_concrete_account_service(self):
        for name in ("material_repository.py", "review_request_repository.py"):
            with self.subTest(name=name):
                path = PACKAGE / "infrastructure" / "database" / name
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imported_names = {
                    (node.module, alias.name)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names
                }
                self.assertNotIn(("trainer.services", "accounts"), imported_names)

    def test_account_controller_has_no_domain_or_database_access(self):
        path = PACKAGE / "api" / "controllers" / "auth.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        direct_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        imports = file_imports(path)

        self.assertFalse(any(module.startswith("trainer.infrastructure") for module in imports), imports)
        self.assertFalse(any(module.startswith("trainer.domain") for module in imports), imports)
        self.assertNotIn("execute", direct_calls)
        self.assertNotIn("runtime.connect", source)
        self.assertNotIn("process_cleanup_jobs", source)

    def test_account_boundary_dependency_direction(self):
        service_imports = file_imports(PACKAGE / "services" / "accounts.py")
        adapter_imports = file_imports(PACKAGE / "infrastructure" / "database" / "account_repository.py")
        sender_imports = file_imports(PACKAGE / "infrastructure" / "mailer" / "account_links.py")

        self.assertFalse(any(module.startswith("trainer.api") for module in service_imports), service_imports)
        self.assertFalse(
            any(module.startswith("trainer.infrastructure") for module in service_imports), service_imports
        )
        self.assertNotIn("sqlite3", service_imports)
        self.assertFalse(any(module.startswith("trainer.api") for module in adapter_imports | sender_imports))

    def test_storage_cleanup_boundary_dependency_direction(self):
        service = PACKAGE / "services" / "storage_cleanup.py"
        port = PACKAGE / "services" / "storage_cleanup_repository.py"
        service_imports = file_imports(service)
        port_imports = file_imports(port)
        self.assertFalse(
            any(name.startswith(("trainer.api", "trainer.infrastructure")) for name in service_imports),
            service_imports,
        )
        self.assertFalse(
            any(name.startswith(("trainer.api", "trainer.infrastructure")) for name in port_imports),
            port_imports,
        )
        self.assertNotIn("sqlite3", service_imports | port_imports)
        source = service.read_text(encoding="utf-8")
        for retired in (
            "def expire_recordings(",
            "def enqueue_cleanup_job(",
            "def process_cleanup_jobs(",
            "def account_review_storage_keys(",
        ):
            self.assertNotIn(retired, source)

        review_adapter = (PACKAGE / "infrastructure/database/review_request_repository.py").read_text(encoding="utf-8")
        self.assertNotIn("def process_cleanup(", review_adapter)

    def test_api_dependencies_uses_account_service_boundary(self):
        path = PACKAGE / "api" / "dependencies.py"
        source = path.read_text(encoding="utf-8")
        imports = file_imports(path)

        self.assertNotIn("trainer.api.runtime.connect", imports)
        self.assertNotIn("trainer.services.accounts", imports)
        self.assertNotIn("account_services", source)

    def test_personal_recording_service_and_port_are_adapter_neutral(self):
        service_imports = file_imports(PACKAGE / "services" / "personal_recordings.py")
        port_path = PACKAGE / "services" / "personal_recording_repository.py"

        self.assertTrue(port_path.is_file())
        port_imports = file_imports(port_path)
        for imports in (service_imports, port_imports):
            self.assertFalse(any(module.startswith("trainer.api") for module in imports), imports)
            self.assertFalse(any(module.startswith("trainer.infrastructure") for module in imports), imports)
            self.assertNotIn("sqlite3", imports)

    def test_personal_recording_controller_has_no_database_storage_or_file_orchestration(self):
        path = PACKAGE / "api" / "controllers" / "personal_recordings.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imports = file_imports(path)
        direct_calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }

        self.assertFalse(any(module.startswith("trainer.infrastructure") for module in imports), imports)
        self.assertNotIn("sqlite3", imports)
        self.assertNotIn("tempfile", imports)
        self.assertNotIn("subprocess", imports)
        self.assertNotIn("pathlib", imports)
        self.assertNotIn("execute", direct_calls)
        self.assertNotIn("runtime.connect", source)
        self.assertNotIn("write_recording", source)
        self.assertNotIn("enqueue_cleanup_job", source)

    def test_personal_recording_adapter_does_not_depend_on_api(self):
        imports = file_imports(PACKAGE / "infrastructure" / "database" / "personal_recording_repository.py")
        self.assertFalse(any(module.startswith("trainer.api") for module in imports), imports)

    def test_recording_access_boundary_dependency_direction(self):
        controller = PACKAGE / "api" / "controllers" / "recordings.py"
        source = controller.read_text(encoding="utf-8")
        for token in (
            ".execute(",
            "connect",
            "import time",
            "owner_email_from_env",
            "trainer.infrastructure",
            "trainer.domain",
        ):
            self.assertNotIn(token, source)
        service_imports = file_imports(PACKAGE / "services" / "recording_access.py")
        port_imports = file_imports(PACKAGE / "services" / "recording_access_repository.py")
        adapter_imports = file_imports(PACKAGE / "infrastructure" / "database" / "recording_access_repository.py")
        for imports in (service_imports, port_imports):
            self.assertFalse(any(item.startswith(("trainer.api", "trainer.infrastructure")) for item in imports))
            self.assertNotIn("sqlite3", imports)
        self.assertFalse(any(item.startswith("trainer.api") for item in adapter_imports))


if __name__ == "__main__":
    unittest.main()
