from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from trainer.services.material_repository import (
    MaterialActor,
    MaterialAssetAccess,
    MaterialAssetRecord,
    MaterialConflictError,
    MaterialImageError,
    MaterialRecord,
    MaterialRequestData,
    MaterialRequestMetadata,
)
from trainer.services.materials import MaterialError, MaterialService

ROOT = Path(__file__).resolve().parents[2]


def material_record(
    *,
    material_id: int = 10,
    slug: str = "author-task",
    owner_id: int = 7,
    kind: str = "task",
    task_number: int | None = 2,
    title: str = "Авторский материал",
    year: int = 2026,
    source: str = "Автор",
    status: str = "draft",
    content: dict | None = None,
) -> MaterialRecord:
    return MaterialRecord(
        id=material_id,
        slug=slug,
        owner_id=owner_id,
        kind=kind,
        task_number=task_number,
        title=title,
        year=year,
        source=source,
        status=status,
        content_json=json.dumps(content or {"2": {"images": []}}, ensure_ascii=False),
    )


def full_draft() -> dict:
    return {
        "1": {
            "situation": "",
            "banner": "",
            "questions": ["", "", "", "", ""],
            "image": "",
            "imageAlt": "",
        },
        "2": {"images": ["", "", ""]},
        "3": {"title": "", "images": ["", ""], "imageLabels": ["", ""]},
    }


class FakeStorage:
    def __init__(self):
        self.deleted = []
        self.delete_error = None
        self.puts = []
        self.put_error = None

    def put(self, key, source, content_type):
        self.puts.append((key, source, content_type, source.exists()))
        if self.put_error:
            raise self.put_error

    def delete(self, key):
        self.deleted.append(key)
        if self.delete_error:
            raise self.delete_error


class FakeMaterialRepository:
    def __init__(
        self,
        *,
        published: list[MaterialRecord] | None = None,
        owned: list[MaterialRecord] | None = None,
        materials: dict[str, MaterialRecord] | None = None,
    ):
        self._published = list(published or [])
        self.owned = list(owned or [])
        self.materials = dict(materials or {})
        self.transaction_count = 0
        self.created = None
        self.update_result = True
        self.updated = None
        self.conflict_on_create = False
        self.conflict_on_update = False
        self.audits = []
        self.asset_records = []
        self.snapshot_jsons = []
        self.owned_asset_ids_result = None
        self.published_update = None
        self.removed_asset_ids = []
        self.archived = None
        self.added_asset = None
        self.add_asset_error = None
        self.asset_access_rows = {}

    def published_materials(self):
        return list(self._published)

    def owned_materials(self, owner_id):
        return [item for item in self.owned if item.owner_id == owner_id]

    def material(self, slug):
        return self.materials.get(slug)

    def owned_material(self, slug, owner_id):
        material = self.materials.get(slug)
        return material if material and material.owner_id == owner_id else None

    def asset_access(self, asset_id):
        return self.asset_access_rows.get(asset_id)

    @contextmanager
    def transaction(self):
        self.transaction_count += 1
        yield self

    def create(self, owner_id, data, now):
        if self.conflict_on_create:
            raise MaterialConflictError
        self.created = {"owner_id": owner_id, "data": data, "now": now}
        return 101

    def update(self, current_slug, owner_id, data, now):
        if self.conflict_on_update:
            raise MaterialConflictError
        self.updated = {
            "current_slug": current_slug,
            "owner_id": owner_id,
            "data": data,
            "now": now,
        }
        return self.update_result

    def owned_asset_ids(self, material_id, asset_ids):
        if self.owned_asset_ids_result is not None:
            return set(self.owned_asset_ids_result)
        return set(asset_ids)

    def assets(self, material_id):
        return [asset for asset in self.asset_records if asset.material_id == material_id]

    def assignment_snapshots(self):
        return list(self.snapshot_jsons)

    def publish(self, material_id, content_json, now):
        self.published_update = {
            "material_id": material_id,
            "content_json": content_json,
            "now": now,
        }

    def remove_assets(self, asset_ids):
        self.removed_asset_ids.extend(asset_ids)

    def archive(self, material_id, now):
        self.archived = {"material_id": material_id, "now": now}

    def add_asset(self, material_id, storage_key, mime_type, size_bytes, created_at):
        if self.add_asset_error:
            raise self.add_asset_error
        self.added_asset = {
            "material_id": material_id,
            "storage_key": storage_key,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "created_at": created_at,
        }
        return 41

    def audit(self, event):
        self.audits.append(event)


class MaterialServiceTest(unittest.TestCase):
    def setUp(self):
        self.repository = FakeMaterialRepository()
        self.actor = MaterialActor(7, "author@example.test", True)
        self.metadata = MaterialRequestMetadata("127.0.0.1", "tests")
        self.valid_data = MaterialRequestData(
            "author-task",
            "task",
            2,
            "Авторский материал",
            2026,
            "Автор",
            {"2": {"images": ["", "", ""]}},
        )

    def service(
        self,
        repository: FakeMaterialRepository | None = None,
        storage: FakeStorage | None = None,
        image_encoder=None,
    ) -> MaterialService:
        return MaterialService(
            repository or self.repository,
            project_root=ROOT,
            asset_root=ROOT / "tmp" / "material-service-test",
            storage=storage or FakeStorage(),
            image_encoder=image_encoder or (lambda body: body),
            editor_emails="author@example.test",
            max_image_body=5_000_000,
            now=lambda: 123,
            storage_token=lambda: "fixed-token",
            temporary_token=lambda: "fixed-temporary",
        )

    def test_catalog_filters_official_materials_for_guest_and_adds_published_custom_for_user(self):
        repository = FakeMaterialRepository(published=[material_record(slug="author-task", status="published")])
        service = self.service(repository)

        guest = service.catalog(None)
        user = service.catalog(MaterialActor(7, "author@example.test", True))

        self.assertEqual([item["id"] for item in guest["materials"]], ["open-2026"])
        self.assertIn("author-task", [item["id"] for item in user["materials"]])
        self.assertFalse(guest["canCreate"])
        self.assertTrue(user["canCreate"])

    def test_detail_applies_the_existing_visibility_rules(self):
        repository = FakeMaterialRepository(
            materials={
                "draft": material_record(slug="draft", owner_id=7, status="draft"),
                "published": material_record(slug="published", owner_id=8, status="published"),
                "archived": material_record(slug="archived", owner_id=7, status="archived"),
            }
        )
        service = self.service(repository)
        actor = MaterialActor(7, "author@example.test", True)

        self.assertEqual(service.detail("draft", actor)["id"], "draft")
        self.assertEqual(service.detail("published", actor)["id"], "published")
        for slug, current_actor in (("draft", None), ("archived", actor)):
            with self.subTest(slug=slug), self.assertRaises(MaterialError) as caught:
                service.detail(slug, current_actor)
            self.assertEqual(caught.exception.reason, "not_found")

    def test_mine_returns_only_repository_owned_rows_in_repository_order(self):
        repository = FakeMaterialRepository(
            owned=[
                material_record(slug="newer", owner_id=7),
                material_record(slug="other-owner", owner_id=8),
                material_record(slug="older", owner_id=7),
            ]
        )
        service = self.service(repository)

        payload = service.mine(MaterialActor(7, "author@example.test", True))

        self.assertEqual([item["id"] for item in payload], ["newer", "older"])

    def test_create_normalizes_metadata_and_audits_numeric_material_id(self):
        created = self.service().create(
            replace(
                self.valid_data,
                slug="  author-task  ",
                title="  Название  ",
                source="  Источник  ",
            ),
            self.actor,
            self.metadata,
        )

        self.assertEqual(created, {"id": "author-task", "status": "draft"})
        self.assertEqual(self.repository.created["data"].title, "Название")
        self.assertEqual(self.repository.created["data"].source, "Источник")
        self.assertEqual(self.repository.created["now"], 123)
        self.assertEqual(self.repository.audits[0].action, "material_created")
        self.assertEqual(self.repository.audits[0].details, {"materialId": 101})

    def test_create_persists_a_canonical_copy_without_mutating_input(self):
        content = {"2": {"images": ["one", "two", "three"]}}
        data = replace(self.valid_data, content=content)

        self.service().create(data, self.actor, self.metadata)

        stored = self.repository.created["data"].content
        self.assertEqual(stored, {"2": {"images": ["one", "two", "three"]}})
        self.assertIsNot(stored, content)
        self.assertIsNot(stored["2"]["images"], content["2"]["images"])
        self.assertEqual(content, {"2": {"images": ["one", "two", "three"]}})

    def test_create_rejects_invalid_content_before_opening_transaction(self):
        data = replace(self.valid_data, content={"2": {"images": ["", ""]}})

        with self.assertRaises(MaterialError) as caught:
            self.service().create(data, self.actor, self.metadata)

        self.assertEqual(caught.exception.reason, "invalid_metadata")
        self.assertEqual(self.repository.transaction_count, 0)

    def test_create_rejects_full_material_with_task_number_before_transaction(self):
        data = replace(self.valid_data, kind="full", task_number=2, content=full_draft())

        with self.assertRaises(MaterialError) as caught:
            self.service().create(data, self.actor, self.metadata)

        self.assertEqual(caught.exception.reason, "invalid_metadata")
        self.assertEqual(self.repository.transaction_count, 0)

    def test_update_resets_status_and_reports_missing_owner_material(self):
        self.repository.update_result = False

        with self.assertRaises(MaterialError) as caught:
            self.service().update("missing", self.valid_data, self.actor, self.metadata)

        self.assertEqual(caught.exception.reason, "not_found")

    def test_slug_conflict_is_adapter_neutral(self):
        self.repository.conflict_on_create = True

        with self.assertRaises(MaterialError) as caught:
            self.service().create(self.valid_data, self.actor, self.metadata)

        self.assertEqual(caught.exception.reason, "slug_exists")

    def test_publish_retains_current_and_assignment_assets_and_deletes_only_unused(self):
        self.repository.materials["author-task"] = material_record(
            content={"2": {"images": ["/api/material-assets/1"] * 3}}
        )
        self.repository.asset_records = [
            MaterialAssetRecord(1, 10, "materials/10/current.webp", "image/webp", 10),
            MaterialAssetRecord(2, 10, "materials/10/assigned.webp", "image/webp", 20),
            MaterialAssetRecord(3, 10, "materials/10/unused.webp", "image/webp", 30),
        ]
        self.repository.snapshot_jsons = [json.dumps({"tasks": {"2": {"images": ["/api/material-assets/2"]}}})]
        storage = FakeStorage()

        result = self.service(storage=storage).publish(
            "author-task",
            self.actor,
            self.metadata,
        )

        self.assertEqual(result, {"id": "author-task", "status": "published"})
        self.assertEqual(self.repository.removed_asset_ids, [3])
        self.assertEqual(storage.deleted, ["materials/10/unused.webp"])
        self.assertEqual(self.repository.published_update["now"], 123)
        self.assertEqual(self.repository.audits[0].action, "material_published")

    def test_publish_rejects_foreign_asset_before_mutation(self):
        self.repository.materials["author-task"] = material_record(
            content={"2": {"images": ["/api/material-assets/1"] * 3}}
        )
        self.repository.owned_asset_ids_result = set()

        with self.assertRaises(MaterialError) as caught:
            self.service().publish("author-task", self.actor, self.metadata)

        self.assertEqual(caught.exception.reason, "foreign_asset")
        self.assertIsNone(self.repository.published_update)
        self.assertEqual(self.repository.removed_asset_ids, [])
        self.assertEqual(self.repository.audits, [])

    def test_publish_ignores_malformed_historical_assignment_snapshots(self):
        self.repository.materials["author-task"] = material_record(
            content={"2": {"images": ["/api/material-assets/1"] * 3}}
        )
        self.repository.asset_records = [
            MaterialAssetRecord(1, 10, "materials/10/current.webp", "image/webp", 10),
            MaterialAssetRecord(2, 10, "materials/10/unused.webp", "image/webp", 20),
        ]
        self.repository.snapshot_jsons = [
            "{",
            None,
            "null",
            "[]",
            json.dumps({"tasks": []}),
            json.dumps({"tasks": {"2": {"images": ["external.webp"]}}}),
        ]

        self.service().publish("author-task", self.actor, self.metadata)

        self.assertEqual(self.repository.removed_asset_ids, [2])

    def test_publish_treats_physical_asset_deletion_as_best_effort(self):
        self.repository.materials["author-task"] = material_record(
            content={"2": {"images": ["/api/material-assets/1"] * 3}}
        )
        self.repository.asset_records = [
            MaterialAssetRecord(1, 10, "materials/10/current.webp", "image/webp", 10),
            MaterialAssetRecord(2, 10, "materials/10/unused.webp", "image/webp", 20),
        ]
        storage = FakeStorage()
        storage.delete_error = OSError("storage unavailable")

        result = self.service(storage=storage).publish("author-task", self.actor, self.metadata)

        self.assertEqual(result["status"], "published")
        self.assertEqual(self.repository.removed_asset_ids, [2])
        self.assertEqual(storage.deleted, ["materials/10/unused.webp"])

    def test_archive_is_owner_bound_and_does_not_create_an_audit_event(self):
        self.repository.materials["author-task"] = material_record()

        result = self.service().archive("author-task", self.actor)

        self.assertEqual(result, {"ok": True})
        self.assertEqual(self.repository.archived, {"material_id": 10, "now": 123})
        self.assertEqual(self.repository.audits, [])

        with self.assertRaises(MaterialError) as caught:
            self.service().archive("author-task", replace(self.actor, id=8))
        self.assertEqual(caught.exception.reason, "not_found")

    def test_upload_rejects_mime_and_size_before_encoder_or_storage(self):
        encoded = []
        storage = FakeStorage()
        service = self.service(
            storage=storage,
            image_encoder=lambda body: encoded.append(body) or body,
        )

        for content_type, body, reason in (
            ("image/gif", b"gif", "unsupported_image"),
            ("image/png", b"", "image_too_large"),
            ("image/png", b"x" * 5_000_001, "image_too_large"),
        ):
            with self.subTest(reason=reason), self.assertRaises(MaterialError) as caught:
                service.upload_asset("author-task", body, content_type, self.actor)
            self.assertEqual(caught.exception.reason, reason)

        self.assertEqual(encoded, [])
        self.assertEqual(storage.puts, [])
        self.assertEqual(self.repository.transaction_count, 0)

    def test_upload_stores_webp_then_persists_metadata_and_removes_temporary_file(self):
        self.repository.materials["author-task"] = material_record()
        storage = FakeStorage()

        result = self.service(
            storage=storage,
            image_encoder=lambda body: b"encoded-webp",
        ).upload_asset("author-task", b"png", "image/png; charset=binary", self.actor)

        self.assertEqual(result, {"id": 41, "url": "/api/material-assets/41"})
        key, temporary, content_type, existed_during_put = storage.puts[0]
        self.assertEqual(key, "materials/10/fixed-token.webp")
        self.assertEqual(content_type, "image/webp")
        self.assertTrue(existed_during_put)
        self.assertFalse(temporary.exists())
        self.assertEqual(self.repository.added_asset["storage_key"], key)
        self.assertEqual(self.repository.added_asset["mime_type"], "image/webp")
        self.assertEqual(self.repository.added_asset["size_bytes"], len(b"encoded-webp"))

    def test_upload_deletes_new_object_when_metadata_insert_fails(self):
        self.repository.materials["author-task"] = material_record()
        self.repository.add_asset_error = RuntimeError("metadata failed")
        storage = FakeStorage()

        with self.assertRaisesRegex(RuntimeError, "metadata failed"):
            self.service(storage=storage).upload_asset(
                "author-task",
                b"png",
                "image/png",
                self.actor,
            )

        self.assertEqual(storage.deleted, [storage.puts[0][0]])
        self.assertFalse(storage.puts[0][1].exists())

    def test_upload_maps_only_expected_image_validation_errors(self):
        self.repository.materials["author-task"] = material_record()

        with self.assertRaises(MaterialError) as caught:
            self.service(image_encoder=lambda body: (_ for _ in ()).throw(MaterialImageError())).upload_asset(
                "author-task",
                b"png",
                "image/png",
                self.actor,
            )
        self.assertEqual(caught.exception.reason, "invalid_image")

    def test_asset_access_preserves_private_material_visibility(self):
        self.repository.asset_access_rows[5] = MaterialAssetAccess(
            "materials/10/5.webp",
            "image/webp",
            14,
            owner_id=7,
            material_status="draft",
        )
        service = self.service()

        self.assertEqual(service.asset(5, self.actor).storage_key, "materials/10/5.webp")
        for actor in (None, replace(self.actor, id=8)):
            with self.subTest(actor=actor), self.assertRaises(MaterialError) as caught:
                service.asset(5, actor)
            self.assertEqual(caught.exception.reason, "asset_not_found")

        self.repository.asset_access_rows[5] = replace(
            self.repository.asset_access_rows[5],
            owner_id=8,
            material_status="published",
        )
        self.assertEqual(service.asset(5, self.actor).storage_key, "materials/10/5.webp")


if __name__ == "__main__":
    unittest.main()
