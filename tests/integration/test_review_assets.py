from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path

from trainer.domain.recording_retention import expires_at
from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.infrastructure.database.queries.review_requests import (
    review_request_detail,
    student_review_requests,
    teacher_review_requests,
)
from trainer.infrastructure.storage import LocalAudioStorage
from trainer.services.review_assets import copy_review_assets
from trainer.services.review_request_repository import MaterialAsset


class FailingSecondPutStorage(LocalAudioStorage):
    def __init__(self, root: Path):
        super().__init__(root)
        self.put_calls = 0

    def put(self, key: str, source: Path, content_type: str) -> None:
        self.put_calls += 1
        super().put(key, source, content_type)
        if self.put_calls == 2:
            raise OSError("second snapshot storage failed")


class FakeReviewAssetRegistry:
    def __init__(self, source_assets: dict[int, MaterialAsset]):
        self.source_assets = source_assets
        self.review_assets: dict[int, dict] = {}

    def material_asset(self, asset_id: int) -> MaterialAsset | None:
        return self.source_assets.get(asset_id)

    def add_review_asset(
        self,
        request_id: int,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        created_at: int,
    ) -> int:
        asset_id = len(self.review_assets) + 1
        self.review_assets[asset_id] = {
            "request_id": request_id,
            "storage_key": storage_key,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "created_at": created_at,
        }
        return asset_id

    def remove_review_asset(self, asset_id: int) -> None:
        self.review_assets.pop(asset_id, None)


class ReviewAssetServiceTest(unittest.TestCase):
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

    def create_material_fixture(self, database) -> dict:
        author_id = database.execute(
            "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
            ("author@example.test", "hash", "Author", "student", 1),
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
        return {
            "id": "author-task",
            "tasks": {"2": {"images": [f"/api/material-assets/{asset_id}"] * 3}},
        }

    def test_uses_asset_registry_without_database_access(self):
        registry = FakeReviewAssetRegistry({1: MaterialAsset("materials/1/source.webp", "image/webp", 14)})
        material = {"tasks": {"2": {"images": ["/api/material-assets/1"]}}}

        snapshot = copy_review_assets(
            registry,
            7,
            material,
            self.source_storage,
            self.target_storage,
        )

        self.assertEqual(snapshot["tasks"]["2"]["images"], ["/api/review-assets/1"])
        self.assertEqual(self.target_storage.read(registry.review_assets[1]["storage_key"]), b"snapshot-image")

    def test_copies_material_assets_into_an_immutable_review_snapshot(self):
        registry = FakeReviewAssetRegistry({1: MaterialAsset("materials/1/source.webp", "image/webp", 14)})
        material = {"tasks": {"2": {"images": ["/api/material-assets/1"] * 3}}}
        created_keys: list[str] = []

        snapshot = copy_review_assets(
            registry,
            7,
            material,
            self.source_storage,
            self.target_storage,
            created_keys,
        )

        snapshot_url = snapshot["tasks"]["2"]["images"][0]
        self.assertEqual(snapshot["tasks"]["2"]["images"], [snapshot_url] * 3)
        self.assertRegex(snapshot_url, r"^/api/review-assets/\d+$")
        row = registry.review_assets[1]
        self.assertEqual(self.target_storage.read(row["storage_key"]), b"snapshot-image")
        self.assertEqual(created_keys, [row["storage_key"]])

        source_file = self.root / "changed-source.webp"
        source_file.write_bytes(b"changed-original")
        self.source_storage.put("materials/1/source.webp", source_file, "image/webp")
        self.assertEqual(self.target_storage.read(row["storage_key"]), b"snapshot-image")

    def test_copies_official_public_images_into_an_immutable_private_review_snapshot(self):
        public_root = self.root / "public"
        source_file = public_root / "assets/variants/demo/candidate.webp"
        source_file.parent.mkdir(parents=True)
        source_file.write_bytes(b"official-snapshot")
        material = {
            "id": "demo",
            "tasks": {
                "2": {
                    "title": "Official task",
                    "images": [
                        "assets/variants/demo/candidate.webp",
                        "/assets/variants/demo/candidate.webp",
                    ],
                }
            },
        }

        registry = FakeReviewAssetRegistry({})
        snapshot = copy_review_assets(
            registry,
            7,
            material,
            self.source_storage,
            self.target_storage,
            public_root=public_root,
        )

        images = snapshot["tasks"]["2"]["images"]
        self.assertEqual(images[0], images[1])
        self.assertRegex(images[0], r"^/api/review-assets/\d+$")
        row = registry.review_assets[1]
        self.assertEqual((row["mime_type"], row["size_bytes"]), ("image/webp", 17))
        source_file.write_bytes(b"changed")
        source_file.unlink()
        self.assertEqual(self.target_storage.read(row["storage_key"]), b"official-snapshot")

    def test_rejects_official_asset_paths_outside_the_public_root(self):
        public_root = self.root / "public"
        escaped_file = self.root / "secret.webp"
        escaped_file.write_bytes(b"not-public")
        material = {
            "tasks": {"2": {"images": ["assets/variants/../../../secret.webp"]}},
        }

        registry = FakeReviewAssetRegistry({})
        with self.assertRaisesRegex(ValueError, "outside the public root"):
            copy_review_assets(
                registry,
                7,
                material,
                self.source_storage,
                self.target_storage,
                public_root=public_root,
            )

        self.assertEqual(registry.review_assets, {})

    def test_removes_review_rows_and_objects_when_a_later_copy_fails(self):
        failing_storage = FailingSecondPutStorage(self.root / "failing-review-assets")
        second_source = self.root / "second-source.webp"
        second_source.write_bytes(b"second-image")
        self.source_storage.put("materials/1/second.webp", second_source, "image/webp")
        registry = FakeReviewAssetRegistry(
            {
                1: MaterialAsset("materials/1/source.webp", "image/webp", 14),
                2: MaterialAsset("materials/1/second.webp", "image/webp", 12),
            }
        )
        material = {
            "tasks": {
                "2": {
                    "images": ["/api/material-assets/1", "/api/material-assets/2"],
                }
            }
        }

        with self.assertRaisesRegex(OSError, "second snapshot storage failed"):
            copy_review_assets(registry, 7, material, self.source_storage, failing_storage)

        self.assertEqual(registry.review_assets, {})
        self.assertEqual(list(failing_storage.root.rglob("*.webp")), [])


class ReviewRequestQueryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.database_path)
        with closing(self.connect()) as database, database:
            self.student_id = database.execute(
                "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
                ("student@example.test", "hash", "Student", "student", 1),
            ).lastrowid
            self.uploading_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json)
                   VALUES (?,?,?,?,?)""",
                (self.student_id, "task", "uploading", "demo-2026", "{}"),
            ).lastrowid
            self.queued_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at)
                   VALUES (?,?,?,?,?,?)""",
                (self.student_id, "attempt", "queued", "demo-2026", "{}", 10),
            ).lastrowid
            item_id = database.execute(
                """INSERT INTO review_request_items(request_id,task_number,task_snapshot_json,scores_json,total_score,max_score)
                   VALUES (?,?,?,?,?,?)""",
                (self.queued_id, 2, '{"images":["/api/review-assets/1"]}', '{"content":3}', 3, 7),
            ).lastrowid
            database.execute(
                """INSERT INTO review_request_recordings
                   (item_id,question_number,label,storage_key,mime_type,size_bytes,created_at,expires_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    item_id,
                    None,
                    "Ответ",
                    "private/audio.webm",
                    "audio/webm",
                    12,
                    int(time.time()),
                    expires_at(int(time.time())),
                ),
            )
            database.execute(
                """INSERT INTO review_request_assets(request_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (self.queued_id, "private/image.webp", "image/webp", 14, 10),
            )

    def tearDown(self):
        self.directory.cleanup()

    def connect(self):
        database = sqlite3.connect(self.database_path)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    def test_query_contracts_keep_uploading_private_and_never_expose_storage_keys(self):
        with closing(self.connect()) as database:
            student_items = student_review_requests(database, self.student_id)
            teacher_items = teacher_review_requests(database)
            detail = review_request_detail(database, self.queued_id)

        self.assertEqual({item["id"] for item in student_items}, {self.uploading_id, self.queued_id})
        self.assertEqual([item["id"] for item in teacher_items], [self.queued_id])
        self.assertEqual(teacher_items[0]["studentName"], "Student")
        self.assertEqual(teacher_items[0]["studentEmail"], "student@example.test")
        self.assertEqual(teacher_items[0]["tasks"], [2])
        self.assertEqual(teacher_items[0]["items"][0]["recordings"][0]["url"], "/api/review-recordings/1")
        self.assertEqual(teacher_items[0]["assets"][0]["url"], "/api/review-assets/1")
        self.assertEqual(detail["material"]["2"], {"images": ["/api/review-assets/1"]})
        self.assertNotIn("private/audio.webm", json.dumps([student_items, teacher_items, detail]))
        self.assertNotIn("private/image.webp", json.dumps([student_items, teacher_items, detail]))

    def test_teacher_queue_orders_queued_oldest_first_and_reviewed_newest_first(self):
        with closing(self.connect()) as database, database:
            oldest_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at)
                   VALUES (?,?,?,?,?,?)""",
                (self.student_id, "task", "queued", "oldest", "{}", 5),
            ).lastrowid
            newest_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at)
                   VALUES (?,?,?,?,?,?)""",
                (self.student_id, "task", "queued", "newest", "{}", 20),
            ).lastrowid
            older_reviewed_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at,reviewed_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (self.student_id, "task", "reviewed", "reviewed-old", "{}", 25, 30),
            ).lastrowid
            newer_reviewed_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at,reviewed_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (self.student_id, "task", "reviewed", "reviewed-new", "{}", 35, 40),
            ).lastrowid

            requests = teacher_review_requests(database)

        self.assertEqual(
            [request["id"] for request in requests],
            [oldest_id, self.queued_id, newest_id, newer_reviewed_id, older_reviewed_id],
        )

    def test_teacher_queue_filters_by_submitted_timestamp_range(self):
        with closing(self.connect()) as database, database:
            included_id = database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at)
                   VALUES (?,?,?,?,?,?)""",
                (self.student_id, "task", "queued", "included", "{}", 100),
            ).lastrowid
            database.execute(
                """INSERT INTO review_requests(student_id,kind,status,variant_id,run_json,submitted_at)
                   VALUES (?,?,?,?,?,?)""",
                (self.student_id, "task", "queued", "excluded", "{}", 200),
            )

            requests = teacher_review_requests(database, submitted_from=50, submitted_before=150)

        self.assertEqual([request["id"] for request in requests], [included_id])


if __name__ == "__main__":
    unittest.main()
