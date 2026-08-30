from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from trainer.infrastructure.database.material_repository import SQLiteMaterialRepository
from trainer.infrastructure.database.migrations import upgrade_sqlite_database


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


if __name__ == "__main__":
    unittest.main()
