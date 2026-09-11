from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path

from trainer.infrastructure.database.material_repository import SQLiteMaterialRepository
from trainer.infrastructure.database.migrations import upgrade_sqlite_database
from trainer.services.material_repository import (
    MaterialActor,
    MaterialAudit,
    MaterialConflictError,
    MaterialRequestData,
    MaterialRequestMetadata,
)


class SQLiteMaterialRepositoryTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.directory.name) / "trainer.sqlite3"
        upgrade_sqlite_database(self.database_path)
        with closing(self.connect()) as database, database:
            self.owner_id = self.add_user(database, "owner@example.test")
            self.other_owner_id = self.add_user(database, "other@example.test")
            self.published_newer_id = self.add_material(
                database,
                "published-newer",
                self.other_owner_id,
                status="published",
                year=2026,
                updated_at=30,
            )
            self.published_older_id = self.add_material(
                database,
                "published-older",
                self.owner_id,
                status="published",
                year=2025,
                updated_at=10,
            )
            self.draft_newer_id = self.add_material(
                database,
                "draft-newer",
                self.owner_id,
                status="draft",
                year=2024,
                updated_at=20,
            )
            self.add_material(
                database,
                "archived",
                self.owner_id,
                status="archived",
                year=2026,
                updated_at=40,
            )
            self.asset_id = database.execute(
                """INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (self.draft_newer_id, "materials/1/source.webp", "image/webp", 14, 1),
            ).lastrowid
        self.repository = SQLiteMaterialRepository(self.connect)
        self.actor = MaterialActor(self.owner_id, "owner@example.test", True)
        self.metadata = MaterialRequestMetadata("127.0.0.1", "tests")
        self.request_data = MaterialRequestData(
            "created-task",
            "task",
            2,
            "Created task",
            2026,
            "Test",
            {"2": {}},
        )

    def tearDown(self):
        self.directory.cleanup()

    def connect(self):
        database = sqlite3.connect(self.database_path)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        return database

    @staticmethod
    def add_user(database, email):
        return database.execute(
            "INSERT INTO users(email,password_hash,display_name,role,created_at) VALUES (?,?,?,?,?)",
            (email, "hash", "Owner", "teacher", 1),
        ).lastrowid

    @staticmethod
    def add_material(database, slug, owner_id, *, status, year, updated_at):
        return database.execute(
            """INSERT INTO materials
               (slug,owner_id,kind,task_number,title,year,source,status,content_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (slug, owner_id, "task", 2, slug, year, "Test", status, '{"2":{}}', 1, updated_at),
        ).lastrowid

    def test_reads_preserve_public_owner_and_detail_ordering(self):
        published = self.repository.published_materials()
        owned = self.repository.owned_materials(self.owner_id)
        detail = self.repository.material("published-newer")

        self.assertEqual([item.slug for item in published], ["published-newer", "published-older"])
        self.assertEqual([item.slug for item in owned], ["draft-newer", "published-older"])
        self.assertEqual(detail.owner_id, self.other_owner_id)
        self.assertEqual(self.repository.owned_material("draft-newer", self.owner_id).id, self.draft_newer_id)
        self.assertIsNone(self.repository.owned_material("draft-newer", self.other_owner_id))

    def test_asset_read_returns_private_storage_metadata_without_transport_fields(self):
        asset = self.repository.asset_access(self.asset_id)

        self.assertEqual(
            (asset.owner_id, asset.material_status, asset.storage_key, asset.mime_type, asset.size_bytes),
            (self.owner_id, "draft", "materials/1/source.webp", "image/webp", 14),
        )

    def test_create_and_audit_commit_together_and_rollback_together(self):
        with self.repository.transaction() as session:
            material_id = session.create(self.owner_id, self.request_data, 100)
            session.audit(
                MaterialAudit(
                    "material_created",
                    self.actor,
                    self.metadata,
                    {"materialId": material_id},
                )
            )

        with closing(self.connect()) as database:
            created = database.execute(
                "SELECT status,created_at,updated_at FROM materials WHERE slug='created-task'"
            ).fetchone()
            audit = database.execute(
                "SELECT action,details_json FROM audit_log WHERE action='material_created'"
            ).fetchone()
        self.assertEqual(tuple(created), ("draft", 100, 100))
        self.assertEqual(tuple(audit), ("material_created", f'{{"materialId":{material_id}}}'))

        with self.assertRaises(RuntimeError):
            with self.repository.transaction() as session:
                session.create(
                    self.owner_id,
                    replace(self.request_data, slug="rolled-back"),
                    101,
                )
                raise RuntimeError("rollback")

        self.assertIsNone(self.repository.material("rolled-back"))

    def test_update_resets_publication_state_and_reports_missing_owner_row(self):
        with self.repository.transaction() as session:
            updated = session.update(
                "published-older",
                self.owner_id,
                replace(self.request_data, slug="renamed-task"),
                200,
            )
            missing = session.update(
                "published-newer",
                self.owner_id,
                replace(self.request_data, slug="forbidden"),
                201,
            )

        row = self.repository.material("renamed-task")
        self.assertTrue(updated)
        self.assertFalse(missing)
        self.assertEqual((row.status, row.content_json), ("draft", '{"2": {}}'))

    def test_create_and_update_translate_slug_integrity_conflicts(self):
        with self.assertRaises(MaterialConflictError):
            with self.repository.transaction() as session:
                session.create(
                    self.owner_id,
                    replace(self.request_data, slug="draft-newer"),
                    100,
                )

        with self.assertRaises(MaterialConflictError):
            with self.repository.transaction() as session:
                session.update(
                    "draft-newer",
                    self.owner_id,
                    replace(self.request_data, slug="published-newer"),
                    100,
                )

    def test_publication_queries_and_mutations_commit_together(self):
        with closing(self.connect()) as database, database:
            unused_asset_id = database.execute(
                """INSERT INTO material_assets(material_id,storage_key,mime_type,size_bytes,created_at)
                   VALUES (?,?,?,?,?)""",
                (self.draft_newer_id, "materials/1/unused.webp", "image/webp", 20, 2),
            ).lastrowid
            group_id = database.execute(
                "INSERT INTO study_groups(teacher_id,name,join_code,created_at) VALUES (?,?,?,?)",
                (self.owner_id, "Snapshots", "SNAP01", 1),
            ).lastrowid
            snapshot = json.dumps({"tasks": {"2": {"images": [f"/api/material-assets/{self.asset_id}"]}}})
            database.execute(
                """INSERT INTO assignments
                   (group_id,teacher_id,title,variant_id,tasks_json,created_at,material_snapshot_json)
                   VALUES (?,?,?,?,?,?,?)""",
                (group_id, self.owner_id, "Snapshot", "draft-newer", "[2]", 1, snapshot),
            )

        with self.repository.transaction() as session:
            material = session.owned_material("draft-newer", self.owner_id)
            owned_ids = session.owned_asset_ids(
                self.draft_newer_id,
                {self.asset_id, 999_999},
            )
            assets = session.assets(self.draft_newer_id)
            snapshots = session.assignment_snapshots()
            session.publish(self.draft_newer_id, '{"2":{"images":[]}}', 300)
            session.remove_assets([unused_asset_id])
            session.audit(
                MaterialAudit(
                    "material_published",
                    self.actor,
                    self.metadata,
                    {"materialId": self.draft_newer_id},
                )
            )

        self.assertEqual(material.id, self.draft_newer_id)
        self.assertEqual(owned_ids, {self.asset_id})
        self.assertEqual([asset.id for asset in assets], [self.asset_id, unused_asset_id])
        self.assertEqual(snapshots, [snapshot])
        with closing(self.connect()) as database:
            row = database.execute(
                "SELECT status,content_json,published_at,updated_at FROM materials WHERE id=?",
                (self.draft_newer_id,),
            ).fetchone()
            removed = database.execute(
                "SELECT id FROM material_assets WHERE id=?",
                (unused_asset_id,),
            ).fetchone()
            audit = database.execute("SELECT action FROM audit_log WHERE action='material_published'").fetchone()
        self.assertEqual(tuple(row), ("published", '{"2":{"images":[]}}', 300, 300))
        self.assertIsNone(removed)
        self.assertEqual(audit["action"], "material_published")

    def test_publication_mutations_roll_back_together(self):
        with self.assertRaises(RuntimeError):
            with self.repository.transaction() as session:
                session.publish(self.draft_newer_id, "{}", 400)
                session.remove_assets([self.asset_id])
                raise RuntimeError("rollback")

        with closing(self.connect()) as database:
            material = database.execute(
                "SELECT status FROM materials WHERE id=?",
                (self.draft_newer_id,),
            ).fetchone()
            asset = database.execute(
                "SELECT id FROM material_assets WHERE id=?",
                (self.asset_id,),
            ).fetchone()
        self.assertEqual(material["status"], "draft")
        self.assertIsNotNone(asset)

    def test_archive_uses_the_owner_checked_record(self):
        with self.repository.transaction() as session:
            self.assertIsNone(session.owned_material("draft-newer", self.other_owner_id))
            material = session.owned_material("draft-newer", self.owner_id)
            session.archive(material.id, 500)

        row = self.repository.material("draft-newer")
        self.assertEqual(row.status, "archived")

    def test_add_asset_commits_and_rolls_back_without_translating_failures(self):
        with self.repository.transaction() as session:
            committed_id = session.add_asset(
                self.draft_newer_id,
                "materials/1/committed.webp",
                "image/webp",
                44,
                600,
            )

        committed = self.repository.asset_access(committed_id)
        self.assertEqual(
            (committed.storage_key, committed.mime_type, committed.size_bytes),
            ("materials/1/committed.webp", "image/webp", 44),
        )

        rolled_back_id = None
        with self.assertRaises(RuntimeError):
            with self.repository.transaction() as session:
                rolled_back_id = session.add_asset(
                    self.draft_newer_id,
                    "materials/1/rolled-back.webp",
                    "image/webp",
                    55,
                    601,
                )
                raise RuntimeError("rollback")

        self.assertIsNotNone(rolled_back_id)
        self.assertIsNone(self.repository.asset_access(rolled_back_id))


if __name__ == "__main__":
    unittest.main()
