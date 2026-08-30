from __future__ import annotations

import json
import unittest
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from trainer.services.material_repository import (
    MaterialActor,
    MaterialConflictError,
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


class FakeStorage:
    def put(self, key, source, content_type):
        raise AssertionError("read scenarios must not write storage")

    def delete(self, key):
        raise AssertionError("read scenarios must not delete storage")


class FakeMaterialRepository:
    def __init__(
        self,
        *,
        published: list[MaterialRecord] | None = None,
        owned: list[MaterialRecord] | None = None,
        materials: dict[str, MaterialRecord] | None = None,
    ):
        self.published = list(published or [])
        self.owned = list(owned or [])
        self.materials = dict(materials or {})
        self.transaction_count = 0
        self.created = None
        self.update_result = True
        self.updated = None
        self.conflict_on_create = False
        self.conflict_on_update = False
        self.audits = []

    def published_materials(self):
        return list(self.published)

    def owned_materials(self, owner_id):
        return [item for item in self.owned if item.owner_id == owner_id]

    def material(self, slug):
        return self.materials.get(slug)

    def owned_material(self, slug, owner_id):
        material = self.materials.get(slug)
        return material if material and material.owner_id == owner_id else None

    def asset_access(self, asset_id):
        return None

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
            {"2": {}},
        )

    def service(self, repository: FakeMaterialRepository | None = None) -> MaterialService:
        return MaterialService(
            repository or self.repository,
            project_root=ROOT,
            asset_root=ROOT / "tmp" / "material-service-test",
            storage=FakeStorage(),
            image_encoder=lambda body: body,
            editor_emails="author@example.test",
            max_image_body=5_000_000,
            now=lambda: 123,
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

    def test_create_rejects_oversized_content_before_opening_transaction(self):
        data = replace(self.valid_data, content={"text": "x" * 150_001})

        with self.assertRaises(MaterialError) as caught:
            self.service().create(data, self.actor, self.metadata)

        self.assertEqual(caught.exception.reason, "invalid_metadata")
        self.assertEqual(caught.exception.message, "Содержание материала слишком велико")
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


if __name__ == "__main__":
    unittest.main()
