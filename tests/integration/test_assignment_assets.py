from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.infrastructure.storage import LocalAudioStorage
from trainer.services.assignment_assets import copy_assignment_assets


class FailingStorage(LocalAudioStorage):
    def put(self, key: str, source: Path, content_type: str) -> None:
        super().put(key, source, content_type)
        raise OSError("snapshot storage failed")


class AssignmentAssetServiceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.database_path = self.root / "trainer.sqlite3"
        upgrade_sqlite_database(self.database_path)
        self.source_storage = LocalAudioStorage(self.root / "source-assets")
        self.target_storage = LocalAudioStorage(self.root / "assignment-assets")
        source_file = self.root / "source.webp"
        source_file.write_bytes(b"snapshot-image")
        self.source_storage.put("materials/1/source.webp", source_file, "image/webp")

    def tearDown(self):
        self.directory.cleanup()

    def connect(self):
        database = sqlite3.connect(self.database_path)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def create_fixture(self, database) -> tuple[int, dict]:
        author_id = database.execute(
            "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
            ("author@example.test", "hash", "Author", "student", 1),
        ).lastrowid
        teacher_id = database.execute(
            "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
            ("teacher@example.test", "hash", "Teacher", "teacher", 1),
        ).lastrowid
        group_id = database.execute(
            "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
            (teacher_id, "Group", "ABCDEF", 1),
        ).lastrowid
        assignment_id = database.execute(
            """INSERT INTO assignments(group_id,teacher_id,title,variant_id,tasks_json,created_at,
                                          material_snapshot_json)
               VALUES (?,?,?,?,?,?,?)""",
            (group_id, teacher_id, "Work", "author-task", "[2]", 1, "{}"),
        ).lastrowid
        material_id = database.execute(
            """INSERT INTO materials(slug,owner_id,kind,task_number,title,year,source,status,content_json,
                                      created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            ("author-task", author_id, "task", 2, "Task", 2027, "Author", "published", "{}", 1, 1),
        ).lastrowid
        asset_id = database.execute(
            """INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at)
               VALUES (?,?,?,?,?)""",
            (material_id, "materials/1/source.webp", "image/webp", 14, 1),
        ).lastrowid
        material = {
            "id": "author-task",
            "tasks": {"2": {"images": [f"/api/material-assets/{asset_id}"] * 3}},
        }
        return assignment_id, material

    def test_copies_each_source_once_and_rewrites_repeated_urls(self):
        with closing(self.connect()) as database, database:
            assignment_id, material = self.create_fixture(database)
            original_images = list(material["tasks"]["2"]["images"])

            rewritten = copy_assignment_assets(
                database,
                assignment_id,
                material,
                self.source_storage,
                self.target_storage,
            )

            images = rewritten["tasks"]["2"]["images"]
            self.assertEqual(images[0], images[1])
            self.assertEqual(images[1], images[2])
            self.assertRegex(images[0], r"^/api/assignment-assets/\d+$")
            row = database.execute("SELECT * FROM assignment_material_assets").fetchone()
            self.assertEqual(row["assignment_id"], assignment_id)
            self.assertEqual(self.target_storage.read(row["storage_key"]), b"snapshot-image")
            self.assertEqual(material["tasks"]["2"]["images"], original_images)

    def test_deletes_copied_object_when_storage_fails(self):
        failing_storage = FailingStorage(self.root / "failing-assets")
        with closing(self.connect()) as database:
            with self.assertRaisesRegex(OSError, "snapshot storage failed"):
                with database:
                    assignment_id, material = self.create_fixture(database)
                    copy_assignment_assets(
                        database,
                        assignment_id,
                        material,
                        self.source_storage,
                        failing_storage,
                    )

            self.assertEqual(list(failing_storage.root.rglob("*.webp")), [])
            self.assertEqual(database.execute("SELECT COUNT(*) FROM assignment_material_assets").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
